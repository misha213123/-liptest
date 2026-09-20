from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable


class IRLLayoutError(RuntimeError):
    pass


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


class IRLLayoutRenderer:
    """Build a TikTok/Reels style 9:16 IRL layout.

    The original frame stays sharp and fully visible in the foreground.
    Empty space above/below (or at the sides for unusual sources) is filled
    with a blurred, slightly dimmed copy of the same video.
    """

    def __init__(
        self,
        ffmpeg_path: str,
        encoder_args=None,
        log: Callable[[str], None] | None = None,
    ):
        self.ffmpeg_path = ffmpeg_path
        self.encoder_args = list(
            encoder_args
            or ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
        )
        self.log = log or (lambda message: None)

    def render(
        self,
        input_path: str,
        output_path: str,
        *,
        output_width: int = 1080,
        output_height: int = 1920,
        foreground_y_pct: float = 0.48,
        background_blur: float = 18.0,
        background_brightness: float = -0.08,
        progress_callback: Callable[[float], None] | None = None,
    ) -> str:
        input_path = str(Path(input_path).resolve())
        output_path = str(Path(output_path).resolve())
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        foreground_y_pct = _clamp(foreground_y_pct, 0.10, 0.90)
        background_blur = _clamp(background_blur, 4.0, 40.0)
        background_brightness = _clamp(background_brightness, -0.35, 0.15)

        # Blur a small background first, then upscale it. It is much faster on
        # local machines and visually gives the same soft TikTok background.
        bg_w = 360
        bg_h = 640

        filter_complex = (
            "[0:v]split=2[bg0][fg0];"
            f"[bg0]scale={bg_w}:{bg_h}:force_original_aspect_ratio=increase:"
            "flags=bicubic,"
            f"crop={bg_w}:{bg_h},"
            f"gblur=sigma={background_blur:.2f},"
            f"eq=brightness={background_brightness:.3f}:saturation=0.90,"
            f"scale={output_width}:{output_height}:flags=bicubic,setsar=1[bg];"
            f"[fg0]scale={output_width}:{output_height}:"
            "force_original_aspect_ratio=decrease:"
            "flags=lanczos+accurate_rnd+full_chroma_int,"
            "setsar=1,unsharp=5:5:0.25:5:5:0.00[fg];"
            f"[bg][fg]overlay=x='(W-w)/2':"
            f"y='max(0,min(H-h,H*{foreground_y_pct:.4f}-h/2))':"
            "eof_action=pass,setsar=1,format=yuv420p[v]"
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
            "  IRL layout: "
            f"{output_width}x{output_height}, foreground=fit, "
            f"y={foreground_y_pct:.2f}, blur={background_blur:.1f}"
        )
        self.log("  FFmpeg: " + " ".join(cmd))

        if progress_callback:
            progress_callback(0.05)

        def run(command):
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            _, stderr_text = proc.communicate()
            return proc.returncode, stderr_text or ""

        code, stderr = run(cmd)

        joined = " ".join(self.encoder_args)
        if code != 0 and any(
            enc in joined
            for enc in ("h264_nvenc", "hevc_nvenc", "h264_qsv", "h264_amf")
        ):
            self.log(
                "  ⚠ GPU encoder не принял IRL-фильтр — повторяю на CPU/libx264."
            )
            fps_args = []
            if "-r" in self.encoder_args:
                idx = self.encoder_args.index("-r")
                if idx + 1 < len(self.encoder_args):
                    fps_args = ["-r", str(self.encoder_args[idx + 1])]
            cpu_args = [
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "20",
                "-maxrate", "12M",
                "-bufsize", "24M",
                "-threads", "0",
                *fps_args,
            ]
            cpu_cmd = [
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
                *cpu_args,
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
            code, stderr = run(cpu_cmd)

        if code != 0:
            tail = "\n".join((stderr or "").splitlines()[-35:])
            raise IRLLayoutError(f"FFmpeg не смог собрать IRL Layout:\n{tail}")

        if not Path(output_path).exists() or Path(output_path).stat().st_size < 10_000:
            raise IRLLayoutError("FFmpeg завершился без итогового IRL-видео.")

        if progress_callback:
            progress_callback(1.0)
        return output_path
