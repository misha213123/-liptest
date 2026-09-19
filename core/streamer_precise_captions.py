from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace


class PreciseCaptionError(RuntimeError):
    pass


def whisperx_available() -> bool:
    python_bin = Path(
        os.environ.get("WHISPERX_PYTHON", "/workspace/whisperx-venv/bin/python")
    )
    return python_bin.exists()


def transcribe_words_whisperx(
    audio_path: str | Path,
    *,
    app_dir: str | Path,
    language: str = "ru",
    model: str = "large-v3",
    batch_size: int = 8,
    cache_root: str | Path = "/workspace/whisperx-cache",
    log=None,
):
    log = log or (lambda _m: None)
    app_dir = Path(app_dir).resolve()
    audio_path = Path(audio_path).resolve()
    python_bin = Path(
        os.environ.get("WHISPERX_PYTHON", "/workspace/whisperx-venv/bin/python")
    )

    if not python_bin.exists():
        raise PreciseCaptionError(
            f"WhisperX Python not found: {python_bin}"
        )

    helper = app_dir / "tools" / "whisperx_align.py"
    if not helper.exists():
        raise PreciseCaptionError(f"WhisperX helper not found: {helper}")

    fd, tmp_name = tempfile.mkstemp(prefix="whisperx_words_", suffix=".json")
    os.close(fd)
    out_json = Path(tmp_name)

    cmd = [
        str(python_bin),
        str(helper),
        str(audio_path),
        str(out_json),
        "--model",
        str(model),
        "--language",
        str(language or "ru"),
        "--batch-size",
        str(max(1, int(batch_size))),
        "--cache-root",
        str(cache_root),
    ]

    env = dict(os.environ)
    env.setdefault("HF_HOME", str(Path(cache_root) / "hf"))
    env.setdefault("TORCH_HOME", str(Path(cache_root) / "torch"))
    # NVENC enumeration shim is only needed by FFmpeg. Keep WhisperX/CUDA clean.
    env.pop("LD_PRELOAD", None)

    log(
        f"[streamer] 🎯 WhisperX forced alignment: model={model}, "
        f"language={language}, batch={batch_size}"
    )
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=900,
    )

    try:
        if proc.returncode != 0:
            tail = "\n".join((proc.stderr or proc.stdout or "").splitlines()[-50:])
            raise PreciseCaptionError("WhisperX failed:\n" + tail)

        data = json.loads(out_json.read_text(encoding="utf-8"))
        words = [
            SimpleNamespace(
                word=str(w.get("word") or "") + " ",
                start=float(w.get("start") or 0.0),
                end=float(w.get("end") or 0.0),
            )
            for w in (data.get("words") or [])
            if str(w.get("word") or "").strip()
        ]
        segments = list(data.get("segments") or [])
        if not words:
            raise PreciseCaptionError("WhisperX returned zero aligned words")

        log(
            f"[streamer] ✓ WhisperX: {len(words)} слов с forced-alignment "
            f"таймкодами ({data.get('device', '?')})."
        )
        return SimpleNamespace(
            words=words,
            segments=segments,
            text=str(data.get("text") or ""),
        )
    finally:
        try:
            out_json.unlink(missing_ok=True)
        except Exception:
            pass
