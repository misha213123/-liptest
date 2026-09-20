from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from core.streamer_dynamic_layout import render_dynamic_streamer_layout
from core.vertical_quality import validate_vertical_output


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vertical-smoke-") as tmp:
        root = Path(tmp)
        source = root / "source.mp4"
        output = root / "output.mp4"

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "testsrc2=size=1280x720:rate=30",
                "-f", "lavfi",
                "-i", "sine=frequency=440:sample_rate=48000",
                "-t", "3.2",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "128k",
                "-shortest",
                source,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        render_dynamic_streamer_layout(
            ffmpeg_path="ffmpeg",
            input_path=str(source),
            output_path=str(output),
            webcam_rect={"x": 0.02, "y": 0.04, "w": 0.28, "h": 0.28},
            encoder_args=[
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
            ],
            layout_events=[
                {"state": "REACTION", "start": 0.8, "end": 2.2},
            ],
            output_width=1080,
            output_height=1920,
            webcam_height_pct=0.365,
            gameplay_center_x=0.50,
        )

        info = validate_vertical_output(
            output,
            ffprobe_path="ffprobe",
            expected_width=1080,
            expected_height=1920,
            require_audio=True,
            expected_fps=30.0,
            log=print,
        )
        assert info["valid"] is True
        print("VERTICAL_RENDER_SMOKE_OK")


if __name__ == "__main__":
    main()
