# 0006 — Deployment Preparation, Backup/Restore, and Operational Hardening (M5a)

Date: 8 October 2026
Status: accepted for POC development baseline; remote cloud provisioning (M5b) remains gated.

## Context

Following financial reporting (M4), Milestone 5 prepares the application for production deployment (recommended on Render or similar Linux PaaS), automated CI testing, and database backup/recovery operations, while preserving the strict security and financial invariants.

## Decisions

- **Separation of M5 into M5a (Local Preparation) and M5b (Hosted Provisioning):**
  - M5a (deployment configuration, scripts, CI pipeline, documentation, and operational tests) executes locally without incurring cloud costs or requiring cloud provider credentials.
  - M5b (remote database provisioning, cloud web service deployment, multi-device testing over public networks, and cloud backup drills) remains gated awaiting explicit owner approval and budget authorization.
- **Production Security Baseline (H01):**
  - `config.settings.production` enforces non-negotiable security requirements at startup:
    - `DEBUG = False`.
    - `SECURE_SSL_REDIRECT = True`, `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`.
    - Exact host matching: rejects wildcards (`*`) in `ALLOWED_HOSTS`.
    - Exact HTTPS origin matching: rejects wildcards (`*`) and plain HTTP in `CSRF_TRUSTED_ORIGINS`.
    - Strong signing secret: rejects signing keys shorter than 50 characters.
    - Reverse-proxy SSL header detection (`TRUST_PROXY_HTTPS=1` enables `HTTP_X_FORWARDED_PROTO` for Render/reverse proxies).
- **Static Asset Serving:**
  - WhiteNoise with `CompressedManifestStaticFilesStorage` serves static assets directly from the Python/Gunicorn service without external CDN dependencies for the POC.
- **Operational Health Check:**
  - `/health/` returns JSON status `{"status": "ok"}` (HTTP 200) on successful database ping (`SELECT 1`).
  - On database failure, returns `{"status": "unavailable"}` (HTTP 503) without leaking credentials, connection strings, or internal errors.
- **Backup & Recovery Engine (A18):**
  - `scripts/backup.py` executes `pg_dump` with custom compressed format (`-Fc`) and computes SHA-256 checksums, hiding credentials and outputting verified dump artifacts to `backups/`.
  - `scripts/restore.py` requires an explicit target database name, actively blocks restore into the active primary database without explicit override, verifies schema integrity, and runs post-restore debit/credit balance checks (`A18`).
- **CI Pipeline:**
  - `.github/workflows/ci.yml` runs locked dependencies (`requirements.lock`), Django deployment checks (`manage.py check --deploy`), migrations, and all isolated PostgreSQL tests on Python 3.12 and PostgreSQL 16/18.

## Consequences & Verification

All 82 automated tests across accounting, identity, reporting, and operations pass cleanly (exit code 0) on isolated PostgreSQL. Backup creation and verification tested successfully locally. Django deployment checks pass with zero security warnings.
