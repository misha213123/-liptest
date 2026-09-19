#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("output_json")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--language", default="ru")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--cache-root", default="/workspace/whisperx-cache")
    args = ap.parse_args()

    cache_root = Path(args.cache_root).resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache_root / "hf"))
    os.environ.setdefault("TORCH_HOME", str(cache_root / "torch"))

    import torch
    import whisperx

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    batch_size = max(1, int(args.batch_size))

    audio = whisperx.load_audio(str(Path(args.audio).resolve()))

    model = whisperx.load_model(
        args.model,
        device,
        compute_type=compute_type,
        language=args.language or None,
        vad_method="silero",
        download_root=str(cache_root / "asr"),
    )
    result = model.transcribe(audio, batch_size=batch_size)

    language = str(result.get("language") or args.language or "ru")
    segments_before_align = result.get("segments") or []

    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    align_model, metadata = whisperx.load_align_model(
        language_code=language,
        device=device,
        model_dir=str(cache_root / "align"),
    )
    aligned = whisperx.align(
        segments_before_align,
        align_model,
        metadata,
        audio,
        device,
        interpolate_method="nearest",
        return_char_alignments=False,
        print_progress=False,
    )

    del align_model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    out_segments = []
    out_words = []
    for seg in aligned.get("segments") or []:
        seg_words = []
        for w in seg.get("words") or []:
            if "start" not in w or "end" not in w:
                continue
            token = str(w.get("word") or "").strip()
            if not token:
                continue
            item = {
                "word": token,
                "start": float(w["start"]),
                "end": float(w["end"]),
                "score": float(w.get("score") or 0.0),
            }
            out_words.append(item)
            seg_words.append(item)

        if seg_words:
            out_segments.append({
                "start": float(seg_words[0]["start"]),
                "end": float(seg_words[-1]["end"]),
                "text": str(seg.get("text") or "").strip(),
            })

    payload = {
        "ok": bool(out_words),
        "engine": "whisperx",
        "model": args.model,
        "language": language,
        "device": device,
        "words": out_words,
        "segments": out_segments,
        "text": " ".join(str(s.get("text") or "").strip() for s in out_segments).strip(),
    }

    Path(args.output_json).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not out_words:
        raise RuntimeError("WhisperX alignment returned no timed words")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
