$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDir '.venv\Scripts\python.exe'
$dashboardPath = Join-Path $projectDir 'dashboard.py'
$runnerPath = Join-Path $projectDir 'windows_runner.py'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install requirements.txt first. See docs/WINDOWS-MIRABOX.md.'
}
$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and
    ($_.CommandLine -like "*$dashboardPath*" -or $_.CommandLine -like "*$runnerPath*")
}
if ($existing) {
    Write-Output "Agentdeck already running (PID $($existing.ProcessId -join ', '))."
    exit 0
}
$process = Start-Process -FilePath $pythonPath -ArgumentList @('-X', 'utf8', '-u', "`"$runnerPath`"") `
    -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 2
$process.Refresh()
if ($process.HasExited) {
    throw "Agentdeck stopped. Check $projectDir\dashboard-error.log and dashboard.log."
}
Write-Output "Agentdeck supervisor started (PID $($process.Id)); dashboard retries every 5s if disconnected."
