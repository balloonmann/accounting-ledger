# Household Ledger ERP
https://household-ledger-5sqb.onrender.com/login/

Demo Credentials: Username - member_demo
             Password - M@mbar123

A double-entry household accounting system built with Django 5.2, PostgreSQL 18, and psycopg 3, following the Household Accounting ERP Functional Requirements Document and Build Bible.

## Architecture Highlights

- **Strict Immutability & Double-Entry Math:** Enforced via PostgreSQL trigger constraints and central atomic posting services. Posted entries and line items cannot be modified or deleted directly.
- **Granular Privacy & Mixed-Visibility:** Account view/post permissions with privacy redaction on multi-leg entries. Unauthorized account narrations and authors are masked as `[Redacted]` across screen and CSV exports, while keeping ledger math balanced.
- **Security Baseline:** Protection against spreadsheet formula injection (`=`, `+`, `-`, `@`, `\t`, `\r`), role separation (`ledger_app` vs `ledger_migrator`), and production configuration safeguards (`H01`).
- **Audit Logging:** Every balance-affecting event, lock-date change, and permission alteration records an immutable audit entry in `operations_activityrecord`.
- **Database Backup & Recovery:** Automated compressed dump scripts (`scripts/backup.py`) with SHA-256 checksums, and guarded restore verification (`scripts/restore.py`).

## Quickstart (Local Development)

### 1. Prerequisites
- Python 3.12+
- PostgreSQL 18+ (running locally on port 5432)
- Docker (optional, used for isolated disposable test databases)

### 2. Environment Setup
```powershell
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install locked dependencies
pip install -r requirements.lock
```

Copy `.env.example` to `.env` and configure your local PostgreSQL database credentials:
```ini
DJANGO_SECRET_KEY=your-local-dev-secret-key-at-least-50-chars
DATABASE_URL=postgresql://ledger_app:your_password@127.0.0.1:5432/household_ledger
MIGRATION_DATABASE_URL=postgresql://ledger_migrator:your_password@127.0.0.1:5432/household_ledger
```

### 3. Database Migrations & Demo Seeding
```powershell
# Apply database migrations
.venv\Scripts\python.exe manage.py migrate

# Seed chart of accounts and Golden Dataset (Bible §11)
.venv\Scripts\python.exe manage.py seed_demo --password password123
```

### 4. Run Development Server
```powershell
.venv\Scripts\python.exe manage.py runserver
```
Navigate to `http://127.0.0.1:8000/login/`:
- **Admin:** `admin_demo` / `password123`
- **Member:** `member_demo` / `password123`

## Running Automated Tests

Tests execute strictly against disposable, loopback Docker PostgreSQL instances to safeguard development and production databases:
```powershell
.venv\Scripts\python.exe scripts\test.py apps.accounting.tests apps.identity.tests apps.reporting.tests apps.operations.tests
```

## Backup & Disaster Recovery

### Create a Backup
```powershell
.venv\Scripts\python.exe scripts\backup.py
```
Produces a compressed `-Fc` dump and `.sha256` checksum in `backups/`.

### Restore into a Target Database
```powershell
.venv\Scripts\python.exe scripts\restore.py backups/household_ledger_backup_<timestamp>.dump --target-db household_ledger_restored
```
Validates schema integrity and post-restore debit/credit balance parity.

## Production Deployment Preparation

The project includes production-ready Docker and Render configurations:
- `Dockerfile`: Multi-stage Linux build with unprivileged runtime user.
- `render.yaml`: Declarative blueprint for Gunicorn web service with isolated migration pre-deploy job.
- `manage.py check --deploy --settings config.settings.production`: Validates security headers, HTTPS, HSTS, and cookie settings.
