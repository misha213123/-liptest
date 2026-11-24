"""Maximum-quality OpenAI captions: GPT-Transcribe for dialogue, Whisper-1 timing.

GPT-Transcribe does not provide word timings as of November 2026.
A separate (billable) Whisper-1 request supplies actual word timestamps.
Only conservatively aligned GPT words replace the timed transcript; unmatched
words retain Whisper-1 text/timings rather than inventing timestamps.
This is not forced alignment and does not guarantee exact word synchronization.
"""
from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from types import SimpleNamespace

from film_openai import (
    MAX_AUDIO_BYTES,
    _word_value,
    find_api_key,
    transcribe_openai,
)

TEXT_MODEL = "gpt-transcribe"
TIMING_MODEL = "whisper-1"


def _token(word: str) -> str:
    """Normalize words for comparison but keep all punctuation for output."""
    return re.sub(r"[^\w]+", "", str(word or "").casefold(), flags=re.UNICODE)


def align_text_to_timed_words(
    high_accuracy_text: str, timed_segments
) -> tuple[list[SimpleNamespace], dict]:
    high_words = [w for w in str(high_accuracy_text or "").split() if _token(w)]
    source_words = [
        w for segment in timed_segments
        for w in (getattr(segment, "words", None) or [])
        if _token(getattr(w, "word", ""))
    ]
    if not high_words:
        raise RuntimeError("GPT-Transcribe не вернул текст диалога.")
    if not source_words:
        raise RuntimeError("Whisper-1 не вернул временные метки слов.")

    texts = [str(w.word).strip() for w in source_words]
    old = [_token(t) for t in texts]
    new = [_token(t) for t in high_words]
    matcher = SequenceMatcher(a=old, b=new, autojunk=False)
    changed = 0
    unmatched = 0

    for operation, a0, a1, b0, b1 in matcher.get_opcodes():
        if operation == "equal":
            # Keep GPT punctuation and case even if the actual word is equal.
            for i, j in zip(range(a0, a1), range(b0, b1)):
                texts[i] = high_words[j]
        elif operation == "replace" and (a1 - a0) == (b1 - b0):
            # One-to-one mapping shares the original audio word interval.
            for i, j in zip(range(a0, a1), range(b0, b1)):
                texts[i] = high_words[j]
                changed += 1
        else:
            # Inserting/deleting words has no safe word-level timestamps;
            # do not fabricate timing by stretching neighboring words.
            unmatched += max(a1 - a0, b1 - b0)

    corrected = [
        SimpleNamespace(
            start=float(word.start), end=float(word.end), word=word_text
        )
        for word, word_text in zip(source_words, texts)
    ]
    segments = [
        SimpleNamespace(
            start=corrected[i].start,
            end=corrected[min(i + 2, len(corrected) - 1)].end,
            text=" ".join(w.word for w in corrected[i:i + 3]),
            words=corrected[i:i + 3],
        )
        for i in range(0, len(corrected), 3)
    ]
    return segments, {
        "words": len(corrected),
        "corrected_words": changed,
        "unaligned_words": unmatched,
    }


def transcribe_max(
    audio: Path | str,
    language: str = "ru",
    *,
    client_factory=None,
    root: Path | None = None,
) -> list[SimpleNamespace]:
    """Two explicit paid transcription calls for maximum text + word timing."""
    language = str(language or "auto").lower()
    if language not in ("ru", "en", "auto"):
        raise ValueError("Язык распознавания: ru, en или auto.")
    audio = Path(audio)
    if not audio.is_file() or not (1000 <= audio.stat().st_size <= MAX_AUDIO_BYTES):
        raise ValueError("Для OpenAI нужен звуковой отрывок размером до 24 МиБ.")
    key, source = find_api_key(root)
    if not key:
        raise RuntimeError("OpenAI API-ключ не найден. Выбери локальный Whisper или настрой OPENAI_API_KEY.")
    if client_factory is None:
        from openai import OpenAI
        client_factory = OpenAI
    client = client_factory(
        api_key=key, base_url="https://api.openai.com/v1",
        timeout=180.0, max_retries=1
    )
    args = {"model": TEXT_MODEL}
    # The current API uses 'languages' (plural) for GPT-Transcribe.
    if language != "auto":
        args["extra_body"] = {"languages": [language]}
        args["prompt"] = (
            "Расшифруй речь дословно, сохраняя имена, междометия и паузы. "
            "Не переводи речь на другой язык."
            if language == "ru" else
            "Transcribe the actual speech verbatim; preserve names and interjections. Do not translate."
        )

    print(
        f"[speech] OpenAI maximum transcription: {TEXT_MODEL} + "
        f"{TIMING_MODEL} word timing, language={language} (two paid API requests).",
        flush=True,
    )
    try:
        with audio.open("rb") as stream:
            text_result = client.audio.transcriptions.create(file=stream, **args)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if status in (401, 403):
            message = "OpenAI отклонил ключ или доступ к модели."
        elif status == 429:
            message = "Превышен лимит OpenAI или недостаточно средств API."
        elif status is not None:
            message = f"OpenAI GPT-Transcribe вернул HTTP {status}."
        else:
            message = "OpenAI GPT-Transcribe недоступен или произошёл тайм-аут."
        # Do not leak provider exception details or request credentials.
        raise RuntimeError(message) from None

    transcript = _word_value(text_result, "text")
    if not str(transcript or "").strip():
        raise RuntimeError("GPT-Transcribe не распознал речь. Остановлено до второго платного запроса.")
    try:
        timed = transcribe_openai(
            audio, language=language,
            client_factory=client_factory, root=root
        )
    except Exception:
        # The first paid call might have succeeded, while the second failed.
        # Never claim word-accurate subtitle output without timing.
        print("[speech] GPT text received, but word timing unavailable.", flush=True)
        raise
    result, stats = align_text_to_timed_words(str(transcript), timed)
    print(
        f"[speech] GPT text aligned to Whisper timing: "
        f"{stats['corrected_words']} corrected, "
        f"{stats['unaligned_words']} unmatched, "
        f"{stats['words']} timed words; unmatched keep Whisper text.",
        flush=True,
    )
    return result
