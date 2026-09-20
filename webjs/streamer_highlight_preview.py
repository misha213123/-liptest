#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
os.chdir(APP_DIR)

from openai import OpenAI

from clipper_core import AutoClipperCore
from config.config_manager import ConfigManager
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
        return max(
            0.0,
            float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2]),
        )
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
        ai_providers=providers or None,
        subtitle_language=cfg.get("subtitle_language", "ru-orig"),
    )


def main():
    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: streamer_highlight_preview.py <job.json> <result.json>"
        )

    job_path = Path(sys.argv[1]).resolve()
    result_path = Path(sys.argv[2]).resolve()
    job = json.loads(job_path.read_text(encoding="utf-8"))

    url = str(job.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Неверная ссылка Twitch/Kick/YouTube")

    start_sec = parse_time(job.get("start_time", 0))
    end_sec = parse_time(job.get("end_time", 0))
    if end_sec <= start_sec:
        raise ValueError("Конец предпросмотра должен быть позже начала")
    if end_sec - start_sec > 120:
        raise ValueError("Предпросмотр ограничен 120 секундами")

    cache_key = hashlib.sha256(
        f"{url}|{start_sec:.3f}|{end_sec:.3f}|v1".encode("utf-8")
    ).hexdigest()[:24]

    preview_dir = APP_DIR / "output" / "streamer_highlight_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    preview_path = preview_dir / f"{cache_key}.mp4"
    temp_source = preview_dir / f".{cache_key}_source.mp4"

    if preview_path.exists() and preview_path.stat().st_size > 10_000:
        payload = {
            "ok": True,
            "cached": True,
            "file": preview_path.name,
            "start_time": start_sec,
            "end_time": end_sec,
            "duration": end_sec - start_sec,
        }
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        debug_log(
            "[progress] Предпросмотр найден в кэше. (overall: 100.0%)",
            flush=True,
        )
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return

    cfg = ConfigManager(APP_DIR / "config.json", APP_DIR / "output").config
    core = build_core(cfg)

    debug_log(
        f"[progress] Загружаю момент {fmt_time(start_sec)} → "
        f"{fmt_time(end_sec)} для предпросмотра... (overall: 12.0%)",
        flush=True,
    )
    downloaded = core.download_video_section(
        url,
        fmt_time(start_sec),
        fmt_time(end_sec),
        str(temp_source),
        resolution="480p",
    )
    downloaded_path = Path(downloaded)

    debug_log(
        "[progress] Делаю лёгкий браузерный MP4... (overall: 72.0%)",
        flush=True,
    )
    ffmpeg = get_ffmpeg_path()
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(downloaded_path),
        "-vf",
        "scale=-2:480:flags=bicubic",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "27",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-movflags",
        "+faststart",
        str(preview_path),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=SUBPROCESS_FLAGS,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-30:])
        raise RuntimeError("Не удалось собрать предпросмотр:\n" + tail)

    if not preview_path.exists() or preview_path.stat().st_size < 10_000:
        raise RuntimeError("Предпросмотр не был создан")

    try:
        if downloaded_path.resolve() != preview_path.resolve():
            downloaded_path.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        temp_source.unlink(missing_ok=True)
    except Exception:
        pass

    payload = {
        "ok": True,
        "cached": False,
        "file": preview_path.name,
        "start_time": start_sec,
        "end_time": end_sec,
        "duration": end_sec - start_sec,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    debug_log("[progress] Предпросмотр готов. (overall: 100.0%)", flush=True)
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
