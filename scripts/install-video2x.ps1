# Video2X 6.x CLI installer, compatible with Windows PowerShell 5.1.
# All source bytes are ASCII to avoid UTF-8-without-BOM mojibake in PowerShell 5.1.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-video2x.ps1
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$api = 'https://api.github.com/repos/k4yt3x/video2x/releases/latest'
$headers = @{
    'User-Agent' = 'AutoClipper-Video2X-Installer'
    'Accept' = 'application/vnd.github+json'
}

Write-Host 'Checking official Video2X GitHub release...' -ForegroundColor Cyan
$release = Invoke-RestMethod -Uri $api -Headers $headers
$asset = $release.assets |
    Where-Object { $_.name -eq 'video2x-windows-amd64.zip' } |
    Select-Object -First 1

if (-not $asset) {
    throw ('Official Video2X CLI ZIP not found in release ' + $release.tag_name +
        '. See https://github.com/k4yt3x/video2x/releases')
}

$downloadUrl = [string]$asset.browser_download_url
if ($downloadUrl -notmatch '^https://github\.com/k4yt3x/video2x/releases/download/') {
    throw 'Unexpected Video2X download host. Installation stopped.'
}

$archive = Join-Path $env:TEMP 'auto-clipper-video2x-windows-amd64.zip'
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\video2x'

Write-Host ('Downloading Video2X CLI ' + $release.tag_name +
    ' (' + [math]::Round($asset.size / 1MB) + ' MiB)...') -ForegroundColor Cyan
Invoke-WebRequest -Uri $downloadUrl -OutFile $archive -UseBasicParsing

if ((-not (Test-Path -LiteralPath $archive)) -or
    (Get-Item -LiteralPath $archive).Length -lt 1000000) {
    throw 'Video2X download is missing or incomplete.'
}

# Release digest is optional. Verify it when GitHub provides sha256:<64 hex>.
if ($asset.digest -and
    ([string]$asset.digest -match '^sha256:([A-Fa-f0-9]{64})$')) {
    $expected = $Matches[1].ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw 'Video2X SHA256 mismatch; installation stopped.'
    }
    Write-Host 'Video2X SHA256 verified.' -ForegroundColor Green
}

New-Item -ItemType Directory -Path $installDir -Force | Out-Null
Write-Host 'Extracting Video2X CLI...' -ForegroundColor Cyan
Expand-Archive -LiteralPath $archive -DestinationPath $installDir -Force

$exe = Get-ChildItem -LiteralPath $installDir -Filter 'video2x.exe' -File -Recurse |
    Select-Object -First 1
if (-not $exe) {
    throw ('video2x.exe not found after extracting into ' + $installDir)
}

# Save for future sessions and expose immediately to this process.
$env:VIDEO2X_BIN = $exe.FullName
[Environment]::SetEnvironmentVariable('VIDEO2X_BIN', $exe.FullName, 'User')

Write-Host ('Installed Video2X: ' + $exe.FullName) -ForegroundColor Green
& $exe.FullName --version
if ($LASTEXITCODE -ne 0) {
    throw 'Video2X did not start. Check Vulkan drivers and MSVC runtime.'
}
Write-Host 'Video2X CLI is ready. Restart Auto Clipper.' -ForegroundColor Green
