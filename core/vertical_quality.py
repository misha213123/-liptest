from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

VERTICAL_WIDTH = 1080
VERTICAL_HEIGHT = 1920
VERTICAL_ASPECT = "9:16"

# Conservative universal safe-zone defaults for TikTok / Shorts / Reels.
SAFE_LEFT = 96
SAFE_RIGHT = 180
SAFE_TOP = 150
SAFE_BOTTOM = 300


class VerticalValidationError(RuntimeError):
    pass


def _parse_fraction(value: Any) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        if "/" in raw:
            a, b = raw.split("/", 1)
            den = float(b or 0)
            return float(a or 0) / den if den else 0.0
        return float(raw)
    except Exception:
        return 0.0


def ffprobe_path_from_ffmpeg(ffmpeg_path: str | None = None) -> str:
    ffmpeg_path = str(ffmpeg_path or "ffmpeg")
    p = Path(ffmpeg_path)
    name = "ffprobe.exe" if p.name.lower().endswith(".exe") else "ffprobe"
    if p.parent and str(p.parent) not in ("", "."):
        return str(p.parent / name)
    return name


def probe_media(path: str | Path, ffprobe_path: str | None = None) -> dict:
    media_path = Path(path)
    if not media_path.exists():
        raise FileNotFoundError(f"Media file not found: {media_path}")

    probe = str(ffprobe_path or "ffprobe")
    cmd = [
        probe,
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(media_path),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-20:])
        raise RuntimeError(f"ffprobe failed for {media_path}:\n{tail}")

    data = json.loads(proc.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = data.get("format") or {}

    fps = _parse_fraction(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    bitrate_raw = video.get("bit_rate") or fmt.get("bit_rate") or 0
    try:
        bitrate = int(float(bitrate_raw or 0))
    except Exception:
        bitrate = 0
    try:
        duration = float(video.get("duration") or fmt.get("duration") or 0.0)
    except Exception:
        duration = 0.0

    return {
        "path": str(media_path),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": fps,
        "video_codec": str(video.get("codec_name") or ""),
        "pixel_format": str(video.get("pix_fmt") or ""),
        "audio_codec": str(audio.get("codec_name") or ""),
        "duration": duration,
        "bitrate": bitrate,
        "file_size": media_path.stat().st_size,
        "has_audio": bool(audio),
    }


def choose_output_fps(source_fps: float) -> float:
    """Keep a sane source FPS; otherwise use the short-form default of 30."""
    try:
        fps = float(source_fps or 0)
    except Exception:
        fps = 0.0
    if not math.isfinite(fps) or fps < 20.0 or fps > 60.0:
        return 30.0
    return fps


def _fmt_fps(value: float) -> str:
    if not value:
        return "0"
    rounded = round(value)
    if abs(value - rounded) < 0.01:
        return str(int(rounded))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _fmt_size(num_bytes: int) -> str:
    value = float(max(0, int(num_bytes or 0)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} GB"


def _fmt_bitrate(bits_per_second: int) -> str:
    if not bits_per_second:
        return "unknown"
    return f"{bits_per_second / 1_000_000:.2f} Mbps"


def validation_lines(info: dict, *, valid: bool) -> list[str]:
    return [
        "OUTPUT VALIDATION",
        f"Resolution: {info.get('width', 0)}x{info.get('height', 0)}",
        f"FPS: {_fmt_fps(float(info.get('fps') or 0))}",
        f"Video codec: {info.get('video_codec') or 'none'}",
        f"Audio codec: {info.get('audio_codec') or 'none'}",
        f"Pixel format: {info.get('pixel_format') or 'none'}",
        f"Duration: {float(info.get('duration') or 0):.2f}s",
        f"Bitrate: {_fmt_bitrate(int(info.get('bitrate') or 0))}",
        f"File size: {_fmt_size(int(info.get('file_size') or 0))}",
        f"VALID: {'YES' if valid else 'NO'}",
    ]


def validate_vertical_output(
    path: str | Path,
    *,
    ffprobe_path: str | None = None,
    expected_width: int = VERTICAL_WIDTH,
    expected_height: int = VERTICAL_HEIGHT,
    require_audio: bool = True,
    expected_fps: float | None = None,
    log: Callable[[str], None] | None = None,
) -> dict:
    info = probe_media(path, ffprobe_path=ffprobe_path)
    problems = []

    if info["width"] != int(expected_width) or info["height"] != int(expected_height):
        problems.append(
            f"resolution {info['width']}x{info['height']} != "
            f"{expected_width}x{expected_height}"
        )
    if info["video_codec"].lower() != "h264":
        problems.append(f"video codec is {info['video_codec'] or 'missing'}, expected h264")
    if info["pixel_format"].lower() != "yuv420p":
        problems.append(
            f"pixel format is {info['pixel_format'] or 'missing'}, expected yuv420p"
        )
    if require_audio and info["audio_codec"].lower() != "aac":
        problems.append(f"audio codec is {info['audio_codec'] or 'missing'}, expected aac")

    fps = float(info.get("fps") or 0)
    if fps < 20.0 or fps > 60.5:
        problems.append(f"fps is {fps:.3f}, expected a sane source fps or 30")
    if expected_fps is not None:
        target_fps = float(expected_fps or 0)
        # Fractional rates such as 29.970/59.940 need a small tolerance.
        if target_fps > 0 and abs(fps - target_fps) > 0.12:
            problems.append(
                f"fps is {fps:.3f}, expected {target_fps:.3f}"
            )

    valid = not problems
    info["valid"] = valid
    info["problems"] = problems

    lines = validation_lines(info, valid=valid)
    if log:
        for line in lines:
            log(line)

    if not valid:
        raise VerticalValidationError(
            "Invalid vertical output: " + "; ".join(problems)
        )
    return info


def render_header_lines(
    source: dict,
    *,
    renderer: str,
    layout: str,
    captions: bool,
    face_tracking: bool,
) -> list[str]:
    return [
        "=== VERTICAL RENDER ===",
        f"Input: {source.get('path') or ''}",
        f"Source resolution: {source.get('width', 0)}x{source.get('height', 0)}",
        f"Source FPS: {_fmt_fps(float(source.get('fps') or 0))}",
        f"Source codec: {source.get('video_codec') or 'unknown'}",
        f"Source bitrate: {_fmt_bitrate(int(source.get('bitrate') or 0))}",
        f"Output resolution: {VERTICAL_WIDTH}x{VERTICAL_HEIGHT}",
        f"Renderer: {renderer}",
        f"Layout: {layout}",
        f"Captions: {'ON' if captions else 'OFF'}",
        f"Face tracking: {'ON' if face_tracking else 'OFF'}",
    ]
