#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
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
from core.streamer_layout import StreamerLayoutRenderer
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
        model=hf.get("model") or cfg.get("model", "gpt-4.1"),
        temperature=cfg.get("temperature", 1.0),
        subtitle_style=cfg.get("subtitle_style", "pop"),
        subtitle_settings=cfg.get("subtitle_settings"),
        subtitle_language=cfg.get("subtitle_language", "ru-orig"),
        subtitle_sync_offset=cfg.get("subtitle_sync_offset", 0),
        ai_providers=providers or None,
    )


def tune_encoder_args(args: list[str]) -> list[str]:
    """Use visibly higher quality for the webcam crop and final text burn."""
    out = list(args or [])
    joined = " ".join(out)

    def replace_value(flag: str, value: str):
        if flag in out:
            idx = out.index(flag)
            if idx + 1 < len(out):
                out[idx + 1] = value

    if "h264_nvenc" in joined or "hevc_nvenc" in joined:
        replace_value("-cq", "16")
        replace_value("-b:v", "10M")
        replace_value("-maxrate", "16M")
        replace_value("-bufsize", "24M")
        replace_value("-preset", "p6")
    elif "libx264" in joined:
        replace_value("-crf", "16")
        replace_value("-preset", "medium")
    return out


def split_title(text: str) -> tuple[str, str]:
    """Split a short hook into two visually balanced lines."""
    clean = re.sub(r"\s+", " ", str(text or "").strip()).upper()
    clean = clean.replace("{", "").replace("}", "").replace("\\", "")
    words = clean.split()[:6]
    if not words:
        return "", ""
    if len(words) == 1:
        return words[0], ""

    # Choose the split with the smallest difference in character width.
    best_idx = 1
    best_score = None
    for i in range(1, len(words)):
        a = " ".join(words[:i])
        b = " ".join(words[i:])
        score = abs(len(a) - len(b))
        if best_score is None or score < best_score:
            best_score = score
            best_idx = i
    return " ".join(words[:best_idx]), " ".join(words[best_idx:])


def ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def create_streamer_ass(
    core: AutoClipperCore,
    source_path: Path,
    out_dir: Path,
    *,
    captions: bool,
    title_text: str,
    title_enabled: bool,
    title_duration: float,
    title_settings: dict | None,
    webcam_height_pct: float,
) -> Path | None:
    if not captions and not title_enabled:
        return None

    ass_file = out_dir / "streamer_text.ass"

    if captions:
        audio_file = out_dir / "captions_audio.wav"
        cmd = [
            get_ffmpeg_path(), "-y",
            "-i", str(source_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            str(audio_file),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=SUBPROCESS_FLAGS,
        )
        if result.returncode != 0 or not audio_file.exists():
            raise RuntimeError("Не удалось извлечь аудио для субтитров.")

        debug_log("[streamer] Субтитры: пробую Faster-Whisper на GPU...", flush=True)
        try:
            transcript = core.transcribe_words(
                str(audio_file),
                allow_cpu_fallback=False,
            )
        except Exception as exc:
            debug_log(
                f"[streamer] GPU Faster-Whisper недоступен: {exc}",
                flush=True,
            )
            debug_log(
                "[streamer] CPU medium пропускаю — использую OpenAI Whisper API "
                "с word timestamps для быстрого рендера.",
                flush=True,
            )
            transcript = core._whisper_transcribe_words_api(str(audio_file))

        sync_offset = float(getattr(core, "subtitle_sync_offset", 0.0) or 0.0)
        sync_offset = max(-1.0, min(1.0, sync_offset))
        subtitle_cfg = dict(getattr(core, "subtitle_settings", {}) or {})
        lead_seconds = max(0.0, min(0.60, float(subtitle_cfg.get("lead_seconds", 0.22) or 0.0)))
        effective_lead = 0.0 if abs(sync_offset) >= 0.15 else lead_seconds
        ass_offset = sync_offset - effective_lead

        subtitle_style = getattr(core, "subtitle_style", "stable")
        if subtitle_style == "karaoke":
            core.create_ass_subtitle_karaoke(transcript, str(ass_file), ass_offset)
        elif subtitle_style == "stable":
            core.create_ass_subtitle_stable(transcript, str(ass_file), ass_offset)
        else:
            core.create_ass_subtitle_capcut(transcript, str(ass_file), ass_offset)
    else:
        ass_file.write_text(
            """[Script Info]
Title: Streamer title
ScriptType: v4.00+
WrapStyle: 2
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,70,&H00FFFFFF,&H00FFFFFF,&H00000000,&H60000000,-1,0,0,0,100,100,0,0,1,5,1,2,60,60,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""",
            encoding="utf-8",
        )

    if title_enabled and title_text.strip():
        title_cfg = dict(title_settings or {})
        top, bottom = split_title(title_text)
        if top:
            canvas_w, canvas_h = ((720, 1280) if captions else (1080, 1920))

            def _inline_ass_color(value: str, fallback: str) -> str:
                raw = str(value or fallback).strip().lstrip("#")
                if not re.fullmatch(r"[0-9A-Fa-f]{6}", raw):
                    raw = fallback.lstrip("#")
                rr, gg, bb = raw[0:2], raw[2:4], raw[4:6]
                return f"&H{bb}{gg}{rr}&".upper()

            x_pct = max(0.05, min(0.95, float(title_cfg.get("x_pct", 0.50) or 0.50)))
            y_pct = max(0.08, min(0.92, float(title_cfg.get("y_pct", 0.50) or 0.50)))
            center_x = int(round(canvas_w * x_pct))
            center_y = int(round(canvas_h * y_pct))
            font_name = str(title_cfg.get("font_name", "Arial Black") or "Arial Black").replace(",", " ")
            requested_size = max(30, min(110, int(title_cfg.get("font_size", 76) or 76)))
            size_scale = canvas_w / 1080.0
            font_size = max(24, int(round(requested_size * size_scale)))
            outline = max(0, min(10, int(title_cfg.get("outline", 6) or 6)))
            outline = max(0, int(round(outline * size_scale)))
            shadow = max(0, min(8, int(title_cfg.get("shadow", 1) or 1)))
            top_color = _inline_ass_color(title_cfg.get("top_color", "#FF2D1A"), "#FF2D1A")
            bottom_color = _inline_ass_color(title_cfg.get("bottom_color", "#FFFFFF"), "#FFFFFF")
            outline_color = _inline_ass_color(title_cfg.get("outline_color", "#000000"), "#000000")
            uppercase = bool(title_cfg.get("uppercase", True))
            scale_pct = max(70, min(120, int(title_cfg.get("scale_pct", 96) or 96)))
            if uppercase:
                top = top.upper()
                bottom = bottom.upper()

            # Reduce only when the text is unusually long; manual font size remains primary.
            longest = max(len(top), len(bottom or ""))
            if longest > 20:
                font_size = int(font_size * 0.80)
            elif longest > 16:
                font_size = int(font_size * 0.90)

            duration = max(0.8, min(5.0, float(title_duration or 2.3)))
            base = (
                r"{\an5\pos(" + str(center_x) + "," + str(center_y) + r")"
                + r"\fn" + font_name + r"\b1\fs" + str(font_size)
                + r"\bord" + str(outline)
                + r"\3c" + outline_color
                + r"\shad" + str(shadow)
                + r"\fscx" + str(scale_pct) + r"\fscy" + str(scale_pct)
            )
            if bottom:
                title_ass = (
                    base
                    + r"\c" + top_color + "}" + top
                    + r"\N{\c" + bottom_color + "}" + bottom
                )
            else:
                title_ass = base + r"\c" + top_color + "}" + top

            with ass_file.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"Dialogue: 10,{ass_time(0)},{ass_time(duration)},Default,,0,0,0,,{title_ass}\n"
                )

    return ass_file


def burn_ass(core: AutoClipperCore, input_path: Path, output_path: Path, ass_file: Path, encoder_args: list[str]) -> None:
    escaped = str(ass_file).replace("\\", "/").replace(":", "\\:")
    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", str(input_path),
        "-vf", f"ass='{escaped}'",
        *encoder_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    debug_log("[streamer] Burn subtitles + 2s title in one pass.", flush=True)
    result = core._run_ffmpeg_subprocess(cmd, timeout=900)
    if result.returncode != 0:
        tail = "\n".join((result.stderr or "").splitlines()[-30:])
        raise RuntimeError("Не удалось прожечь текст:\n" + tail)


def probe_media_info(media_path: Path) -> dict:
    """Return duration and whether an audio stream exists, using ffprobe next to ffmpeg."""
    ffmpeg = Path(get_ffmpeg_path())
    ffprobe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    cmd = [
        str(ffprobe), "-v", "error",
        "-show_entries", "format=duration:stream=codec_type",
        "-of", "json",
        str(media_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=SUBPROCESS_FLAGS,
    )
    if result.returncode != 0:
        raise RuntimeError("Не удалось прочитать рекламное видео через ffprobe.")
    try:
        data = json.loads(result.stdout or "{}")
        duration = float((data.get("format") or {}).get("duration") or 0)
        has_audio = any((s or {}).get("codec_type") == "audio" for s in (data.get("streams") or []))
    except Exception as exc:
        raise RuntimeError("Не удалось определить длительность рекламного видео.") from exc
    if duration <= 0:
        raise RuntimeError("У рекламного видео не определилась длительность.")
    return {"duration": duration, "has_audio": has_audio}


def insert_ad_banner(
    core: AutoClipperCore,
    input_path: Path,
    output_path: Path,
    banner_path: Path,
    encoder_args: list[str],
    *,
    clip_duration: float,
    at_pct: float = 0.50,
    width_pct: float = 0.78,
    height_pct: float = 0.38,
    x_pct: float = 0.50,
    y_pct: float = 0.50,
    blur_sigma: float = 18.0,
    fade_duration: float = 0.20,
    chroma_key: bool = False,
    chroma_color: str = "#00FF00",
    chroma_similarity: float = 0.16,
    chroma_blend: float = 0.08,
    keep_aspect: bool = True,
    mode: str = "pause",
    source_crop: dict | None = None,
) -> float:
    """Pause main clip, blur it, play the whole ad video, then resume exactly where it stopped."""
    if not banner_path.exists():
        raise RuntimeError(f"Файл рекламного видео не найден: {banner_path}")

    ad_info = probe_media_info(banner_path)
    banner_duration = max(0.10, float(ad_info["duration"]))
    ad_has_audio = bool(ad_info["has_audio"])

    main_info = probe_media_info(input_path)
    main_has_audio = bool(main_info["has_audio"])

    clip_duration = max(0.5, float(main_info["duration"] or clip_duration or 0.5))
    at_pct = max(0.05, min(0.95, float(at_pct or 0.50)))
    pause_at = max(0.20, min(clip_duration - 0.20, clip_duration * at_pct))

    width_pct = max(0.15, min(1.00, float(width_pct or 0.78)))
    height_pct = max(0.08, min(1.00, float(height_pct or 0.38)))
    x_pct = max(0.0, min(1.0, float(x_pct or 0.50)))
    y_pct = max(0.0, min(1.0, float(y_pct or 0.50)))
    blur_sigma = max(0.0, min(45.0, float(blur_sigma or 18.0)))
    fade_duration = max(0.0, min(0.8, float(fade_duration or 0.20)))
    fade_duration = min(fade_duration, banner_duration / 3.0)
    fade_out_start = max(0.0, banner_duration - fade_duration)

    target_w = max(64, int(round(1080 * width_pct)))
    target_h = max(64, int(round(1920 * height_pct)))
    post_duration = max(0.0, clip_duration - pause_at)

    # Optional normalized crop from the browser editor. This removes black
    # pillar/letter-box borders from the ad source BEFORE chroma key + scaling.
    crop_prefix = ""
    if source_crop:
        try:
            sx = max(0.0, min(0.95, float(source_crop.get("x", 0.0))))
            sy = max(0.0, min(0.95, float(source_crop.get("y", 0.0))))
            sw = max(0.05, min(1.0 - sx, float(source_crop.get("w", 1.0))))
            sh = max(0.05, min(1.0 - sy, float(source_crop.get("h", 1.0))))
            if sx > 0.002 or sy > 0.002 or sw < 0.998 or sh < 0.998:
                crop_prefix = (
                    f"crop=w='iw*{sw:.6f}':h='ih*{sh:.6f}':"
                    f"x='iw*{sx:.6f}':y='ih*{sy:.6f}',"
                )
                debug_log(
                    f"[streamer] Ad source crop: x={sx:.3f}, y={sy:.3f}, "
                    f"w={sw:.3f}, h={sh:.3f}",
                    flush=True,
                )
        except Exception:
            crop_prefix = ""

    raw_chroma = str(chroma_color or "#00FF00").strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", raw_chroma):
        raw_chroma = "00FF00"
    chroma_similarity = max(0.01, min(0.80, float(chroma_similarity or 0.28)))
    chroma_blend = max(0.0, min(0.35, float(chroma_blend or 0.06)))

    scale_expr = (
        (
            crop_prefix
            + f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            + f"format=rgba,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black@0"
        )
        if keep_aspect
        else crop_prefix + f"scale={target_w}:{target_h}"
    )
    ad_filters = [
        f"trim=duration={banner_duration:.3f}",
        "setpts=PTS-STARTPTS",
        scale_expr,
        "format=rgba",
    ]
    if chroma_key:
        ad_filters.append(f"colorkey=0x{raw_chroma}:{chroma_similarity:.3f}:{chroma_blend:.3f}")
    if fade_duration > 0:
        ad_filters.append(f"fade=t=in:st=0:d={fade_duration:.3f}:alpha=1")
        ad_filters.append(f"fade=t=out:st={fade_out_start:.3f}:d={fade_duration:.3f}:alpha=1")

    blur_filter = (
        f"gblur=sigma={blur_sigma:.2f},eq=brightness=-0.08:saturation=0.82"
        if blur_sigma > 0
        else "eq=brightness=-0.08:saturation=0.82"
    )

    mode = str(mode or "pause").strip().lower()
    if mode == "overlay":
        # The main clip keeps running. During the ad interval we blur the moving
        # background and overlay the ad video; final clip duration does not grow.
        overlay_start = pause_at
        if banner_duration < clip_duration:
            overlay_start = min(overlay_start, max(0.0, clip_duration - banner_duration))
        effective_ad = max(0.10, min(banner_duration, clip_duration - overlay_start))
        overlay_end = overlay_start + effective_ad

        overlay_ad_filters = [
            f"trim=duration={effective_ad:.3f}",
            "setpts=PTS-STARTPTS",
            scale_expr,
            "format=rgba",
        ]
        if chroma_key:
            overlay_ad_filters.append(
                f"colorkey=0x{raw_chroma}:{chroma_similarity:.3f}:{chroma_blend:.3f}"
            )
        overlay_fade = min(fade_duration, effective_ad / 3.0)
        if overlay_fade > 0:
            overlay_ad_filters.append(f"fade=t=in:st=0:d={overlay_fade:.3f}:alpha=1")
            overlay_ad_filters.append(
                f"fade=t=out:st={max(0.0, effective_ad-overlay_fade):.3f}:"
                f"d={overlay_fade:.3f}:alpha=1"
            )
        overlay_ad_filters.append(f"setpts=PTS+{overlay_start:.3f}/TB")

        filter_complex = ";".join([
            # Continue mode is intentionally clean: NO blur, NO dimming and
            # NO freeze. The main clip keeps playing unchanged underneath.
            "[0:v]setpts=PTS-STARTPTS[vbg]",
            f"[1:v]{','.join(overlay_ad_filters)}[advid]",
            (
                f"[vbg][advid]overlay="
                f"x='W*{x_pct:.4f}-w/2':y='H*{y_pct:.4f}-h/2':"
                f"eof_action=pass[vout]"
            ),
        ])

        cmd = [
            get_ffmpeg_path(), "-y",
            "-i", str(input_path),
            "-i", str(banner_path),
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "0:a?",
            *encoder_args,
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]
        debug_log(
            f"[streamer] Реклама overlay: start={overlay_start:.1f}s, "
            f"ad={effective_ad:.2f}s, size={width_pct*100:.0f}%x{height_pct*100:.0f}%, "
            f"pos={x_pct*100:.0f}%/{y_pct*100:.0f}%, no-blur, "
            f"chroma={'on' if chroma_key else 'off'}.",
            flush=True,
        )
        result = core._run_ffmpeg_subprocess(cmd, timeout=1200)
        if result.returncode != 0:
            tail = "\n".join((result.stderr or "").splitlines()[-40:])
            raise RuntimeError("Не удалось наложить рекламное видео:\n" + tail)
        return effective_ad

    video_parts = [
        "[0:v]split=3[vpre0][vfreeze0][vpost0]",
        f"[vpre0]trim=start=0:end={pause_at:.3f},setpts=PTS-STARTPTS[vpre]",
        (
            f"[vfreeze0]select='gte(t,{pause_at:.3f})',setpts=PTS-STARTPTS,"
            f"trim=end_frame=1,tpad=stop_mode=clone:stop_duration={banner_duration:.3f},"
            f"trim=duration={banner_duration:.3f},{blur_filter}[vblur]"
        ),
        f"[vpost0]trim=start={pause_at:.3f},setpts=PTS-STARTPTS[vpost]",
        f"[1:v]{','.join(ad_filters)}[advid]",
        (
            f"[vblur][advid]overlay="
            f"x='W*{x_pct:.4f}-w/2':y='H*{y_pct:.4f}-h/2':"
            f"eof_action=pass:shortest=1[vad]"
        ),
        "[vpre][vad][vpost]concat=n=3:v=1:a=0[vout]",
    ]

    audio_parts = []
    if main_has_audio:
        audio_parts.extend([
            "[0:a]asplit=2[apre0][apost0]",
            (
                f"[apre0]atrim=start=0:end={pause_at:.3f},asetpts=PTS-STARTPTS,"
                f"aformat=sample_rates=48000:channel_layouts=stereo[apre]"
            ),
            (
                f"[apost0]atrim=start={pause_at:.3f},asetpts=PTS-STARTPTS,"
                f"aformat=sample_rates=48000:channel_layouts=stereo[apost]"
            ),
        ])
    else:
        audio_parts.extend([
            f"anullsrc=r=48000:cl=stereo:d={pause_at:.3f}[apre]",
            f"anullsrc=r=48000:cl=stereo:d={post_duration:.3f}[apost]",
        ])

    if ad_has_audio:
        audio_parts.append(
            f"[1:a]atrim=duration={banner_duration:.3f},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=48000:channel_layouts=stereo,"
            f"apad=pad_dur={banner_duration:.3f},atrim=duration={banner_duration:.3f}[aad]"
        )
    else:
        audio_parts.append(f"anullsrc=r=48000:cl=stereo:d={banner_duration:.3f}[aad]")

    audio_parts.append("[apre][aad][apost]concat=n=3:v=0:a=1[aout]")
    filter_complex = ";".join(video_parts + audio_parts)

    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", str(input_path),
        "-i", str(banner_path),
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        *encoder_args,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    debug_log(
        f"[streamer] Рекламное видео: pause={pause_at:.1f}s, ad={banner_duration:.2f}s, "
        f"size={width_pct*100:.0f}%x{height_pct*100:.0f}%, "
        f"pos={x_pct*100:.0f}%/{y_pct*100:.0f}%, chroma={'on' if chroma_key else 'off'}.",
        flush=True,
    )
    result = core._run_ffmpeg_subprocess(cmd, timeout=1200)
    if result.returncode != 0:
        tail = "\n".join((result.stderr or "").splitlines()[-40:])
        raise RuntimeError("Не удалось вставить рекламное видео:\n" + tail)

    return banner_duration

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
    subtitle_style = str(job.get("subtitle_style") or "pop").strip().lower()
    subtitle_settings = dict(job.get("subtitle_settings") or {})
    webcam_enhance = str(job.get("webcam_enhance") or "hq").strip().lower()
    title_enabled = bool(job.get("title_enabled", True))
    title_text = str(job.get("title_text") or "").strip()
    title_duration = float(job.get("title_duration", 2.3) or 2.3)
    title_settings = dict(job.get("title_settings") or {})

    banner_enabled = bool(job.get("banner_enabled", False))
    banner_file = str(job.get("banner_file") or "").strip()
    banner_at_pct = float(job.get("banner_at_pct", 0.50) or 0.50)
    banner_width_pct = float(job.get("banner_width_pct", 0.78) or 0.78)
    banner_height_pct = float(job.get("banner_height_pct", 0.38) or 0.38)
    banner_x_pct = float(job.get("banner_x_pct", 0.50) or 0.50)
    banner_y_pct = float(job.get("banner_y_pct", 0.50) or 0.50)
    banner_blur = float(job.get("banner_blur", 18.0) or 18.0)
    banner_fade = float(job.get("banner_fade", 0.20) or 0.20)
    banner_chroma_key = bool(job.get("banner_chroma_key", False))
    banner_chroma_color = str(job.get("banner_chroma_color") or "#00FF00")
    banner_chroma_similarity = float(job.get("banner_chroma_similarity", 0.28) or 0.28)
    banner_chroma_blend = float(job.get("banner_chroma_blend", 0.06) or 0.06)
    banner_keep_aspect = bool(job.get("banner_keep_aspect", False))
    banner_mode = str(job.get("banner_mode") or "pause").strip().lower()
    banner_source_crop = dict(job.get("banner_source_crop") or {})

    clip_id = str(job.get("id") or uuid.uuid4().hex[:12])
    out_dir = APP_DIR / "output" / "streamer_clips" / clip_id
    out_dir.mkdir(parents=True, exist_ok=True)

    source_path = out_dir / "source_16x9.mp4"
    layout_path = out_dir / "layout_9x16.mp4"
    text_path = out_dir / "text_9x16.mp4"
    final_path = out_dir / "final_9x16.mp4"

    cfg = ConfigManager(APP_DIR / "config.json", APP_DIR / "output").config
    core = build_core(cfg)
    if subtitle_style in ("pop", "karaoke", "stable"):
        core.subtitle_style = subtitle_style
    if subtitle_settings:
        merged_subtitle_settings = dict(getattr(core, "subtitle_settings", {}) or {})
        merged_subtitle_settings.update(subtitle_settings)
        core.subtitle_settings = merged_subtitle_settings

    debug_log("[progress] Загружаю выбранный момент... (overall: 5.0%)", flush=True)
    debug_log(f"[streamer] {fmt_time(start_sec)} -> {fmt_time(end_sec)}", flush=True)
    core.download_video_section(
        url,
        fmt_time(start_sec),
        fmt_time(end_sec),
        str(source_path),
        resolution=str(job.get("resolution") or "best"),
    )

    debug_log("[progress] Собираю webcam + gameplay... (overall: 35.0%)", flush=True)
    core.enable_gpu_acceleration(bool(job.get("gpu", True)))
    encoder_args = tune_encoder_args(core.get_video_encoder_args())

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
        webcam_enhance=webcam_enhance,
    )

    ass_file = None
    if captions or (title_enabled and title_text):
        debug_log("[progress] Готовлю субтитры и заголовок... (overall: 70.0%)", flush=True)
        ass_file = create_streamer_ass(
            core,
            source_path,
            out_dir,
            captions=captions,
            title_text=title_text,
            title_enabled=title_enabled,
            title_duration=title_duration,
            title_settings=title_settings,
            webcam_height_pct=top_pct,
        )

    banner_duration_actual = 0.0
    target_before_banner = text_path if banner_enabled else final_path
    if ass_file:
        debug_log("[progress] Прожигаю текст... (overall: 84.0%)", flush=True)
        burn_ass(core, layout_path, target_before_banner, ass_file, encoder_args)
    else:
        shutil.copy2(layout_path, target_before_banner)

    if banner_enabled:
        if not banner_file:
            raise RuntimeError("Реклама включена, но баннер не загружен.")
        assets_dir = (APP_DIR / "output" / "streamer_assets").resolve()
        banner_path = (assets_dir / Path(banner_file).name).resolve()
        if assets_dir not in banner_path.parents:
            raise RuntimeError("Недопустимый путь баннера.")
        debug_log("[progress] Вставляю рекламную паузу... (overall: 92.0%)", flush=True)
        banner_duration_actual = insert_ad_banner(
            core,
            target_before_banner,
            final_path,
            banner_path,
            encoder_args,
            clip_duration=end_sec - start_sec,
            at_pct=banner_at_pct,
            width_pct=banner_width_pct,
            height_pct=banner_height_pct,
            x_pct=banner_x_pct,
            y_pct=banner_y_pct,
            blur_sigma=banner_blur,
            fade_duration=banner_fade,
            chroma_key=banner_chroma_key,
            chroma_color=banner_chroma_color,
            chroma_similarity=banner_chroma_similarity,
            chroma_blend=banner_chroma_blend,
            keep_aspect=banner_keep_aspect,
            mode=banner_mode,
            source_crop=banner_source_crop,
        )

    if not final_path.exists() or final_path.stat().st_size < 10_000:
        raise RuntimeError("Итоговый 9:16 файл не создан")

    # Keep a flat folder with ONLY finished clips so they are easy to drag to
    # Telegram/TikTok/Drive without digging through technical render folders.
    export_dir = APP_DIR / "output" / "FINAL_STREAMER_CLIPS"
    export_dir.mkdir(parents=True, exist_ok=True)
    base_name = re.sub(r'[<>:"/\\|?*]+', "_", title_text or "streamer_clip")
    base_name = re.sub(r"\s+", "_", base_name).strip(" ._")[:80] or "streamer_clip"
    export_name = f"{base_name}_{clip_id}.mp4"
    export_path = export_dir / export_name
    shutil.copy2(final_path, export_path)
    debug_log(f"[export] {export_path}", flush=True)

    meta = {
        "id": clip_id,
        "url": url,
        "start_time": start_sec,
        "end_time": end_sec,
        "webcam_rect": webcam_rect,
        "webcam_height_pct": top_pct,
        "gameplay_center_x": game_center_x,
        "captions": captions,
        "subtitle_style": subtitle_style,
        "subtitle_settings": subtitle_settings,
        "webcam_enhance": webcam_enhance,
        "title_enabled": title_enabled,
        "title_text": title_text,
        "title_duration": title_duration,
        "title_settings": title_settings,
        "banner_enabled": banner_enabled,
        "banner_file": banner_file,
        "banner_at_pct": banner_at_pct,
        "banner_duration": banner_duration_actual,
        "banner_width_pct": banner_width_pct,
        "banner_height_pct": banner_height_pct,
        "banner_x_pct": banner_x_pct,
        "banner_y_pct": banner_y_pct,
        "banner_blur": banner_blur,
        "banner_fade": banner_fade,
        "banner_chroma_key": banner_chroma_key,
        "banner_chroma_color": banner_chroma_color,
        "banner_chroma_similarity": banner_chroma_similarity,
        "banner_chroma_blend": banner_chroma_blend,
        "banner_keep_aspect": banner_keep_aspect,
        "banner_mode": banner_mode,
        "banner_source_crop": banner_source_crop,
        "source_file": source_path.name,
        "layout_file": layout_path.name,
        "final_file": final_path.name,
        "export_file": export_name,
        "export_path": str(export_path),
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
        "export_file": export_name,
        "export_path": str(export_path),
        "title_text": title_text,
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
