"""Video2X 6.x CLI integration for the Film & Series Studio post-processing stage.

External Video2X binary: https://github.com/k4yt3x/video2x
No external source code or model assets are bundled into Auto Clipper.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
MODELS = {
    "off": None,
    "realesrgan-plus": ("realesrgan", "realesrgan-plus"),
    "realesr-generalv3": ("realesrgan", "realesr-generalv3"),
    "realesr-animevideov3": ("realesrgan", "realesr-animevideov3"),
    "anime4k-v4-a+a": ("libplacebo", "anime4k-v4-a+a"),
}
FRAME_MULTIPLIERS = (1, 2, 4)


def options(job: dict) -> tuple[str, int]:
    model = str(job.get("video2x_upscale") or "off").strip().lower()
    if model not in MODELS:
        raise ValueError("Неизвестная модель Video2X.")
    try:
        multiplier = int(job.get("video2x_rife") or 1)
    except (ValueError, TypeError):
        raise ValueError("Неверный множитель Video2X RIFE.") from None
    if multiplier not in FRAME_MULTIPLIERS:
        raise ValueError("RIFE поддерживает множитель 1, 2 или 4.")
    return model, multiplier


def find_binary() -> str | None:
    override = os.environ.get("VIDEO2X_BIN", "").strip().strip('"')
    if override:
        p = Path(override)
        if p.is_file():
            return str(p)
        raise RuntimeError("VIDEO2X_BIN указывает на несуществующий файл: " + override)

    names = ["video2x", "video2x.exe"]
    for name in names:
        found = shutil.which(name)
        if found:
            return found

    candidates = [
        Path("C:/Program Files/Video2X/video2x.exe"),
        Path("C:/Program Files/video2x/video2x.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Video2X" / "video2x.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Video2X" / "video2x.exe",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


def require_binary() -> str:
    exe = find_binary()
    if not exe:
        raise RuntimeError(
            "Video2X не установлен или его CLI не найден. Установи Video2X 6.x из "
            "https://github.com/k4yt3x/video2x/releases и добавь папку с video2x.exe "
            "в PATH, либо задай VIDEO2X_BIN=полный_путь_к_video2x.exe. "
            "До установки выбери «Обычный FFmpeg» и «Без RIFE»."
        )
    try:
        probe = subprocess.run(
            [exe, "--help"], capture_output=True, text=True, errors="replace",
            timeout=20, creationflags=SUBPROCESS_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Не удалось запустить Video2X CLI: " + str(exc)[:200]) from exc
    help_text = (probe.stdout or "") + "\n" + (probe.stderr or "")
    if "realesrgan" not in help_text.lower() or "rife" not in help_text.lower():
        raise RuntimeError("Нужна современная CLI-версия Video2X 6.x (не старая Python-версия).")
    return exe


def build_steps(
    executable: str,
    source: Path,
    folder: Path,
    model: str,
    multiplier: int,
    output_width: int,
    output_height: int,
) -> list[tuple[str, list[str], Path]]:
    """Construct official Video2X 6.x commands. No shell execution."""
    if model not in MODELS or multiplier not in FRAME_MULTIPLIERS:
        raise ValueError("Некорректные настройки Video2X.")
    steps = []
    current = Path(source)
    common = ["-c", "libx264", "--pix-fmt", "yuv420p", "-e", "crf=16", "-e", "preset=slow"]
    if model != "off":
        processor, model_name = MODELS[model]
        target = Path(folder) / "video2x_upscaled.mp4"
        if processor == "realesrgan":
            cmd = [
                executable, "-i", str(current), "-o", str(target),
                "-p", processor, "-s", "2", "--realesrgan-model", model_name,
                *common,
            ]
        else:
            cmd = [
                executable, "-i", str(current), "-o", str(target),
                "-p", processor, "-w", str(output_width), "-h", str(output_height),
                "--libplacebo-shader", model_name, *common,
            ]
        steps.append(("AI upscale", cmd, target))
        current = target

    if multiplier > 1:
        target = Path(folder) / "video2x_rife.mp4"
        cmd = [
            executable, "-i", str(current), "-o", str(target),
            "-p", "rife", "-m", str(multiplier),
            "--rife-model", "rife-v4.26",
            "--scene-thresh", "20", *common,
        ]
        steps.append((f"RIFE {multiplier}x", cmd, target))

    return steps


def run_steps(
    source: Path,
    folder: Path,
    model: str,
    multiplier: int,
    output_width: int,
    output_height: int,
    report=None,
    timeout_seconds: int = 14400,
) -> Path:
    """Return AI-processed file, leaving the original untouched on failures."""
    if model == "off" and multiplier == 1:
        return Path(source)
    exe = require_binary()
    folder.mkdir(parents=True, exist_ok=True)
    steps = build_steps(
        exe, Path(source), folder, model, multiplier, output_width, output_height
    )
    current = Path(source)
    total = len(steps)
    for index, (label, command, target) in enumerate(steps):
        if target.exists():
            target.unlink()
        if report:
            report(f"Video2X: {label} ({index+1}/{total})", 72 + index * 10)
        proc = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=SUBPROCESS_FLAGS, bufsize=1,
        )
        started = time.monotonic()
        tail = []
        try:
            for line in proc.stdout:
                line = re.sub(r"\x1b\[[0-9;]*[mK]", "", line.strip())
                if line:
                    tail.append(line[-260:])
                    if len(tail) > 35:
                        tail.pop(0)
                if time.monotonic() - started > timeout_seconds:
                    proc.kill()
                    raise RuntimeError(f"Video2X: {label} превысил ограничение времени.")
            returncode = proc.wait(timeout=20)
            if returncode != 0:
                raise RuntimeError(
                    f"Video2X: {label} завершился с кодом {returncode}. "
                    + " | ".join(tail[-7:])[-1000:]
                )
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if not target.is_file() or target.stat().st_size < 100_000:
            raise RuntimeError(f"Video2X: {label} не создал выходное видео.")
        current = target
    return current
