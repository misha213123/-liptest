"""Reusable ASS caption styles for Film & Series Studio.

Templates are exposed in Film Studio and rendered into the actual MP4.
The CSS preview in film.html mirrors these names, but it remains illustrative
until speech recognition produces the real timed words.
"""
from __future__ import annotations

import math
import unicodedata
from pathlib import Path

STYLES = {
    "bold": {"font": "Arial", "factor": 0.074, "color": "&H00FFFFFF",
             "secondary": "&H0000FFFF", "outline": "&H00101010",
             "bold": 1, "border": 1, "thickness": 4, "shadow": 2, "uppercase": True},
    "karaoke": {"font": "Arial", "factor": 0.068, "color": "&H0000FFFF",
                "secondary": "&H00FFFFFF", "outline": "&H00101010",
                "bold": 1, "border": 1, "thickness": 4, "shadow": 2, "uppercase": False},
    "cinema": {"font": "Segoe UI", "factor": 0.056, "color": "&H00FFFFFF",
               "secondary": "&H0000FFFF", "outline": "&H00181818",
               "bold": 0, "border": 1, "thickness": 2, "shadow": 2, "uppercase": False},
    "minimal": {"font": "Segoe UI", "factor": 0.063, "color": "&H00FFFFFF",
                "secondary": "&H0000FFFF", "outline": "&H00191919",
                "bold": 1, "border": 1, "thickness": 1, "shadow": 1, "uppercase": False},
    "boxed": {"font": "Arial", "factor": 0.061, "color": "&H00FFFFFF",
              "secondary": "&H0000FFFF", "outline": "&H00161616",
              "bold": 1, "border": 3, "thickness": 2, "shadow": 0, "uppercase": False},
}


def validate(style: str, position: int = 78) -> tuple[str, int]:
    style = str(style or "bold").lower()
    if style not in STYLES:
        raise ValueError("Неизвестный шаблон субтитров.")
    try:
        position = int(position)
    except (ValueError, TypeError):
        raise ValueError("Положение субтитров должно быть числом.") from None
    if not 10 <= position <= 95:
        raise ValueError("Положение субтитров должно быть от 10 до 95%.")
    return style, position


def stamp(t: float) -> str:
    # Round to integer centiseconds first; floating-point truncation
    # incorrectly turns 1.20 into 1.19 in some ASR timestamp combinations.
    cs = max(0, int(round(float(t) * 100)))
    hours, remainder = divmod(cs, 360000)
    minutes, remainder = divmod(remainder, 6000)
    seconds, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def clean_text(s: str) -> str:
    return (str(s or "").replace("\\", "").replace("{", "")
            .replace("}", "").replace("\n", " ").replace("\r", " ")
            .strip())



def caption_size(value: int) -> int:
    try:
        size = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Размер субтитров должен быть от 30 до 180%.") from exc
    if not 30 <= size <= 180:
        raise ValueError("Размер субтитров должен быть от 30 до 180%.")
    return size


def caption_letter_case(value: str) -> str:
    case = str(value or "source").lower()
    if case not in ("source", "lower", "upper"):
        raise ValueError("Регистр субтитров должен быть source/lower/upper.")
    return case


def apply_caption_case(value: str, case: str, default_upper: bool = False) -> str:
    if case == "lower":
        return value.lower()
    if case == "upper" or (case == "source" and default_upper):
        return value.upper()
    return value


def caption_words_count(value: int) -> int:
    """Validate visible words per cue; output 1..8 actual recognized words."""
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Количество слов должно быть числом от 1 до 8.") from exc
    if count not in range(1, 9):
        raise ValueError("Выбери от 1 до 8 слов в субтитрах.")
    return count


def caption_text(value: str, remove_punctuation: bool = False) -> str:
    """Sanitize ASS markup and optionally remove punctuation from speech.

    Preserve lexical hyphens/apostrophes inside words such as «кто-то»,
    remove external periods, commas, quotes, emojis' punctuation etc.
    """
    text = clean_text(value)
    if not remove_punctuation:
        return text
    result = []
    for i, char in enumerate(text):
        if not unicodedata.category(char).startswith("P"):
            result.append(char)
            continue
        if char in ("-", "‐", "‑", "'", "’") and i and i + 1 < len(text):
            if text[i - 1].isalnum() and text[i + 1].isalnum():
                result.append(char)
    return "".join(result).strip()


def _group_words(segments, word_limit: int) -> list[tuple[str, object]]:
    """Merge consecutive word-timed chunks independently from Whisper segments.

    Cloud responses currently arrive in 3-word segments, so grouping only
    inside each segment breaks selections of 4–8 words. Use the flattened
    original word timeline, but split at significant speech pauses (0.9s)
    and avoid displaying a cue for longer than ~4 seconds.
    """
    timeline = []
    buffer = []
    previous_end = None

    def flush():
        nonlocal buffer, previous_end
        if buffer:
            timeline.append(("words", buffer))
        buffer = []
        previous_end = None

    for segment in segments:
        recognized = list(getattr(segment, "words", None) or [])
        if not recognized:
            flush()
            timeline.append(("plain", segment))
            continue
        for word in recognized:
            text = clean_text(getattr(word, "word", ""))
            if not text:
                continue
            try:
                start = float(word.start)
                end = float(word.end)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(start) or not math.isfinite(end) or end <= start:
                continue
            if buffer and (
                len(buffer) >= word_limit
                or (previous_end is not None and start - previous_end >= 0.9)
                or end - float(buffer[0].start) > 4.0
            ):
                flush()
            buffer.append(word)
            previous_end = end
    flush()
    return timeline


def subtitle_ass(
    segments, width: int, height: int, style: str = "bold", position: int = 78,
    offset: float = 0.0, words_per_caption: int = 3,
    remove_punctuation: bool = False,
    size_percent: int = 100, letter_case: str = "source",
) -> tuple[str, int]:
    """Create ASS cues with configurable words, no invented word timestamps."""
    style, position = validate(style, position)
    words_per_caption = caption_words_count(words_per_caption)
    size_percent = caption_size(size_percent)
    letter_case = caption_letter_case(letter_case)
    offset = float(offset)
    if not math.isfinite(offset) or abs(offset) > 5:
        raise ValueError("Сдвиг субтитров должен быть от -5 до +5 секунд.")
    if not isinstance(remove_punctuation, bool):
        raise ValueError("Настройка пунктуации должна быть true/false.")
    data = STYLES[style]
    font_size = max(8, round(width * data["factor"] * size_percent / 100))
    margin_v = max(1, round(height * (100 - position) / 100))
    margin_x = max(18, round(width * .04))
    events = []

    for kind, payload in _group_words(segments, words_per_caption):
        if kind == "words":
            group = payload
            parts = [apply_caption_case(
                caption_text(getattr(word, "word", ""), remove_punctuation),
                letter_case, data["uppercase"],
            ) for word in group]
            nonempty = [(word, part) for word, part in zip(group, parts) if part]
            if not nonempty:
                continue
            begin = max(0.0, float(nonempty[0][0].start) + offset)
            end = max(begin + 0.04, float(nonempty[-1][0].end) + offset)
            if style == "karaoke":
                chunks = []
                previous = begin
                for word, word_text in nonempty:
                    # Highlight the exact original word's timestamp.
                    stop = max(previous + 0.03, float(word.end) + offset)
                    dur = max(1, int(round((stop - previous) * 100)))
                    chunks.append(r"{\kf" + str(dur) + "}" + word_text)
                    previous = stop
                value = " ".join(chunks)
            else:
                value = " ".join(part for _, part in nonempty)
                value = r"{\fad(50,80)}" + value
        else:
            segment = payload
            value = apply_caption_case(
                caption_text(getattr(segment, "text", ""), remove_punctuation),
                letter_case, data["uppercase"],
            )
            if not value:
                continue
            begin = max(0.0, float(segment.start) + offset)
            end = max(begin + 0.04, float(segment.end) + offset)
        events.append(
            f"Dialogue: 0,{stamp(begin)},{stamp(end)},Default,,0,0,0,,{value}"
        )
    fmt = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
    )
    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\n"
        f"ScaledBorderAndShadow: yes\nWrapStyle: 2\n"
        "\n[V4+ Styles]\n" + fmt
        + "Style: Default,"
        + ",".join([
            data["font"], str(font_size), data["color"], data["secondary"],
            data["outline"], "&H88000000", str(data["bold"]), "0", "0", "0",
            "100", "100", "0", "0", str(data["border"]),
            str(max(1, round(data["thickness"] * size_percent / 100))),
            str(max(0, round(data["shadow"] * size_percent / 100))), "2",
            str(margin_x), str(margin_x), str(margin_v), "1",
        ])
        + "\n\n[Events]\n"
        + "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    return header + "\n".join(events) + "\n", len(events)


def save_ass(
    segments, path: Path, width: int, height: int, style: str,
    position: int, offset: float = 0.0, words_per_caption: int = 3,
    remove_punctuation: bool = False,
    size_percent: int = 100, letter_case: str = "source",
) -> int:
    content, count = subtitle_ass(
        segments, width, height, style, position, offset,
        words_per_caption, remove_punctuation,
        size_percent, letter_case,
    )
    Path(path).write_text(content, encoding="utf-8")
    return count
