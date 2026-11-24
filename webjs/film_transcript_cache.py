"""Local transcript cache: changing caption STYLE never re-bills cloud speech.

Cache key includes video fingerprint, selected excerpt, provider and language.
Only recognized words are stored; API keys are never written to disk.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace


def _fingerprint(source: Path, start: float, end: float, engine: str, model: str, language: str) -> str:
    source = Path(source)
    stat = source.stat()
    raw = json.dumps({
        "path": str(source.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "start": round(float(start), 3),
        "end": round(float(end), 3),
        "engine": engine,
        "model": model if engine == "local" else "api",
        "language": language,
        "version": 1,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _safe_float(value) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("Invalid transcript timestamp.")
    return number


def _serialize(segments) -> list[dict]:
    result = []
    for segment in segments:
        text = str(getattr(segment, "text", "") or "")
        words = []
        for word in getattr(segment, "words", None) or []:
            words.append({
                "start": _safe_float(getattr(word, "start")),
                "end": _safe_float(getattr(word, "end")),
                "word": str(getattr(word, "word", "")),
            })
        start = _safe_float(getattr(segment, "start"))
        end = _safe_float(getattr(segment, "end"))
        result.append({"text": text, "start": start, "end": end, "words": words})
    if len(result) > 10000:
        raise ValueError("Transcript has too many segments.")
    return result


def _deserialize(items) -> list[SimpleNamespace]:
    if not isinstance(items, list) or len(items) > 10000:
        raise ValueError("Invalid transcript cache.")
    result = []
    for row in items:
        if not isinstance(row, dict):
            raise ValueError("Invalid transcript cache row.")
        words = [
            SimpleNamespace(
                word=str(word["word"]),
                start=_safe_float(word["start"]),
                end=_safe_float(word["end"]),
            )
            for word in row.get("words", [])
        ]
        result.append(SimpleNamespace(
            text=str(row["text"]),
            start=_safe_float(row["start"]),
            end=_safe_float(row["end"]),
            words=words,
        ))
    return result


def transcribe_cached(
    source: Path, start: float, end: float, engine: str,
    model: str, language: str, producer, *, cache_dir: Path,
) -> list:
    """Use cache or call producer once. Reformatting ASS costs no new API call."""
    name = _fingerprint(source, start, end, engine, model, language) + ".json"
    cache_dir = Path(cache_dir)
    target = cache_dir / name
    if target.is_file():
        try:
            result = _deserialize(json.loads(target.read_text(encoding="utf-8")))
            print("[speech] ♻ Reusing cached speech transcript; no new API calls.", flush=True)
            return result
        except (OSError, ValueError, KeyError, TypeError):
            # Re-run recognition if the cache was corrupted; do not reuse.
            pass
    segments = list(producer())
    # Don't fail a successful transcription if the cache cannot be written.
    try:
        data = _serialize(segments)
        cache_dir.mkdir(parents=True, exist_ok=True)
        fd, name_tmp = tempfile.mkstemp(prefix=".transcript-", suffix=".tmp", dir=cache_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
            os.replace(name_tmp, target)
        finally:
            try:
                Path(name_tmp).unlink(missing_ok=True)
            except OSError:
                pass
    except (OSError, TypeError, ValueError) as exc:
        print("[speech] Transcript cache unavailable: " + type(exc).__name__, flush=True)
    return segments
