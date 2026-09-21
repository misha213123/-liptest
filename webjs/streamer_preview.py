#!/usr/bin/env python3
from __future__ import annotations

import json
import os
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
from core.local_media import is_local_source, probe_local_source, resolve_local_source
from utils.helpers import get_ffmpeg_path, get_ytdlp_path
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
    if len(sys.argv) < 4:
        raise SystemExit("Usage: streamer_preview.py <url> <timestamp> <result_json>")

    url = sys.argv[1].strip()
    timestamp = parse_time(sys.argv[2])
    result_json = Path(sys.argv[3]).resolve()
    local_source = is_local_source(url)

    if not local_source and not url.startswith(("http://", "https://")):
        raise ValueError("Нужна ссылка или загруженный локальный видеофайл")

    cfg = ConfigManager(APP_DIR / "config.json", APP_DIR / "output").config
    core = build_core(cfg)

    token = uuid.uuid4().hex[:16]
    preview_dir = APP_DIR / "output" / "streamer_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    sample_path = preview_dir / f"{token}_sample.mp4"
    image_path = preview_dir / f"{token}.jpg"

    start = max(0.0, timestamp)
    end = start + 3.0

    if local_source:
        downloaded = resolve_local_source(url)
        seek_in_downloaded = start
        debug_log(
            f"[streamer-preview] Локальный файл: беру кадр с {fmt_time(start)} без скачивания."
        )
    else:
        # A short section is enough for a stable preview frame and is much cheaper
        # than downloading the whole VOD.
        debug_log(f"[streamer-preview] Загружаю 3 сек. с {fmt_time(start)}")
        downloaded = core.download_video_section(
            url,
            fmt_time(start),
            fmt_time(end),
            str(sample_path),
            resolution="720p",
        )
        seek_in_downloaded = 1.0

    ffmpeg = get_ffmpeg_path()
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        f"{seek_in_downloaded:.3f}",
        "-i",
        str(downloaded),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(image_path),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if proc.returncode != 0 or not image_path.exists():
        raise RuntimeError("Не удалось получить кадр:\n" + "\n".join(proc.stderr.splitlines()[-20:]))

    info = {}
    try:
        info = probe_local_source(url) if local_source else core.fetch_video_info(url)
    except Exception as exc:
        debug_log(f"[streamer-preview] metadata warning: {exc}")

    if not local_source:
        try:
            Path(downloaded).unlink(missing_ok=True)
        except Exception:
            pass

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
