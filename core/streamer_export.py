"""Streamer Clips output presets and high quality FFmpeg export.

Only standard FFmpeg filters are used. "Ultra" is high-quality encoding and
Lanczos scaling, NOT CapCut's proprietary AI super-resolution model.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

ASPECT_PRESETS = {
    "9:16": (1080, 1920),
    "4:5": (1080, 1350),
    "5:4": (1350, 1080),
    "1:1": (1080, 1080),
    "3:4": (1080, 1440),
    "2:3": (1080, 1620),
    "4:3": (1440, 1080),
    "16:9": (1920, 1080),
    "21:9": (2520, 1080),
}
SIZES = (1080, 1440, 2160)
FPS_OPTIONS = ("source", "30", "60")
QUALITY_OPTIONS = ("high", "ultra")
MOTION_OPTIONS = ("off", "optical")


def export_settings(job: dict) -> dict:
    """Allowlist output options; never insert raw user-provided FFmpeg flags."""
    ratio = str(job.get("output_ratio") or "9:16")
    if ratio not in ASPECT_PRESETS:
        raise ValueError(f"Формат кадра не поддерживается: {ratio}")
    try:
        size = int(job.get("output_size") or 1080)
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректный размер экспорта") from exc
    if size not in SIZES:
        raise ValueError(f"Размер экспорта не поддерживается: {size}")
    fps = str(job.get("output_fps") or "source")
    if fps not in FPS_OPTIONS:
        raise ValueError(f"FPS не поддерживается: {fps}")
    quality = str(job.get("output_quality") or "ultra")
    if quality not in QUALITY_OPTIONS:
        raise ValueError(f"Качество не поддерживается: {quality}")
    motion = str(job.get("motion_mode") or "off")
    if motion not in MOTION_OPTIONS:
        raise ValueError(f"Режим плавности не поддерживается: {motion}")
    base_w, base_h = ASPECT_PRESETS[ratio]
    width = int(round(base_w * size / 1080))
    height = int(round(base_h * size / 1080))
    width += width % 2
    height += height % 2
    return {
        "ratio": ratio, "width": width, "height": height, "size": size,
        "fps": fps, "quality": quality, "motion": motion,
    }


def intermediate_encoder_args(gpu_args: list[str], quality: str) -> list[str]:
    """Keep intermediate generations near visually-lossless, including CPU fallback."""
    if any("nvenc" in arg for arg in (gpu_args or [])):
        return [
            "-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq",
            "-rc", "vbr", "-cq", "15" if quality == "ultra" else "18",
            "-b:v", "0", "-spatial-aq", "1",
        ]
    return [
        "-c:v", "libx264", "-preset", "slow" if quality == "ultra" else "medium",
        "-crf", "14" if quality == "ultra" else "17",
    ]


def probe_fps(ffmpeg_path: str, video: Path) -> float:
    """Detect source FPS with ffprobe, or OpenCV if ffprobe is not installed."""
    ffmpeg = Path(ffmpeg_path)
    ffprobe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    executable = str(ffprobe) if ffprobe.exists() else "ffprobe"
    try:
        p = subprocess.run([
            executable, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=avg_frame_rate,r_frame_rate",
            "-of", "json", str(video)
        ], capture_output=True, text=True, timeout=20)
        if p.returncode == 0:
            streams = json.loads(p.stdout or "{}").get("streams") or []
            if streams:
                frame_rate = streams[0].get("avg_frame_rate") or streams[0].get("r_frame_rate")
                fps = float(Fraction(str(frame_rate)))
                if 1 <= fps <= 240:
                    return fps
    except (OSError, ValueError, ZeroDivisionError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    try:
        import cv2
        cap = cv2.VideoCapture(str(video))
        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS))
        finally:
            cap.release()
        return fps if 1 <= fps <= 240 else 0.0
    except (ImportError, OSError, ValueError):
        return 0.0


def final_export(
    ffmpeg_path: str, composed_path: Path, output_path: Path, settings: dict,
    log=None,
) -> dict:
    """Preserve the source FPS without a needless encode, or opt into CFR / MCI."""
    log = log or (lambda message: None)
    fps_before = probe_fps(ffmpeg_path, composed_path)
    fps_text = settings["fps"]
    requested = float(fps_text) if fps_text != "source" else 0.0
    if not requested or (fps_before and abs(fps_before - requested) < 0.25):
        shutil.copy2(composed_path, output_path)
        log(f"[export] Без повторного кодирования; исходный FPS: {fps_before or 'не определён'}")
        return {"fps_before": fps_before, "interpolated": False, "reencoded": False}

    filters = []
    optical = settings["motion"] == "optical" and bool(fps_before) and fps_before < requested - 0.25
    if optical:
        filters.append(
            f"minterpolate=fps={int(requested)}:mi_mode=mci:"
            "mc_mode=aobmc:me_mode=bidir"
        )
        log("[export] Optical flow: новые промежуточные кадры (нагрузка на CPU высокая)")
    else:
        filters.append(f"fps={int(requested)}")
        if settings["motion"] == "optical" and not fps_before:
            log("[export] Частота источника неизвестна; обычное CFR без optical flow")
    filters.extend(["setsar=1", "format=yuv420p"])
    quality = settings["quality"]
    args = [
        ffmpeg_path, "-y", "-i", str(composed_path),
        "-map", "0:v:0", "-map", "0:a?",
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "slow" if quality == "ultra" else "medium",
        "-crf", "15" if quality == "ultra" else "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
        "-movflags", "+faststart", str(output_path),
    ]
    proc = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=7200, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if proc.returncode:
        tail = "\n".join(proc.stderr.splitlines()[-25:])
        raise RuntimeError("Финальный FFmpeg экспорт не удался:\n" + tail)
    if not output_path.exists() or output_path.stat().st_size < 10000:
        raise RuntimeError("Итоговый файл пуст или не создан")
    return {"fps_before": fps_before, "interpolated": optical, "reencoded": True}
