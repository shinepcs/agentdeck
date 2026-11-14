$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDir '.venv\Scripts\python.exe'
$dashboardPath = Join-Path $projectDir 'dashboard.py'
$runnerPath = Join-Path $projectDir 'windows_runner.py'
$processes = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and
    ($_.CommandLine -like "*$dashboardPath*" -or $_.CommandLine -like "*$runnerPath*")
}
# Stop supervisors before their children so intentional stops cannot restart them.
$processes | Sort-Object { $_.CommandLine -notlike "*$runnerPath*" } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
    Write-Output "Agentdeck stopped (PID $($_.ProcessId))."
}
