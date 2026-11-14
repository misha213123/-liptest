# Verify that bundled runtimes work through the existing Node HTTP endpoints on Windows.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$env:CLIPPER_PY = Join-Path $root 'desktop\runtime\python\python.exe'
$env:PATH = (Join-Path $root 'desktop\runtime\ffmpeg') + ';' +
  (Join-Path $root 'desktop\runtime\bin') + ';' + $env:PATH
$env:CLIPPER_DESKTOP = '1'
$env:PORT = '31894'
$server = Start-Process -FilePath 'node.exe' -ArgumentList (Join-Path $root 'webjs\server.js') -PassThru -WindowStyle Hidden
try {
  Start-Sleep -Seconds 3
  $disk = Invoke-RestMethod 'http://127.0.0.1:31894/api/disk'
  if ($disk.error -or $disk.total -le 0 -or $disk.free -le 0) {
    throw ('Windows disk endpoint returned invalid values: ' + ($disk | ConvertTo-Json -Compress))
  }
  $binaries = Invoke-RestMethod 'http://127.0.0.1:31894/api/binaries'
  foreach ($name in @('ffmpeg','deno','yt-dlp')) {
    $component = $binaries | Where-Object { $_.name -eq $name } | Select-Object -First 1
    if (-not $component -or -not $component.ok) { throw "Dependency health check failed: $name" }
  }
  Write-Host ('Disk: ' + ($disk | ConvertTo-Json -Compress))
  Write-Host ('Dependencies: ' + ($binaries | ConvertTo-Json -Compress))
} finally {
  if ($server) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
}
