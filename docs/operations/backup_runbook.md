# Database Backup & Restoration Runbook

## Overview
Household Ledger uses PostgreSQL custom-format (`-Fc`) compressed backups. These backups are:
- Checksummed using SHA-256
- Verified using rehearsal restoration against non-production databases
- Automated locally via Windows Task Scheduler or cloud storage lifecycle policies

---

## 1. Automated Daily Backups on Windows

The repository provides `scripts/backup_task.ps1` which:
1. Runs `scripts/backup.py` using `.venv`
2. Reads the migration credentials securely from `C:\Users\Harshit\ledger_secrets\.env.migration`
3. Stores dumps in `backups/household_ledger_backup_<timestamp>.dump`
4. Logs execution to `backups/backup_task.log`
5. Automatically purges backups older than 30 days

### Registration Command (Run in Administrative PowerShell):
```powershell
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File C:\Users\Harshit\OneDrive\Desktop\accounting_ledger\scripts\backup_task.ps1"
$Trigger = New-ScheduledTaskTrigger -Daily -At 3:00AM
Register-ScheduledTask -TaskName "HouseholdLedgerDailyBackup" -Action $Action -Trigger $Trigger -Description "Automated daily compressed backup of Household Ledger PostgreSQL"
```

To test execution manually:
```powershell
Start-ScheduledTask -TaskName "HouseholdLedgerDailyBackup"
Get-Content backups\backup_task.log -Tail 20
```

---

## 2. On-Demand Manual Backup
```powershell
.\.venv\Scripts\python scripts/backup.py --output-dir backups
```

---

## 3. Restoration & Disaster Recovery Drill

Restores must **always** be tested against a disposable recovery database before touching primary data:
```powershell
.\.venv\Scripts\python scripts/restore.py `
    --dump-file backups\household_ledger_backup_YYYYMMDD_HHMMSS.dump `
    --target-db household_ledger_recovery_drill
```

The restore script automatically checks:
- Active user counts
- Chart of accounts preservation
- Debit and credit balance equality (Debit == Credit)
- Database integrity triggers (`posted_entry_immutable`, `posted_lines_immutable`, `check_posted_balance`)
- Posting sequence existence (`accounting_posting_number_seq`)
- Role table grants for `ledger_app`
