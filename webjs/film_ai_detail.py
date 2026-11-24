"""Optional genuine neural detail-restoration via portable Real-ESRGAN NCNN Vulkan.

This is NOT Topaz AI and is NOT a conventional sharpness filter. It uses the
official xinntao Real-ESRGAN-ncnn-vulkan executable with 64-pixel GPU tiles
for 4GB GPUs. It processes entire short clips and keeps original audio.
The model can hallucinate textures or flicker between frames; it does not
guarantee reconstruction of real source details.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("realesrgan-x4plus", "realesrnet-x4plus")
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def find_binary() -> tuple[Path | None, Path | None]:
    configured = str(os.environ.get("AI_RESTORE_NCNN_BIN") or "").strip()
    places = []
    if configured:
        places.append(Path(configured))
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Programs" / "realesrgan-ncnn-vulkan"
    places += [
        local / "realesrgan-ncnn-vulkan.exe",
        ROOT / "bin" / "realesrgan-ncnn-vulkan" / "realesrgan-ncnn-vulkan.exe",
    ]
    which = shutil.which("realesrgan-ncnn-vulkan.exe" if os.name == "nt" else "realesrgan-ncnn-vulkan")
    if which:
        places.append(Path(which))
    for file in places:
        if not file.is_file():
            continue
        model_path = file.parent / "models"
        if all((model_path / f"{name}.param").is_file() and
               (model_path / f"{name}.bin").is_file() for name in MODELS):
            return file, model_path
    return None, None


def require_binary() -> tuple[Path, Path]:
    exe, models = find_binary()
    if not exe:
        raise RuntimeError(
            "AI Detail Restore не установлен. Установи официальный "
            "Real-ESRGAN NCNN: powershell -ExecutionPolicy Bypass "
            "-File .\\scripts\\install-ai-detail-restore.ps1. "
            "Пока можно пользоваться работающим пресетом 60 FPS."
        )
    return exe, models


def run_cmd(args: list[str], timeout: int):
    result = subprocess.run(
        args, capture_output=True, text=True, errors="replace",
        timeout=timeout, creationflags=FLAGS,
    )
    if result.returncode != 0:
        # Raw stderr from external executables may contain local paths.
        raise RuntimeError(
            f"FFmpeg AI-проход завершился с кодом {result.returncode}: "
            + str(result.stderr or "")[-600:]
        )


def terminate_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=12, creationflags=FLAGS,
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


def ai_source_dimensions(crop_w: int, crop_h: int) -> tuple[int, int]:
    """Preserve native 720p cropping; bound very large sources for 4GB GPUs."""
    if crop_w < 2 or crop_h < 2:
        raise ValueError("Неверные исходные размеры кадра для AI Restore.")
    ratio = min(1.0, math.sqrt((1280 * 720) / (crop_w * crop_h)))
    width = max(2, int(crop_w * ratio / 2) * 2)
    height = max(2, int(crop_h * ratio / 2) * 2)
    return width, height


def _strength(value: float) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("AI Detail Strength должен быть от 0 до 100%.") from exc
    if not math.isfinite(amount) or not 0 <= amount <= 100:
        raise ValueError("AI Detail Strength должен быть от 0 до 100%.")
    return amount / 100.0


def restore_preview_frame(
    preview: Path, ffmpeg: str, width: int, height: int,
    *, model: str = "realesrgan-x4plus", tile: int = 64,
    strength: float = 100,
) -> None:
    """Explicit one-frame neural preview, without modifying the video.

    This is only called by the user clicking 'Test AI on one frame'.
    Automated thumbnail updates deliberately do NOT run inference.
    """
    import tempfile

    alpha = _strength(strength)
    if model not in MODELS or tile not in (32, 64, 96, 128):
        raise ValueError("Неверная модель или размер GPU-блока для AI-превью.")
    if alpha <= 0:
        return
    if width < 16 or height < 16 or width * height > 3840 * 2160:
        raise ValueError("Неверные размеры AI-превью.")
    preview = Path(preview)
    if not preview.is_file():
        raise ValueError("Нет готовой миниатюры для AI-превью.")
    exe, models = require_binary()
    with tempfile.TemporaryDirectory(prefix="film-ai-preview-",
                                     dir=str(preview.parent)) as tmp:
        base = Path(tmp)
        source_png = base / "input.png"
        neural_png = base / "enhanced.png"
        final_jpg = base / "after.jpg"
        run_cmd([
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
            "-y", "-i", str(preview), "-frames:v", "1", str(source_png),
        ], timeout=45)
        result = subprocess.run([
            str(exe), "-i", str(source_png), "-o", str(neural_png),
            "-m", str(models), "-n", model,
            "-s", "2", "-t", str(tile), "-g", "0", "-j", "1:1:1",
            "-f", "png",
        ], cwd=str(exe.parent), capture_output=True,
           timeout=150, creationflags=FLAGS)
        if result.returncode or not neural_png.is_file():
            raise RuntimeError(
                "Real-ESRGAN не обработал тестовый кадр. "
                "Проверь Vulkan или выбери блок 32 px."
            )
        blend = (
            f"[0:v]scale={width}:{height}:flags=lanczos[base];"
            f"[1:v]scale={width}:{height}:flags=lanczos[ai];"
            f"[base][ai]blend=all_expr=A*(1-{alpha:.4f})+B*{alpha:.4f}[out]"
        )
        run_cmd([
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-i", str(source_png), "-i", str(neural_png),
            "-filter_complex", blend, "-map", "[out]", "-frames:v", "1",
            "-q:v", "2", str(final_jpg),
        ], timeout=45)
        if not final_jpg.is_file() or final_jpg.stat().st_size < 500:
            raise RuntimeError("Нейросеть не создала изображение предпросмотра.")
        final_jpg.replace(preview)


def restore_clip(
    prepared: Path, out_dir: Path, ffmpeg: str, duration: float,
    fps: float, report,
    *, crop_width: int = 1280, crop_height: int = 720,
    target_width: int = 1920, target_height: int = 1080,
    tile: int = 64, model: str = "realesrgan-x4plus",
    strength: float = 100,
) -> Path:
    if not 0.1 <= duration <= 30.0:
        raise ValueError(
            "Нейросетевой AI Detail Restore рассчитан на короткие сцены до 30 секунд. "
            "Раздели длинный эпизод на клипы."
        )
    alpha = _strength(strength)
    if model not in MODELS:
        raise ValueError("Неизвестная модель AI Detail Restore.")
    if tile not in (32, 64, 96, 128):
        raise ValueError("Размер GPU-блока должен быть 32, 64, 96 или 128.")
    if not 1 <= fps <= 120:
        raise ValueError("Неверная частота кадров нейросетевого рендера.")
    source_w, source_h = ai_source_dimensions(crop_width, crop_height)
    if target_width < 2 or target_height < 2 or target_width % 2 or target_height % 2:
        raise ValueError("Выходные размеры AI Restore должны быть положительными чётными.")
    exe, models = require_binary()
    frames = out_dir / "ai_detail_in"
    enhanced = out_dir / "ai_detail_out"
    frames.mkdir(parents=True, exist_ok=True)
    enhanced.mkdir(parents=True, exist_ok=True)
    target = out_dir / "ai_detail_restored.mp4"
    log = out_dir / "ai_detail_restore.log"

    try:
        report("AI Detail Restore: подготавливаю кадры (Vulkan, без Video2X)", 73)
        # Keep the actual cropped source resolution (e.g. 404x720), instead of
        # blindly halving the 1080p render to 540p and losing real details.
        # GPU tile 64 plus bounded 720p input keeps intermediate files smaller.
        # The final FFmpeg pass restores exactly the requested output size.
        run_cmd([
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-i", str(prepared),
            "-vf", f"scale={source_w}:{source_h}:flags=lanczos",
            "-fps_mode", "passthrough",
            str(frames / "frame_%06d.png"),
        ], timeout=1200)
        input_files = sorted(frames.glob("frame_*.png"))
        if not input_files:
            raise RuntimeError("AI Restore: FFmpeg не создал кадры.")
        report(f"AI Detail Restore: нейросеть обрабатывает {len(input_files)} кадров", 76)
        cmd = [
            str(exe),
            "-i", str(frames), "-o", str(enhanced),
            "-m", str(models), "-n", model,
            "-s", "2", "-t", str(tile), "-g", "0",
            "-j", "1:1:1", "-f", "png",
        ]
        started = time.monotonic()
        last_made = started
        last_count = 0
        with log.open("wb") as output:
            proc = subprocess.Popen(
                cmd, cwd=str(exe.parent), stdout=output, stderr=subprocess.STDOUT,
                creationflags=FLAGS,
            )
            try:
                while True:
                    code = proc.poll()
                    files = list(enhanced.glob("frame_*.png"))
                    made = len(files)
                    now = time.monotonic()
                    if made > last_count:
                        last_made = now
                        last_count = made
                        report(f"AI Detail Restore: готово {made}/{len(input_files)} кадров",
                               76 + min(13, int(13 * made / len(input_files))))
                    if code is not None:
                        if code != 0:
                            raise RuntimeError(
                                f"AI Restore завершился с кодом {code}; "
                                "проверь драйвер Vulkan и 4 ГБ памяти GPU."
                            )
                        break
                    if now - last_made > 180:
                        raise RuntimeError(
                            "AI Restore: видеокарта не обрабатывает кадры 180 секунд. "
                            "Останавливаю процесс и сохраняю обычный MP4."
                        )
                    if now - started > 7200:
                        raise RuntimeError("AI Restore: ограничение времени 2 часа.")
                    time.sleep(2)
            finally:
                if proc.poll() is None:
                    terminate_tree(proc)

        if len(list(enhanced.glob("frame_*.png"))) != len(input_files):
            raise RuntimeError("AI Restore: число обработанных кадров не совпадает с исходником.")
        report("AI Detail Restore: собираю финальный MP4 со звуком", 90)
        blend = (
            f"[0:v]scale={target_width}:{target_height}:flags=lanczos[ai];"
            f"[1:v]scale={target_width}:{target_height}:flags=lanczos[base];"
            f"[base][ai]blend=all_expr=A*(1-{alpha:.4f})+B*{alpha:.4f}[v]"
        )
        run_cmd([
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-framerate", f"{fps:.6f}",
            "-start_number", "1", "-i", str(enhanced / "frame_%06d.png"),
            "-i", str(prepared),
            "-filter_complex", blend, "-map", "[v]", "-map", "1:a:0?",
            "-c:v", "libx264", "-preset", "slow", "-crf", "16",
            "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-movflags", "+faststart", "-shortest", str(target),
        ], timeout=5400)
        if not target.is_file() or target.stat().st_size < 100000:
            raise RuntimeError("AI Restore: итоговый MP4 не создан.")
        report("Нейросетевое восстановление деталей выполнено", 98)
        return target
    finally:
        # Frame stacks may consume multiple GB. Never delete the original MP4.
        shutil.rmtree(frames, ignore_errors=True)
        shutil.rmtree(enhanced, ignore_errors=True)


if __name__ == "__main__":
    import json
    exe, _ = find_binary()
    print(json.dumps({
        "installed": bool(exe),
        "engine": "Real-ESRGAN NCNN Vulkan",
        "max_clip_seconds": 30,
        "tile": 64,
        "strength_control": "0-100 blend between original and neural restoration",
    }))
