#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
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


def parse_time(value) -> float:
    raw = str(value or "0").strip().replace(",", ".")
    if not raw:
        return 0.0
    if ":" not in raw:
        return max(0.0, float(raw))
    parts = raw.split(":")
    if len(parts) == 2:
        return max(0.0, float(parts[0]) * 60 + float(parts[1]))
    if len(parts) == 3:
        return max(
            0.0,
            float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2]),
        )
    raise ValueError(f"Неверный таймкод диапазона: {value}")


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def offset_transcript_timestamps(core: AutoClipperCore, transcript: str, offset: float) -> str:
    """Shift SRT-like transcript timestamps to the original VOD timeline."""
    if offset <= 0:
        return transcript

    pattern = re.compile(
        r"^\[(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-\s*"
        r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\](.*)$"
    )
    out = []
    for line in (transcript or "").splitlines():
        m = pattern.match(line)
        if not m:
            out.append(line)
            continue
        start = core.parse_timestamp(m.group(1)) + offset
        end = core.parse_timestamp(m.group(2)) + offset
        out.append(
            f"[{core._seconds_to_srt_timestamp(start)} - "
            f"{core._seconds_to_srt_timestamp(end)}]{m.group(3)}"
        )
    return "\n".join(out)


def download_analysis_range(
    core: AutoClipperCore,
    url: str,
    out_dir: Path,
    start_sec: float,
    end_sec: float,
) -> Path:
    """Download only the selected Twitch/Kick/YouTube range for transcription."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "analysis_range.mp4"
    debug_log(
        f"[progress] Скачиваю выбранный отрезок {fmt_time(start_sec)} → "
        f"{fmt_time(end_sec)}... (overall: 7.0%)",
        flush=True,
    )
    downloaded = core.download_video_section(
        url,
        fmt_time(start_sec),
        fmt_time(end_sec),
        str(target),
        resolution="360p",
    )
    path = Path(downloaded)
    if not path.exists() or path.stat().st_size < 10_000:
        raise RuntimeError("Не удалось скачать выбранный отрезок VOD.")
    return path


def split_transcript(transcript: str, max_chars: int = 24000) -> list[str]:
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


def cache_paths(
    url: str,
    min_duration: int,
    max_duration: int,
    requested: int,
    source_start: float = 0.0,
    source_end: float = 0.0,
) -> dict:
    range_key = (
        f"{source_start:.3f}-{source_end:.3f}"
        if source_start > 0 or source_end > 0
        else "full"
    )
    url_key = hashlib.sha256(
        f"{url.strip()}|{range_key}".encode("utf-8")
    ).hexdigest()[:24]
    cache_dir = APP_DIR / "output" / "streamer_cache" / url_key
    analysis_key = f"{min_duration}_{max_duration}_{requested}_v3"
    pool_key = f"{min_duration}_{max_duration}_v3"
    return {
        "dir": cache_dir,
        "transcript": cache_dir / "transcript.txt",
        "info": cache_dir / "video_info.json",
        "candidates": cache_dir / f"candidates_{pool_key}.json",
        "analysis": cache_dir / f"analysis_{analysis_key}.json",
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
    requested = max(1, min(30, int(job.get("num_clips") or 5)))

    source_start = parse_time(job.get("source_start", 0))
    source_end_requested = parse_time(job.get("source_end", 0))
    if source_end_requested > 0 and source_end_requested <= source_start:
        raise ValueError("Конец диапазона должен быть позже начала.")

    cache = cache_paths(
        url,
        min_duration,
        max_duration,
        requested,
        source_start,
        source_end_requested,
    )
    cache["dir"].mkdir(parents=True, exist_ok=True)

    # Exact same URL + duration range + clip count: return saved AI result.
    # This avoids BOTH Whisper and highlight-model API spend on repeat runs.
    if cache["analysis"].exists():
        try:
            cached_payload = json.loads(cache["analysis"].read_text(encoding="utf-8"))
            if int(cached_payload.get("schema_version") or 0) < 2:
                raise ValueError("старый формат кэша")
            cached_payload["ok"] = True
            cached_payload["id"] = str(job.get("id") or cached_payload.get("id") or uuid.uuid4().hex[:12])
            cached_payload["cached"] = True
            cached_payload["cache_kind"] = "analysis"
            debug_log("[progress] ♻ Использую сохранённый AI-анализ — токены не тратятся. (overall: 100.0%)", flush=True)
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(cached_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(cached_payload, ensure_ascii=False), flush=True)
            return
        except Exception as exc:
            debug_log(f"[streamer-ai] Не удалось прочитать кэш анализа: {exc}", flush=True)

    cfg = ConfigManager(APP_DIR / "config.json", APP_DIR / "output").config
    core = build_core(cfg)
    core.system_prompt = streamer_prompt(min_duration, max_duration)

    analysis_id = str(job.get("id") or uuid.uuid4().hex[:12])
    analysis_dir = APP_DIR / "output" / "streamer_analysis" / analysis_id
    analysis_dir.mkdir(parents=True, exist_ok=True)

    debug_log("[progress] Читаю данные VOD... (overall: 2.0%)", flush=True)
    if cache["info"].exists():
        try:
            info = json.loads(cache["info"].read_text(encoding="utf-8"))
        except Exception:
            info = fetch_info(url)
            write_json(cache["info"], info)
    else:
        info = fetch_info(url)
        write_json(cache["info"], info)

    full_duration = float(info.get("duration") or 0)
    if full_duration > 0 and source_start >= full_duration:
        raise ValueError(
            f"Начало диапазона ({fmt_time(source_start)}) находится после конца VOD "
            f"({fmt_time(full_duration)})."
        )

    source_end = source_end_requested
    if source_end <= 0:
        source_end = full_duration
    elif full_duration > 0:
        source_end = min(source_end, full_duration)

    range_requested = source_start > 0 or source_end_requested > 0
    if range_requested and source_end <= source_start:
        raise ValueError("Не удалось определить корректный конец выбранного диапазона.")

    analysis_duration = (
        source_end - source_start
        if source_end > source_start
        else max(0.0, full_duration - source_start)
    )
    timeline_end = source_end if source_end > 0 else full_duration

    info = dict(info)
    info["analysis_range_start"] = source_start
    info["analysis_range_end"] = source_end
    info["analysis_range_duration"] = analysis_duration

    debug_log(
        f"[streamer-ai] {info.get('title')} | {info.get('channel')} | "
        f"{full_duration:.0f}s",
        flush=True,
    )
    if range_requested:
        debug_log(
            f"[streamer-ai] Анализирую только диапазон "
            f"{fmt_time(source_start)} → {fmt_time(source_end)} "
            f"({analysis_duration / 60:.1f} мин).",
            flush=True,
        )

    if cache["transcript"].exists() and cache["transcript"].stat().st_size > 20:
        transcript = cache["transcript"].read_text(encoding="utf-8")
        debug_log(
            "[progress] ♻ Использую сохранённую транскрипцию — Whisper API не вызывается. (overall: 45.0%)",
            flush=True,
        )
    else:
        if range_requested:
            debug_log(
                "[progress] Загружаю только выбранный диапазон VOD... (overall: 5.0%)",
                flush=True,
            )
            audio_path = download_analysis_range(
                core,
                url,
                analysis_dir,
                source_start,
                source_end,
            )
        else:
            debug_log("[progress] Загружаю аудио всего ролика... (overall: 5.0%)", flush=True)
            audio_path = download_audio(url, analysis_dir)

        debug_log("[progress] Проверяю быстрый Faster-Whisper на GPU... (overall: 28.0%)", flush=True)
        try:
            transcript = core._transcribe_full_faster_whisper(
                str(audio_path),
                allow_cpu_fallback=False,
                progress_callback=lambda p: debug_log(
                    f"[progress] Faster-Whisper GPU {int(p * 100)}% "
                    f"(overall: {28 + p * 17:.1f}%)",
                    flush=True,
                ),
            )
        except Exception as exc:
            debug_log(
                f"[streamer-ai] GPU Faster-Whisper недоступен: {exc}",
                flush=True,
            )
            debug_log(
                "[streamer-ai] CPU medium пропускаю: для длинного VOD это слишком медленно и сильно греет ноутбук.",
                flush=True,
            )
            debug_log(
                "[progress] Переключаюсь на OpenAI Whisper API... (overall: 30.0%)",
                flush=True,
            )
            transcript = core.transcribe_full_video(str(audio_path))

        if range_requested and source_start > 0:
            transcript = offset_transcript_timestamps(core, transcript, source_start)
            debug_log(
                f"[streamer-ai] Таймкоды расшифровки сдвинуты на "
                f"{fmt_time(source_start)} к оригинальному Twitch VOD.",
                flush=True,
            )

        cache["transcript"].write_text(transcript, encoding="utf-8")
        debug_log("[streamer-ai] ✓ Транскрипция сохранена в кэш для повторных запусков.", flush=True)

    (analysis_dir / "transcript.txt").write_text(transcript, encoding="utf-8")

    candidates = []
    if cache["candidates"].exists():
        try:
            cached_candidates = json.loads(cache["candidates"].read_text(encoding="utf-8"))
            if isinstance(cached_candidates, list) and cached_candidates:
                candidates = cached_candidates
                debug_log(
                    f"[progress] ♻ Использую сохранённый пул из {len(candidates)} моментов — повторно весь VOD не анализирую. (overall: 84.0%)",
                    flush=True,
                )
        except Exception as exc:
            debug_log(f"[streamer-ai] Кэш кандидатов не прочитан: {exc}", flush=True)

    if not candidates:
        chunks = split_transcript(transcript)
        video_duration = timeline_end
        scanned_duration = analysis_duration or full_duration
        # Long ranges need a large candidate pool. Rough target: at least one
        # candidate per ~3 minutes, or 3x the requested TOP count.
        pool_target = max(12, requested * 3, math.ceil(scanned_duration / 180.0) if scanned_duration else 12)
        pool_target = min(120, pool_target)
        per_chunk = max(4, min(12, math.ceil(pool_target / max(1, len(chunks)))))

        debug_log(
            f"[streamer-ai] Расшифровка: {len(chunks)} частей. "
            f"Цель — собрать до ~{pool_target} сильных кандидатов ({per_chunk} на часть).",
            flush=True,
        )

        all_candidates = []
        for i, chunk in enumerate(chunks, 1):
            p0 = 48 + ((i - 1) / len(chunks)) * 34
            debug_log(
                f"[progress] OpenAI ищет моменты по всему VOD: часть {i}/{len(chunks)} (overall: {p0:.1f}%)",
                flush=True,
            )
            try:
                found = core.find_highlights(
                    chunk,
                    dict(info),
                    per_chunk,
                    min_duration=min_duration,
                    max_duration=max_duration,
                )
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
            video_duration,
        )
        if not candidates:
            raise RuntimeError("После проверки длительности не осталось подходящих моментов.")

        # Keep the whole deduplicated pool. It can be reused when user later
        # changes only the desired TOP count.
        write_json(cache["candidates"], candidates)
        debug_log(
            f"[streamer-ai] ✓ Сохранён пул из {len(candidates)} моментов. "
            f"Можно менять TOP N без повторного анализа всего VOD.",
            flush=True,
        )

    debug_log(
        f"[progress] OpenAI выбирает TOP-{min(requested, len(candidates))} из {len(candidates)} кандидатов... (overall: 88.0%)",
        flush=True,
    )
    best = global_rank(core, candidates, min(requested, len(candidates)), info)

    def sig(h):
        return (
            str(h.get("start_time") or ""),
            str(h.get("end_time") or ""),
            str(h.get("title") or ""),
        )

    best_sigs = {sig(h) for h in best}
    alternatives = [
        h for h in sorted(candidates, key=lambda x: x.get("virality_score", 0), reverse=True)
        if sig(h) not in best_sigs
    ]

    # Strip internal ids from both lists before they reach UI/cache.
    for h in list(best) + alternatives:
        h.pop("_candidate_id", None)

    payload = {
        "schema_version": 2,
        "ok": True,
        "id": analysis_id,
        "video_info": info,
        "source_range": {
            "start": source_start,
            "end": source_end,
            "duration": analysis_duration,
            "limited": range_requested,
        },
        "min_duration": min_duration,
        "max_duration": max_duration,
        "top_count": len(best),
        "candidate_count": len(best) + len(alternatives),
        "highlights": best,
        "alternatives": alternatives,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (analysis_dir / "analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    cache_payload = dict(payload)
    cache_payload["cached"] = False
    cache_payload["cache_kind"] = "fresh"
    write_json(cache["analysis"], cache_payload)
    debug_log("[streamer-ai] ✓ AI-анализ сохранён. Повтор с теми же настройками будет без API.", flush=True)

    debug_log(
        f"[progress] Готово: TOP {len(best)} + ещё {len(alternatives)} подходящих моментов. (overall: 100.0%)",
        flush=True,
    )
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
