from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path
from typing import Callable, Dict, Tuple


class StreamerLayoutError(RuntimeError):
    pass


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def normalize_rect(rect: Dict[str, float]) -> Dict[str, float]:
    """Validate a normalized webcam crop rectangle."""
    x = clamp(rect.get("x", 0.0), 0.0, 1.0)
    y = clamp(rect.get("y", 0.0), 0.0, 1.0)
    w = clamp(rect.get("w", 0.25), 0.03, 1.0)
    h = clamp(rect.get("h", 0.25), 0.03, 1.0)

    if x + w > 1.0:
        w = max(0.03, 1.0 - x)
    if y + h > 1.0:
        h = max(0.03, 1.0 - y)

    if w < 0.03 or h < 0.03:
        raise StreamerLayoutError("Рамка веб-камеры слишком маленькая.")

    return {"x": x, "y": y, "w": w, "h": h}


def probe_video_size(video_path: str) -> Tuple[int, int]:
    try:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise StreamerLayoutError(f"Не удалось открыть видео: {video_path}")
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        if width <= 0 or height <= 0:
            raise StreamerLayoutError("Не удалось определить размер исходного видео.")
        return width, height
    except ImportError as exc:
        raise StreamerLayoutError("OpenCV не установлен.") from exc


class StreamerLayoutRenderer:
    """Render webcam-over-game vertical clips from a normal streamer recording."""

    def __init__(
        self,
        ffmpeg_path: str,
        encoder_args=None,
        log: Callable[[str], None] | None = None,
    ):
        self.ffmpeg_path = ffmpeg_path
        self.encoder_args = list(encoder_args or ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
        self.log = log or (lambda message: None)

    def render(
        self,
        input_path: str,
        output_path: str,
        webcam_rect: Dict[str, float],
        *,
        output_width: int = 1080,
        output_height: int = 1920,
        webcam_height_pct: float = 0.365,
        gameplay_center_x: float = 0.50,
        webcam_padding: int = 0,
        progress_callback: Callable[[float], None] | None = None,
    ) -> str:
        input_path = str(Path(input_path).resolve())
        output_path = str(Path(output_path).resolve())
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        source_w, source_h = probe_video_size(input_path)
        rect = normalize_rect(webcam_rect)

        webcam_height_pct = clamp(webcam_height_pct, 0.22, 0.50)
        gameplay_center_x = clamp(gameplay_center_x, 0.0, 1.0)
        webcam_padding = max(0, min(int(webcam_padding), 80))

        top_h = int(round(output_height * webcam_height_pct))
        top_h -= top_h % 2
        game_h = output_height - top_h
        game_h -= game_h % 2
        top_h = output_height - game_h

        cam_x = max(0, min(source_w - 2, int(round(rect["x"] * source_w))))
        cam_y = max(0, min(source_h - 2, int(round(rect["y"] * source_h))))
        cam_w = max(2, min(source_w - cam_x, int(round(rect["w"] * source_w))))
        cam_h = max(2, min(source_h - cam_y, int(round(rect["h"] * source_h))))
        cam_w -= cam_w % 2
        cam_h -= cam_h % 2

        # Bottom gameplay panel uses full source height and crops horizontally to
        # the aspect ratio required by its slot. This usually removes side chat /
        # facecam overlays without tracking the game every frame.
        game_aspect = output_width / float(game_h)
        game_crop_w = min(source_w, int(round(source_h * game_aspect)))
        game_crop_w = max(2, game_crop_w - (game_crop_w % 2))
        max_game_x = max(0, source_w - game_crop_w)
        game_x = int(round(max_game_x * gameplay_center_x))
        game_x = max(0, min(max_game_x, game_x))
        game_x -= game_x % 2

        pad = webcam_padding
        inner_w = max(2, output_width - pad * 2)
        inner_h = max(2, top_h - pad * 2)

        filter_complex = (
            f"[0:v]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},"
            f"scale={inner_w}:{inner_h}:force_original_aspect_ratio=increase,"
            f"crop={inner_w}:{inner_h},"
            f"pad={output_width}:{top_h}:{pad}:{pad}:black[cam];"
            f"[0:v]crop={game_crop_w}:{source_h}:{game_x}:0,"
            f"scale={output_width}:{game_h}:flags=lanczos[game];"
            f"[cam][game]vstack=inputs=2[v]"
        )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i",
            input_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            *self.encoder_args,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            output_path,
        ]

        self.log(
            "  Streamer layout: "
            f"webcam=({cam_x},{cam_y},{cam_w},{cam_h}), "
            f"game_x={game_x}, top={top_h}px, bottom={game_h}px"
        )
        self.log("  FFmpeg: " + " ".join(cmd))

        if progress_callback:
            progress_callback(0.05)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        _, stderr = proc.communicate()

        if proc.returncode != 0:
            tail = "\n".join((stderr or "").splitlines()[-35:])
            raise StreamerLayoutError(f"FFmpeg не смог собрать Streamer Layout:\n{tail}")

        if not Path(output_path).exists() or Path(output_path).stat().st_size < 10_000:
            raise StreamerLayoutError("FFmpeg завершился без итогового видео.")

        if progress_callback:
            progress_callback(1.0)
        return output_path
