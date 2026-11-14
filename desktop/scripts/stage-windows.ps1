# Stage self-contained Windows dependencies for Electron-builder.
# Run on a Windows GitHub Actions runner with Python 3.11 installed by setup-python.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtime = Join-Path $repo 'desktop\runtime'
$pyHome = Join-Path $runtime 'python'
$pyPackages = Join-Path $pyHome 'Lib\site-packages'
$ffHome = Join-Path $runtime 'ffmpeg'
$binHome = Join-Path $runtime 'bin'
New-Item -Force -ItemType Directory $pyHome,$pyPackages,$ffHome,$binHome | Out-Null

function Download([string]$url, [string]$filename) {
  Write-Host "Downloading $url"
  Invoke-WebRequest -Uri $url -OutFile $filename -MaximumRedirection 10
  if (-not (Test-Path $filename) -or (Get-Item $filename).Length -eq 0) {
    throw "Download failed: $url"
  }
}

# Official CPython embeddable distribution is relocatable and doesn't depend on host Python.
$pythonArchive = Join-Path $env:RUNNER_TEMP 'python-3.11.9-embed-amd64.zip'
Download 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' $pythonArchive
Expand-Archive -Path $pythonArchive -DestinationPath $pyHome -Force
@'
python311.zip
.
Lib
Lib\site-packages
import site
'@ | Set-Content -Encoding ascii -Path (Join-Path $pyHome 'python311._pth')

# Use setup-python's pip to install Windows wheels for this ABI into embedded Python.
python -m pip install --upgrade pip
python -m pip install --no-warn-script-location --target $pyPackages -r (Join-Path $repo 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Failed to resolve Python runtime dependencies' }

# FFmpeg release with h264_nvenc / h264_amf / ffprobe where supported by drivers.
$ffArchive = Join-Path $env:RUNNER_TEMP 'ffmpeg-windows.zip'
Download 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip' $ffArchive
$extract = Join-Path $env:RUNNER_TEMP 'ffmpeg-extracted'
Expand-Archive -Path $ffArchive -DestinationPath $extract -Force
foreach ($name in @('ffmpeg.exe', 'ffprobe.exe')) {
  $source = Get-ChildItem $extract -Recurse -File -Filter $name | Select-Object -First 1
  if (-not $source) { throw "Missing $name in FFmpeg archive" }
  Copy-Item -Force $source.FullName (Join-Path $ffHome $name)
}

$denoArchive = Join-Path $env:RUNNER_TEMP 'deno-windows.zip'
Download 'https://github.com/denoland/deno/releases/download/v2.6.7/deno-x86_64-pc-windows-msvc.zip' $denoArchive
Expand-Archive -Path $denoArchive -DestinationPath $binHome -Force

# Face landmarker data is needed for automatic portrait tracking.
Download 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task' (Join-Path $binHome 'face_landmarker.task')

Write-Host 'Validating embedded Python & video programs...'
& (Join-Path $pyHome 'python.exe') -c 'import sys, cv2, numpy, mediapipe, yt_dlp, faster_whisper, openai; print(sys.version); print("Core Python imports ready")'
if ($LASTEXITCODE -ne 0) { throw 'Embedded Python imports failed' }
& (Join-Path $ffHome 'ffmpeg.exe') -hide_banner -version
if ($LASTEXITCODE -ne 0) { throw 'FFmpeg check failed' }
& (Join-Path $binHome 'deno.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'Deno check failed' }
Write-Host 'Windows media runtime staged successfully.'
