#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import traceback
import uuid
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
os.chdir(APP_DIR)

from openai import OpenAI

from clipper_core import AutoClipperCore
from config.config_manager import ConfigManager
from core.streamer_layout import StreamerLayoutRenderer
from utils.helpers import get_ffmpeg_path, get_ytdlp_path
from utils.logger import debug_log

SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def parse_time(value) -> float:
    raw = str(value or "0").strip().replace(",", ".")
    if ":" not in raw:
        return max(0.0, float(raw or 0))
    parts = raw.split(":")
    if len(parts) == 2:
        return max(0.0, float(parts[0]) * 60 + float(parts[1]))
    if len(parts) == 3:
        return max(0.0, float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2]))
    raise ValueError(f"Неверный таймкод: {value}")


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def build_core(cfg: dict) -> AutoClipperCore:
    providers = cfg.get("ai_providers") or {}
    hf = providers.get("highlight_finder") or {}
    client = OpenAI(
        api_key=hf.get("api_key") or cfg.get("api_key") or "x",
        base_url=hf.get("base_url") or cfg.get("base_url") or "https://api.openai.com/v1",
    )
    return AutoClipperCore(
        client=client,
        ffmpeg_path=get_ffmpeg_path(),
        ytdlp_path=get_ytdlp_path(),
        output_dir=str(APP_DIR / "output"),
        model=hf.get("model") or cfg.get("model", "gpt-4.1"),
        temperature=cfg.get("temperature", 1.0),
        subtitle_style=cfg.get("subtitle_style", "pop"),
        subtitle_settings=cfg.get("subtitle_settings"),
        subtitle_language=cfg.get("subtitle_language", "ru-orig"),
        subtitle_sync_offset=cfg.get("subtitle_sync_offset", 0),
        ai_providers=providers or None,
    )


def tune_encoder_args(args: list[str]) -> list[str]:
    """Use visibly higher quality for the webcam crop and final text burn."""
    out = list(args or [])
    joined = " ".join(out)

    def replace_value(flag: str, value: str):
        if flag in out:
            idx = out.index(flag)
            if idx + 1 < len(out):
                out[idx + 1] = value

    if "h264_nvenc" in joined or "hevc_nvenc" in joined:
        replace_value("-cq", "18")
        replace_value("-b:v", "8M")
        replace_value("-maxrate", "12M")
        replace_value("-bufsize", "20M")
        replace_value("-preset", "p5")
    elif "libx264" in joined:
        replace_value("-crf", "18")
        replace_value("-preset", "medium")
    return out


def split_title(text: str) -> tuple[str, str]:
    """Split a short hook into two visually balanced lines."""
    clean = re.sub(r"\s+", " ", str(text or "").strip()).upper()
    clean = clean.replace("{", "").replace("}", "").replace("\\", "")
    words = clean.split()[:6]
    if not words:
        return "", ""
    if len(words) == 1:
        return words[0], ""

    # Choose the split with the smallest difference in character width.
    best_idx = 1
    best_score = None
    for i in range(1, len(words)):
        a = " ".join(words[:i])
        b = " ".join(words[i:])
        score = abs(len(a) - len(b))
        if best_score is None or score < best_score:
            best_score = score
            best_idx = i
    return " ".join(words[:best_idx]), " ".join(words[best_idx:])


def ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def create_streamer_ass(
    core: AutoClipperCore,
    source_path: Path,
    out_dir: Path,
    *,
    captions: bool,
    title_text: str,
    title_enabled: bool,
    title_duration: float,
    webcam_height_pct: float,
) -> Path | None:
    if not captions and not title_enabled:
        return None

    ass_file = out_dir / "streamer_text.ass"

    if captions:
        audio_file = out_dir / "captions_audio.wav"
        cmd = [
            get_ffmpeg_path(), "-y",
            "-i", str(source_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            str(audio_file),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=SUBPROCESS_FLAGS,
        )
        if result.returncode != 0 or not audio_file.exists():
            raise RuntimeError("Не удалось извлечь аудио для субтитров.")

        debug_log("[streamer] Субтитры: пробую Faster-Whisper на GPU...", flush=True)
        try:
            transcript = core.transcribe_words(
                str(audio_file),
                allow_cpu_fallback=False,
            )
        except Exception as exc:
            debug_log(
                f"[streamer] GPU Faster-Whisper недоступен: {exc}",
                flush=True,
            )
            debug_log(
                "[streamer] CPU medium пропускаю — использую OpenAI Whisper API "
                "с word timestamps для быстрого рендера.",
                flush=True,
            )
            transcript = core._whisper_transcribe_words_api(str(audio_file))

        sync_offset = float(getattr(core, "subtitle_sync_offset", 0.0) or 0.0)
        sync_offset = max(-1.0, min(1.0, sync_offset))
        subtitle_cfg = dict(getattr(core, "subtitle_settings", {}) or {})
        lead_seconds = max(0.0, min(0.60, float(subtitle_cfg.get("lead_seconds", 0.22) or 0.0)))
        effective_lead = 0.0 if abs(sync_offset) >= 0.15 else lead_seconds
        ass_offset = sync_offset - effective_lead

        if getattr(core, "subtitle_style", "pop") == "karaoke":
            core.create_ass_subtitle_karaoke(transcript, str(ass_file), ass_offset)
        else:
            core.create_ass_subtitle_capcut(transcript, str(ass_file), ass_offset)
    else:
        ass_file.write_text(
            """[Script Info]
Title: Streamer title
ScriptType: v4.00+
WrapStyle: 2
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,70,&H00FFFFFF,&H00FFFFFF,&H00000000,&H60000000,-1,0,0,0,100,100,0,0,1,5,1,2,60,60,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""",
            encoding="utf-8",
        )

    if title_enabled and title_text.strip():
        top, bottom = split_title(title_text)
        if top:
            # IMPORTANT: when captions are enabled the ASS canvas is 720x1280,
            # otherwise this title-only file is 1080x1920. Use the matching
            # coordinate system so the hook is always truly centered.
            canvas_w, canvas_h = ((720, 1280) if captions else (1080, 1920))
            center_x = canvas_w // 2
            center_y = canvas_h // 2

            longest = max(len(top), len(bottom or ""))
            if canvas_w == 720:
                font_size = 54 if longest <= 13 else 48 if longest <= 17 else 42
                outline = 4
            else:
                font_size = 82 if longest <= 13 else 72 if longest <= 17 else 62
                outline = 6

            duration = max(1.2, min(3.5, float(title_duration or 2.3)))
            base = (
                r"{\an5\pos(" + str(center_x) + "," + str(center_y) + r")"
                r"\fnArial Black\b1\fs" + str(font_size)
                + r"\bord" + str(outline) + r"\shad1\fscx96\fscy96"
            )
            if bottom:
                title_ass = (
                    base
                    + r"\c&H0000FF&}" + top
                    + r"\N{\c&HFFFFFF&}" + bottom
                )
            else:
                title_ass = base + r"\c&H0000FF&}" + top

            with ass_file.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"Dialogue: 10,{ass_time(0)},{ass_time(duration)},Default,,0,0,0,,{title_ass}\n"
                )

    return ass_file


def burn_ass(core: AutoClipperCore, input_path: Path, output_path: Path, ass_file: Path, encoder_args: list[str]) -> None:
    escaped = str(ass_file).replace("\\", "/").replace(":", "\\:")
    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", str(input_path),
        "-vf", f"ass='{escaped}'",
        *encoder_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    debug_log("[streamer] Burn subtitles + 2s title in one pass.", flush=True)
    result = core._run_ffmpeg_subprocess(cmd, timeout=900)
    if result.returncode != 0:
        tail = "\n".join((result.stderr or "").splitlines()[-30:])
        raise RuntimeError("Не удалось прожечь текст:\n" + tail)


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Usage: streamer_render.py <job.json> <result.json>")

    job_path = Path(sys.argv[1]).resolve()
    result_path = Path(sys.argv[2]).resolve()
    job = json.loads(job_path.read_text(encoding="utf-8"))

    url = str(job.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Неверная ссылка Twitch/Kick/YouTube")

    start_sec = parse_time(job.get("start_time", 0))
    end_sec = parse_time(job.get("end_time", 0))
    if end_sec <= start_sec:
        raise ValueError("Конец клипа должен быть позже начала")
    if end_sec - start_sec > 15 * 60:
        raise ValueError("Один клип пока ограничен 15 минутами")

    webcam_rect = dict(job.get("webcam_rect") or {})
    top_pct = float(job.get("webcam_height_pct", 0.365) or 0.365)
    game_center_x = float(job.get("gameplay_center_x", 0.50) or 0.50)
    captions = bool(job.get("captions", True))
    title_enabled = bool(job.get("title_enabled", True))
    title_text = str(job.get("title_text") or "").strip()
    title_duration = float(job.get("title_duration", 2.3) or 2.3)

    clip_id = str(job.get("id") or uuid.uuid4().hex[:12])
    out_dir = APP_DIR / "output" / "streamer_clips" / clip_id
    out_dir.mkdir(parents=True, exist_ok=True)

    source_path = out_dir / "source_16x9.mp4"
    layout_path = out_dir / "layout_9x16.mp4"
    final_path = out_dir / "final_9x16.mp4"

    cfg = ConfigManager(APP_DIR / "config.json", APP_DIR / "output").config
    core = build_core(cfg)

    debug_log("[progress] Загружаю выбранный момент... (overall: 5.0%)", flush=True)
    debug_log(f"[streamer] {fmt_time(start_sec)} -> {fmt_time(end_sec)}", flush=True)
    core.download_video_section(
        url,
        fmt_time(start_sec),
        fmt_time(end_sec),
        str(source_path),
        resolution=str(job.get("resolution") or "auto"),
    )

    debug_log("[progress] Собираю webcam + gameplay... (overall: 35.0%)", flush=True)
    core.enable_gpu_acceleration(bool(job.get("gpu", True)))
    encoder_args = tune_encoder_args(core.get_video_encoder_args())

    renderer = StreamerLayoutRenderer(
        ffmpeg_path=get_ffmpeg_path(),
        encoder_args=encoder_args,
        log=lambda m: debug_log(m, flush=True),
    )
    renderer.render(
        str(source_path),
        str(layout_path),
        webcam_rect,
        webcam_height_pct=top_pct,
        gameplay_center_x=game_center_x,
        webcam_padding=int(job.get("webcam_padding", 0) or 0),
    )

    ass_file = None
    if captions or (title_enabled and title_text):
        debug_log("[progress] Готовлю субтитры и заголовок... (overall: 70.0%)", flush=True)
        ass_file = create_streamer_ass(
            core,
            source_path,
            out_dir,
            captions=captions,
            title_text=title_text,
            title_enabled=title_enabled,
            title_duration=title_duration,
            webcam_height_pct=top_pct,
        )

    if ass_file:
        debug_log("[progress] Прожигаю текст... (overall: 88.0%)", flush=True)
        burn_ass(core, layout_path, final_path, ass_file, encoder_args)
    else:
        shutil.copy2(layout_path, final_path)

    if not final_path.exists() or final_path.stat().st_size < 10_000:
        raise RuntimeError("Итоговый 9:16 файл не создан")

    meta = {
        "id": clip_id,
        "url": url,
        "start_time": start_sec,
        "end_time": end_sec,
        "webcam_rect": webcam_rect,
        "webcam_height_pct": top_pct,
        "gameplay_center_x": game_center_x,
        "captions": captions,
        "title_enabled": title_enabled,
        "title_text": title_text,
        "title_duration": title_duration,
        "source_file": source_path.name,
        "layout_file": layout_path.name,
        "final_file": final_path.name,
    }
    (out_dir / "streamer_job.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    payload = {
        "ok": True,
        "id": clip_id,
        "output_dir": str(out_dir),
        "source_file": source_path.name,
        "final_file": final_path.name,
        "title_text": title_text,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    debug_log("[progress] Streamer Clip готов. (overall: 100.0%)", flush=True)
    debug_log(f"[output] {final_path}", flush=True)
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
