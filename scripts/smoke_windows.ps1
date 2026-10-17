param(
  [Parameter(Mandatory=$true)][string]$ExePath
)
$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path $ExePath).Path
$env:MUSE_PORT = '18875'
$env:MUSE_DATA_DIR = Join-Path $env:TEMP 'MuseMultiStudio-CISmoke'
$url='http://127.0.0.1:18875/api/health'
$process=$null
try {
  $process=Start-Process -FilePath $exe -ArgumentList '--server-only' -PassThru -WindowStyle Hidden
  $success=$false
  for($i=0; $i -lt 50; $i++) {
    if($process.HasExited) { throw "Windows EXE exited prematurely, code $($process.ExitCode)" }
    try {
      $result=Invoke-RestMethod -Uri $url -TimeoutSec 2
      if($result.status -eq 'ok' -and $result.version -eq '0.2.0') {
        $success=$true; break
      }
    } catch { Start-Sleep -Milliseconds 350 }
  }
  if(-not $success) { throw 'Windows EXE failed backend /api/health smoke test' }
  Write-Host 'PASS: Windows EXE starts and backend health reports v0.2.0'
} finally {
  if($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
}
