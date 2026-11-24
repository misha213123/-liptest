"""OpenAI cloud subtitles for Film & Series Studio.

Uses only the official OpenAI audio transcription endpoint and the selected
audio excerpt. No API key is sent to the browser, GitHub, render jobs or logs.

The current word-timed API model (whisper-1) is scheduled for retirement
on 2027-02-26. Replace it with a future timestamp-capable model when available.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

TRANSCRIPTION_MODEL = "whisper-1"
MAX_AUDIO_BYTES = 24 * 1024 * 1024  # OpenAI hard limit: 25 MB/request.
_OPENAI_HOST = "api.openai.com"


def _official_openai_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value or ""))
        return (
            parsed.scheme == "https"
            and parsed.hostname == _OPENAI_HOST
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
    except (ValueError, TypeError):
        return False


def _nonempty(candidate) -> str:
    return str(candidate or "").strip() if isinstance(candidate, str) else ""


def find_api_key(root: Path | None = None) -> tuple[str, str]:
    """Read a dedicated key, then safely reuse a previously saved OpenAI key.

    Never accept tokens from generic provider settings unless their base URL
    explicitly identifies the *official* OpenAI API, not OpenRouter or another
    OpenAI-compatible third-party service.
    """
    environment = _nonempty(os.environ.get("OPENAI_API_KEY"))
    if environment:
        return environment, "OPENAI_API_KEY"

    if root is None:
        root = Path(__file__).resolve().parents[1]
    config_path = Path(root) / "config.json"
    if not config_path.is_file():
        return "", ""
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return "", ""
    if not isinstance(cfg, dict):
        return "", ""

    providers = cfg.get("ai_providers") or {}
    if not isinstance(providers, dict):
        providers = {}
    caption = providers.get("caption_maker") or {}
    if isinstance(caption, dict):
        key = _nonempty(caption.get("openai_api_key"))
        if key:
            return key, "config.caption_maker.openai_api_key"

    direct = _nonempty(cfg.get("openai_api_key"))
    if direct:
        return direct, "config.openai_api_key"

    openai_settings = providers.get("openai") or {}
    if isinstance(openai_settings, dict):
        key = _nonempty(openai_settings.get("api_key"))
        if key and _official_openai_url(openai_settings.get("base_url") or "https://api.openai.com/v1"):
            return key, "config.ai_providers.openai"

    for name in ("hook_maker", "highlight_finder"):
        service = providers.get(name) or {}
        if not isinstance(service, dict):
            continue
        key = _nonempty(service.get("api_key"))
        if key and _official_openai_url(service.get("base_url")):
            return key, "config.ai_providers." + name

    legacy = _nonempty(cfg.get("api_key"))
    if legacy and _official_openai_url(cfg.get("base_url")):
        return legacy, "config.api_key"

    return "", ""


def availability(root: Path | None = None) -> dict:
    key, source = find_api_key(root)
    return {
        "configured": bool(key),
        "source": source if key else "",
        "engine": "openai",
        "model": TRANSCRIPTION_MODEL,
        "retirement_date": "2027-02-26",
    }


def _word_value(item, field: str):
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field, None)


def normalise_words(raw_words) -> list[SimpleNamespace]:
    """Convert cloud word timestamps into existing ASS renderer segments.

    No made-up word times: fail explicitly if OpenAI returned no usable words.
    """
    result = []
    last_end = 0.0
    for item in raw_words or []:
        word = str(_word_value(item, "word") or "").strip()
        if not word:
            continue
        begin_raw = _word_value(item, "start")
        finish_raw = _word_value(item, "end")
        try:
            begin = float(begin_raw)
            finish = float(finish_raw)
        except (ValueError, TypeError):
            continue
        if not all(map(math.isfinite, (begin, finish))) or finish <= begin:
            continue
        begin = max(0.0, begin, last_end)
        finish = max(begin + .01, finish)
        result.append(SimpleNamespace(word=word, start=begin, end=finish))
        last_end = finish
    if not result:
        raise RuntimeError(
            "OpenAI не вернул таймкоды слов. Попробуй локальный Whisper "
            "или проверь качество звуковой дорожки."
        )
    # _make_subtitles expects Whisper-style segments with .words.
    # Caption renderer groups words by threes for Shorts/Reels.
    return [
        SimpleNamespace(
            start=result[i].start,
            end=result[min(i + 2, len(result)-1)].end,
            words=result[i:i+3],
            text=" ".join(word.word for word in result[i:i+3])
        )
        for i in range(0, len(result), 3)
    ]


def transcribe_openai(
    audio: Path | str,
    language: str = "ru",
    *,
    client_factory=None,
    root: Path | None = None,
):
    """Upload only a selected, bounded audio clip; return word-timed segments.

    Authentication errors are sanitized to avoid putting secret-bearing
    exception bodies into the UI render log. No silent paid-to-local fallback.
    """
    language = str(language or "auto").lower()
    if language not in ("ru", "en", "auto"):
        raise ValueError("Язык OpenAI: ru, en или auto.")

    file = Path(audio)
    if not file.is_file():
        raise FileNotFoundError("Звуковой фрагмент для OpenAI не найден.")
    size = file.stat().st_size
    if size < 1000 or size > MAX_AUDIO_BYTES:
        raise ValueError(
            "Аудиофайл для OpenAI слишком большой или пустой. "
            "Максимум 24 МиБ на один фрагмент."
        )
    key, source = find_api_key(root)
    if not key:
        raise RuntimeError(
            "OpenAI API-ключ не настроен. Добавь OPENAI_API_KEY в окружение "
            "Auto Clipper или настрой ключ OpenAI в локальном config.json. "
            "Ключ не нужно вставлять в GitHub."
        )

    if client_factory is None:
        from openai import OpenAI
        client_factory = OpenAI
    client = client_factory(
        api_key=key,
        base_url="https://api.openai.com/v1",
        timeout=180.0,
        max_retries=1,
    )
    kwargs = {
        "model": TRANSCRIPTION_MODEL,
        "response_format": "verbose_json",
        "timestamp_granularities": ["word"],
    }
    if language != "auto":
        kwargs["language"] = language

    print(
        f"[speech] OpenAI cloud transcription (model={TRANSCRIPTION_MODEL}, "
        f"language={language}, source={source}); audio {size / 1048576:.1f} MiB.",
        flush=True,
    )
    try:
        with file.open("rb") as audio_stream:
            response = client.audio.transcriptions.create(
                file=audio_stream, **kwargs
            )
    except Exception as exc:
        # Never print the raw API exception (may contain request information).
        status = getattr(exc, "status_code", None)
        if status in (401, 403):
            reason = "ключ отклонён или нет доступа к модели."
        elif status == 429:
            reason = "лимит запросов или недостаточно средств API."
        elif status in (400, 413):
            reason = "неподдерживаемый аудиофайл или слишком большой запрос."
        elif status is not None:
            reason = f"сервер вернул HTTP {status}."
        else:
            reason = "ошибка соединения, тайм-аут или недоступность сервиса."
        raise RuntimeError(
            "Ошибка OpenAI: " + reason +
            " Проверь ключ и баланс API либо выбери локальный Whisper."
        ) from None

    segments = normalise_words(_word_value(response, "words"))
    print(
        f"[speech] OpenAI word timestamps received: "
        f"{sum(len(s.words) for s in segments)} words.",
        flush=True,
    )
    return segments


if __name__ == "__main__":
    print(json.dumps(availability(), ensure_ascii=False))
