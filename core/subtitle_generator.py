import os
import re

class SubtitleGeneratorMixin:
    def format_time(self, seconds: float) -> str:
        """Convert seconds to ASS time format"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"

    def create_ass_subtitle_karaoke(self, transcript, output_path: str, time_offset: float = 0):
        """Create configurable karaoke captions for short-form video."""
        cfg = dict(getattr(self, "subtitle_settings", {}) or {})

        font_size = max(28, min(96, int(cfg.get("font_size", 48) or 48)))
        position_y_pct = max(0.40, min(0.92, float(cfg.get("position_y_pct", 0.76) or 0.76)))
        safe_margin = max(20, min(220, int(cfg.get("safe_margin", 72) or 72)))
        max_words = max(1, min(7, int(cfg.get("max_words", 3) or 3)))
        outline = max(0, min(10, int(cfg.get("outline", 3) or 3)))
        shadow = max(0, min(8, int(cfg.get("shadow", 1) or 1)))
        spacing = max(-2, min(8, int(cfg.get("spacing", 0) or 0)))
        font_name = str(cfg.get("font_name", "Arial Black") or "Arial Black").replace(",", " ")
        uppercase = bool(cfg.get("uppercase", True))
        background_box = bool(cfg.get("background_box", False))
        background_opacity = max(0, min(100, int(cfg.get("background_opacity", 55) or 55)))

        def ass_style_color(hex_value: str, fallback: str, alpha: int = 0) -> str:
            s = str(hex_value or "").strip().lstrip("#")
            if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
                s = fallback.lstrip("#")
            r, g, b = s[0:2], s[2:4], s[4:6]
            return f"&H{alpha:02X}{b}{g}{r}".upper()

        primary = ass_style_color(cfg.get("highlight_color", "#FFD400"), "#FFD400")
        secondary = ass_style_color(cfg.get("text_color", "#FFFFFF"), "#FFFFFF")
        outline_color = ass_style_color(cfg.get("outline_color", "#000000"), "#000000")
        bg_alpha = int(round(255 * (1.0 - background_opacity / 100.0)))
        back_color = ass_style_color(cfg.get("background_color", "#000000"), "#000000", bg_alpha)
        border_style = 3 if background_box else 1
        margin_v = int(round((1.0 - position_y_pct) * 1280))

        ass_content = f"""[Script Info]
Title: Karaoke captions
ScriptType: v4.00+
WrapStyle: 2
PlayResX: 720
PlayResY: 1280
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary},{secondary},{outline_color},{back_color},-1,0,0,0,100,100,{spacing},0,{border_style},{outline},{shadow},2,{safe_margin},{safe_margin},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        words = list(getattr(transcript, "words", None) or [])
        events = []

        if words:
            chunk = []
            for w in words:
                token = str(getattr(w, "word", "") or "").strip()
                if not token:
                    continue
                if chunk and (
                    len(chunk) >= max_words
                    or len(" ".join(str(getattr(x, "word", "") or "").strip() for x in chunk + [w])) > 28
                    or float(getattr(w, "start", 0.0)) - float(getattr(chunk[-1], "end", 0.0)) > 0.60
                ):
                    events.append(chunk)
                    chunk = []
                chunk.append(w)
            if chunk:
                events.append(chunk)

        for chunk in events:
            parts = []
            for w in chunk:
                token = str(getattr(w, "word", "") or "").strip()
                if uppercase:
                    token = token.upper()
                dur_cs = max(1, int(round((float(w.end) - float(w.start)) * 100)))
                parts.append("{\\kf%d}%s" % (dur_cs, token))
            start_t = max(0.0, float(chunk[0].start) + time_offset)
            end_t = max(start_t + 0.15, float(chunk[-1].end) + time_offset)
            ass_content += (
                f"Dialogue: 0,{self.format_time(start_t)},{self.format_time(end_t)},"
                f"Default,,0,0,0,,{' '.join(parts)}\n"
            )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

    def create_ass_subtitle_capcut(self, transcript, output_path: str, time_offset: float = 0):
        """Create configurable TikTok/CapCut-style captions with word highlighting."""
        cfg = dict(getattr(self, "subtitle_settings", {}) or {})

        font_size = max(28, min(96, int(cfg.get("font_size", 48) or 48)))
        position_y_pct = max(0.40, min(0.92, float(cfg.get("position_y_pct", 0.76) or 0.76)))
        safe_margin = max(20, min(220, int(cfg.get("safe_margin", 72) or 72)))
        max_words = max(1, min(7, int(cfg.get("max_words", 3) or 3)))
        user_max_chars = max(8, min(48, int(cfg.get("max_chars", 24) or 24)))
        outline = max(0, min(10, int(cfg.get("outline", 3) or 3)))
        shadow = max(0, min(8, int(cfg.get("shadow", 1) or 1)))
        spacing = max(-2, min(8, int(cfg.get("spacing", 0) or 0)))
        font_name = str(cfg.get("font_name", "Arial Black") or "Arial Black").replace(",", " ")
        text_hex = str(cfg.get("text_color", "#FFFFFF") or "#FFFFFF")
        highlight_hex = str(cfg.get("highlight_color", "#25F4EE") or "#25F4EE")
        outline_hex = str(cfg.get("outline_color", "#000000") or "#000000")
        background_hex = str(cfg.get("background_color", "#000000") or "#000000")
        uppercase = bool(cfg.get("uppercase", True))
        active_boost = bool(cfg.get("active_boost", True))
        background_box = bool(cfg.get("background_box", False))
        background_opacity = max(0, min(100, int(cfg.get("background_opacity", 55) or 55)))

        def ass_color(hex_value: str, fallback: str, alpha: int = 0) -> str:
            s = str(hex_value or "").strip().lstrip("#")
            if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
                s = fallback.lstrip("#")
            r, g, b = s[0:2], s[2:4], s[4:6]
            return f"&H{alpha:02X}{b}{g}{r}".upper()

        text_color = ass_color(text_hex, "#FFFFFF")
        highlight_color = ass_color(highlight_hex, "#25F4EE")
        outline_color = ass_color(outline_hex, "#000000")
        bg_alpha = int(round(255 * (1.0 - background_opacity / 100.0)))
        back_color = ass_color(background_hex, "#000000", bg_alpha)
        border_style = 3 if background_box else 1

        def inline_color(style_color: str) -> str:
            raw = style_color.replace("&H", "")
            return f"&H{raw[-6:]}&"

        text_inline = inline_color(text_color)
        highlight_inline = inline_color(highlight_color)
        margin_v = int(round((1.0 - position_y_pct) * 1280))

        safe_width = max(220, 720 - 2 * safe_margin)
        dynamic_char_limit = max(8, int(safe_width / max(1.0, font_size * 0.58)))
        max_chars = min(user_max_chars, dynamic_char_limit)

        ass_content = f"""[Script Info]
Title: Auto-generated captions
ScriptType: v4.00+
WrapStyle: 2
PlayResX: 720
PlayResY: 1280
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{text_color},{highlight_color},{outline_color},{back_color},-1,0,0,0,100,100,{spacing},0,{border_style},{outline},{shadow},2,{safe_margin},{safe_margin},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        def clean_text(value):
            text = str(value or "").strip()
            text = re.sub(r"\s+", " ", text)
            return text.replace("{", "（").replace("}", "）")

        raw_words = list(getattr(transcript, "words", None) or [])
        words = []
        last_start = -1.0
        last_token = None

        for w in raw_words:
            token = clean_text(getattr(w, "word", ""))
            if not token:
                continue
            try:
                start = max(0.0, float(getattr(w, "start", 0.0)) + time_offset)
                end = max(start + 0.06, float(getattr(w, "end", start + 0.15)) + time_offset)
            except Exception:
                continue
            if last_token == token and abs(start - last_start) < 0.08:
                continue
            if start + 0.05 < last_start:
                continue
            words.append({"text": token, "start": start, "end": end})
            last_start = start
            last_token = token

        if not words:
            for seg in list(getattr(transcript, "segments", None) or []):
                text = clean_text(seg.get("text", ""))
                if not text:
                    continue
                parts = text.split()
                if not parts:
                    continue
                try:
                    s = max(0.0, float(seg.get("start", 0.0)) + time_offset)
                    e = max(s + 0.2, float(seg.get("end", s + 1.0)) + time_offset)
                except Exception:
                    continue
                per = max(0.08, (e - s) / len(parts))
                for i, token in enumerate(parts):
                    ws = s + i * per
                    words.append({
                        "text": clean_text(token),
                        "start": ws,
                        "end": min(e, ws + per),
                    })

        if not words:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(ass_content)
            return

        chunks = []
        current = []
        for word in words:
            proposed = current + [word]
            proposed_text = " ".join(x["text"] for x in proposed)
            gap = word["start"] - current[-1]["end"] if current else 0.0
            if current and (
                len(proposed) > max_words
                or len(proposed_text) > max_chars
                or gap > 0.60
            ):
                chunks.append(current)
                current = [word]
            else:
                current = proposed
        if current:
            chunks.append(current)

        for chunk in chunks:
            chunk_end = max(x["end"] for x in chunk)
            for i, active_word in enumerate(chunk):
                start = active_word["start"]
                if i + 1 < len(chunk):
                    end = max(start + 0.10, chunk[i + 1]["start"])
                else:
                    end = max(start + 0.16, chunk_end)
                end = min(end, start + 1.20)

                parts = []
                for j, item in enumerate(chunk):
                    token = item["text"].upper() if uppercase else item["text"]
                    if j == i:
                        if active_boost:
                            parts.append(
                                "{\\c" + highlight_inline
                                + "\\fscx112\\fscy112}" + token
                                + "{\\c" + text_inline + "\\fscx100\\fscy100}"
                            )
                        else:
                            parts.append(
                                "{\\c" + highlight_inline + "}" + token
                                + "{\\c" + text_inline + "}"
                            )
                    else:
                        parts.append(token)

                line = " ".join(parts)
                ass_content += (
                    f"Dialogue: 0,{self.format_time(start)},{self.format_time(end)},"
                    f"Default,,0,0,0,,{line}\n"
                )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
