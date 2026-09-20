from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable, Dict, Iterable

from core.streamer_layout import normalize_rect, probe_video_size


VALID_LAYOUT_STATES = {"NORMAL", "FACE_FOCUS", "GAME_FOCUS", "REACTION"}


class DynamicLayoutError(RuntimeError):
    pass


def _even(value: int, minimum: int = 2) -> int:
    value = max(minimum, int(round(value)))
    return value - (value % 2)


def _state_name(value) -> str:
    state = str(value or "NORMAL").strip().upper()
    return state if state in VALID_LAYOUT_STATES else "NORMAL"


def _focus_rect(rect: Dict[str, float], factor: float) -> Dict[str, float]:
    rect = normalize_rect(rect)
    factor = max(0.55, min(1.0, float(factor)))
    nw = rect["w"] * factor
    nh = rect["h"] * factor
    cx = rect["x"] + rect["w"] / 2.0
    cy = rect["y"] + rect["h"] / 2.0
    x = max(0.0, min(1.0 - nw, cx - nw / 2.0))
    y = max(0.0, min(1.0 - nh, cy - nh / 2.0))
    return {"x": x, "y": y, "w": nw, "h": nh}


def _profile(state: str, base_top_pct: float) -> tuple[float, float]:
    state = _state_name(state)
    base = max(0.22, min(0.50, float(base_top_pct)))
    if state == "FACE_FOCUS":
        return max(base, 0.50), 0.88
    if state == "GAME_FOCUS":
        return min(base, 0.24), 1.0
    if state == "REACTION":
        return max(base, 0.56), 0.72
    return base, 1.0


def _probe_duration(ffmpeg_path: str, input_path: str) -> float:
    ffprobe = Path(ffmpeg_path)
    ffprobe = ffprobe.with_name("ffprobe.exe" if ffprobe.name.lower().endswith(".exe") else "ffprobe")
    try:
        proc = subprocess.run(
            [
                str(ffprobe), "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                input_path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        data = json.loads(proc.stdout or "{}")
        return max(0.0, float((data.get("format") or {}).get("duration") or 0.0))
    except Exception:
        return 0.0


def normalize_layout_timeline(
    events: Iterable[dict] | None,
    *,
    duration: float,
    default_state: str = "NORMAL",
) -> list[dict]:
    """Build a conservative state timeline.

    AI events are optional. We cap them, reject sub-second layout flicker, and
    fill all gaps with NORMAL so layout changes remain deliberate rather than
    becoming random effects.
    """
    duration = max(0.05, float(duration or 0.0))
    default_state = _state_name(default_state)
    cleaned = []
    for raw in list(events or [])[:6]:
        if not isinstance(raw, dict):
            continue
        state = _state_name(raw.get("state"))
        if state == "NORMAL":
            continue
        try:
            start = max(0.0, float(raw.get("start", 0.0) or 0.0))
            end = min(duration, float(raw.get("end", 0.0) or 0.0))
        except Exception:
            continue
        # No half-second layout spam. Focus moments must be visually readable.
        if end - start < 1.20:
            continue
        cleaned.append({"state": state, "start": start, "end": end})

    cleaned.sort(key=lambda x: (x["start"], x["end"]))
    timeline = []
    cursor = 0.0
    for ev in cleaned[:4]:
        start = max(cursor, ev["start"])
        end = max(start, ev["end"])
        if start > cursor + 0.03:
            timeline.append({"state": default_state, "start": cursor, "end": start})
        if end - start >= 1.20:
            timeline.append({"state": ev["state"], "start": start, "end": end})
            cursor = end
    if cursor < duration - 0.03:
        timeline.append({"state": default_state, "start": cursor, "end": duration})
    if not timeline:
        timeline = [{"state": default_state, "start": 0.0, "end": duration}]
    return timeline


def render_dynamic_streamer_layout(
    *,
    ffmpeg_path: str,
    input_path: str,
    output_path: str,
    webcam_rect: Dict[str, float],
    encoder_args: list[str],
    ass_file: str | Path | None = None,
    layout_events: Iterable[dict] | None = None,
    layout_state: str = "NORMAL",
    output_width: int = 1080,
    output_height: int = 1920,
    webcam_height_pct: float = 0.365,
    gameplay_center_x: float = 0.50,
    webcam_padding: int = 0,
    log: Callable[[str], None] | None = None,
) -> str:
    """Render state-aware streamer layout directly on the 1080x1920 canvas.

    NORMAL is the existing split-screen composition. FACE_FOCUS enlarges the
    webcam block, GAME_FOCUS gives gameplay more room, and REACTION combines a
    larger webcam block with a tighter face crop. All states are assembled in
    one FFmpeg filter graph and encoded once.
    """
    log = log or (lambda _m: None)
    input_path = str(Path(input_path).resolve())
    output_path = str(Path(output_path).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    source_w, source_h = probe_video_size(input_path)
    base_rect = normalize_rect(webcam_rect)
    duration = _probe_duration(ffmpeg_path, input_path)
    if duration <= 0:
        raise DynamicLayoutError("Не удалось определить длительность клипа для layout states.")

    timeline = normalize_layout_timeline(
        layout_events,
        duration=duration,
        default_state=layout_state,
    )
    gameplay_center_x = max(0.0, min(1.0, float(gameplay_center_x)))
    pad = max(0, min(int(webcam_padding), 80))

    graph = []
    segment_labels = []

    # FFmpeg filter inputs are consumable pads. Duplicate the source once up
    # front, then trim each independent branch; do not reference [0:v]
    # repeatedly for multiple state segments.
    if len(timeline) == 1:
        graph.append("[0:v]null[src0]")
    else:
        graph.append(
            f"[0:v]split={len(timeline)}"
            + "".join(f"[src{i}]" for i in range(len(timeline)))
        )

    for idx, seg in enumerate(timeline):
        state = _state_name(seg["state"])
        top_pct, crop_factor = _profile(state, webcam_height_pct)
        rect = _focus_rect(base_rect, crop_factor)

        top_h = _even(output_height * top_pct)
        game_h = _even(output_height - top_h)
        top_h = output_height - game_h

        cam_x = max(0, min(source_w - 2, int(round(rect["x"] * source_w))))
        cam_y = max(0, min(source_h - 2, int(round(rect["y"] * source_h))))
        cam_w = _even(min(source_w - cam_x, int(round(rect["w"] * source_w))))
        cam_h = _even(min(source_h - cam_y, int(round(rect["h"] * source_h))))

        inner_w = _even(max(2, output_width - pad * 2))
        inner_h = _even(max(2, top_h - pad * 2))

        game_aspect = output_width / float(max(game_h, 2))
        game_crop_w = _even(min(source_w, round(source_h * game_aspect)))
        max_game_x = max(0, source_w - game_crop_w)
        game_x = int(round(max_game_x * gameplay_center_x))
        game_x = max(0, min(max_game_x, game_x))
        game_x -= game_x % 2

        start = float(seg["start"])
        end = float(seg["end"])
        graph.append(
            f"[src{idx}]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,"
            f"split=2[s{idx}cam0][s{idx}game0]"
        )
        graph.append(
            f"[s{idx}cam0]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},"
            f"scale={inner_w}:{inner_h}:force_original_aspect_ratio=increase:"
            f"flags=lanczos+accurate_rnd+full_chroma_int,"
            f"crop={inner_w}:{inner_h},"
            f"pad={output_width}:{top_h}:{pad}:{pad}:black[s{idx}cam]"
        )
        graph.append(
            f"[s{idx}game0]crop={game_crop_w}:{source_h}:{game_x}:0,"
            f"scale={output_width}:{game_h}:flags=lanczos+accurate_rnd+full_chroma_int,"
            f"setsar=1[s{idx}game]"
        )
        graph.append(
            f"[s{idx}cam][s{idx}game]vstack=inputs=2,setsar=1,format=yuv420p[s{idx}]"
        )
        segment_labels.append(f"[s{idx}]")

    if len(segment_labels) == 1:
        graph.append(f"{segment_labels[0]}null[stack]")
    else:
        graph.append(
            "".join(segment_labels)
            + f"concat=n={len(segment_labels)}:v=1:a=0[stack]"
        )

    if ass_file:
        escaped = str(Path(ass_file).resolve()).replace("\\", "/").replace(":", "\\:")
        graph.append(f"[stack]ass='{escaped}',format=yuv420p[v]")
    else:
        graph.append("[stack]format=yuv420p[v]")

    cmd = [
        ffmpeg_path, "-y",
        "-i", input_path,
        "-filter_complex", ";".join(graph),
        "-map", "[v]",
        "-map", "0:a?",
        *list(encoder_args or []),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        output_path,
    ]

    log(
        "  Dynamic layout timeline: "
        + " | ".join(
            f"{x['state']} {x['start']:.1f}-{x['end']:.1f}s" for x in timeline
        )
    )
    log("  FFmpeg dynamic layout: " + " ".join(cmd))

    def run(command):
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            timeout=1200,
        )
        return proc.returncode, proc.stderr or ""

    code, stderr = run(cmd)
    joined = " ".join(encoder_args or [])
    if code != 0 and any(x in joined for x in ("h264_nvenc", "hevc_nvenc", "h264_qsv", "h264_amf")):
        log("  ⚠ Hardware encoder failed for dynamic layout; retrying with libx264.")
        fps_args = []
        if "-r" in list(encoder_args or []):
            idx = list(encoder_args).index("-r")
            if idx + 1 < len(encoder_args):
                fps_args = ["-r", str(encoder_args[idx + 1])]
        cpu = [
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-maxrate", "12M",
            "-bufsize", "24M",
            "-threads", "0",
            *fps_args,
        ]
        cpu_cmd = [
            ffmpeg_path, "-y",
            "-i", input_path,
            "-filter_complex", ";".join(graph),
            "-map", "[v]",
            "-map", "0:a?",
            *cpu,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-shortest",
            output_path,
        ]
        code, stderr = run(cpu_cmd)

    if code != 0:
        tail = "\n".join(stderr.splitlines()[-45:])
        raise DynamicLayoutError("Dynamic layout FFmpeg failed:\n" + tail)

    out = Path(output_path)
    if not out.exists() or out.stat().st_size < 10_000:
        raise DynamicLayoutError("Dynamic layout finished without a valid output file.")
    return str(out)
