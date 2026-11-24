"""Reusable ASS caption styles for Film & Series Studio.

Templates are exposed in Film Studio and rendered into the actual MP4.
The CSS preview in film.html mirrors these names, but it remains illustrative
until speech recognition produces the real timed words.
"""
from __future__ import annotations

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
    if not 50 <= position <= 90:
        raise ValueError("Положение субтитров должно быть от 50 до 90%.")
    return style, position


def stamp(t: float) -> str:
    t = max(0, float(t))
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}.{int((t % 1) * 100):02d}"


def clean_text(s: str) -> str:
    return (str(s or "").replace("\\", "").replace("{", "")
            .replace("}", "").replace("\n", " ").replace("\r", " ")
            .replace(",", ",").strip())


def subtitle_ass(segments, width: int, height: int, style: str = "bold", position: int = 78) -> tuple[str, int]:
    """Create an ASS document from Faster-Whisper segments (or equivalents)."""
    style, position = validate(style, position)
    data = STYLES[style]
    font_size = max(14, round(width * data["factor"]))
    margin_v = max(1, round(height * (100 - position) / 100))
    margin_x = max(18, round(width * .04))
    events = []
    for segment in segments:
        words = list(getattr(segment, "words", None) or [])
        if words:
            for index in range(0, len(words), 3):
                group = words[index:index + 3]
                text_parts = [clean_text(getattr(word, "word", "")) for word in group]
                if not any(text_parts):
                    continue
                begin = max(0.0, float(group[0].start))
                end = max(begin + 0.04, float(group[-1].end))
                if style == "karaoke":
                    # ASS karaoke highlights each word at the actual speech time.
                    # \kf takes centiseconds; gaps are folded into the next word.
                    chunks = []
                    previous = begin
                    for word, text in zip(group, text_parts):
                        if not text:
                            continue
                        stop = max(previous + 0.03, float(word.end))
                        dur = max(1, int(round((stop - previous) * 100)))
                        chunks.append(r"{\kf" + str(dur) + "}" + text)
                        previous = stop
                    value = " ".join(chunks)
                else:
                    value = " ".join(text_parts)
                    if data["uppercase"]:
                        value = value.upper()
                    value = r"{\fad(50,80)}" + value
                events.append(
                    f"Dialogue: 0,{stamp(begin)},{stamp(end)},Default,,0,0,0,,{value}"
                )
        else:
            text = clean_text(getattr(segment, "text", ""))
            if not text:
                continue
            if data["uppercase"]:
                text = text.upper()
            begin = max(0.0, float(segment.start))
            end = max(begin + 0.04, float(segment.end))
            events.append(f"Dialogue: 0,{stamp(begin)},{stamp(end)},Default,,0,0,0,,{text}")
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
            str(data["thickness"]), str(data["shadow"]), "2",
            str(margin_x), str(margin_x), str(margin_v), "1",
        ])
        + "\n\n[Events]\n"
        + "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    return header + "\n".join(events) + "\n", len(events)


def save_ass(segments, path: Path, width: int, height: int, style: str, position: int) -> int:
    content, count = subtitle_ass(segments, width, height, style, position)
    Path(path).write_text(content, encoding="utf-8")
    return count
