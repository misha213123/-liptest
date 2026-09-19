#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import re
import sys
import traceback
import uuid
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
os.chdir(APP_DIR)

import yt_dlp
from openai import OpenAI

from clipper_core import AutoClipperCore
from config.config_manager import ConfigManager
from utils.helpers import get_app_dir, get_deno_path, get_ffmpeg_path, get_ytdlp_path
from utils.logger import debug_log


def build_core(cfg: dict) -> AutoClipperCore:
    providers = cfg.get("ai_providers") or {}
    hf = providers.get("highlight_finder") or {}
    client = OpenAI(
        api_key=hf.get("api_key") or cfg.get("api_key") or "x",
        base_url=hf.get("base_url") or cfg.get("base_url") or "https://api.openai.com/v1",
    )
    core = AutoClipperCore(
        client=client,
        ffmpeg_path=get_ffmpeg_path(),
        ytdlp_path=get_ytdlp_path(),
        output_dir=str(APP_DIR / "output"),
        model=hf.get("model") or cfg.get("model", "gpt-4.1"),
        temperature=cfg.get("temperature", 1.0),
        subtitle_language=cfg.get("subtitle_language", "ru-orig"),
        ai_providers=providers or None,
    )
    lang = str(getattr(core, "subtitle_language", "") or "").strip()
    if lang and lang != "none":
        core.subtitle_language = lang.split("-", 1)[0].lower()
    return core


def streamer_prompt(min_duration: int, max_duration: int) -> str:
    return f"""Ты — монтажёр вирусных клипов из стримов Twitch/Kick/YouTube.
Найди САМЫЕ СИЛЬНЫЕ моменты во всей переданной расшифровке.

Что ценить выше всего:
- сильная реакция стримера, смех, крик, удивление;
- clutch, победа, фейл, смерть, неожиданный игровой момент;
- спор, конфликт, шутка, провокационная или смешная фраза;
- короткая история с понятным началом и завершением;
- момент, который понятен без просмотра всего стрима.

ЖЁСТКИЕ ПРАВИЛА:
1. Каждый клип должен быть от {min_duration} до {max_duration} секунд.
2. Начинай за 1-3 секунды до сути, чтобы был контекст.
3. Заканчивай после реакции/панчлайна, не обрывай фразу.
4. Не выбирай скучные меню, ожидание, молчание, повторы и похожие моменты.
5. Используй ТОЛЬКО реальные таймкоды из расшифровки.
6. Заголовок — максимум 6 слов, цепкий и честный.
7. timed_title показывается только первые 2.3 секунды.
8. Верни ТОЛЬКО JSON-массив без markdown и пояснений.

ФОРМАТ:
[
  {{
    "start_time": "00:10:15,000",
    "end_time": "00:10:55,000",
    "title": "ОН НЕ ОЖИДАЛ ЭТОГО",
    "description": "Что происходит в моменте",
    "virality_score": 92,
    "virality_reason": "Почему момент удерживает внимание",
    "hook_text": "Короткий хук",
    "timed_title": {{"text": "ОН НЕ ОЖИДАЛ ЭТОГО", "start": 0.0, "end": 2.3}}
  }}
]

{{video_context}}

РАСШИФРОВКА:
{{transcript}}"""


def ytdlp_base_opts() -> dict:
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    app_dir = get_app_dir()
    for loc in [Path("cookies.txt"), app_dir / "cookies.txt"]:
        if loc.exists() and loc.stat().st_size > 0:
            opts["cookiefile"] = str(loc)
            break
    return opts


def add_youtube_runtime(opts: dict, url: str) -> None:
    if "youtube.com" not in url and "youtu.be" not in url:
        return
    deno = get_deno_path()
    if deno and Path(deno).exists():
        opts["js_runtimes"] = {"deno": {"path": deno}}
        opts["remote_components"] = ["ejs:github"]
    opts["extractor_args"] = {
        "youtube": {"player_client": ["web", "web_embedded", "web_safari", "mweb"]}
    }


def fetch_info(url: str) -> dict:
    opts = ytdlp_base_opts()
    opts["skip_download"] = True
    add_youtube_runtime(opts, url)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "title": info.get("title") or "Streamer VOD",
        "channel": info.get("channel") or info.get("uploader") or "",
        "description": (info.get("description") or "")[:2000],
        "duration": float(info.get("duration") or 0),
        "extractor": info.get("extractor_key") or info.get("extractor") or "",
    }


def download_audio(url: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    last_pct = {"v": -10}

    def hook(d):
        if d.get("status") != "downloading":
            return
        raw = str(d.get("_percent_str") or "").replace("%", "").strip()
        try:
            cleaned = re.sub(r"[^0-9.]", "", raw)
            pct = int(float(cleaned))
        except Exception:
            return
        if pct >= last_pct["v"] + 10:
            last_pct["v"] = pct
            debug_log(
                f"[progress] Загружаю аудио {pct}% (overall: {5 + pct * 0.20:.1f}%)",
                flush=True,
            )

    opts = ytdlp_base_opts()
    opts.update({
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "source_audio.%(ext)s"),
        "progress_hooks": [hook],
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
        "ffmpeg_location": str(Path(get_ffmpeg_path()).parent),
    })
    add_youtube_runtime(opts, url)

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    wav = out_dir / "source_audio.wav"
    if wav.exists():
        return wav
    candidates = list(out_dir.glob("source_audio.*"))
    if not candidates:
        raise RuntimeError("Не удалось скачать аудио из источника.")
    return candidates[0]


def split_transcript(transcript: str, max_chars: int = 32000) -> list[str]:
    lines = [line for line in (transcript or "").splitlines() if line.strip()]
    chunks = []
    current = []
    size = 0
    for line in lines:
        extra = len(line) + 1
        if current and size + extra > max_chars:
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += extra
    if current:
        chunks.append("\n".join(current))
    return chunks or [transcript]


def normalize_candidates(core: AutoClipperCore, items: list[dict], min_dur: int, max_dur: int, total_duration: float) -> list[dict]:
    out = []
    for idx, h in enumerate(items):
        if not isinstance(h, dict):
            continue
        try:
            start = core.parse_timestamp(h.get("start_time", "0"))
            end = core.parse_timestamp(h.get("end_time", "0"))
        except Exception:
            continue
        if end <= start:
            continue

        dur = end - start
        if dur > max_dur:
            end = start + max_dur
        elif dur < min_dur:
            end = min(total_duration or (start + min_dur), start + min_dur)

        if end <= start:
            continue

        h = dict(h)
        h["start_time"] = core._seconds_to_srt_timestamp(start)
        h["end_time"] = core._seconds_to_srt_timestamp(end)
        h["duration_seconds"] = round(end - start, 1)
        h["title"] = str(h.get("title") or h.get("hook_text") or "СИЛЬНЫЙ МОМЕНТ").strip()[:80]
        try:
            h["virality_score"] = int(float(h.get("virality_score") or 0))
        except Exception:
            h["virality_score"] = 0
        tt = h.get("timed_title") if isinstance(h.get("timed_title"), dict) else {}
        h["timed_title"] = {
            "text": str(tt.get("text") or h["title"]).strip()[:80],
            "start": 0.0,
            "end": 2.3,
        }
        h["_candidate_id"] = f"c{idx+1}"
        out.append(h)

    deduped = []
    for h in sorted(out, key=lambda x: x.get("virality_score", 0), reverse=True):
        hs = core.parse_timestamp(h["start_time"])
        he = core.parse_timestamp(h["end_time"])
        keep = True
        for d in deduped:
            ds = core.parse_timestamp(d["start_time"])
            de = core.parse_timestamp(d["end_time"])
            overlap = max(0.0, min(he, de) - max(hs, ds))
            if overlap / max(1.0, min(he - hs, de - ds)) > 0.55:
                keep = False
                break
        if keep:
            deduped.append(h)
    return deduped


def global_rank(core: AutoClipperCore, candidates: list[dict], target: int, video_info: dict) -> list[dict]:
    if len(candidates) <= target:
        return candidates

    compact = []
    by_id = {}
    for i, h in enumerate(candidates):
        cid = f"m{i+1}"
        by_id[cid] = h
        compact.append({
            "id": cid,
            "start": h.get("start_time"),
            "end": h.get("end_time"),
            "title": h.get("title"),
            "description": h.get("description", ""),
            "score": h.get("virality_score", 0),
            "reason": h.get("virality_reason", ""),
        })

    prompt = f"""Ты главный редактор коротких роликов.
Из кандидатов со всего стрима выбери {target} самых сильных и РАЗНЫХ моментов.
Не бери два почти одинаковых эпизода. Приоритет: эмоция, игровой экшен, юмор,
неожиданность, конфликт, законченная история и понятность без контекста.

Видео: {video_info.get('title','')}
Канал: {video_info.get('channel','')}

Кандидаты:
{json.dumps(compact, ensure_ascii=False)}

Верни только JSON:
{{"ids":["m1","m4"]}}
"""
    kwargs = {
        "model": core.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": 800,
        "timeout": float(os.environ.get("AI_HIGHLIGHT_TIMEOUT", "600")),
    }
    if not str(core.model or "").lower().startswith(("gpt-5", "o1", "o3", "o4")):
        kwargs["temperature"] = 0.4

    try:
        response = core.highlight_client.chat.completions.create(**kwargs)
        raw = response.choices[0].message.content.strip()
        fence = chr(96) * 3
        raw = raw.replace(fence + "json", "").replace(fence, "").strip()
        match = re.search(r"\{.*\}", raw, flags=re.S)
        data = json.loads(match.group(0) if match else raw)
        ids = [x for x in data.get("ids", []) if x in by_id][:target]
        ranked = [by_id[x] for x in ids]
        if len(ranked) >= max(1, target // 2):
            return ranked
    except Exception as exc:
        debug_log(f"[streamer-ai] Глобальный рейтинг OpenAI не удался: {exc}", flush=True)

    return sorted(candidates, key=lambda x: x.get("virality_score", 0), reverse=True)[:target]


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Usage: streamer_analyze.py <job.json> <result.json>")

    job_path = Path(sys.argv[1]).resolve()
    result_path = Path(sys.argv[2]).resolve()
    job = json.loads(job_path.read_text(encoding="utf-8"))

    url = str(job.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Нужна ссылка Twitch, Kick или YouTube")

    min_duration = max(10, min(180, int(job.get("min_duration") or 25)))
    max_duration = max(min_duration, min(240, int(job.get("max_duration") or 55)))
    requested = max(1, min(12, int(job.get("num_clips") or 5)))

    cfg = ConfigManager(APP_DIR / "config.json", APP_DIR / "output").config
    core = build_core(cfg)
    core.system_prompt = streamer_prompt(min_duration, max_duration)

    analysis_id = str(job.get("id") or uuid.uuid4().hex[:12])
    analysis_dir = APP_DIR / "output" / "streamer_analysis" / analysis_id
    analysis_dir.mkdir(parents=True, exist_ok=True)

    debug_log("[progress] Читаю данные VOD... (overall: 2.0%)", flush=True)
    info = fetch_info(url)
    debug_log(
        f"[streamer-ai] {info.get('title')} | {info.get('channel')} | {info.get('duration',0):.0f}s",
        flush=True,
    )

    debug_log("[progress] Загружаю аудио всего ролика... (overall: 5.0%)", flush=True)
    audio_path = download_audio(url, analysis_dir)

    debug_log("[progress] Распознаю весь стрим Faster-Whisper... (overall: 28.0%)", flush=True)
    transcript = core._transcribe_full_faster_whisper(str(audio_path))
    (analysis_dir / "transcript.txt").write_text(transcript, encoding="utf-8")

    chunks = split_transcript(transcript)
    debug_log(f"[streamer-ai] Расшифровка разделена на {len(chunks)} частей.", flush=True)

    per_chunk = max(2, min(6, math.ceil((requested * 2.2) / max(1, len(chunks)))))
    all_candidates = []
    for i, chunk in enumerate(chunks, 1):
        p0 = 48 + ((i - 1) / len(chunks)) * 34
        debug_log(
            f"[progress] OpenAI ищет моменты: часть {i}/{len(chunks)} (overall: {p0:.1f}%)",
            flush=True,
        )
        try:
            found = core.find_highlights(chunk, dict(info), per_chunk)
            all_candidates.extend(found or [])
        except Exception as exc:
            debug_log(f"[streamer-ai] Часть {i}: {exc}", flush=True)

    if not all_candidates:
        raise RuntimeError("OpenAI не нашёл подходящих моментов в ролике.")

    candidates = normalize_candidates(
        core,
        all_candidates,
        min_duration,
        max_duration,
        float(info.get("duration") or 0),
    )
    if not candidates:
        raise RuntimeError("После проверки длительности не осталось подходящих моментов.")

    debug_log("[progress] OpenAI выбирает лучшие моменты всего ролика... (overall: 88.0%)", flush=True)
    best = global_rank(core, candidates, requested, info)

    for h in best:
        h.pop("_candidate_id", None)

    payload = {
        "ok": True,
        "id": analysis_id,
        "video_info": info,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "highlights": best,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (analysis_dir / "analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    debug_log(f"[progress] Найдено {len(best)} лучших моментов. (overall: 100.0%)", flush=True)
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        try:
            if len(sys.argv) >= 3:
                Path(sys.argv[2]).write_text(
                    json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
                    encoding="utf-8",
                )
        except Exception:
            pass
        sys.exit(1)
