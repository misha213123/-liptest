"""Reliable per-highlight video downloads for Streamer Clips.

A single yt-dlp invocation with several --download-sections options can
produce only one output file. Never guess which requested time span it
contains. Download/cache each numbered section independently instead.
"""
from __future__ import annotations

import json
from pathlib import Path


def get_cached_section(core, url: str, sections: list, index: int, output_dir: Path, resolution: str, log=None) -> Path:
    """Return the exact numbered clip; reuse it only when its manifest matches."""
    log = log or (lambda _message: None)
    if not isinstance(sections, list) or not 0 <= index < len(sections):
        raise ValueError("Неверный индекс секции Streamer")
    spec = sections[index]
    if not isinstance(spec, dict):
        raise ValueError("Неверный формат секции Streamer")
    start = str(spec.get("start_time") or "").strip().replace(",", ".")
    end = str(spec.get("end_time") or "").strip().replace(",", ".")
    if not start or not end:
        raise ValueError(f"У секции {index + 1} отсутствуют таймкоды")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"section_{index + 1:03d}.mp4"
    manifest = output_dir / f"section_{index + 1:03d}.json"
    expected = {"url": url, "start": start, "end": end, "resolution": resolution}

    try:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        metadata = None
    if (
        metadata == expected
        and target.is_file()
        and target.stat().st_size >= 10_000
    ):
        log(f"[streamer] ♻ Использую кэш секции {index + 1}/{len(sections)}: {start}–{end}")
        return target

    manifest.unlink(missing_ok=True)
    target.unlink(missing_ok=True)
    log(f"[streamer] Скачиваю отдельно секцию {index + 1}/{len(sections)}: {start}–{end}")
    result = Path(core.download_video_section(url, start, end, str(target), resolution=resolution))
    if not result.is_file() or result.stat().st_size < 10_000:
        raise RuntimeError(f"Загрузка секции {index + 1} не создала полноценный видеофайл")
    if result.resolve() != target.resolve():
        if result.suffix.lower() != ".mp4":
            raise RuntimeError(f"Секция {index + 1}: ожидался MP4, получен {result.suffix}")
        target.write_bytes(result.read_bytes())

    # Publish the manifest only after yt-dlp produced the complete target.
    temporary = manifest.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
    temporary.replace(manifest)
    log(f"[streamer] ✓ Секция {index + 1}/{len(sections)} готова")
    return target
