# run_sector_collector.ps1
# Wrapper for Windows Task Scheduler.
# Schedule this script to run once daily (e.g. 7:00 AM on weekdays).
#
# To register the task, run once as Administrator:
#   Register-ScheduledTask -Xml (Get-Content "$PSScriptRoot\sector_collector_task.xml" -Raw) -TaskName "SectorDataCollector" -Force
#
# Or create manually in Task Scheduler:
#   Program : powershell.exe
#   Arguments: -NonInteractive -ExecutionPolicy Bypass -File "P:\OneDrive\[03] Cowork\scripts\run_sector_collector.ps1"
#   Trigger  : Daily, Mon–Fri, 7:00 AM (after market open data is available)

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ScriptDir "sector_data_collector.py"
$LogFile    = "P:\OneDrive\[03] Cowork\Sector Rotation\scheduler.log"

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"$timestamp  Starting sector data collector..." | Out-File -Append -FilePath $LogFile

try {
    $result = & python $PythonScript 2>&1
    $result | Out-File -Append -FilePath $LogFile
    "$timestamp  Completed successfully." | Out-File -Append -FilePath $LogFile
} catch {
    "$timestamp  ERROR: $_" | Out-File -Append -FilePath $LogFile
}
