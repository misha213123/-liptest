"""Resilient Film Studio AI dependencies for OpenCV faces and Whisper speech.

- OpenCV face cascade: prefer installed file, otherwise cache the exact OpenCV
  4.10.0 official XML with a pinned Git blob hash.
- Faster-Whisper: CUDA failure may occur during model loading, transcribe(), OR
  lazy segment iteration; on failure retry with CPU/int8.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

CASCADE_NAME = "haarcascade_frontalface_default.xml"
CASCADE_URL = (
    "https://raw.githubusercontent.com/opencv/opencv/4.10.0/"
    "data/haarcascades/haarcascade_frontalface_default.xml"
)
# OpenCV/opencv tag 4.10.0, data/haarcascades/haarcascade_frontalface_default.xml
CASCADE_GIT_BLOB_SHA1 = "cbd1aa89e927d8d54b49fe666bf17244c3c46a7b"
MAX_CASCADE_BYTES = 1_200_000


def _verify_cascade(data: bytes) -> bool:
    if not 100_000 < len(data) < MAX_CASCADE_BYTES:
        return False
    if not data.startswith(b"<?xml") or b"<opencv_storage>" not in data:
        return False
    git_blob = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    return hashlib.sha1(git_blob).hexdigest() == CASCADE_GIT_BLOB_SHA1


def locate_cascade(cv2, cache_dir: Path) -> Path:
    """Return a verified, loadable cascade; cache official fallback if necessary."""
    package_dir = Path(getattr(cv2, "__file__", "")).resolve().parent
    try:
        installed_dir = Path(cv2.data.haarcascades)
    except (AttributeError, TypeError):
        installed_dir = package_dir / "data"
    candidates = (
        installed_dir / CASCADE_NAME,
        package_dir / "data" / CASCADE_NAME,
        cache_dir / CASCADE_NAME,
    )
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 100_000:
            if candidate == cache_dir / CASCADE_NAME and not _verify_cascade(candidate.read_bytes()):
                continue
            return candidate

    cache_dir.mkdir(parents=True, exist_ok=True)
    print("[faces] OpenCV cascade missing; downloading pinned OpenCV 4.10.0 model.", flush=True)
    request = Request(CASCADE_URL, headers={"User-Agent": "AutoClipper-FilmStudio/1.0"})
    with urlopen(request, timeout=25) as response:
        data = response.read(MAX_CASCADE_BYTES + 1)
    if not _verify_cascade(data):
        raise RuntimeError("The downloaded OpenCV face model failed verification.")

    # Atomic cache replacement, safe if interrupted mid-download.
    with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".tmp", delete=False) as temp:
        temporary = Path(temp.name)
        temp.write(data)
    try:
        temporary.replace(cache_dir / CASCADE_NAME)
    finally:
        temporary.unlink(missing_ok=True)
    print("[faces] OpenCV face detector model installed into cache.", flush=True)
    return cache_dir / CASCADE_NAME


def face_detector(cv2, cache_dir: Path):
    classifier = cv2.CascadeClassifier(str(locate_cascade(cv2, cache_dir)))
    if classifier.empty():
        raise RuntimeError("OpenCV cannot initialize the face detector.")
    return classifier


# Official OpenCV 4.10.0 profile-face cascade for actors shown in profile.
PROFILE_NAME = "haarcascade_profileface.xml"
PROFILE_URL = (
    "https://raw.githubusercontent.com/opencv/opencv/4.10.0/"
    "data/haarcascades/haarcascade_profileface.xml"
)
PROFILE_GIT_BLOB = "486d8e3d83075578c446be96b75a2414efe75ecb"


def _verify_profile(data: bytes) -> bool:
    if not 100_000 < len(data) < MAX_CASCADE_BYTES or b"<opencv_storage>" not in data:
        return False
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data).hexdigest() == PROFILE_GIT_BLOB


def optional_profile_detector(cv2, cache_dir: Path):
    """Best-effort profile detector, with full-face Haar still available offline."""
    try:
        installed = Path(cv2.data.haarcascades) / PROFILE_NAME
        cache = cache_dir / PROFILE_NAME
        if installed.is_file() and installed.stat().st_size > 100_000:
            candidate = installed
        elif cache.is_file() and _verify_profile(cache.read_bytes()):
            candidate = cache
        else:
            cache_dir.mkdir(parents=True, exist_ok=True)
            request = Request(PROFILE_URL, headers={"User-Agent": "AutoClipper-FilmStudio/1.0"})
            with urlopen(request, timeout=12) as response:
                data = response.read(MAX_CASCADE_BYTES + 1)
            if not _verify_profile(data):
                raise RuntimeError("Invalid OpenCV profile face cascade")
            with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".tmp", delete=False) as temp:
                temporary = Path(temp.name)
                temp.write(data)
            try:
                temporary.replace(cache)
            finally:
                temporary.unlink(missing_ok=True)
            candidate = cache
        detector = cv2.CascadeClassifier(str(candidate))
        if detector.empty():
            raise RuntimeError("OpenCV profile face cascade did not load")
        print("[faces] Frontal and profile face detectors enabled.", flush=True)
        return detector
    except Exception as exc:
        print("[faces] Profile detector unavailable; frontal fallback: " + str(exc)[:130], flush=True)
        return None


def _cuda_dll_present() -> bool:
    """On Windows avoid a broken CUDA attempt if the required cuBLAS is absent."""
    if os.name != "nt":
        return True
    try:
        ctypes.WinDLL("cublas64_12.dll")
        return True
    except (OSError, AttributeError):
        return False


def transcribe_segments(
    audio_file: str, model_factory=None, device: str | None = None,
    model_name: str = "medium", language: str = "ru",
):
    """Return materialized segments with automatic CUDA -> CPU recovery.

    The segments iterable is lazy; runtime errors there must trigger fallback.
    Set FILM_WHISPER_DEVICE=cpu to force CPU on machines with unreliable CUDA.
    """
    if model_factory is None:
        from faster_whisper import WhisperModel
        model_factory = WhisperModel
    choice = str(device or os.environ.get("FILM_WHISPER_DEVICE", "auto")).lower()
    if choice not in ("auto", "cuda", "cpu"):
        raise ValueError("FILM_WHISPER_DEVICE must be auto, cpu or cuda.")
    model_name = str(model_name or "medium").lower()
    if model_name not in ("small", "medium"):
        raise ValueError("Доступны модели Whisper: small и medium.")
    language = str(language or "auto").lower()
    if language not in ("ru", "en", "auto"):
        raise ValueError("Язык распознавания должен быть ru, en или auto.")

    def transcribe(target_device: str):
        args = {"device": target_device,
                "compute_type": "float16" if target_device == "cuda" else "int8"}
        model = model_factory(model_name, **args)
        transcription = {
            "word_timestamps": True,
            # On a clipped movie segment preserve the original audio timeline:
            # avoid removing silence before aligning the recognized words.
            "vad_filter": False,
            "beam_size": 5,
            "condition_on_previous_text": False,
        }
        if language != "auto":
            transcription["language"] = language
        segments, info = model.transcribe(str(audio_file), **transcription)
        print(
            f"[speech] Whisper {model_name} ({target_device}), "
            f"language={language}, VAD off; word timestamps enabled.",
            flush=True,
        )
        # Eagerly consume lazy generator INSIDE the try/fallback boundary.
        return list(segments)

    if choice == "cpu":
        print("[speech] Whisper CPU/int8 selected.", flush=True)
        return transcribe("cpu")
    if not _cuda_dll_present():
        print(
            "[speech] cublas64_12.dll not available; using Whisper CPU/int8 "
            "to avoid CUDA runtime failure.",
            flush=True,
        )
        return transcribe("cpu")

    try:
        print("[speech] Trying Whisper CUDA/float16.", flush=True)
        return transcribe("cuda")
    except Exception as exc:
        print(
            "[speech] CUDA failed (" + str(exc).strip().replace("\n", " ")[:250]
            + "). Retrying transcription on CPU/int8.",
            flush=True,
        )
        return transcribe("cpu")
