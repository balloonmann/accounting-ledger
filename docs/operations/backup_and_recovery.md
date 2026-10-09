# Backup and Recovery Procedures (M5)

## 1. Overview and Principles

All financial transactions in the Household Ledger are permanently stored in PostgreSQL with strict immutability triggers on posted headers and lines. To ensure business continuity and disaster recovery:
1. **Regular Backups:** Full custom-format PostgreSQL dumps (`-Fc`) are produced regularly.
2. **Credential Safety:** Credentials are supplied via environment variables (`PGPASSWORD`) or ignored `.env.migration` files and are never printed to console logs or committed to git.
3. **Explicit Recovery Targets:** Restoration procedures strictly forbid restoring into the active production or development database without explicit danger flags. Restores must target isolated recovery/test databases.

---

## 2. Creating a Backup

The backup script [`scripts/backup.py`](file:///c:/Users/Harshit/OneDrive/Desktop/accounting_ledger/scripts/backup.py) locates the local or server `pg_dump` binary, extracts connection credentials from `.env.migration`, and produces a compressed custom-format dump:

```powershell
# Using Python virtual environment
.venv\Scripts\python.exe scripts\backup.py --output-dir backups
```

On Linux:
```bash
python scripts/backup.py --output-dir backups
```

### Output:
- File format: `backups/household_ledger_backup_YYYYMMDD_HHMMSS.dump`
- SHA256 checksum is printed to verify archive integrity.
- Custom format (`-Fc`) supports compressed storage and flexible schema/data restoration.

---

## 3. Disaster Recovery and Rehearsal

Restoring from a backup uses [`scripts/restore.py`](file:///c:/Users/Harshit/OneDrive/Desktop/accounting_ledger/scripts/restore.py).

### Rehearsal into a Test/Recovery Database

To verify a backup or rehearse disaster recovery:
1. Ensure a recovery database target is designated (e.g. `household_ledger_recovery_test`).
2. If the target database does not exist, create it via your PostgreSQL admin account:
   ```sql
   CREATE DATABASE "household_ledger_recovery_test" OWNER "ledger_migrator";
   ```
3. Execute the restoration script:
   ```powershell
   .venv\Scripts\python.exe scripts\restore.py --dump-file backups\household_ledger_backup_YYYYMMDD_HHMMSS.dump --target-db household_ledger_recovery_test
   ```

### Automated Verification on Restore:
The script automatically connects to the restored database and executes integrity checks:
- Counts active users in `identity_user`.
- Counts chart of accounts in `accounting_account`.
- Counts posted journal entries in `accounting_journalentry`.
- Computes `sum(debit)` and `sum(credit)` across all lines in `accounting_journalline` and asserts that **Total Debits equal Total Credits**.

---

## 4. Safety Guard against Primary Database Overwrite

The restore script detects protected database names (`household_ledger`, `production`, `prod`) and refuses to execute unless explicitly commanded with:
```bash
--dangerously-allow-primary-db-overwrite
```
This prevents accidental data loss on the active production system.
