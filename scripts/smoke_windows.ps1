param(
  [Parameter(Mandatory=$true)][string]$ExePath
)
$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path $ExePath).Path
$env:MUSE_PORT = '18875'
$env:MUSE_DATA_DIR = Join-Path $env:TEMP 'MuseMultiStudio-CISmoke'
$startupLog = Join-Path $env:MUSE_DATA_DIR 'startup-error.log'
New-Item -ItemType Directory -Path $env:MUSE_DATA_DIR -Force | Out-Null
Remove-Item -Path $startupLog -Force -ErrorAction SilentlyContinue
$url = 'http://127.0.0.1:18875/api/health'
$process = $null
try {
  $process = Start-Process -FilePath $exe -ArgumentList '--server-only' -PassThru -WindowStyle Hidden
  $success = $false
  for ($i=0; $i -lt 50; $i++) {
    if ($process.HasExited) { throw "EXE exited early with code $($process.ExitCode)" }
    if (Test-Path $startupLog) { throw 'EXE startup exception detected' }
    try {
      $result = Invoke-RestMethod -Uri $url -TimeoutSec 2 -NoProxy
      if ($result.status -eq 'ok' -and $result.version -eq '0.2.0') {
        $success = $true
        break
      }
    } catch {
      Start-Sleep -Milliseconds 350
    }
  }
  if (-not $success) { throw 'Windows EXE failed backend health smoke test' }
  Write-Host 'PASS: Windows EXE starts; backend health reports v0.2.0'
} finally {
  if (Test-Path $startupLog) {
    Write-Host '=== Captured EXE startup error ==='
    Get-Content $startupLog | ForEach-Object { Write-Host $_ }
  }
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
  }
}
