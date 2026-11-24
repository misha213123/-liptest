"""Face-aware local skin retouch and adaptive Smart Colors for Film Studio.

Unlike a global blur, Face Beauty detects faces and smooths only a feathered
skin mask, protecting the eye and mouth regions. No remote APIs are called.
Smart Colors uses local CLAHE luminance enhancement and adaptive HSV
saturation. Neither pass is a proprietary CapCut/Topaz model or a guarantee
of recovering missing detail. All transforms happen at source FPS BEFORE
motion interpolation, the high-resolution export and burned-in subtitles.
"""
from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path

from film_runtime import face_detector, optional_profile_detector

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _level(job: dict, name: str, default: float) -> float:
    try:
        amount = float(job.get(name, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Неверная настройка Face Beauty / Smart Colors: {name}") from exc
    if not math.isfinite(amount) or amount < 0 or amount > 100:
        raise ValueError(f"Настройка {name} должна быть от 0 до 100.")
    return amount / 100.0


def settings(job: dict) -> dict:
    beauty = job.get("face_beauty", False)
    smart = job.get("smart_colors", False)
    if not isinstance(beauty, bool) or not isinstance(smart, bool):
        raise ValueError("Переключатели Face Beauty / Smart Colors должны быть true или false.")
    return {
        "beauty": beauty,
        "smart": smart,
        "skin": _level(job, "beauty_skin", 40),
        "tone": _level(job, "beauty_tone", 30),
        "colors": _level(job, "smart_color_strength", 45),
        "clarity": _level(job, "smart_clarity", 20),
    }


def active(options: dict) -> bool:
    return bool(
        options["beauty"] and (options["skin"] or options["tone"])
        or options["smart"] and (options["colors"] or options["clarity"])
    )


def _cv():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Face Beauty / Smart Colors требует opencv-python и numpy. "
            "Установи зависимости в .venv: pip install opencv-python numpy."
        ) from exc
    return cv2, np


def preflight(options: dict, model_cache: Path) -> None:
    if not active(options):
        return
    cv2, _ = _cv()
    if options["beauty"]:
        # Use the existing OpenCV model/cache; fail BEFORE paid ASR requests.
        face_detector(cv2, model_cache)


def detect_faces(frame, cv2, detector, profile=None) -> list[tuple[int, int, int, int]]:
    if detector is None:
        return []
    h, w = frame.shape[:2]
    factor = min(1.0, 640.0 / max(w, h))
    small = cv2.resize(frame, None, fx=factor, fy=factor) if factor < 1.0 else frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    min_face = max(20, int(min(small.shape[:2]) * .055))
    candidates = list(detector.detectMultiScale(
        gray, scaleFactor=1.10, minNeighbors=4,
        minSize=(min_face, min_face),
    ))
    if profile is not None:
        candidates.extend(list(profile.detectMultiScale(
            gray, scaleFactor=1.12, minNeighbors=4,
            minSize=(min_face, min_face),
        )))
    scale = 1.0 / factor
    boxes = []
    for x, y, bw, bh in candidates:
        x, y = int(x * scale), int(y * scale)
        bw, bh = int(bw * scale), int(bh * scale)
        # Keep the bounding box inside the decoded image.
        x, y = max(0, x), max(0, y)
        bw, bh = min(w - x, bw), min(h - y, bh)
        if bw >= 32 and bh >= 32 and all(
            _overlap_ratio((x, y, bw, bh), other) < .50 for other in boxes
        ):
            boxes.append((x, y, bw, bh))
    return boxes[:5]


def _overlap_ratio(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    y = max(0, min(ay + ah, by + bh) - max(ay, by))
    intersection = x * y
    return intersection / max(1, min(aw * ah, bw * bh))


def smart_colors(frame, cv2, np, color_strength: float, clarity: float):
    if not color_strength and not clarity:
        return frame
    result = frame
    if color_strength:
        lab = cv2.cvtColor(result, cv2.COLOR_BGR2LAB)
        light, channel_a, channel_b = cv2.split(lab)
        # Cap CLAHE per-tile gain for a filmic look, not extreme HDR halos.
        clahe = cv2.createCLAHE(
            clipLimit=1.2 + 1.8 * color_strength,
            tileGridSize=(8, 8),
        )
        local_light = clahe.apply(light)
        alpha = .12 + .42 * color_strength
        light = cv2.addWeighted(light, 1 - alpha, local_light, alpha, 0)
        result = cv2.cvtColor(cv2.merge((light, channel_a, channel_b)), cv2.COLOR_LAB2BGR)
        hsv = cv2.cvtColor(result, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1].astype(np.float32)
        # Adaptively boost dull colors, not already-saturated yellows/reds.
        multiplier = 1 + .50 * color_strength * (1 - (sat / 255.0) ** 2)
        hsv[:, :, 1] = np.clip(sat * multiplier, 0, 255).astype(np.uint8)
        result = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    if clarity:
        # Gentle edge contrast, not a substitute for a neural deblur model.
        blurred = cv2.GaussianBlur(result, (0, 0), 1.25)
        result = cv2.addWeighted(result, 1 + .44 * clarity, blurred, -.44 * clarity, 0)
    return result


def beauty_face(frame, box, cv2, np, skin_strength: float, tone_strength: float):
    """Retouch skin within a soft face ellipse, preserving lips/eyes/contours."""
    if not skin_strength and not tone_strength:
        return frame
    x, y, w, h = [int(n) for n in box]
    height, width = frame.shape[:2]
    x, y = max(0, x), max(0, y)
    w, h = min(width - x, w), min(height - y, h)
    if w < 32 or h < 32:
        return frame
    region = frame[y:y + h, x:x + w]
    if region.size == 0:
        return frame
    # Face-aware geometric region, feathered to avoid obvious beauty borders.
    ellipse = np.zeros((h, w), dtype=np.uint8)
    cv2.ellipse(
        ellipse, (w // 2, h // 2), (max(1, int(w * .45)), max(1, int(h * .48))),
        0, 0, 360, 255, -1,
    )
    # Protect eyes/brows and lips; don't turn facial features into plastic.
    ellipse[int(.22*h):int(.49*h), int(.12*w):int(.88*w)] = 0
    ellipse[int(.73*h):int(.88*h), int(.26*w):int(.74*w)] = 0

    ycrcb = cv2.cvtColor(region, cv2.COLOR_BGR2YCrCb)
    # Use chroma to constrain smoothing to likely skin. Threshold is
    # intentionally broad; the geometric mask still protects features.
    cr = ycrcb[:, :, 1]
    cb = ycrcb[:, :, 2]
    skin = ((cr >= 119) & (cr <= 187) & (cb >= 73) & (cb <= 148)).astype(np.uint8)
    mask = (ellipse.astype(np.float32) / 255.0) * skin.astype(np.float32)
    feather = max(2.0, min(w, h) * .035)
    mask = cv2.GaussianBlur(mask, (0, 0), feather)
    if float(mask.max()) < .05:
        return frame

    original = region.astype(np.float32)
    revised = original
    if skin_strength:
        # Edge-aware bilateral blur retains the stronger mouth/hair boundary.
        smoothed = cv2.bilateralFilter(
            region, d=9,
            sigmaColor=35 + 65 * skin_strength,
            sigmaSpace=6 + 10 * skin_strength,
        ).astype(np.float32)
        blend = (mask * (.18 + .78 * skin_strength))[:, :, None]
        revised = revised * (1 - blend) + smoothed * blend
    if tone_strength:
        lab = cv2.cvtColor(np.clip(revised, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB)
        lum = lab[:, :, 0].astype(np.float32)
        smooth_luma = cv2.GaussianBlur(lum, (0, 0), 2.0 + 10.0 * tone_strength)
        blend_luma = mask * .48 * tone_strength
        lab[:, :, 0] = np.clip(
            lum * (1 - blend_luma) + smooth_luma * blend_luma, 0, 255
        ).astype(np.uint8)
        tonemapped = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR).astype(np.float32)
        blend = (mask * tone_strength * .60)[:, :, None]
        revised = revised * (1 - blend) + tonemapped * blend
    frame[y:y+h, x:x+w] = np.clip(revised, 0, 255).astype(np.uint8)
    return frame


class VideoProcessor:
    def __init__(self, options: dict, cache_dir: Path, cv2=None, np=None,
                 detector=None, profile=None):
        if cv2 is None or np is None:
            cv2, np = _cv()
        self.cv2, self.np = cv2, np
        self.options = options
        self.detector = detector
        self.profile = profile
        if options["beauty"] and self.detector is None:
            self.detector = face_detector(cv2, cache_dir)
            self.profile = optional_profile_detector(cv2, cache_dir)
        self.frame_index = 0
        self.boxes = []
        self.missed = 0
        self.faces_seen = 0
        self.previous_small = None

    def process(self, frame):
        cv2, np = self.cv2, self.np
        # Detect hard scene cuts: reset previous faces so skin patches do not
        # incorrectly move with a person into a new, unrelated scene.
        if self.options["beauty"]:
            small = cv2.resize(frame, (40, 24))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if self.previous_small is not None:
                difference = float(cv2.absdiff(gray, self.previous_small).mean())
                if difference > 34:
                    self.boxes = []
                    self.missed = 100
            self.previous_small = gray
            if self.frame_index % 7 == 0 or not self.boxes:
                found = detect_faces(frame, cv2, self.detector, self.profile)
                if found:
                    self.boxes = found
                    self.missed = 0
                else:
                    self.missed += 1
                    if self.missed >= 3:
                        self.boxes = []
            if self.boxes:
                self.faces_seen += len(self.boxes)
        result = smart_colors(
            frame, cv2, np,
            self.options["colors"] if self.options["smart"] else 0,
            self.options["clarity"] if self.options["smart"] else 0,
        )
        if self.options["beauty"]:
            for box in self.boxes:
                result = beauty_face(result, box, cv2, np,
                                     self.options["skin"], self.options["tone"])
        self.frame_index += 1
        return result


def _read_frame(reader, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        part = reader.read(remaining)
        if not part:
            break
        chunks.append(part)
        remaining -= len(part)
    return b"".join(chunks)


def process_clip(
    source: Path, out: Path, ffmpeg: str, start: float, duration: float,
    fps: float, width: int, height: int, options: dict, cache_dir: Path,
    report=None,
) -> tuple[Path, dict]:
    """Local frame pass -> high-quality video-only MP4; later mux source audio."""
    if not active(options):
        raise ValueError("Face Beauty / Smart Colors not enabled.")
    if not 0 <= start or not 0 < duration <= 300 or not 1 <= fps <= 120:
        raise ValueError("Неверный диапазон времени для ретуши видео.")
    if width < 2 or height < 2 or width * height > 3840 * 2160:
        raise ValueError("Неверный размер источника для Face Beauty.")
    cv2, np = _cv()
    processor = VideoProcessor(options, cache_dir, cv2=cv2, np=np)
    frame_bytes = width * height * 3
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    decoder = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", str(start), "-i", str(source), "-t", str(duration),
        "-map", "0:v:0", "-an", "-sn", "-dn",
        "-vf", f"fps={fps:.7f},format=bgr24",
        "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1",
    ]
    encoder = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
        "-f", "rawvideo", "-pixel_format", "bgr24",
        "-video_size", f"{width}x{height}", "-framerate", f"{fps:.7f}",
        "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "fast",
        "-crf", "15", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out),
    ]
    print(
        f"[beauty] Local face/skin processing at {width}x{height} "
        f"{fps:.2f} FPS. No cloud API calls.",
        flush=True,
    )
    # Avoid a blocked stderr pipe: log FFmpeg errors directly to disk.
    log = out.with_suffix(".beauty.log")
    frames = 0
    decoder_proc, encoder_proc = None, None
    try:
        with log.open("wb") as trace:
            decoder_proc = subprocess.Popen(
                decoder, stdout=subprocess.PIPE, stderr=trace,
                creationflags=FLAGS,
            )
            encoder_proc = subprocess.Popen(
                encoder, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=trace, creationflags=FLAGS,
            )
            total = max(1, int(math.ceil(duration * fps)))
            last_report = -1
            while True:
                raw = _read_frame(decoder_proc.stdout, frame_bytes)
                if not raw:
                    break
                if len(raw) != frame_bytes:
                    raise RuntimeError("Декодер отдал неполный кадр при ретуши лица.")
                # Copy because np.frombuffer(bytes) is read-only.
                frame = np.frombuffer(raw, np.uint8).reshape(height, width, 3).copy()
                cleaned = processor.process(frame)
                encoder_proc.stdin.write(cleaned.tobytes())
                frames += 1
                fraction = int(100 * frames / total)
                if fraction // 10 > last_report // 10:
                    last_report = fraction
                    if report:
                        report(
                            f"Face Beauty / Smart Colors: {frames}/{total} кадров",
                            58 + min(3, int(3 * frames / total)),
                        )
            decoder_proc.stdout.close()
            encoder_proc.stdin.close()
            decode_code = decoder_proc.wait(timeout=60)
            encode_code = encoder_proc.wait(timeout=180)
            if frames < 1 or decode_code != 0 or encode_code != 0:
                raise RuntimeError(
                    f"Ошибка обработки Face Beauty / Smart Colors "
                    f"(кадры={frames}, decoder={decode_code}, encoder={encode_code}). "
                    "Открой *.beauty.log рядом с файлом рендера."
                )
        if not out.is_file() or out.stat().st_size < 500:
            raise RuntimeError("Face Beauty не сформировал видео.")
        info = {"frames": frames, "faces_detected_frames": processor.faces_seen}
        print(
            f"[beauty] Completed {frames} frames; face regions processed in "
            f"{processor.faces_seen} frames (approximate count).",
            flush=True,
        )
        return out, info
    finally:
        for proc in (decoder_proc, encoder_proc):
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    pass


def process_preview_image(path: Path, job: dict, cache_dir: Path) -> dict:
    options = settings(job)
    if not active(options):
        return {"enabled": False, "faces": 0}
    cv2, np = _cv()
    image = cv2.imread(str(path))
    if image is None:
        raise RuntimeError("Не удалось прочитать миниатюру для Face Beauty.")
    processor = VideoProcessor(options, cache_dir, cv2=cv2, np=np)
    updated = processor.process(image)
    if not cv2.imwrite(str(path), updated, [int(cv2.IMWRITE_JPEG_QUALITY), 95]):
        raise RuntimeError("Не удалось сохранить миниатюру после ретуши.")
    return {"enabled": True, "faces": processor.faces_seen}
