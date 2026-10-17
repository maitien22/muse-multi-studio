param([Parameter(Mandatory=$true)][string]$ExePath)
$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path $ExePath).Path
$root = Join-Path $env:TEMP 'Muse-CI-kiểm thử-giao diện'
$env:MUSE_DATA_DIR = $root
$startupLog = Join-Path $root 'startup-error.log'
$env:MUSE_PORT = '18875'
New-Item -ItemType Directory -Path $root -Force | Out-Null
Remove-Item -Path $startupLog -Force -ErrorAction SilentlyContinue

function Print-StartupLog {
  if (Test-Path $startupLog) {
    Write-Host '=== Captured EXE startup error ==='
    Get-Content $startupLog | ForEach-Object { Write-Host $_ }
  }
}

$process = $null
try {
  $process = Start-Process -FilePath $exe -ArgumentList '--server-only' -PassThru -WindowStyle Hidden
  $ok = $false
  for ($i = 0; $i -lt 60; $i++) {
    if ($process.HasExited) { throw "EXE backend exit code: $($process.ExitCode)" }
    if (Test-Path $startupLog) { throw 'EXE backend startup error' }
    try {
      $response = Invoke-RestMethod -Uri 'http://127.0.0.1:18875/api/health' -TimeoutSec 2 -NoProxy
      if ($response.status -eq 'ok' -and $response.version -eq '0.2.1') { $ok = $true; break }
    } catch { Start-Sleep -Milliseconds 300 }
  }
  if (-not $ok) { throw 'Windows EXE backend health smoke test failed' }
  Write-Host 'PASS: Frozen Windows EXE backend /api/health v0.2.1'
} finally {
  Print-StartupLog
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    $process.WaitForExit(10000) | Out-Null
  }
}

$env:MUSE_PORT = '18876'
$env:MUSE_UI_SMOKE_PATH = Join-Path $root 'ui-smoke.png'
Remove-Item -Path $startupLog,$env:MUSE_UI_SMOKE_PATH -Force -ErrorAction SilentlyContinue
$process = $null
try {
  $process = Start-Process -FilePath $exe -ArgumentList '--ui-smoke' -PassThru -WindowStyle Hidden
  if (-not $process.WaitForExit(70000)) { throw 'Windows Chromium UI smoke test timed out' }
  if ($process.ExitCode -ne 0) { throw "Windows Chromium UI smoke test exit: $($process.ExitCode)" }
  if (Test-Path $startupLog) { throw 'EXE Chromium UI startup error' }
  if (-not (Test-Path $env:MUSE_UI_SMOKE_PATH)) { throw 'Chromium did not produce a screenshot' }
  $bytes = [System.IO.File]::ReadAllBytes($env:MUSE_UI_SMOKE_PATH)
  if ($bytes.Length -lt 1000 -or $bytes[0] -ne 137 -or $bytes[1] -ne 80) {
    throw 'Chromium screenshot is invalid PNG'
  }
  Write-Host "PASS: Chromium rendered real Muse UI ($($bytes.Length) bytes)"
} finally {
  Print-StartupLog
  if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
}
