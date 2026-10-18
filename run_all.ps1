Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "LAUNCHING AI TECH CONSULTANT" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

& "$scriptDir\.venv\Scripts\python.exe" "$scriptDir\scripts\start_services.py"
