$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Port = 8000

Set-Location $ProjectRoot
$env:PYTHONPATH = $ProjectRoot
$listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
  $processId = $listener.OwningProcess
  if ($processId -and $processId -ne $PID) {
    Write-Host "Stopping old server on port 8000, PID $processId"
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
  }
}
$listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
  Write-Host "Port 8000 is still busy. Starting MovieRec on 8001 instead."
  $Port = 8001
}
$env:MOVIEREC_PORT = [string]$Port
Write-Host "MovieRec root: $ProjectRoot"
Write-Host "Python: $Python"
Write-Host "MovieRec URL: http://127.0.0.1:$Port"
Write-Host "Backend module check:"
& $Python -c "import backend.app as app; print(app.__file__); print(app.APP_VERSION)"
& $Python -m backend.app
