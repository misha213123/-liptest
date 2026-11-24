# Optional Real-ESRGAN NCNN-Vulkan portable installer (Windows PowerShell 5.1).
# Source: xinntao/Real-ESRGAN official tagged Windows executable release.
# Downloads outside GitHub repository and does not require API keys.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$url = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip'
$target = Join-Path $env:LOCALAPPDATA 'Programs\realesrgan-ncnn-vulkan'
$exe = Join-Path $target 'realesrgan-ncnn-vulkan.exe'
$modelDir = Join-Path $target 'models'
$required = @(
  'realesrgan-x4plus.param', 'realesrgan-x4plus.bin',
  'realesrnet-x4plus.param', 'realesrnet-x4plus.bin'
)
$complete = Test-Path -LiteralPath $exe
foreach ($name in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $modelDir $name))) {
        $complete = $false
    }
}
if ($complete) {
    Write-Host 'Real-ESRGAN NCNN is fully installed:'
    Write-Host $exe
    exit 0
}
$tempRoot = Join-Path $env:TEMP ('film-ai-detail-' + [guid]::NewGuid().ToString('N'))
$archive = Join-Path $tempRoot 'realesrgan.zip'
$extract = Join-Path $tempRoot 'package'
New-Item -ItemType Directory -Force -Path $tempRoot, $extract | Out-Null
try {
    Write-Host 'Downloading original Real-ESRGAN NCNN Vulkan binary from official xinntao release...'
    Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing
    Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force
    $binary = Get-ChildItem -LiteralPath $extract -Filter 'realesrgan-ncnn-vulkan.exe' -File -Recurse |
      Select-Object -First 1
    if ($null -eq $binary) {
        throw 'Installer package does not contain realesrgan-ncnn-vulkan.exe'
    }
    $root = $binary.Directory.FullName
    $models = Join-Path $root 'models'
    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $models $name))) {
            throw ('Installer package is missing required neural model: ' + $name)
        }
    }
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Copy-Item -Path (Join-Path $root '*') -Destination $target -Recurse -Force
    if (-not (Test-Path -LiteralPath $exe)) {
        throw 'Real-ESRGAN executable was not copied'
    }
    Write-Host 'Real-ESRGAN NCNN Vulkan installed:'
    Write-Host $exe
    Write-Host 'Return to Film Studio and choose AI Detail Restore. Use a 5-second test clip first.'
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
