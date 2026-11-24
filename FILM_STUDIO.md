# Film & Series Studio (beta)

New page: http://localhost:3000/film.html

## Install on Windows (PowerShell)

```powershell
cd "$HOME\Desktop\auto-clipper-v2"
git fetch origin
git switch feature/movie-series-studio
git pull --ff-only origin feature/movie-series-studio
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start-web.bat
```

## Workflow

- Paste an hdrezka.rest film or series link to request available seasons, episodes and voice translations. Source availability depends on the provider.
- Alternatively, upload an authorized MP4/MKV/MOV/WEBM (up to 8 GB) directly to the local computer. This workflow does not depend on the website.
- Pick clip start/end (up to 300 seconds), aspect ratio, output resolution, source or 30/60 FPS, face-follow cropping, spoken subtitles, and color enhancement.
- Render an MP4, view progress, then download it locally.

Output: output/film_clips/<job_id>/final.mp4.
Source uploads: output/film_inputs.
Remote source cache: output/film_source_cache.

## Limitations and quality

- HDRezka integration uses the unofficial HdRezkaApi provider for metadata and available streams. The provider may block requests or lack access to the selected item. We have not verified live downloading from hdrezka.rest.
- The 4K option is a high-quality Lanczos upscale with adjustable gamma/saturation, gentle sharpening, and CRF-16 H.264 encoding. It cannot restore real source detail or reproduce proprietary CapCut AI super-resolution.
- Face tracking uses OpenCV Haar frontal-face detection with smoothed crop coordinates. Hard cuts, profiles and group shots can cause the crop to lag or choose the wrong person.
- Subtitles come from the actual audio using local Faster-Whisper (small model, word timestamps). Their accuracy depends on dialogue and background noise; first run may download a speech model.
- Optional optical flow to 60 FPS can be very slow and may introduce motion artifacts.
- Initial feature scope is one manually selected scene per render. Automatic semantic highlights, queues and speaker identification are not yet implemented.
- Only process content you have rights to download and edit. The tool does not circumvent DRM, authentication or paywalls.

## Troubleshooting

Ensure yt-dlp, HdRezkaApi, faster-whisper and OpenCV are installed in the same Python .venv used by the Node server.
Ensure FFmpeg has the libass/subtitles filter. If the provider blocks the film URL, use the local upload.
Test 1080p at source FPS first, then enable optional 2160p and optical flow.