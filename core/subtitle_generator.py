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
        """Create ASS subtitle file with KTV-style karaoke: the WHOLE sentence is
        shown while each word lights up in yellow (PrimaryColour) as it is spoken,
        with unspoken words staying gray (SecondaryColour).
        """
        ass_content = """[Script Info]
Title: Karaoke captions
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,62,&H0000FFFF&,&H00808080&,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        events = []
        words = list(getattr(transcript, 'words', None) or [])
        segments = list(getattr(transcript, 'segments', None) or [])
        
        def make_karaoke_line(chunk):
            parts = []
            for w in chunk:
                dur_cs = max(1, int(round((w.end - w.start) * 100)))
                parts.append("{\\kf%d}%s" % (dur_cs, str(w.word).strip().upper()))
            return {
                'start': self.format_time(chunk[0].start + time_offset),
                'end': self.format_time(chunk[-1].end + time_offset),
                'text': " ".join(parts)
            }
        
        if words and segments:
            for seg in segments:
                seg_words = [w for w in words
                             if w.start >= seg.get('start', 0) - 0.15
                             and w.start <= seg.get('end', 0) + 0.15]
                if not seg_words:
                    continue
                for i in range(0, len(seg_words), 8):
                    events.append(make_karaoke_line(seg_words[i:i + 8]))
        elif words:
            current = []
            for w in words:
                if current and w.start - current[-1].end > 1.0:
                    events.append(make_karaoke_line(current))
                    current = []
                current.append(w)
            if current:
                events.append(make_karaoke_line(current))
        elif segments:
            for segment in segments:
                start = segment.get('start', 0) + time_offset
                end = segment.get('end', 0) + time_offset
                text = segment.get('text', '').strip().upper()
                if text:
                    events.append({
                        'start': self.format_time(start),
                        'end': self.format_time(end),
                        'text': text
                    })
        
        for event in events:
            ass_content += f"Dialogue: 0,{event['start']},{event['end']},Default,,0,0,0,,{event['text']}\n"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(ass_content)

    def create_ass_subtitle_capcut(self, transcript, output_path: str, time_offset: float = 0):
        """Create stable short-form captions with word highlighting.

        - 2-4 words remain on screen as a phrase.
        - Only the spoken word changes colour.
        - Events are made contiguous to avoid flicker/gaps.
        - Bad/duplicate/non-monotonic Whisper tokens are discarded.
        """
        ass_content = """[Script Info]
Title: Auto-generated captions
ScriptType: v4.00+
WrapStyle: 2
PlayResX: 720
PlayResY: 1280
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,56,&H00FFFFFF,&H0000FFFF,&H00000000,&H70000000,-1,0,0,0,100,100,0,0,1,3,1,2,45,45,185,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        def clean_text(value):
            text = str(value or "").strip()
            text = re.sub(r"\s+", " ", text)
            # ASS override braces in spoken text must never become style commands.
            text = text.replace("{", "（").replace("}", "）")
            return text

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

            # Ignore obvious duplicated Whisper tokens with the same timestamp.
            if last_token == token and abs(start - last_start) < 0.08:
                continue
            if start + 0.05 < last_start:
                continue

            words.append({"text": token, "start": start, "end": end})
            last_start = start
            last_token = token

        # If word timestamps are unavailable, build conservative pseudo-words
        # from segments.
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
                    we = min(e, ws + per)
                    words.append({"text": clean_text(token), "start": ws, "end": we})

        if not words:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(ass_content)
            return

        # Group words into compact readable phrases. A long pause starts a new one.
        chunks = []
        current = []
        for word in words:
            if current:
                gap = word["start"] - current[-1]["end"]
                current_chars = sum(len(x["text"]) for x in current) + max(0, len(current) - 1)
                if len(current) >= 4 or current_chars + 1 + len(word["text"]) > 28 or gap > 0.65:
                    chunks.append(current)
                    current = []
            current.append(word)
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

                # Prevent one phrase from hanging over a large silence.
                end = min(end, start + 1.25)

                parts = []
                for j, item in enumerate(chunk):
                    token = item["text"].upper()
                    if j == i:
                        parts.append("{\\c&H00FFFF&}" + token + "{\\c&HFFFFFF&}")
                    else:
                        parts.append(token)
                line = " ".join(parts)

                ass_content += (
                    f"Dialogue: 0,{self.format_time(start)},{self.format_time(end)},"
                    f"Default,,0,0,0,,{line}\n"
                )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
