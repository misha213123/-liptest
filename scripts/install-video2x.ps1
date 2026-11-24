# Install the official Video2X 6.x command-line release for Film & Series Studio.
# Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File .\scripts\install-video2x.ps1
#
# Official CLI docs: https://docs.video2x.org/installing/windows.html
# This script does not modify the project or package third-party binaries.
$ErrorActionPreference = 'Stop'

$repo = 'https://api.github.com/repos/k4yt3x/video2x/releases/latest'
Write-Host 'Video2X: проверяю официальный релиз GitHub...' -ForegroundColor Cyan
$headers = @{ 'User-Agent' = 'AutoClipper-Video2X-Installer'; 'Accept' = 'application/vnd.github+json' }
$release = Invoke-RestMethod -Uri $repo -Headers $headers
$asset = $release.assets | Where-Object { $_.name -eq 'video2x-windows-amd64.zip' } | Select-Object -First 1
if (-not $asset) {
    throw ('Официальный архив CLI не найден в релизе ' + $release.tag_name + '. Проверь https://github.com/k4yt3x/video2x/releases')
}
if ($asset.browser_download_url -notmatch '^https://github\.com/k4yt3x/video2x/releases/download/') {
    throw 'Адрес архива не соответствует официальным релизам.'
}

$archive = Join-Path $env:TEMP 'auto-clipper-video2x-windows-amd64.zip'
$install = Join-Path $env:LOCALAPPDATA 'Programs\video2x'
Write-Host ('Скачиваю Video2X CLI ' + $release.tag_name + '...') -ForegroundColor Cyan
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archive -UseBasicParsing
if (-not (Test-Path $archive) -or (Get-Item $archive).Length -lt 1000000) {
    throw 'Архив Video2X не скачался полностью.'
}

if ($asset.digest -and $asset.digest -match '^sha256:([A-Fa-f0-9]{64})$') {
    $expected = $Matches[1].ToLowerInvariant()
    $actual = (Get-FileHash -Path $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw 'SHA256 архива Video2X не совпадает с данными релиза GitHub.'
    }
    Write-Host 'Проверка SHA256 пройдена.'
}

New-Item -ItemType Directory -Path $install -Force | Out-Null
Expand-Archive -Path $archive -DestinationPath $install -Force
$exe = Join-Path $install 'video2x.exe'
if (-not (Test-Path $exe)) {
    throw ('Не найден video2x.exe в ' + $install + '. Проверь структуру официального ZIP.')
}

$env:VIDEO2X_BIN = $exe
[Environment]::SetEnvironmentVariable('VIDEO2X_BIN', $exe, 'User')
Write-Host ('Установлено: ' + $exe) -ForegroundColor Green
& $exe --version
if ($LASTEXITCODE -ne 0) {
    throw 'Video2X не запустился. Проверь драйвер Vulkan и Microsoft Visual C++ Runtime.'
}
Write-Host 'Video2X готов. Можно запускать .\start-web.bat и включать AI Ultra.' -ForegroundColor Green
