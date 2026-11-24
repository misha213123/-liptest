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

## HDrezka Grabber browser download integration

- Extension repository: https://github.com/kristal374/HDrezka-Grabber
- Chrome Web Store: https://chromewebstore.google.com/detail/hdrezka-grabber/aamnmboocelpaiagegjicbefiinkcoal/
- Film Studio uses a **local Downloads-folder bridge**, not the extension API.
  This means it works even if the extension updates, and no GPL-licensed
  browser extension code is bundled with Auto Clipper.
- Install the extension separately. On the supported film/series website,
  select the season, episode, voice track and source quality; download a video
  that you are authorized to edit.
- Keep the downloaded MP4/MKV/MOV/WEBM in your regular Windows Downloads folder.
- Open http://localhost:3000/film.html and use
  **Browser Downloads -> Refresh -> Import**, or enable the opt-in auto-import
  checkbox **before** the download finishes.
- The page checks every six seconds for completed files (at least 12 seconds
  without file modification). It discovers files in Downloads and up to two
  subfolder levels (for example Series / Season / Episode).
- A completed file is registered in output/film_inputs using a hardlink when
  possible (instant, no additional disk usage); otherwise it is copied locally.
  The original Downloads file is never deleted or moved.
- Auto-import only operates **while the Film Studio page is open**.
  Existing files are listed, not auto-imported retroactively.
  Auto-import is disabled by default to avoid importing unrelated downloads.
- The import APIs are restricted to requests from this computer's loopback
  interface. Other devices on the local network cannot browse Downloads or
  request imports. No browser cookies, extension permissions, or site credentials
  are shared with Auto Clipper.
- To use a different browser download directory, set `FILM_DOWNLOADS_DIR`
  before running the Node server:

```powershell
$env:FILM_DOWNLOADS_DIR = "D:\Videos\Downloads"
.\start-web.bat
```

- Only fully downloaded files between 1 KiB and 8 GiB with supported extensions
  are eligible. In-progress .crdownload and .part files are excluded.
- Selecting a downloaded file does not infer its season, voice language or licensing;
  the browser extension handles these choices before download.
- This does not bypass any website protection or guarantee downloading from HDrezka.

## Workflow

- Paste an hdrezka.rest film or series link to request available seasons, episodes and voice translations. Source availability depends on the provider.
- Alternatively, upload an authorized MP4/MKV/MOV/WEBM (up to 8 GB) directly to the local computer. This workflow does not depend on the website.
- Pick clip start/end (up to 300 seconds), aspect ratio, output resolution, source or 30/60 FPS, face-follow cropping, spoken subtitles, and color enhancement.
- Render an MP4, view progress, then download it locally.

Output: output/film_clips/<job_id>/final.mp4.
Source uploads: output/film_inputs.
Remote source cache: output/film_source_cache.

## Quick Video2X CLI install (Windows)

Run from the Auto Clipper repository directory (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-video2x.ps1
```

The script downloads **only the official Video2X CLI ZIP** from the latest
k4yt3x/video2x GitHub release, checks the release SHA256 digest when provided,
extracts to %LOCALAPPDATA%\Programs\video2x, and sets VIDEO2X_BIN for your user.
Restart the Auto Clipper server after installation.

## Video2X 6.x integration (optional AI enhancement)

Official source: https://github.com/k4yt3x/video2x
CLI installation: https://docs.video2x.org/installing/windows.html

The Auto Clipper adapter calls the Video2X 6.x CLI as an external executable.
No Video2X binaries, neural-network weights, or AGPL source code are copied into this repository.

Install the official command-line ZIP on Windows using PowerShell:

```powershell
$release = Invoke-RestMethod "https://api.github.com/repos/k4yt3x/video2x/releases/latest"
$asset = $release.assets | Where-Object { $_.name -eq "video2x-windows-amd64.zip" } | Select-Object -First 1
if (-not $asset) { throw "Video2X CLI ZIP not found in latest release. Check https://github.com/k4yt3x/video2x/releases" }
$archive = Join-Path $env:TEMP "video2x-windows-amd64.zip"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archive
$target = Join-Path $env:LOCALAPPDATA "Programs\video2x"
New-Item -ItemType Directory -Path $target -Force | Out-Null
Expand-Archive -Path $archive -DestinationPath $target -Force
$env:VIDEO2X_BIN = Join-Path $target "video2x.exe"
& $env:VIDEO2X_BIN --help
```

Keep `VIDEO2X_BIN` set in the PowerShell session where you run `start-web.bat`,
or add the folder containing video2x.exe to PATH. The adapter also searches
`%LOCALAPPDATA%\Programs\video2x\video2x.exe` by default.

**Film Studio UI controls:**

- Upscale: off, Real-ESRGAN Plus, Real-ESRGAN General v3, AnimeVideo v3, or Anime4K v4 A+A.
- AI FPS: RIFE v4.26 at original FPS, x2, or x4 with scene-change threshold 20.
- One-click Ultra AI preset: Real-ESRGAN Plus, RIFE x2, 2160p output, gamma 1.07, saturation 1.14.
- Existing face-follow crop, audio-derived captions, color adjustment and selected aspect ratio run before the Video2X stage.
- A 4K request uses an intermediate suited to 2x upscaling; Video2X may take significant GPU time and memory.
- If Video2X CLI is absent, the selected AI mode produces a clear error, never a false AI-enhanced export. Non-AI exports remain available.
- This integrates the executable by invoking its documented CLI; it does not include the Video2X GUI.
- Video2X is separately licensed under AGPL-3.0; check licensing obligations before bundling or distributing it.

### Limitations

- The filter/caption pass is encoded first, then Video2X enhances/interpolates the finished frames; it does not independently track speakers or improve speech transcription.
- RIFE multiplies **source FPS** (for example 24=>48 or 30=>60). If you explicitly select 60 FPS after RIFE 2x on 24 FPS, an extra normalization pass may duplicate frames.
- Video2X may create temporal artifacts on cuts, complex faces and fast action. Use a short sample before a full export.
- Only a CLI syntax + test suite has run in GitHub CI; no Vulkan GPU rendering benchmark has been performed here.

## Limitations and quality

- HDRezka integration uses the unofficial HdRezkaApi provider for metadata and available streams. The provider may block requests or lack access to the selected item. We have not verified live downloading from hdrezka.rest.
- The 4K option uses Lanczos and CRF-16 H.264 by default. If Video2X Real-ESRGAN is selected and installed, the export additionally applies neural upscaling; neither route can guarantee authentic recovered source detail.
- Face tracking uses OpenCV Haar frontal-face detection with smoothed crop coordinates. Hard cuts, profiles and group shots can cause the crop to lag or choose the wrong person.
- Subtitles come from the actual audio using local Faster-Whisper (small model, word timestamps). Their accuracy depends on dialogue and background noise; first run may download a speech model.
- Optional optical flow to 60 FPS can be very slow and may introduce motion artifacts.
- Initial feature scope is one manually selected scene per render. Automatic semantic highlights, queues and speaker identification are not yet implemented.
- Only process content you have rights to download and edit. The tool does not circumvent DRM, authentication or paywalls.

## Face tracking and transcription error recovery

- When OpenCV lacks its standard haarcascade_frontalface_default.xml, Film Studio
  automatically fetches the *exact* official OpenCV 4.10.0 XML from
  `opencv/opencv/data/haarcascades` and verifies its pinned Git blob hash
  before caching it under output/film_models/.
- If the download fails (offline/network blocked), the console explains why and
  the current render uses center crop, not misleadingly claiming face tracking.
  For an offline install, restore the official cascade by reinstalling a compatible
  `opencv-python` package into the project's .venv.
- If CUDA runtime reports cublas64_12.dll missing during Whisper initialization,
  transcription or lazy segment processing, the AI tries CPU int8 and continues
  with spoken subtitles. It doesn't require reinstalling NVIDIA drivers to proceed.
- To force reliable CPU speech transcription on Windows, launch from PowerShell:

```powershell
$env:FILM_WHISPER_DEVICE = "cpu"
.\start-web.bat
```

- CPU speech recognition may be slower than a properly configured NVIDIA CUDA
  environment. This setting only affects speech recognition; Video2X can still
  use the Vulkan GPU for upscaling and RIFE.

## Troubleshooting

Ensure yt-dlp, HdRezkaApi, faster-whisper and OpenCV are installed in the same Python .venv used by the Node server.
Ensure FFmpeg has the libass/subtitles filter. If the provider blocks the film URL, use the local upload.
Test 1080p at source FPS first, then enable optional 2160p and optical flow.