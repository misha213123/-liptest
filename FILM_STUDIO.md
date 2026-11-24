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

- Upscale: off, Real-ESRGAN Plus (4x), AnimeVideo v3 (2x), or Anime4K v4 A+A.
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

## Video2X Real-ESRGAN Plus 4x fix (November 2026)

Video2X 6.4.0 contains `models/realesrgan/realesrgan-plus-x4.param`
and `realesrgan-plus-x4.bin`, **not** `realesrgan-plus-x2`.
The adapter now selects the packaged model's native factor, prepares a
proportionally smaller video for requested 4K output, runs Video2X
with its models directory as the working directory, and checks model
assets **before** starting the expensive FFmpeg/video render.

If a model is missing from an incomplete installation, reinstall the
**full official Video2X CLI ZIP** using:

```powershell
cd "$HOME\Desktop\auto-clipper-v2"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-video2x.ps1
```

The official v6.4.0 archive does not include `realesr-generalv3`,
so this unsupported option is not offered by the UI in this release.
These changes fix CLI model lookup and scale selection; actual neural
processing still depends on the local Vulkan driver and available GPU memory.

## Stop stuck Video2X jobs safely (Windows)

Film Studio has an **Stop render and Video2X** button for active jobs.
It calls the local-only `/api/film/render/cancel` endpoint, which uses
Windows `taskkill /PID <Film Python renderer PID> /T /F` to terminate the
renderer and all its FFmpeg/Video2X descendants without deleting the original
downloaded input. Shutdown via Ctrl+C also attempts to terminate the film job.

If old orphaned Video2X processes were created by earlier versions, inspect:

```powershell
Get-CimInstance Win32_Process -Filter "name = 'video2x.exe'" |
  Select-Object ProcessId,ParentProcessId,CommandLine
```

After confirming these are stale Auto Clipper jobs, stop **only their PIDs**.
Do not use `Stop-Process -Name video2x -Force` if another independent Video2X
task is running.

A zero-byte MP4 may remain on disk until FFmpeg writes its final index;
do not infer a GPU hang from the MP4's size alone. With Windows WDDM and Vulkan,
`nvidia-smi` also might not accurately show all GPU work. For GTX 1650 4GB,
first test a 3-5 second clip with Real-ESRGAN Plus at 1080p and RIFE disabled;
if it completes, test RIFE separately.

## Visual editor updates: thumbnails, real filters, styled captions, face motion

- **Five caption templates** under Film Studio Step 2: Bold Reels, Word Karaoke,
  Cinema, Minimal, and Boxed. Their appearance is rendered into the MP4 with
  the ASS subtitles generator. Karaoke synchronizes highlighted words using
  Faster-Whisper word timestamps. Caption vertical position is adjustable.
- **Six real color grade presets** under Step 3: Natural, Vibrant, Bright,
  Cinema, Warm and Cool. They control gamma, brightness, contrast, saturation
  and optional FFmpeg colorbalance. The same filter module is used for JPEG
  thumbnails and finished video.
- **Show Scene Thumbnail** now reads one frame from a locally imported source
  and applies actual crop, face-follow detection and color correction. The
  example caption overlay demonstrates styling; actual timed text is only
  known after speech recognition.
- At the Video2X stage, the right preview can show `film_prepared.mp4` — the
  completed FFmpeg intermediate with face crop, color and genuine subtitles.
  It is *not yet the AI-upscaled result*. The final player switches to
  `final.mp4` after successful processing.
- Face tracking now detects twice per second, follows between detections using
  Lucas-Kanade optical flow and resets tracking after scene cuts. This improves
  continuity but does not yet identify the speaking character through audio
  or guarantee robust face tracking in every film scene.
- If Video2X has no reported progress and does not write output for a
  configurable idle period (default **240 seconds**), Auto Clipper stops
  the AI step and exports a **usable standard FFmpeg MP4** instead of leaving
  the project at 72%. A warning makes clear that no AI upscaling / RIFE was
  applied in this fallback. The idle threshold can be changed before
  launching with `FILM_VIDEO2X_IDLE_TIMEOUT`.
- GitHub CI tests syntax and formatting logic. A successful actual GPU
  4K/60 FPS result still requires a Windows Vulkan test on the real hardware.

## Thumbnail reliability fix

The Film Studio preview now:
- Maintains exact aspect ratios without cropping the displayed JPG again
  (`object-fit: contain` and responsive dimensions).
- Defaults to a frame **halfway through the selected scene** instead of near
  the start, which often shows a black film cut.
- Exposes a frame-position slider (5–95%) and earlier/later buttons.
  This only selects the preview still, not the scene's actual trimming times.
- Pre-renders face detection to the requested still-frame position.
- Sends the verified JPEG inline to the local browser, avoiding a
  second HTTP fetch that could leave an empty/white image.
- Shows an explicit image-loading error rather than reporting success before
  the browser has decoded the picture.
- Saves the most recent locally imported source ID in browser localStorage
  so a page refresh can restore its thumbnail without reuploading.
- Exposes the preview's timestamp and whether a face was found.

Preview clips are generated using the normal FFmpeg color filters,
but AI super-resolution and actual timed subtitles still require a render.

## Dialogue alignment, actor focus and color comparison (2026-11-24)

- Faster-Whisper defaults to the **medium** model with **Russian** selected.
  Select English or Auto if the source audio is in another language.
  This can improve transcription quality but does not guarantee perfect words.
- Speech VAD removal is disabled on short movie clips to preserve timestamps
  across dialogue and silence. Automatic word timestamps are still approximate.
- Subtitle offset slider: **negative = show earlier**, **positive = show later**;
  adjusts every ASS cue (including karaoke word highlights) by up to 2 seconds
  without modifying the original audio. Rendering is required to apply changes.
- ASS timestamps are rounded to integer centiseconds instead of truncating a
  floating-point timestamp (e.g., 1.20 seconds previously sometimes became 1.19).
- Face tracking also tries the officially pinned OpenCV profile cascade. Choose
  Auto / Left / Center / Right when several actors share a shot. This is
  spatial character selection, **not speaker diarization or lip-sync detection**.
- The **Ultra · сочный** color preset provides a visible gamma/brightness/
  contrast/saturation increase. The preview has **Before / After** buttons
  showing two actual FFmpeg-generated frames with identical cropping.
  Neither color preset nor upscaling reconstructs a native 4K source.
- Movie dialogue with background music and overlapping speakers can still
  require manual subtitle corrections. To check improvements, render 5–10
  seconds with Video2X disabled first, then enable neural enhancement only
  once frame selection and text timing are correct.

## Optional OpenAI cloud subtitles with word timestamps

Film Studio > Step 2 > **Speech recognition** now offers:

- **Local Faster-Whisper**: on-device, no OpenAI charges.
- **OpenAI Cloud**: transcribe just the selected audio excerpt via the official OpenAI Audio Transcriptions API, returning word timestamps in the existing ASS subtitle renderer.
- The UI status shows only whether an API key is configured and where it was found; never the key value. The selected mode is passed in the local render payload as `speech_engine`, not the credential.
- Selecting OpenAI incurs separate API usage fees. The app does not make a paid API call merely to display key status. Speech audio is sent to OpenAI only if OpenAI is explicitly selected and a render is started.

**Important migration note:** At the time of this integration, the recommended `gpt-transcribe` model returns a transcript, but **word-level timestamps** for edited captions are still documented only for `whisper-1`. We use `whisper-1` with `response_format="verbose_json"` and `timestamp_granularities=["word"]`. This legacy model is scheduled to shut down on **2027-02-26**. Once a supported new word-timing model becomes available, the adapter must migrate. Do not assume support after that date.

Official docs: https://developers.openai.com/api/docs/guides/speech-to-text

### Key configuration (local Windows only)

The adapter accepts `OPENAI_API_KEY` from the environment. It also reuses a key already present in local `config.json` under `ai_providers.caption_maker.openai_api_key`, `openai_api_key`, or a clearly identified **official OpenAI API** provider entry. It deliberately ignores keys for OpenRouter/other services.

If the OpenAI status indicator reports **not configured**, launch the server with a key in your current PowerShell session. Avoid putting the key into command history or GitHub:

```powershell
cd "$HOME\Desktop\auto-clipper-v2"
$secret = Read-Host 'OpenAI API key' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try { $env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
.\start-web.bat
```

The key remains in that shell's environment until the shell closes. Do **not** enter a key in chat or commit it to Git. The key is not stored in Film Studio job JSON, URL, UI, or render log.

### Audio / reliability

- The module extracts only the user's selected ≤5-minute scene as 16 kHz mono WAV. Such a WAV is under the current 25 MB limit; we explicitly cap upload at 24 MiB.
- The OpenAI response is converted into Whisper-compatible `words` objects and uses the same bold/karaoke/cinema/minimal/boxed ASS styles, offset controls and final MP4 path.
- Word timestamps are model estimates. Incorrect dialogue, music, overlapping speakers and translation mismatches may still need manual review; OpenAI cloud is not a guarantee of lip-synced words.
- Authentication/rate-limit/network errors show sanitized messages, without tokens. There is no silent fallback that would misrepresent a locally generated transcript as OpenAI output.
- Subtitle requests require an active OpenAI API account and may incur charges. ChatGPT Plus is separate from API billing.

## OpenAI maximum subtitle accuracy — GPT-Transcribe + Whisper-1

The **OpenAI МАКСИМУМ** option is now selected by default in the Film Studio
speech engine selector. This mode is specifically designed for movie dialogue:

1. Send the selected audio excerpt to `gpt-transcribe`, OpenAI's currently
   recommended high-accuracy file transcription model. Use a language hint
   (`languages`) and a verbatim dialogue prompt when Russian or English is chosen.
2. Send the same excerpt separately to `whisper-1` with
   `response_format="verbose_json"` and `timestamp_granularities=["word"]`.
3. Align GPT text conservatively to word intervals from Whisper-1.
   Matched words keep GPT spelling/punctuation; one-to-one corrections can
   replace individual words. Insertions/deletions that lack trustworthy times
   **retain the original timed Whisper text** — the program never invents
   precise timestamps. This is not an audio-based forced aligner.
4. Export the aligned words using the selected ASS subtitle template and
   optional global timing offset.

**Billing and privacy:** This mode sends the short scene audio to OpenAI
**twice** and makes **two separately chargeable API calls**. No calls are
made by merely opening Film Studio. The API key stays in the local server
environment or config; it is never committed or sent to the browser.
OpenAI's `whisper-1` model is scheduled for retirement on 2027-02-26.
After that date, word alignment requires an alternative timing provider.

Two alternative modes remain in the selector: `OpenAI Whisper-1` (one paid
word-timed request) and local Faster-Whisper (no OpenAI API charges).
Note: GPT-Transcribe itself does not currently return per-word timestamps.
Even with maximum quality, exact word/voice sync may need corrections.

## Topaz-style manual video enhancement (FFmpeg equivalents)

Film Studio > Quality & Export now has a separate **manual restoration**
panel, inspired by Topaz Video's enhancement workflow but implemented
with open FFmpeg filters, not Topaz's commercial models.

| UI control | Actual processing |
|---|---|
| Compressed-block artifact reduction | `deblock` (strong mode; bounded thresholds) |
| Denoise | `hqdn3d` spatial/temporal luma/chroma suppression |
| Microdetail / local contrast | Fine-radius `unsharp` (3x3) |
| Sharpen | Edge sharpening via `unsharp` (5x5) |
| Film grain | Deliberate fine `noise` (temporal/uniform) |
| Gamma, saturation, brightness and contrast | `eq`, `colorbalance` |
| Frame rate increase | `minterpolate` FFmpeg optical flow or optional RIFE |

Each parameter is a constrained 0–100 slider, shared between the
real JPEG **Before/After** frame and actual MP4 export. Four built-in
restoration profiles are provided: Balanced, Clean source, Detail and
Film grain. Moving any slider enables manual mode. Color correction
must remain checked in Film Studio to apply restoration filters.

No slider performs proprietary Topaz Proteus, Iris, Starlight or
Chronos inference. The maximum detail depends on the original video.
For GTX 1650 (4 GB), prefer 1080p + FFmpeg optical flow 60 FPS first,
and try Video2X separately on a short clip. The Video2X watchdog now
checks stalled work even if the CLI keeps printing unrelated logs;
after an idle timeout the pipeline exports a usable FFmpeg MP4
instead of waiting at 72% indefinitely.

## Automatic best-moment search in an entire episode

Film Studio now includes **AI-поиск лучших моментов серии**, immediately
after the source importer and before the clip editor.

1. Import a local MP4 (or download/import one episode through the existing
   source workflow). Select **2–12** highlights and a clip length range
   (e.g. **18–55 seconds**), then explicitly click
   **Найти интересные моменты автоматически**.
2. The background Python job uses ffprobe to validate the whole episode
   (8 seconds to **2 hours**) and extracts only 16k mono audio chunks of
   **7 minutes** (<24 MiB). It uses the user's configured OpenAI key,
   transcribes audio with **whisper-1 word timestamps**, then uses
   **gpt-4.1** to suggest and score emotionally strong scenes, jokes,
   conflict, reveals, memorable dialogue, etc.
3. Chat outputs undergo strict numerical validation: source-relative
   start/end range, selected clip length, presence of actual speech and
   overlap suppression. Ratings are editorial **AI estimates** out of
   100, not objectively measured virality.
4. Selected highlights appear as ranked cards with titles, summaries,
   time range and one-click **Выбрать для рендера**, which fills the
   existing start/end editor and generates a thumbnail. For an imported
   episode there is also **Смотреть сцену** using browser-range playback
   from the local source; MKV/container support depends on the browser.
5. After selecting a highlight, continue using normal Film Studio
   captions, face tracking, color grading, frame interpolation and MP4
   export. This automatically transfers scene boundaries but does not
   launch a GPU render until the user clicks Render.

**Privacy, cost and reliability:** The service is opt-in and uploads
episode **audio and transcript**, not full video, to OpenAI. This is
paid API usage, separate from ChatGPT Plus; for a full TV episode there
may be multiple transcription requests plus several ranking calls.
The API key stays on the server, never in the HTML/JSON jobs. Transcripts
and AI results are cached locally under `output/film_highlights`, with
the source file size, mtime and language in the cache fingerprint, to
avoid paying again on unchanged source material. Progress is visible
in the UI; cancellation terminates the child process tree on Windows.
The scene finder is **dialogue-based**: silent fights/action, cinematography,
silent reaction shots and music-only moments are not visually assessed
and might be missed. User should inspect proposed scenes before export.
Do not analyze content without the right to do so.

## Adjustable clean subtitles and Video2X first-byte watchdog

Film Studio now has two subtitle controls in the styles section:

- **Words per caption:** 1 through 8, default 3. Unlike the old
  implementation which grouped inside each 3-word Whisper segment,
  the generator now merges consecutive word timestamps *across* segment
  boundaries to honor larger limits. Natural pauses >= 0.9 seconds
  and groups longer than ~4 seconds split automatically to avoid long
  static captions; word timing remains grounded to the source audio.
- **Без знаков препинания** (checked by default): removes commas,
  full stops, exclamation/question marks, quotes and other surrounding
  punctuation, while preserving internal lexical hyphens in words
  like `кто-то`. This changes the real ASS file burned into MP4,
  not just the demo screenshot. Disabling restores punctuation.
- **Cloud speech transcript cache:** recognized word timings and words
  are cached at `output/film_transcripts` by source file fingerprint,
  selected start/end, engine/model and audio language. Re-rendering the
  same source and times with different ASS styles, punctuation or word
  grouping reuses the transcript *without paying for OpenAI speech
  transcription again*. Changing selected excerpt, language or engine
  triggers a new recognition request. Stored transcriptions contain
  dialogue text locally and can be deleted by the user.

**Stuck Video2X:** Continuous CLI percentages or heartbeats cannot
demonstrate that the encoder produced any frames. The previous
idle watchdog could remain active indefinitely because text containing
a percentage reset the timer. The new default behavior has:
- `FILM_VIDEO2X_FIRST_BYTE_TIMEOUT=180`: if no output MP4 bytes are
  written by then, terminate Video2X and descendants and save the
  prepared FFmpeg clip without AI upscaling.
- `FILM_VIDEO2X_IDLE_TIMEOUT=240`: terminate if neither output size
  nor genuinely higher reported progress advances for this long.

These checks are safety fallbacks, not a guarantee that Real-ESRGAN
works on GTX 1650 4GB. The MP4 produced without Video2X still contains
selected crop, real captions, color, sound and FFmpeg motion interpolation
where enabled. If heavy AI is required, diagnose Video2X separately
after a short 3–5 second sample; avoid re-running a full movie scene
until it completes.

## Drag-and-resize subtitles and advanced color grading

- **Caption size** is now an actual ASS export scale from **30–180%**, controlled by a slider (100% default). Stroke and shadow scale with it.
- **Move subtitles on the preview** by dragging the sample text up or down on the thumbnail. The label/position slider updates immediately (10–95% from top), and the resulting bottom ASS alignment/margin uses that value. This works on a loaded thumbnail; while showing an already burned MP4, click **Обновить кадр с фильтрами** to switch back to the editable thumbnail. Use Arrow Up/Down with keyboard focus for accessible fine tuning.
- **Caption letter case:** lowercase by default for every template, including Karaoke (no random sentence-initial caps), with options to preserve original ASR spelling or force uppercase. Letter case, font size, punctuation and word grouping are all applied to the **real exported MP4**, not only the sample overlay.
- **Pro color controls** increase the limits: gamma 0.60–1.60, saturation 0.50–2.50, contrast 0.50–1.80, brightness -0.20–0.25. **Выкрутить фильтры на MAX** applies intentionally very aggressive values; compare before/after because strong settings can clip highlights and make actors' skin tones unnatural. **Вернуть плавный пресет** restores the stable 60fps option.

## Optional AI Detail Restore (true neural inference, not Topaz)

Film Studio now has an **AI Detail Restore** checkbox, separate from the
existing (sometimes-stalling) Video2X 6.x mode. It uses the official
**Real-ESRGAN NCNN-Vulkan** portable application with 64-pixel tiles and
single worker threads for compatibility with GTX 1650 4GB. Click the
**Установить нейросеть на компьютер** button once; the installer downloads
the official pinned portable Windows package from:
https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip

Installation also has a manual local script:
`powershell -ExecutionPolicy Bypass -File .\scripts\install-ai-detail-restore.ps1`.
No model executables are committed to your GitHub repository. The installer
downloads third-party program files only after the user explicitly requests
installation in the UI. Keep GPU drivers up to date.

- Render a short **5-second test** before larger scenes. AI mode supports
  **1080p and clips up to 30 seconds** and keeps actual 60fps interpolation.
- Prepared graded/captioned video is resized to the **actual source crop**
  (e.g. 404x720 or 900x720 from a 720p episode), not blindly halved,
  to avoid discarding existing detail. Very large source crops are bounded to
  about 720p for 4GB GPU compatibility. The model runs at 2x output, and
  FFmpeg then resamples the result to the requested 1080p dimensions with
  original audio copied from the prepared clip.
- Neural inference can introduce **artificial texture, flickering between
  frames or distort already rendered subtitles**: it is not video-temporal
  restoration, does not guarantee preserving the original true detail and
  cannot promise the quality of Topaz Proteus/Iris.
- If the process crashes, fails to produce frames or stalls for 180 seconds,
  Film Studio stops the subprocess tree, cleans up the large PNG frame files
  and exports the original prepared MP4. An explicit warning identifies that
  the neural pass did **not** complete.
- **Video2X and AI Detail Restore cannot both be selected** in one render.
  The default smooth/vivid color preset does *not* enable neural inference;
  it continues working as before.

## Troubleshooting

Ensure yt-dlp, HdRezkaApi, faster-whisper and OpenCV are installed in the same Python .venv used by the Node server.
Ensure FFmpeg has the libass/subtitles filter. If the provider blocks the film URL, use the local upload.
Test 1080p at source FPS first, then enable optional 2160p and optical flow.