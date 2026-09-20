from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Dict

from core.streamer_layout import normalize_rect, probe_video_size


class StreamerGpuTurboError(RuntimeError):
    pass


def _even(value: int, minimum: int = 2) -> int:
    value = max(minimum, int(value))
    return value - (value % 2)


def _fit_dims(source_w: int, source_h: int, target_w: int, target_h: int) -> tuple[int, int]:
    source_aspect = source_w / float(max(source_h, 1))
    target_aspect = target_w / float(max(target_h, 1))
    if source_aspect >= target_aspect:
        width = target_w
        height = _even(round(target_w / max(source_aspect, 1e-6)))
    else:
        height = target_h
        width = _even(round(target_h * source_aspect))
    return _even(width), _even(height)


def _cover_dims(source_w: int, source_h: int, target_w: int, target_h: int) -> tuple[int, int]:
    source_aspect = source_w / float(max(source_h, 1))
    target_aspect = target_w / float(max(target_h, 1))
    if source_aspect >= target_aspect:
        height = target_h
        width = _even(round(target_h * source_aspect))
    else:
        width = target_w
        height = _even(round(target_w / max(source_aspect, 1e-6)))
    return max(target_w, _even(width)), max(target_h, _even(height))


def cuda_filters_available(ffmpeg_path: str) -> bool:
    if os.name == "nt":
        return False
    try:
        proc = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except Exception:
        return False
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode == 0 and "scale_cuda" in text and "hwupload_cuda" in text


def render_streamer_gpu_turbo(
    *,
    ffmpeg_path: str,
    input_path: str,
    output_path: str,
    webcam_rect: Dict[str, float],
    encoder_args: list[str],
    ass_file: str | Path | None = None,
    output_width: int = 1080,
    output_height: int = 1920,
    webcam_height_pct: float = 0.365,
    gameplay_center_x: float = 0.50,
    webcam_padding: int = 0,
    log: Callable[[str], None] | None = None,
) -> str:
    """One-pass RunPod/RTX renderer.

    Heavy Lanczos scaling runs in scale_cuda on the GPU, subtitles/title are
    burned in the same FFmpeg pass, and the result is encoded once with NVENC.
    The caller keeps the legacy renderer as an automatic fallback.
    """
    log = log or (lambda _m: None)
    input_path = str(Path(input_path).resolve())
    output_path = str(Path(output_path).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    source_w, source_h = probe_video_size(input_path)
    rect = normalize_rect(webcam_rect)

    output_width = _even(output_width)
    output_height = _even(output_height)
    webcam_height_pct = max(0.22, min(0.50, float(webcam_height_pct)))
    gameplay_center_x = max(0.0, min(1.0, float(gameplay_center_x)))
    pad = max(0, min(int(webcam_padding), 80))

    top_h = _even(round(output_height * webcam_height_pct))
    game_h = _even(output_height - top_h)
    top_h = output_height - game_h

    cam_x = max(0, min(source_w - 2, int(round(rect["x"] * source_w))))
    cam_y = max(0, min(source_h - 2, int(round(rect["y"] * source_h))))
    cam_w = _even(min(source_w - cam_x, int(round(rect["w"] * source_w))))
    cam_h = _even(min(source_h - cam_y, int(round(rect["h"] * source_h))))

    inner_w = _even(max(2, output_width - pad * 2))
    inner_h = _even(max(2, top_h - pad * 2))

    # Preserve webcam aspect ratio while filling its slot. The expensive resize
    # happens on CUDA; the final crop is cheap and remains on CPU.
    cam_aspect = cam_w / float(max(cam_h, 1))
    target_aspect = inner_w / float(max(inner_h, 1))
    if cam_aspect >= target_aspect:
        scaled_h = inner_h
        scaled_w = _even(round(inner_h * cam_aspect))
    else:
        scaled_w = inner_w
        scaled_h = _even(round(inner_w / max(cam_aspect, 1e-6)))
    scaled_w = max(inner_w, scaled_w)
    scaled_h = max(inner_h, scaled_h)

    game_aspect = output_width / float(game_h)
    game_crop_w = _even(min(source_w, round(source_h * game_aspect)))
    max_game_x = max(0, source_w - game_crop_w)
    game_x = int(round(max_game_x * gameplay_center_x))
    game_x = max(0, min(max_game_x, game_x))
    game_x -= game_x % 2

    graph = [
        "[0:v]split=2[cam0][game0]",
        (
            f"[cam0]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},"
            "format=nv12,hwupload_cuda,"
            f"scale_cuda=w={scaled_w}:h={scaled_h}:interp_algo=lanczos,"
            "hwdownload,format=nv12,"
            f"crop={inner_w}:{inner_h},"
            f"pad={output_width}:{top_h}:{pad}:{pad}:black[cam]"
        ),
        (
            f"[game0]crop={game_crop_w}:{source_h}:{game_x}:0,"
            "format=nv12,hwupload_cuda,"
            f"scale_cuda=w={output_width}:h={game_h}:interp_algo=lanczos,"
            "hwdownload,format=nv12[game]"
        ),
        "[cam][game]vstack=inputs=2,setsar=1[stack]",
    ]

    if ass_file:
        escaped = str(Path(ass_file).resolve()).replace("\\", "/").replace(":", "\\:")
        graph.append(f"[stack]format=yuv420p,ass='{escaped}'[v]")
    else:
        graph.append("[stack]format=yuv420p[v]")

    cmd = [
        ffmpeg_path,
        "-y",
        "-i",
        input_path,
        "-filter_complex",
        ";".join(graph),
        "-map",
        "[v]",
        "-map",
        "0:a?",
        *list(encoder_args or []),
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

    log(
        "  🚀 GPU TURBO: one-pass CUDA scale + NVENC "
        f"(source={source_w}x{source_h}, cam={cam_w}x{cam_h}, "
        f"game_crop={game_crop_w}x{source_h})"
    )
    log("  FFmpeg GPU TURBO: " + " ".join(cmd))

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        timeout=1200,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-45:])
        raise StreamerGpuTurboError("GPU TURBO FFmpeg failed:\n" + tail)

    out = Path(output_path)
    if not out.exists() or out.stat().st_size < 10_000:
        raise StreamerGpuTurboError("GPU TURBO finished without a valid output file")

    return str(out)



def render_irl_gpu_turbo(
    *,
    ffmpeg_path: str,
    input_path: str,
    output_path: str,
    encoder_args: list[str],
    ass_file: str | Path | None = None,
    output_width: int = 1080,
    output_height: int = 1920,
    foreground_y_pct: float = 0.48,
    background_blur: float = 18.0,
    background_brightness: float = -0.08,
    log: Callable[[str], None] | None = None,
) -> str:
    """GPU-heavy IRL renderer for RunPod.

    Expensive resize work is done with scale_cuda. The blur itself stays on a
    small 360x640 CPU frame, then the background is uploaded back to CUDA and
    enlarged on the GPU. The final 9:16 composition and ASS text are produced
    in one encode pass. If NVENC is available, encoding is also done on GPU.
    """
    log = log or (lambda _m: None)
    input_path = str(Path(input_path).resolve())
    output_path = str(Path(output_path).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    source_w, source_h = probe_video_size(input_path)
    output_width = _even(output_width)
    output_height = _even(output_height)
    foreground_y_pct = max(0.10, min(0.90, float(foreground_y_pct)))
    background_blur = max(4.0, min(40.0, float(background_blur)))
    background_brightness = max(-0.35, min(0.15, float(background_brightness)))

    bg_low_w, bg_low_h = 360, 640
    bg_scaled_w, bg_scaled_h = _cover_dims(
        source_w, source_h, bg_low_w, bg_low_h
    )
    bg_crop_x = max(0, (bg_scaled_w - bg_low_w) // 2)
    bg_crop_y = max(0, (bg_scaled_h - bg_low_h) // 2)
    bg_crop_x -= bg_crop_x % 2
    bg_crop_y -= bg_crop_y % 2

    fg_w, fg_h = _fit_dims(source_w, source_h, output_width, output_height)
    fg_x = max(0, (output_width - fg_w) // 2)
    fg_y = int(round(output_height * foreground_y_pct - fg_h / 2))
    fg_y = max(0, min(output_height - fg_h, fg_y))
    fg_x -= fg_x % 2
    fg_y -= fg_y % 2

    graph = [
        "[0:v]split=2[bg0][fg0]",
        (
            "[bg0]format=nv12,hwupload_cuda,"
            f"scale_cuda=w={bg_scaled_w}:h={bg_scaled_h}:interp_algo=bicubic,"
            "hwdownload,format=nv12,"
            f"crop={bg_low_w}:{bg_low_h}:{bg_crop_x}:{bg_crop_y},"
            f"gblur=sigma={background_blur:.2f},"
            f"eq=brightness={background_brightness:.3f}:saturation=0.90,"
            "format=nv12,hwupload_cuda,"
            f"scale_cuda=w={output_width}:h={output_height}:interp_algo=bicubic,"
            "hwdownload,format=nv12[bg]"
        ),
        (
            "[fg0]format=nv12,hwupload_cuda,"
            f"scale_cuda=w={fg_w}:h={fg_h}:interp_algo=lanczos,"
            "hwdownload,format=nv12[fg]"
        ),
        (
            f"[bg][fg]overlay=x={fg_x}:y={fg_y}:"
            "eof_action=pass,setsar=1[stack]"
        ),
    ]

    if ass_file:
        escaped = str(Path(ass_file).resolve()).replace("\\", "/").replace(":", "\\:")
        graph.append(f"[stack]format=yuv420p,ass='{escaped}'[v]")
    else:
        graph.append("[stack]format=yuv420p[v]")

    cmd = [
        ffmpeg_path,
        "-y",
        "-i",
        input_path,
        "-filter_complex",
        ";".join(graph),
        "-map",
        "[v]",
        "-map",
        "0:a?",
        *list(encoder_args or []),
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

    log(
        "  🚀 IRL GPU TURBO: CUDA resize foreground/background + one-pass text "
        f"(source={source_w}x{source_h}, fg={fg_w}x{fg_h}, "
        f"bg_low={bg_low_w}x{bg_low_h})"
    )
    log("  FFmpeg IRL GPU TURBO: " + " ".join(cmd))

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        timeout=1200,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-45:])
        raise StreamerGpuTurboError("IRL GPU TURBO FFmpeg failed:\n" + tail)

    out = Path(output_path)
    if not out.exists() or out.stat().st_size < 10_000:
        raise StreamerGpuTurboError(
            "IRL GPU TURBO finished without a valid output file"
        )

    return str(out)
