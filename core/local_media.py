from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

from utils.helpers import get_ffmpeg_path


APP_DIR = Path(__file__).resolve().parents[1]
LOCAL_SOURCE_RE = re.compile(r"^local://([A-Za-z0-9_-]{1,40})/([^/?#]+)$")
ALLOWED_VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ts", ".m2ts", ".mts"
}


class LocalMediaError(RuntimeError):
    pass


def is_local_source(value: str) -> bool:
    return str(value or "").strip().lower().startswith("local://")


def resolve_local_source(value: str) -> Path:
    raw = str(value or "").strip()
    match = LOCAL_SOURCE_RE.fullmatch(raw)
    if not match:
        raise LocalMediaError("Некорректный локальный источник.")

    project_id = match.group(1)
    file_name = unquote(match.group(2))
    if Path(file_name).name != file_name:
        raise LocalMediaError("Некорректное имя локального файла.")

    suffix = Path(file_name).suffix.lower()
    if suffix not in ALLOWED_VIDEO_EXTENSIONS:
        raise LocalMediaError(f"Неподдерживаемый видеоформат: {suffix or 'без расширения'}")

    base = (APP_DIR / "output" / "streamer_uploads" / project_id).resolve()
    path = (base / file_name).resolve()
    if path.parent != base:
        raise LocalMediaError("Локальный файл находится вне разрешённой папки.")
    if not path.exists() or not path.is_file():
        raise LocalMediaError("Загруженный локальный файл не найден.")
    if path.stat().st_size < 1024:
        raise LocalMediaError("Локальный видеофайл пустой или повреждён.")
    return path


def _ffprobe_path() -> str:
    ffmpeg = Path(get_ffmpeg_path())
    sibling = ffmpeg.with_name("ffprobe.exe" if ffmpeg.name.lower().endswith(".exe") else "ffprobe")
    return str(sibling) if sibling.exists() else "ffprobe"


def probe_local_source(value: str) -> dict:
    path = resolve_local_source(value)
    cmd = [
        _ffprobe_path(),
        "-v", "error",
        "-show_entries",
        "format=duration,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate",
        "-of", "json",
        str(path),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-20:])
        raise LocalMediaError("ffprobe не смог прочитать локальное видео:\n" + tail)

    try:
        data = json.loads(proc.stdout or "{}")
    except Exception as exc:
        raise LocalMediaError(f"Не удалось разобрать ffprobe: {exc}") from exc

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    if not video:
        raise LocalMediaError("В локальном файле не найден видеопоток.")

    duration = float((data.get("format") or {}).get("duration") or 0.0)
    return {
        "title": path.stem,
        "channel": "Локальный файл",
        "description": "",
        "duration": duration,
        "extractor": "local",
        "path": str(path),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "video_codec": str(video.get("codec_name") or ""),
        "bitrate": int((data.get("format") or {}).get("bit_rate") or 0),
    }


def extract_local_audio(
    source: str,
    output_path: str | Path,
    *,
    start_sec: float = 0.0,
    end_sec: float = 0.0,
) -> Path:
    input_path = resolve_local_source(source)
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    start_sec = max(0.0, float(start_sec or 0.0))
    end_sec = max(0.0, float(end_sec or 0.0))
    cmd = [get_ffmpeg_path(), "-y"]
    if start_sec > 0:
        cmd += ["-ss", f"{start_sec:.3f}"]
    cmd += ["-i", str(input_path)]
    if end_sec > start_sec:
        cmd += ["-t", f"{end_sec - start_sec:.3f}"]
    cmd += [
        "-map", "0:a:0?",
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(output_path),
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1024:
        tail = "\n".join((proc.stderr or "").splitlines()[-30:])
        raise LocalMediaError("Не удалось извлечь аудио из локального видео:\n" + tail)
    return output_path


def cut_local_section(
    source: str,
    output_path: str | Path,
    start_sec: float,
    end_sec: float,
) -> Path:
    input_path = resolve_local_source(source)
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    start_sec = max(0.0, float(start_sec or 0.0))
    end_sec = max(start_sec + 0.1, float(end_sec or 0.0))
    duration = end_sec - start_sec

    # MKV accepts practically every common movie/series video+audio codec, so
    # this fast local cut avoids an unnecessary generation before the real
    # 9:16/1:1 renderer performs its final encode.
    cmd = [
        get_ffmpeg_path(),
        "-y",
        "-ss", f"{start_sec:.3f}",
        "-i", str(input_path),
        "-t", f"{duration:.3f}",
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c", "copy",
        "-fflags", "+genpts",
        "-avoid_negative_ts", "make_zero",
        str(output_path),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 10_000:
        tail = "\n".join((proc.stderr or "").splitlines()[-30:])
        raise LocalMediaError("Не удалось вырезать локальный момент:\n" + tail)
    return output_path
