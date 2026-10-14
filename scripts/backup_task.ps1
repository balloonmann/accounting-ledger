# Windows PowerShell automated daily backup script for Household Ledger
# Suitable for execution via Windows Task Scheduler.
#
# To register this task in Windows Task Scheduler:
#   $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File C:\Users\Harshit\OneDrive\Desktop\accounting_ledger\scripts\backup_task.ps1"
#   $Trigger = New-ScheduledTaskTrigger -Daily -At 3:00AM
#   Register-ScheduledTask -TaskName "HouseholdLedgerDailyBackup" -Action $Action -Trigger $Trigger -Description "Automated daily compressed backup of Household Ledger PostgreSQL"

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BackupScript = Join-Path $ProjectRoot "scripts\backup.py"
$BackupDir = Join-Path $ProjectRoot "backups"
$LogFile = Join-Path $BackupDir "backup_task.log"

# Ensure backup directory exists
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$Timestamp] Starting scheduled automated database backup..." | Out-File -FilePath $LogFile -Append -Encoding utf8

try {
    $result = & $PythonExe $BackupScript --output-dir $BackupDir 2>&1
    $result | Out-File -FilePath $LogFile -Append -Encoding utf8

    # Retention policy: Delete backups older than 30 days
    $CutoffDate = (Get-Date).AddDays(-30)
    Get-ChildItem -Path $BackupDir -Filter "*.dump" | Where-Object { $_.LastWriteTime -lt $CutoffDate } | ForEach-Object {
        "[$Timestamp] Purging expired backup: $($_.Name)" | Out-File -FilePath $LogFile -Append -Encoding utf8
        Remove-Item $_.FullName -Force
    }

    "[$Timestamp] Automated backup task completed successfully." | Out-File -FilePath $LogFile -Append -Encoding utf8
} catch {
    "[$Timestamp] ERROR during backup: $_" | Out-File -FilePath $LogFile -Append -Encoding utf8
    exit 1
}
