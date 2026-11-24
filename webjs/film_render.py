#!/usr/bin/env python3
"""Film & Series Studio: source acquisition, face-follow reframing, subtitles, HQ export.

Only process media you are authorized to download and edit. This module does not
bypass DRM, authentication, subscriptions or inaccessible streams.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import socket
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from core.streamer_export import ASPECT_PRESETS
from utils.helpers import get_ffmpeg_path
from film_video2x import (
    options as video2x_options,
    require_binary as require_video2x,
    run_steps as run_video2x,
    upscale_factor as video2x_upscale_factor,
    intermediate_dimensions as video2x_intermediate_dimensions,
)
from film_runtime import face_detector, optional_profile_detector, transcribe_segments
from film_openai import transcribe_openai, availability as openai_availability
from film_openai_max import transcribe_max
from film_captions import save_ass, validate as validate_caption_style
from film_transcript_cache import transcribe_cached
from film_filters import color_filters

OUT = ROOT / "output"
INPUT_DIR = OUT / "film_inputs"
CACHE_DIR = OUT / "film_source_cache"
RENDER_DIR = OUT / "film_clips"
FFMPEG = get_ffmpeg_path()
FFPROBE = str(Path(FFMPEG).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def progress(message: str, percent: int):
    print(f"[progress] {message} (overall: {percent:.1f}%)", flush=True)


def run(command, timeout=7200):
    p = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=FLAGS,
    )
    if p.returncode:
        raise RuntimeError("FFmpeg: " + "\n".join((p.stderr or "").splitlines()[-15:])[:2500])
    return p


def encode_with_progress(command: list[str], duration: float, timeout: int = 10800, progress_start: int = 62, progress_span: int = 36):
    """Keep the UI updated during long 4K/optical-flow encodes."""
    command = command[:1] + ["-progress", "pipe:1", "-nostats"] + command[1:]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=FLAGS,
    )
    started = time.monotonic()
    lines = []
    last_percent = progress_start - 1
    try:
        for line in process.stdout:
            line = line.strip()
            if line:
                lines.append(line)
                if len(lines) > 80:
                    lines.pop(0)
            if line.startswith("out_time="):
                raw = line[len("out_time="):]
                try:
                    current = sec(raw)
                    pct = min(progress_start + progress_span, progress_start + int(current / max(1, duration) * progress_span))
                    if pct > last_percent:
                        progress("Кодирую итоговый MP4", pct)
                        last_percent = pct
                except (ValueError, ZeroDivisionError):
                    pass
            if time.monotonic() - started > timeout:
                process.kill()
                raise TimeoutError("Рендер превысил установленный лимит времени.")
        code = process.wait(timeout=30)
        if code:
            raise RuntimeError("FFmpeg не завершил рендер:\n" + "\n".join(lines[-20:])[-2500:])
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def probe(path: Path) -> dict:
    p = run(
        [FFPROBE, "-v", "error", "-show_entries",
         "stream=width,height,avg_frame_rate,codec_type:format=duration",
         "-of", "json", str(path)], timeout=30
    )
    info = json.loads(p.stdout or "{}")
    videos = [stream for stream in info.get("streams") or [] if stream.get("codec_type") == "video"]
    if not videos:
        raise RuntimeError("Исходник не содержит видеодорожку.")
    video = videos[0]
    num, _, den = str(video.get("avg_frame_rate") or "30/1").partition("/")
    try:
        fps = float(num) / max(1.0, float(den or "1"))
    except ValueError:
        fps = 30.0
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": min(240, max(1, fps)),
        "duration": float(info.get("format", {}).get("duration") or 0),
    }


def sec(raw):
    pieces = str(raw or "0").replace(",", ".").strip().split(":")
    if len(pieces) > 3:
        raise ValueError("Неверный таймкод.")
    values = [float(v) for v in pieces]
    return sum(value * (60 ** i) for i, value in enumerate(reversed(values)))


def authorized_input(job: dict) -> Path:
    input_id = str(job.get("input_id") or "")
    if input_id:
        if not re.fullmatch(r"[a-f0-9]{24}\.(mp4|mkv|mov|webm|m4v)", input_id):
            raise ValueError("Некорректный идентификатор загруженного файла.")
        path = INPUT_DIR / input_id
        if not path.is_file():
            raise FileNotFoundError("Загруженный файл не найден. Загрузи его повторно.")
        return path

    from film_catalog import stream_url, validate_url
    url = validate_url(str(job.get("url") or ""))
    season = str(job.get("season") or "").strip()
    episode = str(job.get("episode") or "").strip()
    voice = str(job.get("voice") or "").strip()
    if bool(season) != bool(episode):
        raise ValueError("Выбери и сезон, и серию.")
    media_url, resolution = stream_url(url, season, episode, voice)
    url_host = urlparse(media_url).hostname or ""
    # Basic SSRF protection: reject explicit private/loopback IP addresses.
    try:
        ip = ipaddress.ip_address(url_host)
        if not ip.is_global:
            raise ValueError("Приватные адреса видеопотоков запрещены.")
    except ValueError as exc:
        if "запрещены" in str(exc):
            raise
    key = hashlib.sha256(
        (url + "|" + season + "|" + episode + "|" + voice + "|" + resolution).encode()
    ).hexdigest()[:24]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / (key + ".mp4")
    if target.is_file() and target.stat().st_size > 100_000:
        progress("♻ Исходник найден в кэше", 14)
        return target

    tmp = CACHE_DIR / (key + ".partial.mp4")
    progress("Скачиваю выбранную серию в максимальном доступном качестве " + resolution, 5)
    # The provider supplies the playable stream; yt-dlp handles MP4 and HLS.
    # No cookies, decrypted content or protected-site bypass.
    import yt_dlp
    opts = {
        "outtmpl": str(tmp),
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "continuedl": True,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "socket_timeout": 30,
        "noplaylist": True,
        "http_headers": {"Referer": url},
        "ffmpeg_location": str(Path(FFMPEG).parent),
    }
    with yt_dlp.YoutubeDL(opts) as dl:
        dl.download([media_url])
    possible = [tmp, CACHE_DIR / (key + ".partial.mp4.mp4"), *CACHE_DIR.glob(key + ".partial.*")]
    file = next((p for p in possible if p.is_file() and p.stat().st_size > 100_000 and not p.name.endswith(".part")), None)
    if not file:
        raise RuntimeError("Сайт не разрешил получить видеопоток. Используй импорт своего видеофайла.")
    file.replace(target)
    return target


def _track_centres(
    video: Path, start: float, duration: float,
    width: int, height: int, focus: str = "auto",
):
    """Follow a face using Haar detections plus optical flow between detections.

    Frontal face Haar by itself can miss profiles/occluded faces in films.
    LK flow keeps the same face moving between sparse detections. Hard scene
    cuts reset tracked points, reducing the chance of following background.
    """
    try:
        import cv2
        import numpy as np
        if focus not in ("auto", "left", "center", "right"):
            raise ValueError("Неизвестный выбор лица.")
        detector = face_detector(cv2, ROOT / "output" / "film_models")
        profile_detector = optional_profile_detector(cv2, ROOT / "output" / "film_models")
        cap = cv2.VideoCapture(str(video))
        points = []
        preferred_x = {"auto": 0.5, "left": 0.25, "center": 0.5, "right": 0.75}[focus] * width
        last_x, last_y = preferred_x, height / 2
        last_gray = None
        features = None
        detected = 0
        followed = 0
        scene_cuts = 0
        try:
            count = min(180, max(4, int(duration * 2)))
            for i in range(count + 1):
                t = duration * i / count
                cap.set(cv2.CAP_PROP_POS_MSEC, (start + t) * 1000)
                ok, frame = cap.read()
                if not ok:
                    continue
                factor = min(1, 640 / max(1, frame.shape[1]))
                small = cv2.resize(frame, None, fx=factor, fy=factor) if factor < 1 else frame
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                changed = False
                if last_gray is not None and last_gray.shape == gray.shape:
                    # Ignore optical-flow points after a hard cut.
                    if float(cv2.absdiff(gray, last_gray).mean()) > 45:
                        scene_cuts += 1
                        features = None
                        last_x, last_y = preferred_x, height / 2
                        changed = True
                faces = list(detector.detectMultiScale(
                    gray, scaleFactor=1.08, minNeighbors=3, minSize=(24, 24)
                ))
                if profile_detector is not None:
                    try:
                        profiles = profile_detector.detectMultiScale(
                            gray, scaleFactor=1.1, minNeighbors=3, minSize=(28,28)
                        )
                        faces.extend(list(profiles))
                        flipped = cv2.flip(gray, 1)
                        other_side = profile_detector.detectMultiScale(
                            flipped, scaleFactor=1.1, minNeighbors=3, minSize=(28,28)
                        )
                        faces.extend([
                            (gray.shape[1]-x-w, y, w, h)
                            for x,y,w,h in other_side
                        ])
                    except cv2.error:
                        pass
                if len(faces):
                    candidates = [
                        ((x + w/2)/factor, (y + h/2)/factor, w * h, x, y, w, h)
                        for x,y,w,h in faces
                    ]
                    if focus == "auto":
                        picked = max(
                            candidates,
                            key=lambda p: p[2] - .035 * (
                                (p[0]-last_x)**2 + (p[1]-last_y)**2
                            )
                        )
                    else:
                        picked = max(
                            candidates,
                            # User can select which side to follow when
                            # several actors appear in the same shot.
                            key=lambda p: -.13*(p[0]-preferred_x)**2 + .01*p[2]
                        )
                    fx, fy = picked[:2]
                    last_x = last_x * .58 + fx * .42
                    last_y = last_y * .58 + fy * .42
                    detected += 1
                    x,y,w,h = picked[3:]
                    mask = np.zeros_like(gray)
                    mask[max(0,y):min(mask.shape[0],y+h),
                         max(0,x):min(mask.shape[1],x+w)] = 255
                    features = cv2.goodFeaturesToTrack(
                        gray, maxCorners=65, qualityLevel=.025,
                        minDistance=5, mask=mask
                    )
                elif features is not None and last_gray is not None and not changed:
                    try:
                        new, status, _ = cv2.calcOpticalFlowPyrLK(
                            last_gray, gray, features, None,
                            winSize=(19,19), maxLevel=2
                        )
                        if new is not None and status is not None:
                            good = status.ravel() == 1
                            if int(good.sum()) >= 6:
                                shifts = new[good].reshape(-1,2) - features[good].reshape(-1,2)
                                dx, dy = np.median(shifts, axis=0) / factor
                                if abs(dx) < width * .18 and abs(dy) < height * .18:
                                    last_x = min(width, max(0, last_x + float(dx)))
                                    last_y = min(height, max(0, last_y + float(dy)))
                                    features = new[good].reshape(-1,1,2)
                                    followed += 1
                                else:
                                    features = None
                            else:
                                features = None
                    except cv2.error:
                        features = None
                last_gray = gray
                points.append((t, last_x, last_y))
        finally:
            cap.release()
        print(
            f"[faces] Tracking focus={focus}; "
            f"face detected in {detected}/{len(points)} samples, "
            f"optical-flow follow in {followed} samples, "
            f"hard cuts {scene_cuts}.",
            flush=True,
        )
        if not detected:
            print("[faces] No face found; crop falls back to scene center.", flush=True)
        return points if detected else []
    except Exception as err:
        print("[faces] Tracking unavailable; center crop fallback:", str(err)[:260], flush=True)
        return []


def _curve(points, axis: int, size: int, crop_size: int) -> str:
    if not points:
        return str(max(0, (size-crop_size)//2))
    trajectory = [(t, int(max(0, min(size - crop_size, centre - crop_size / 2))))
                  for t, *xy in points for centre in [xy[axis]]]
    expr = str(trajectory[-1][1])
    for (t0, v0), (t1, v1) in reversed(list(zip(trajectory[:-1], trajectory[1:]))):
        gap = max(0.001, t1 - t0)
        motion = str(v0) if v0 == v1 else f"({v0}+({v1-v0})*(t-{t0:.3f})/{gap:.3f})"
        expr = f"if(lt(t,{t1:.3f}),{motion},{expr})"
    return expr


def _make_subtitles(
    source: Path, start: float, end: float, out: Path, w: int, h: int,
    style: str = "bold", position: int = 78,
    model: str = "medium", language: str = "ru", offset: float = 0.0,
    engine: str = "local",
    words_per_caption: int = 3,
    remove_punctuation: bool = False,
    caption_size_percent: int = 100,
    caption_case: str = "source",
):
    validate_caption_style(style, position)
    engine = str(engine or "local").lower()
    if engine not in ("local", "openai", "openai_max"):
        raise ValueError("Неизвестный движок распознавания речи.")

    def recognize():
        audio = out / "speech.wav"
        progress("Извлекаю голос для субтитров", 24)
        run([FFMPEG, "-y", "-nostdin", "-loglevel", "error",
             "-ss", str(start), "-i", str(source), "-t", str(end - start),
             "-vn", "-ar", "16000", "-ac", "1", str(audio)], timeout=1200)
        if engine == "openai_max":
            progress("OpenAI GPT-Transcribe: максимум качества + таймкоды слов", 32)
            return transcribe_max(audio, language=language)
        if engine == "openai":
            progress("OpenAI: распознаю речь и таймкоды слов (облачный API)", 32)
            return transcribe_openai(audio, language=language)
        progress("Локальный Whisper: распознаю речь", 32)
        return transcribe_segments(
            str(audio), model_name=model, language=language,
        )

    segments = transcribe_cached(
        source, start, end, engine, model, language,
        recognize, cache_dir=OUT / "film_transcripts",
    )
    progress("Речь распознана; формирую субтитры", 47)
    ass = out / "subtitles.ass"
    count = save_ass(
        segments, ass, w, h, style, position, offset,
        words_per_caption, remove_punctuation,
        caption_size_percent, caption_case,
    )
    progress(
        f"Субтитры готовы: {count} фрагментов · шаблон {style} · "
        f"слов на экране: {words_per_caption} · "
        f"без пунктуации: {remove_punctuation}", 58,
    )
    return ass, count


def _ass_filter(path: Path) -> str:
    # FFmpeg filtergraph escaping for Windows drive colon, backslashes and quotes.
    name = str(path.resolve()).replace("\\", "/")
    name = name.replace(":", "\\:").replace("'", "\\'")
    return f"ass=filename='{name}'"


def optical_motion_filter(source_fps: float, requested_fps: float, enabled: bool) -> str:
    """Real motion-compensated in-between frames, not duplicated fps=60 labels.

    Source material below the requested frame rate is interpolated only when
    requested, otherwise the plain fps converter may duplicate frames.
    """
    if not enabled or requested_fps <= source_fps + 0.5:
        return ""
    if requested_fps not in (30, 60):
        raise ValueError("Optical interpolation only supports 30 or 60 FPS.")
    return (
        f"minterpolate=fps={int(requested_fps)}:mi_mode=mci:"
        "mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=fdiff:scd_threshold=10"
    )


def render(job: dict) -> dict:
    if bool(job.get("captions", True)):
        engine = str(job.get("speech_engine") or "local").lower()
        if engine not in ("local", "openai", "openai_max"):
            raise ValueError("Неизвестный движок субтитров.")
        if engine in ("openai", "openai_max") and not openai_availability()["configured"]:
            raise RuntimeError(
                "OpenAI не настроен. Добавь свой ключ через OPENAI_API_KEY "
                "или настройки OpenAI и перезапусти Film Studio."
            )
    ai_model, rife_multiplier = video2x_options(job)
    ai_enabled = ai_model != "off" or rife_multiplier > 1
    if ai_enabled:
        # Fail before downloading a long film if the external CLI is unavailable.
        require_video2x(ai_model, rife_multiplier)
    source = authorized_input(job)
    metadata = probe(source)
    start, end = sec(job.get("start", 0)), sec(job.get("end", 0))
    if end <= start or end - start > 300:
        raise ValueError("Выбери отрезок от 1 до 300 секунд.")
    if metadata["duration"] and end > metadata["duration"] + 0.5:
        raise ValueError("Конец клипа выходит за пределы исходного видео.")
    ratio = str(job.get("ratio") or "9:16")
    if ratio not in ASPECT_PRESETS:
        raise ValueError("Неизвестный формат кадра.")
    size = int(job.get("size") or 1080)
    if size not in (1080, 1440, 2160):
        raise ValueError("Допустимые размеры: 1080, 1440, 2160.")
    fps_choice = str(job.get("fps") or "source")
    if fps_choice not in ("source", "30", "60"):
        raise ValueError("Неверная частота кадров.")
    base_w, base_h = ASPECT_PRESETS[ratio]
    target_w, target_h = round(base_w * size / 1080), round(base_h * size / 1080)
    target_w += target_w % 2
    target_h += target_h % 2
    iw, ih = metadata["width"], metadata["height"]
    cw = min(iw, int(ih * target_w / target_h))
    ch = min(ih, int(iw * target_h / target_w))
    cw = max(2, cw - cw % 2)
    ch = max(2, ch - ch % 2)
    # Avoid feeding a 270x480 image to an AI model when the cropped source
    # contains roughly 404x720 pixels. Preserve native source detail as far
    # as practical without producing a gigantic 4x AI intermediate.
    scale = video2x_upscale_factor(ai_model)
    render_w, render_h = video2x_intermediate_dimensions(
        cw, ch, target_w, target_h, ai_model
    )
    if scale > 1:
        print(
            f"[video2x] Source crop {cw}x{ch}; preparing {render_w}x{render_h} "
            f"for native {scale}x AI upscale, target {target_w}x{target_h}.",
            flush=True,
        )

    job_id = str(job.get("id") or uuid.uuid4().hex[:12])
    out = RENDER_DIR / job_id
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "final.mp4"
    duration = end-start
    progress("Получен исходник " + str(iw) + "x" + str(ih), 16)

    face_tracking = bool(job.get("face_tracking", True))
    progress("Отслеживаю лица и выравниваю кадр", 19)
    centres = _track_centres(
        source, start, duration, iw, ih,
        str(job.get("face_focus") or "auto"),
    ) if face_tracking else []
    progress("Кадрирование подготовлено", 22)
    if face_tracking:
        print(f"[faces] Найдено {len(centres)} точек отслеживания", flush=True)
    x_expr = _curve(centres, 0, iw, cw)
    y_expr = _curve(centres, 1, ih, ch)

    # Interpolate motion at the *native crop resolution* before 1080p scaling.
    # A 900x720 source is ~2.25x fewer pixels than 1350x1080 output, saving
    # CPU cycles for optical-flow quality instead of wasting them on upscale.
    # Final resample/color/subtitles are applied after the motion stage.
    fps = metadata["fps"] if fps_choice == "source" else int(fps_choice)
    optical = (
        not (rife_multiplier > 1)
        and bool(job.get("optical_flow", False))
        and fps_choice != "source"
        and fps > metadata["fps"] + 0.5
    )
    vf = [
        "setpts=PTS-STARTPTS",
        f"crop={cw}:{ch}:x='{x_expr}':y='{y_expr}'",
    ]
    if optical:
        vf.append(optical_motion_filter(metadata["fps"], fps, True))
        print(
            f"[motion] Real motion-compensated interpolation "
            f"{metadata['fps']:.2f} -> {fps} FPS, at native "
            f"cropped resolution {cw}x{ch}.",
            flush=True,
        )
    vf += [
        f"scale={render_w}:{render_h}:flags=lanczos",
        "setsar=1",
    ]
    vf.extend(color_filters(job, ai_enabled=ai_enabled))
    if fps_choice != "source" and rife_multiplier == 1 and not optical:
        vf.append(f"fps={int(fps)}")
    caption_count = 0
    if bool(job.get("captions", True)):
        ass, caption_count = _make_subtitles(
            source, start, end, out, render_w, render_h,
            str(job.get("caption_style") or "bold"),
            int(job.get("caption_position", 78)),
            str(job.get("whisper_model") or "medium"),
            str(job.get("speech_language") or "ru"),
            float(job.get("caption_offset", 0)),
            str(job.get("speech_engine") or "local"),
            int(job.get("caption_words", 3)),
            job.get("caption_no_punctuation", False),
            int(job.get("caption_size_percent", 100)),
            str(job.get("caption_case") or "lower"),
        )
        if caption_count:
            vf.append(_ass_filter(ass))
    vf.append("format=yuv420p")
    progress("Рендер Ultra HD / плавность", 61)
    prepared = out / "film_prepared.mp4" if ai_enabled else dest
    cmd = [
        FFMPEG, "-hide_banner", "-y", "-nostdin", "-ss", str(start),
        "-i", str(source), "-t", str(duration), "-vf", ",".join(vf),
        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
        "-c:a", "aac", "-b:a", "256k",
        "-movflags", "+faststart", str(prepared),
    ]
    encode_with_progress(
        cmd, duration, timeout=10800, progress_start=62,
        progress_span=9 if ai_enabled else 36,
    )
    video2x_warning = ""
    ai_succeeded = False
    if ai_enabled:
        progress("Запускаю Video2X (на видеокарте Vulkan)", 72)
        enhanced = prepared
        try:
            enhanced = run_video2x(
                prepared, out, ai_model, rife_multiplier,
                target_w, target_h, report=progress,
            )
            ai_succeeded = True
        except Exception as err:
            video2x_warning = (
                "Video2X не завершился, готовый клип будет экспортирован "
                "обычным FFmpeg (без AI-улучшения и RIFE): " + str(err)[:400]
            )
            print("[video2x] WARNING: " + video2x_warning, flush=True)
            # This is a legitimate finished video with face crop, captions
            # and color grading. Do not discard it when Vulkan gets stuck.
            enhanced = prepared
            progress("Video2X недоступен; сохраняю обычный MP4", 88)
        enhanced_info = probe(enhanced)
        final_filters = []
        if enhanced_info["width"] != target_w or enhanced_info["height"] != target_h:
            final_filters.append(f"scale={target_w}:{target_h}:flags=lanczos")
        if fps_choice != "source" and abs(enhanced_info["fps"] - float(fps_choice)) > 0.4:
            # If RIFE failed or returned an unexpected rate, still deliver
            # motion-interpolated frames when the user asked for 60 FPS.
            # In the old code this unconditionally duplicated source frames.
            target_fps = int(fps_choice)
            interpolator = optical_motion_filter(
                enhanced_info["fps"], target_fps,
                bool(job.get("optical_flow", False)) or (
                    rife_multiplier > 1 and not ai_succeeded
                )
            )
            final_filters.append(interpolator or f"fps={target_fps}")
            if interpolator:
                print(f"[motion] Fallback FFmpeg motion interpolation {enhanced_info['fps']:.2f} → {target_fps} FPS.", flush=True)
        if final_filters:
            progress("Финальный экспорт MP4", 90)
            normalize_cmd = [
                FFMPEG, "-hide_banner", "-y", "-nostdin", "-i", str(enhanced),
                "-vf", ",".join(final_filters + ["format=yuv420p"]),
                "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                "-c:a", "copy", "-movflags", "+faststart", str(dest),
            ]
            encode_with_progress(
                normalize_cmd, duration, timeout=10800,
                progress_start=90, progress_span=8,
            )
        else:
            enhanced.replace(dest)
        # Do not let old video intermediates fill up the user's disk.
        for intermediate in (
            prepared, out / "video2x_upscaled.mp4", out / "video2x_rife.mp4",
        ):
            if intermediate != dest:
                intermediate.unlink(missing_ok=True)
    if not dest.is_file() or dest.stat().st_size < 100_000:
        raise RuntimeError("Файл рендера не создан.")
    finished = probe(dest)
    progress("Клип готов", 100)
    return {
        "ok": True, "id": job_id, "file": "final.mp4",
        "width": finished["width"], "height": finished["height"],
        "fps": finished["fps"],
        "source_resolution": str(iw) + "x" + str(ih),
        "captions": caption_count, "tracked_samples": len(centres),
        "optical_flow": optical,
        "video2x": {
            "enabled": ai_succeeded, "requested": ai_enabled,
            "upscale": ai_model if ai_succeeded else "off",
            "rife_multiplier": rife_multiplier if ai_succeeded else 1,
            "warning": video2x_warning,
        },
    }


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: film_render.py job.json result.json")
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    destination = Path(sys.argv[2])
    try:
        result = render(job)
        destination.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
    except Exception as exc:
        traceback.print_exc()
        destination.write_text(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
