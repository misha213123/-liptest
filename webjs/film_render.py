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
)
from film_runtime import face_detector, transcribe_segments

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


def _track_centres(video: Path, start: float, duration: float, width: int, height: int):
    try:
        import cv2
        detector = face_detector(cv2, ROOT / "output" / "film_models")
        cap = cv2.VideoCapture(str(video))
        points = []
        last_x, last_y = width / 2, height / 2
        detections = 0
        try:
            count = min(110, max(3, int(duration / 1.5)))
            for i in range(count + 1):
                t = duration * i / count
                cap.set(cv2.CAP_PROP_POS_MSEC, (start + t) * 1000)
                ok, frame = cap.read()
                if not ok:
                    continue
                fw = frame.shape[1]
                fh = frame.shape[0]
                factor = min(1, 640 / max(1, fw))
                small = cv2.resize(frame, None, fx=factor, fy=factor) if factor < 1 else frame
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                faces = detector.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(24, 24))
                if len(faces):
                    detections += 1
                    candidates = [
                        ((x + w / 2) / factor, (y + h / 2) / factor, w * h)
                        for x, y, w, h in faces
                    ]
                    # Favor a stable subject when two people share the screen.
                    face = max(
                        candidates,
                        key=lambda p: p[2] - 0.0008 * ((p[0]-last_x)**2 + (p[1]-last_y)**2),
                    )
                    x, y = face[:2]
                    last_x = last_x * 0.68 + x * 0.32
                    last_y = last_y * 0.68 + y * 0.32
                points.append((t, last_x, last_y))
        finally:
            cap.release()
        if detections:
            print(f"[faces] Face detected in {detections}/{len(points)} sampled frames.", flush=True)
        else:
            print("[faces] No frontal faces detected in sampled frames; using center crop.", flush=True)
        return points
    except Exception as err:
        print("[faces] Face tracking unavailable; center crop fallback:", str(err)[:300], flush=True)
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


def _make_subtitles(source: Path, start: float, end: float, out: Path, w: int, h: int):
    audio = out / "speech.wav"
    progress("Извлекаю голос для субтитров", 24)
    run([FFMPEG, "-y", "-nostdin", "-loglevel", "error",
         "-ss", str(start), "-i", str(source), "-t", str(end-start),
         "-vn", "-ar", "16000", "-ac", "1", str(audio)], timeout=1200)
    progress("Распознаю речь и точные таймкоды слов", 32)
    segments = transcribe_segments(str(audio))
    progress("Речь распознана; формирую субтитры", 47)
    events = []
    def stamp(t):
        t = max(0, float(t))
        return f"{int(t//3600)}:{int(t%3600//60):02d}:{int(t%60):02d}.{int((t%1)*100):02d}"
    for segment in segments:
        words = list(segment.words or [])
        if words:
            for index in range(0, len(words), 3):
                group = words[index:index+3]
                text = " ".join(str(w.word).strip() for w in group).strip()
                if not text:
                    continue
                text = text.replace("\\", "").replace("{", "").replace("}", "").replace("\n", " ")
                events.append(f"Dialogue: 0,{stamp(group[0].start)},{stamp(group[-1].end)},Default,,0,0,0,,{{\\fad(60,80)}}{text}")
        elif segment.text:
            text = segment.text.replace("{", "").replace("}", "").replace("\\", "").replace("\n", " ")
            events.append(f"Dialogue: 0,{stamp(segment.start)},{stamp(segment.end)},Default,,0,0,0,,{text}")

    ass = out / "subtitles.ass"
    font_size = max(28, round(w * 0.065))
    content = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: " + str(w) +
        "\nPlayResY: " + str(h) +
        "\nScaledBorderAndShadow: yes\nWrapStyle: 2\n"
        "\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial,{font_size},&H00FFFFFF,&H0000FFFF,&H00101010,&H80000000,"
        "1,0,0,0,100,100,0,0,1,3,1,2,30,30," + str(max(100,round(h*0.13))) + ",1\n"
        "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "\n".join(events) + "\n"
    )
    ass.write_text(content, encoding="utf-8")
    progress(f"Субтитры готовы: {len(events)} фрагментов", 58)
    return ass, len(events)


def _ass_filter(path: Path) -> str:
    # FFmpeg filtergraph escaping for Windows drive colon, backslashes and quotes.
    name = str(path.resolve()).replace("\\", "/")
    name = name.replace(":", "\\:").replace("'", "\\'")
    return f"ass=filename='{name}'"


def render(job: dict) -> dict:
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
    # Match the actual on-disk Video2X model scale.
    # Real-ESRGAN Plus is 4x, not 2x in official Video2X 6.4.0.
    # Pre-render only 1/4 dimensions for a 4K result to avoid
    # accidentally generating 8K and exhausting video memory.
    scale = video2x_upscale_factor(ai_model)
    if scale > 1:
        render_w = max(2, (round(target_w / scale) // 2) * 2)
        render_h = max(2, (round(target_h / scale) // 2) * 2)
    else:
        render_w, render_h = target_w, target_h
    if scale > 1:
        print(f"[video2x] Preparing {render_w}x{render_h} for {scale}x AI upscale "
              f"to {target_w}x{target_h}.", flush=True)
    iw, ih = metadata["width"], metadata["height"]
    cw = min(iw, int(ih * target_w / target_h))
    ch = min(ih, int(iw * target_h / target_w))
    cw = max(2, cw - cw%2)
    ch = max(2, ch - ch%2)

    job_id = str(job.get("id") or uuid.uuid4().hex[:12])
    out = RENDER_DIR / job_id
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "final.mp4"
    duration = end-start
    progress("Получен исходник " + str(iw) + "x" + str(ih), 16)

    face_tracking = bool(job.get("face_tracking", True))
    progress("Отслеживаю лица и выравниваю кадр", 19)
    centres = _track_centres(source, start, duration, iw, ih) if face_tracking else []
    progress("Кадрирование подготовлено", 22)
    if face_tracking:
        print(f"[faces] Найдено {len(centres)} точек отслеживания", flush=True)
    x_expr = _curve(centres, 0, iw, cw)
    y_expr = _curve(centres, 1, ih, ch)

    vf = [
        f"crop={cw}:{ch}:x='{x_expr}':y='{y_expr}'",
        f"scale={render_w}:{render_h}:flags=lanczos",
        "setsar=1",
    ]
    if bool(job.get("enhance", True)):
        gamma = min(1.20, max(0.85, float(job.get("gamma", 1.05))))
        saturation = min(1.30, max(0.75, float(job.get("saturation", 1.10))))
        brightness = min(0.12, max(-0.05, float(job.get("brightness", 0.02))))
        contrast = min(1.30, max(0.80, float(job.get("contrast", 1.06))))
        vf.extend([
            f"eq=brightness={brightness:.3f}:gamma={gamma:.3f}:contrast={contrast:.3f}:saturation={saturation:.3f}",
            "unsharp=5:5:0.32:5:5:0.0" if ai_enabled else "unsharp=5:5:0.42:5:5:0.0",
        ])
    # RIFE works on actual source frames. Do not duplicate/interpolate
    # the frames with FFmpeg before passing them into the neural network.
    fps = metadata["fps"] if fps_choice == "source" else int(fps_choice)
    optical = (
        not (rife_multiplier > 1)
        and bool(job.get("optical_flow", False))
        and fps_choice != "source"
        and fps > metadata["fps"] + 0.5
    )
    if optical:
        vf.append(f"minterpolate=fps={int(fps)}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir")
    elif fps_choice != "source" and rife_multiplier == 1:
        vf.append(f"fps={int(fps)}")

    caption_count = 0
    if bool(job.get("captions", True)):
        ass, caption_count = _make_subtitles(source, start, end, out, render_w, render_h)
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
    if ai_enabled:
        progress("Запускаю Video2X (на видеокарте Vulkan)", 72)
        enhanced = run_video2x(
            prepared, out, ai_model, rife_multiplier,
            target_w, target_h, report=progress,
        )
        enhanced_info = probe(enhanced)
        final_filters = []
        if enhanced_info["width"] != target_w or enhanced_info["height"] != target_h:
            final_filters.append(f"scale={target_w}:{target_h}:flags=lanczos")
        if fps_choice != "source" and abs(enhanced_info["fps"] - float(fps_choice)) > 0.4:
            final_filters.append(f"fps={int(fps_choice)}")
        if final_filters:
            progress("Привожу видео к выбранному разрешению и FPS", 90)
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
        # Do not let video intermediates fill the user's disk.
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
            "enabled": ai_enabled, "upscale": ai_model,
            "rife_multiplier": rife_multiplier,
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
