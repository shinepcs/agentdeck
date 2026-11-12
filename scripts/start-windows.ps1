$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDir '.venv\Scripts\python.exe'
$dashboardPath = Join-Path $projectDir 'dashboard.py'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install requirements.txt first. See docs/WINDOWS-MIRABOX.md.'
}
$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -eq $pythonPath -and $_.CommandLine -like "*$dashboardPath*"
}
if ($existing) {
    Write-Output "Agentdeck already running (PID $($existing.ProcessId -join ', '))."
    exit 0
}
$process = Start-Process -FilePath $pythonPath -ArgumentList @('-X', 'utf8', '-u', "`"$dashboardPath`"") `
    -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $projectDir 'dashboard.log') `
    -RedirectStandardError (Join-Path $projectDir 'dashboard-error.log')
Start-Sleep -Seconds 2
$process.Refresh()
if ($process.HasExited) {
    throw "Agentdeck stopped. Check $projectDir\dashboard-error.log and dashboard.log."
}
Write-Output "Agentdeck started (PID $($process.Id))."
