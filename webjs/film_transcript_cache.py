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


def episode_cache_directory(source: Path, language: str, root: Path) -> Path:
    """Compatible with existing film_highlights Whisper-1 cache keys."""
    source = Path(source)
    stat = source.stat()
    key = hashlib.sha256((
        str(source.resolve()) + "|" + str(stat.st_size) +
        "|" + str(stat.st_mtime_ns) + "|" + language + "|whisper1-v1"
    ).encode("utf-8")).hexdigest()[:24]
    return Path(root) / key


def cached_episode_excerpt(source: Path, start: float, end: float,
                           language: str, *, root: Path):
    """Reuse a completed episode transcript; rebase word times to clip start."""
    try:
        path = episode_cache_directory(source, language, root) / "transcript.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return None
        selected = []
        for row in raw:
            a, b = _safe_float(row["start"]), _safe_float(row["end"])
            if a >= end or b <= start:
                continue
            a, b = max(0.0, a-start), min(end-start, b-start)
            if b > a:
                selected.append(SimpleNamespace(word=str(row["word"]), start=a, end=b))
        selected.sort(key=lambda w: w.start)
        return [
            SimpleNamespace(start=group[0].start, end=group[-1].end,
                            words=group, text=" ".join(w.word for w in group))
            for i in range(0, len(selected), 3)
            if (group := selected[i:i+3])
        ]
    except (OSError, ValueError, TypeError, KeyError):
        return None


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
