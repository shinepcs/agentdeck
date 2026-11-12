$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDir '.venv\Scripts\python.exe'
$dashboardPath = Join-Path $projectDir 'dashboard.py'
Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -eq $pythonPath -and $_.CommandLine -like "*$dashboardPath*"
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId
    Write-Output "Agentdeck stopped (PID $($_.ProcessId))."
}
