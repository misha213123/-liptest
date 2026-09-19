#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
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
        model=cfg.get("model", "gpt-4.1"),
        temperature=cfg.get("temperature", 1.0),
        subtitle_style=cfg.get("subtitle_style", "pop"),
        subtitle_settings=cfg.get("subtitle_settings"),
        subtitle_language=cfg.get("subtitle_language", "ru-orig"),
        subtitle_sync_offset=cfg.get("subtitle_sync_offset", 0),
        ai_providers=providers or None,
    )


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
        resolution=str(job.get("resolution") or "1080p"),
    )

    debug_log("[progress] Собираю webcam + gameplay... (overall: 35.0%)", flush=True)

    # Prefer GPU when it is healthy, but StreamerLayoutRenderer has its own CPU
    # retry so this mode remains reliable on Windows FFmpeg builds.
    core.enable_gpu_acceleration(bool(job.get("gpu", True)))
    encoder_args = core.get_video_encoder_args()

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

    if captions:
        debug_log("[progress] Добавляю субтитры... (overall: 70.0%)", flush=True)
        core.add_captions_api_with_progress(
            str(layout_path),
            str(final_path),
            audio_source=str(source_path),
            time_offset=0,
            progress_callback=lambda p: debug_log(
                f"[progress] Субтитры {int(p * 100)}% (overall: {70 + p * 28:.1f}%)",
                flush=True,
            ),
            source_start_sec=0.0,
            source_end_sec=end_sec - start_sec,
        )
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
