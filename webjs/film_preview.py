"""Create an actual preview frame from an imported Film Studio video.

This is a local 1-frame FFmpeg preview, NOT an AI/Video2X enhancement.
The browser draws a sample caption on top for instant template previews.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from film_render import (
    INPUT_DIR, FFMPEG, ROOT, _track_centres, probe, run, sec,
)
from core.streamer_export import ASPECT_PRESETS
from film_filters import color_filters


def render_preview(job: dict, output: Path) -> dict:
    input_id = str(job.get("input_id") or "")
    if not re.fullmatch(r"[a-f0-9]{24}\.(mp4|mkv|mov|webm|m4v)", input_id):
        raise ValueError("Предпросмотр доступен для импортированного файла.")
    source = INPUT_DIR / input_id
    if not source.is_file():
        raise ValueError("Исходный файл не найден. Импортируй видео заново.")
    dims = probe(source)
    ratio = str(job.get("ratio") or "9:16")
    if ratio not in ASPECT_PRESETS:
        raise ValueError("Неизвестный формат.")
    bx, by = ASPECT_PRESETS[ratio]
    iw, ih = dims["width"], dims["height"]
    crop_w = min(iw, int(ih * bx / by))
    crop_h = min(ih, int(iw * by / bx))
    crop_w = max(2, crop_w - crop_w % 2)
    crop_h = max(2, crop_h - crop_h % 2)
    start = sec(job.get("start", 0))
    end = sec(job.get("end", start + 5))
    if start < 0 or end <= start:
        raise ValueError("Укажи правильный диапазон времени.")
    if dims["duration"] and start >= dims["duration"]:
        raise ValueError("Таймкод вне видео.")
    try:
        position = float(job.get("preview_position", 50))
    except (TypeError, ValueError) as exc:
        raise ValueError("Позиция кадра должна быть от 0 до 100%.") from exc
    if not 0 <= position <= 100:
        raise ValueError("Позиция кадра должна быть от 0 до 100%.")
    # Use the middle of the selected scene rather than its opening seconds:
    # those often contain a black cut or transition.
    frame_time = start + (end - start) * position / 100.0
    if dims["duration"]:
        frame_time = min(frame_time, max(0, dims["duration"] - 0.12))
    frame_time = max(0, frame_time)
    center_x, center_y = iw / 2, ih / 2
    detected = False
    if bool(job.get("face_tracking", True)):
        track_start = max(0, frame_time - 0.65)
        points = _track_centres(source, track_start, max(.05, frame_time - track_start), iw, ih)
        if points:
            detected = True
            # Last sampled point corresponds to the requested preview moment,
            # not the beginning of the tracking window.
            center_x = points[-1][1]
            center_y = points[-1][2]
        # This does not claim a face if Haar returned only fallback positions.
        # The full render logs the actual number of faces detected.
    x = min(iw - crop_w, max(0, round(center_x - crop_w / 2)))
    y = min(ih - crop_h, max(0, round(center_y - crop_h / 2)))
    w = 360
    h = max(2, int(round(w * by / bx / 2) * 2))
    filters = [f"crop={crop_w}:{crop_h}:{x}:{y}", f"scale={w}:{h}:flags=lanczos"]
    filters.extend(color_filters(job, preview=True))
    output.parent.mkdir(parents=True, exist_ok=True)
    run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
        "-ss", str(frame_time), "-i", str(source), "-frames:v", "1",
        "-vf", ",".join(filters), "-q:v", "3", str(output)
    ], timeout=75)
    if not output.exists() or output.stat().st_size < 500:
        raise RuntimeError("FFmpeg не смог сформировать миниатюру.")
    return {"ok": True, "width": w, "height": h,
            "at": round(frame_time, 3), "face_detected": detected,
            "source_width": iw, "source_height": ih,
            "crop_width": crop_w, "crop_height": crop_h}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: film_preview.py job.json output.jpg")
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = render_preview(payload, Path(sys.argv[2]))
    print(json.dumps(result, ensure_ascii=False))
