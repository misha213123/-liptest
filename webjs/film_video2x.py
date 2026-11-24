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
import queue
import threading
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

# Actual .param/.bin combinations shipped with Video2X 6.4.0.
# realesrgan-plus-x2 does NOT exist; realesrgan-plus-x4 does.
REAL_ESRGAN_SCALES = {
    "realesrgan-plus": 4,
    "realesr-generalv3": 4,  # Not shipped in Video2X 6.4.0; checked before launch.
    "realesr-animevideov3": 2,
}


def upscale_factor(model: str) -> int:
    """Native scale of the selected model; 1 for shader/off."""
    if model not in MODELS:
        raise ValueError("Неизвестная модель Video2X.")
    return REAL_ESRGAN_SCALES.get(model, 1)


def intermediate_dimensions(
    crop_width: int, crop_height: int, target_width: int, target_height: int,
    model: str,
) -> tuple[int, int]:
    """Keep source face detail instead of shrinking to target/native_scale.

    Real-ESRGAN Plus is natively 4x. For a 720p 9:16 crop of about 404x720,
    a 1080x1920 export should feed roughly 404x720 into the model, NOT
    downsample it to 270x480. Cap excessive input size to 1.5x the minimum
    native model input to avoid accidental 8K+ AI processing.
    """
    if min(crop_width, crop_height, target_width, target_height) < 2:
        raise ValueError("Invalid source or export dimensions")
    scale = upscale_factor(model)
    if scale == 1:
        return int(target_width), int(target_height)
    needed_scale = max(
        target_width / (scale * crop_width),
        target_height / (scale * crop_height),
    )
    # If the source is already larger than needed, keep its detail up to
    # 150% of the minimum model input; if smaller, upscale as little as needed.
    if needed_scale >= 1.0:
        # Cropped input has fewer pixels than the target/native_scale.
        # Round against target aspect directly to avoid tiny distortion.
        width = max(2, int(round(target_width / scale / 2) * 2))
        height = max(2, int(round(target_height / scale / 2) * 2))
        return width, height
    resize = min(1.0, needed_scale * 1.5)
    width = max(2, int(round(crop_width * resize / 2) * 2))
    height = max(2, int(round(crop_height * resize / 2) * 2))
    return width, height


def resources_root(executable: str) -> Path:
    """Locate the official Video2X models folder near its executable."""
    exe = Path(executable).resolve()
    for parent in (exe.parent, *list(exe.parents)[1:4]):
        if (parent / "models").is_dir():
            return parent
    # Let required_model_files report a useful missing-assets error.
    return exe.parent


def required_model_files(model: str, multiplier: int) -> list[Path]:
    """Relative assets from the official Video2X 6.4.0 release archive."""
    if model not in MODELS or multiplier not in FRAME_MULTIPLIERS:
        raise ValueError("Неизвестные параметры модели Video2X.")
    needed = []
    if model in REAL_ESRGAN_SCALES:
        scale = REAL_ESRGAN_SCALES[model]
        stem = Path("models") / "realesrgan" / f"{model}-x{scale}"
        needed += [Path(str(stem) + ext) for ext in (".param", ".bin")]
    elif model.startswith("anime4k-"):
        needed.append(Path("models") / "libplacebo" / f"{model}.glsl")
    if multiplier > 1:
        stem = Path("models") / "rife" / "rife-v4.26" / "flownet"
        needed += [Path(str(stem) + ext) for ext in (".param", ".bin")]
    return needed


def validate_model_files(executable: str, model: str, multiplier: int) -> Path:
    root = resources_root(executable)
    missing = [
        path for path in required_model_files(model, multiplier)
        if not (root / path).is_file()
    ]
    if missing:
        detail = ", ".join(str(p) for p in missing[:4])
        raise RuntimeError(
            "Video2X: отсутствуют необходимые файлы AI-модели: " + detail
            + ". Папка моделей: " + str(root / "models")
            + ". Распакуй официальный CLI ZIP Video2X 6.x целиком "
              "(video2x.exe и папку models рядом), либо повтори "
              "scripts/install-video2x.ps1. Не нужно скачивать модель по отдельности."
        )
    return root


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


def require_binary(model: str = "off", multiplier: int = 1) -> str:
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
    validate_model_files(exe, model, multiplier)
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
                "-p", processor, "-s", str(upscale_factor(model)), "--realesrgan-model", model_name,
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



def stall_reason(
    now: float, started: float, last_activity: float, output_bytes: int,
    first_byte_timeout: int, idle_timeout: int,
) -> str | None:
    """Separate a zero-byte MP4 from log noise or harmless percentage lines."""
    if output_bytes <= 0 and now - started >= first_byte_timeout:
        return (
            f"Video2X не создал ни одного байта MP4 за "
            f"{first_byte_timeout} секунд. Переключаюсь на FFmpeg."
        )
    if now - last_activity >= idle_timeout:
        return (
            f"Video2X не продвигает обработку уже {idle_timeout} секунд. "
            "Переключаюсь на FFmpeg."
        )
    return None


def terminate_tree(proc) -> None:
    """On Windows, killing video2x.exe alone can leave Vulkan/FFmpeg children."""
    if proc.poll() is not None:
        return
    if os.name == "nt" and getattr(proc, "pid", None):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=12, creationflags=SUBPROCESS_FLAGS,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=6)
    except subprocess.TimeoutExpired:
        pass



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
    exe = require_binary(model, multiplier)
    resource_dir = resources_root(exe)
    print("[video2x] Model resources loaded from " + str(resource_dir / "models"), flush=True)
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
            command, cwd=str(resource_dir),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=SUBPROCESS_FLAGS, bufsize=1,
        )
        started = time.monotonic()
        tail = []
        messages = queue.Queue()
        last_reported = 0
        last_heartbeat = started
        latest_line_at = started
        last_activity_at = started
        last_output_bytes = 0
        last_actual_percent = -1.0
        # Very important: a log line saying "99%" is not proof that frames
        # were encoded. A hard *first-byte* deadline keeps 4GB Vulkan hangs
        # from holding the entire render at 72% indefinitely.
        first_byte_timeout = max(60, min(900, int(os.environ.get(
            "FILM_VIDEO2X_FIRST_BYTE_TIMEOUT", "180"
        ))))
        idle_timeout = max(60, min(3600, int(os.environ.get(
            "FILM_VIDEO2X_IDLE_TIMEOUT", "240"
        ))))

        def drain():
            try:
                for line in proc.stdout:
                    messages.put(line)
            finally:
                messages.put(None)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        try:
            while True:
                now = time.monotonic()
                if now - started > timeout_seconds:
                    raise RuntimeError(f"Video2X: {label} превысил ограничение времени.")
                # IMPORTANT: check stalled work in EVERY loop iteration.
                # Video2X may emit endless FFmpeg log lines even when Vulkan
                # processes no frames. Previously the watchdog only ran in
                # queue.Empty, so a busy log stream could hang at 72% forever.
                output_bytes = target.stat().st_size if target.exists() else 0
                if output_bytes > last_output_bytes:
                    last_output_bytes = output_bytes
                    last_activity_at = now
                stall = stall_reason(
                    now, started, last_activity_at, output_bytes,
                    first_byte_timeout, idle_timeout,
                )
                if stall:
                    print("[video2x] WATCHDOG: " + stall, flush=True)
                    raise RuntimeError(stall)
                if now - last_heartbeat >= 12:
                    elapsed = int(now - started)
                    age = int(now - latest_line_at)
                    print(
                        f"[video2x] {label}: PID={proc.pid}, "
                        f"{elapsed}s elapsed, output {output_bytes / 1048576:.1f} MiB, "
                        f"last log line {age}s ago; "
                        f"no confirmed frame progress yet.",
                        flush=True,
                    )
                    last_heartbeat = now
                try:
                    raw = messages.get(timeout=0.5)
                except queue.Empty:
                    if proc.poll() is not None and not reader.is_alive():
                        break
                    continue
                if raw is None:
                    break
                line = re.sub(r"\x1b\[[0-9;]*[mK]", "", raw.strip())
                if not line:
                    continue
                latest_line_at = time.monotonic()
                tail.append(line[-260:])
                if len(tail) > 35:
                    tail.pop(0)
                # Video2X writes percentages through its terminal progress view.
                # Forward grounded real progress rather than inventing an ETA.
                if report:
                    match = re.search(r"(?<!\d)(\d{1,3}(?:\.\d+)?)%", line)
                    if match:
                        value = max(0, min(100, float(match.group(1))))
                        # Mere repeated percentages are NOT actual progress.
                        # Move the idle timer only on a genuinely higher
                        # percent. The first-byte timer never resets.
                        if value > last_actual_percent + .05:
                            last_actual_percent = value
                            last_activity_at = time.monotonic()
                        local_pct = int(value * 0.08)
                        if local_pct > last_reported:
                            last_reported = local_pct
                            report(f"Video2X: {label} {value:.0f}%", min(89, 72 + index * 10 + local_pct))
            returncode = proc.wait(timeout=20)
            print(f"[video2x] {label}: exited with code {returncode}", flush=True)
            if returncode != 0:
                raise RuntimeError(
                    f"Video2X: {label} завершился с кодом {returncode}. "
                    + " | ".join(tail[-7:])[-1000:]
                )
        finally:
            if proc.poll() is None:
                terminate_tree(proc)
        if not target.is_file() or target.stat().st_size < 100_000:
            raise RuntimeError(f"Video2X: {label} не создал выходное видео.")
        current = target
    return current
