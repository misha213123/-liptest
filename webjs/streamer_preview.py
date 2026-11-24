#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import os
import subprocess
import sys
import traceback
import uuid
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
os.chdir(APP_DIR)

# Heavy AI/video dependencies are loaded only if the fast frame method fails.
from utils.helpers import get_ffmpeg_path, get_ytdlp_path, get_deno_path, get_app_dir
import yt_dlp
from utils.logger import debug_log


def parse_time(value: str) -> float:
    raw = str(value or "0").strip().replace(",", ".")
    if not raw:
        return 0.0
    if ":" not in raw:
        return max(0.0, float(raw))
    parts = raw.split(":")
    if len(parts) == 2:
        return max(0.0, float(parts[0]) * 60 + float(parts[1]))
    if len(parts) == 3:
        return max(0.0, float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2]))
    raise ValueError("Неверный таймкод")


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def build_core(cfg: dict):
    from openai import OpenAI
    from clipper_core import AutoClipperCore
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
        ai_providers=providers or None,
        subtitle_language=cfg.get("subtitle_language", "ru-orig"),
    )


def fast_source_frame(url: str, timestamp: float, image_path: Path) -> dict:
    """Extract one preview JPEG from a source video stream without downloading a clip."""
    opts = {
        "format": "bestvideo[height<=720]/best[height<=720]/bestvideo/best",
        "skip_download": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 20,
        "retries": 2,
    }
    is_youtube = "youtube.com" in url or "youtu.be" in url
    if is_youtube:
        deno = get_deno_path()
        if deno and Path(deno).exists():
            opts["js_runtimes"] = {"deno": {"path": deno}}
            opts["remote_components"] = ["ejs:github"]
        opts["extractor_args"] = {"youtube": {"player_client": ["default", "-web_embedded"]}}
    app_dir = get_app_dir()
    for cookie_path in (app_dir / "cookies.txt", Path("cookies.txt")):
        if cookie_path.is_file() and cookie_path.stat().st_size > 0:
            opts["cookiefile"] = str(cookie_path)
            break

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        raise RuntimeError("Не удалось получить данные видео.")

    # yt-dlp may put chosen stream in requested_formats or directly in info.
    selected = next(
        (fmt for fmt in info.get("requested_formats", [])
         if fmt.get("vcodec") != "none" and fmt.get("url")), info
    )
    media_url = selected.get("url")
    if not media_url:
        raise RuntimeError("Источник не предоставил адрес видеопотока.")
    headers = selected.get("http_headers") or info.get("http_headers") or {}
    header_string = "".join(
        f"{name}: {value}\r\n"
        for name, value in headers.items()
        if name.lower() not in ("host", "content-length", "range")
    )
    cmd = [
        get_ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
        "-rw_timeout", "20000000",
        "-ss", str(timestamp),
    ]
    if header_string:
        cmd += ["-headers", header_string]
    cmd += [
        "-i", str(media_url), "-map", "0:v:0", "-frames:v", "1",
        "-q:v", "2", str(image_path),
    ]
    debug_log(f"[streamer-preview] Быстрый кадр по таймкоду {fmt_time(timestamp)} (без загрузки видео)")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=55, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Быстрое получение кадра превысило 55 секунд") from exc
    if proc.returncode != 0 or not image_path.is_file() or image_path.stat().st_size < 100:
        # Signed media URLs may be in FFmpeg errors: never echo them to the UI/log.
        tail = "\n".join((proc.stderr or "").splitlines()[-4:])
        tail = re.sub(r"https?://\S+", "[media URL]", tail)
        raise RuntimeError("FFmpeg не получил кадр напрямую: " + tail[-500:])

    return {
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": float(info.get("duration") or 0),
    }


def main():
    if len(sys.argv) < 4:
        raise SystemExit("Usage: streamer_preview.py <url> <timestamp> <result_json>")

    url = sys.argv[1].strip()
    timestamp = parse_time(sys.argv[2])
    result_json = Path(sys.argv[3]).resolve()

    if not url.startswith(("http://", "https://")):
        raise ValueError("Нужна ссылка Twitch, Kick или YouTube")

    token = uuid.uuid4().hex[:16]
    preview_dir = APP_DIR / "output" / "streamer_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    sample_path = preview_dir / f"{token}_sample.mp4"
    image_path = preview_dir / f"{token}.jpg"

    start = max(0.0, timestamp)
    info = {}
    try:
        info = fast_source_frame(url, start, image_path)
    except Exception as direct_exc:
        debug_log(f"[streamer-preview] Быстрый кадр недоступен: {str(direct_exc)[:400]}")
        debug_log("[streamer-preview] Резервный способ: короткий 3-секундный фрагмент.")
        from config.config_manager import ConfigManager
        cfg = ConfigManager(APP_DIR / "config.json", APP_DIR / "output").config
        core = build_core(cfg)
        end = start + 3.0
        # The normal section downloader is the compatibility fallback for
        # extractors that cannot seek directly to a remote frame.
        downloaded = core.download_video_section(
            url, fmt_time(start), fmt_time(end), str(sample_path),
            resolution="360p",
        )
        cmd = [
            get_ffmpeg_path(), "-y", "-nostdin", "-loglevel", "error",
            "-ss", "1.0", "-i", str(downloaded),
            "-map", "0:v:0", "-frames:v", "1", "-q:v", "2", str(image_path),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if proc.returncode or not image_path.is_file():
                tail = re.sub(r"https?://\S+", "[media URL]", (proc.stderr or "")[-600:])
                raise RuntimeError("Не удалось получить кадр из фрагмента: " + tail)
        finally:
            Path(downloaded).unlink(missing_ok=True)
        try:
            info = core.fetch_video_info(url)
        except Exception as exc:
            debug_log(f"[streamer-preview] Метаданные недоступны: {str(exc)[:200]}")

    payload = {
        "ok": True,
        "token": token,
        "image_name": image_path.name,
        "title": info.get("title", ""),
        "channel": info.get("channel", ""),
        "duration": info.get("duration", 0),
        "timestamp": start,
    }
    result_json.parent.mkdir(parents=True, exist_ok=True)
    result_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        try:
            if len(sys.argv) >= 4:
                Path(sys.argv[3]).write_text(
                    json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
                    encoding="utf-8",
                )
        except Exception:
            pass
        sys.exit(1)
