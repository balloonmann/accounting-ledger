# Household Ledger ERP — Progress Record

Updated: 8 October 2026

## Summary

| Milestone | Status |
|---|---|
| M0 — Foundation and database verification | Complete |
| M1 — Posting engine and database guarantees | Complete |
| M2 — Accounts and entry workflows | Complete |
| M3 — Complete privacy, grants, and administration | Not started |
| M4 — Reports and export | Not started |
| M5 — Deployment preparation | Not started |
| M6 — Walkthrough and pilot release | Not started |

---

## M0 — Foundation and database verification

**Status:** Complete
**Environment:** Windows, Python 3.12, Django 5.2, PostgreSQL 18.6 local
**Executed:** 8 October 2026

### What was implemented

- Git repository initialized; custom User model, domain models, migrations, policy layer, health endpoint, test infrastructure, ADRs.
- 14 foundation tests pass in an isolated Docker PostgreSQL instance.
- Runtime role privilege boundary verified.

### Acceptance tests executed

| ID | Test | Result |
|---|---|---|
| (foundation) | 14 tests in test_foundation.py | All pass |
| Runtime role | ledger_test_app can DML, cannot CREATE TABLE or DISABLE TRIGGER | Pass |
| Singleton | Second LedgerSettings row rejected | Pass |
| Currency | Update to USD rejected | Pass |
| Visibility | Personal account without owner rejected at DB | Pass |
| Grant | Posting grant without view rejected at DB | Pass |
| Line sign | Zero/both-sided lines rejected at DB | Pass |

### Known limitations from M0

- Development migrations not yet applied to local household_ledger DB.
- No posting engine (resolved in M1).
- No DB triggers protecting posted journals (resolved in M1).

---

## M1 — Posting engine and database guarantees

**Status:** Complete
**Environment:** Windows, Python 3.12, Django 5.2, PostgreSQL 18.6 (Docker isolated instance)
**Executed:** 8 October 2026

### What was implemented

- apps/accounting/services.py: complete posting service layer implementing:
  - create_draft, update_draft, delete_draft
  - post_entry with full Bible §7 protocol: idempotency hash, LedgerSettings lock, account locking in stable UUID order, permission reload after lock, date/amount/account/balance validation, posting-number sequence
  - reverse_entry: full reversal with swapped lines, deferred check, one-per-original guard
  - set_posting_lock_date: Admin-only, serialized, logged
  - create_account, update_account, deactivate_account: frozen-field enforcement per D04
- apps/accounting/migrations/0004_posting_engine.py:
  - accounting_posting_number_seq (gap-tolerant, never MAX+1)
  - Trigger posted_entry_immutable: blocks DELETE and frozen-field UPDATE on POSTED headers
  - Trigger posted_lines_immutable: blocks INSERT/UPDATE/DELETE on lines of POSTED entries
  - Constraint trigger check_posted_balance: DEFERRABLE INITIALLY DEFERRED; enforces >= 2 lines and debit = credit at transaction end when state = POSTED
  - GRANT for ledger_app and ledger_test_app roles on the sequence
- ServiceError, ConflictError, StaleVersionError, AuthorizationError exception hierarchy
- All psycopg connections in tests now explicitly closed to prevent teardown failures

### Acceptance tests executed

All 35 tests pass cleanly (exit code 0, clean DB teardown).

| ID | Test | Result |
|---|---|---|
| A01 | Balanced posting commits one entry + all lines; unique posting numbers | Pass |
| A02 | Unequal totals, invalid precision, negative, both-sided, zero, group, inactive, locked-date | Pass (10 cases) |
| A03 | Injected failure after persistence rolls back completely | Pass |
| A04 | Same key/payload repeated returns original result | Pass |
| A05 | Same key, different payload raises ConflictError | Pass |
| A06 | Concurrent post of same draft yields exactly one posting | Pass |
| A11 | Direct ORM UPDATE date, DELETE entry, DELETE line, INSERT line into posted entry all blocked by trigger | Pass (4 cases) |
| A19 | Direct unbalanced (1-line) and 2-line unbalanced POSTED entry via runtime role rejected at DB | Pass (2 cases) |
| M0 foundation | All 14 foundation tests continue to pass | Pass |

---

## M2 — Accounts and entry workflows

**Status:** Complete
**Environment:** Windows, Python 3.12, Django 5.2, PostgreSQL 18.6 (Docker isolated instance)
**Executed:** 8 October 2026

### What was implemented

- **Account Administration:**
  - Admin account creation (`account_create`), editing (`account_edit`), and deactivation (`account_deactivate`).
  - D04 frozen field enforcement: when an account has recorded journal lines, `classical_type`, `reporting_class`, `purpose`, `normal_side`, and `parent` cannot be changed; labels remain safely editable.
  - D08 protected accounts: configured `opening_equity` account in `LedgerSettings` cannot be deactivated or deleted. Deleting used accounts or parent groups with children is blocked.
  - Member visibility: members only view shared, owned, or granted accounts (`visible_accounts`).
- **Entry Workflows:**
  - **Expense Entry (`entry_expense`):** Paid from asset account, charged to expense category, supports immediate posting and draft saving.
  - **Income Entry (`entry_income`):** Received into asset account, credited to income category, immediate post and draft.
  - **Transfer Entry (`entry_transfer`):** Transfer between two asset accounts, validates distinct source and destination.
  - **Full Journal (`entry_journal`):** Dynamic multi-line rows with client-side live balancing calculation (debit sum, credit sum, difference indicator) and server-side validation.
  - **Opening Balance (`entry_opening`):** Admin-only opening balance offset against configured equity account.
  - **Draft Management (`draft_list`, `draft_edit`, `draft_delete`, `draft_post`):** Optimistic concurrency check via `version`, input preservation on conflict (`StaleVersionError`).
  - **Reversal & Replacement (`entry_reverse`, `entry_replace`):** Linked full reversal with swapped lines; replacement draft pre-populates original lines and links to `replacement_of`.
  - **Atomic Immediate Posting:** Posting workflows run inside `transaction.atomic()`, ensuring no orphan draft is left if immediate posting fails.
- **UI Design System:**
  - Responsive layout for laptop and phone with clean Inter typography, curated emerald/slate palette, status badges, and alert notifications.
  - Accessible accounts overview and recent activity on dashboard.
- **Management Command `seed_demo`:**
  - Repeatable command seeds synthetic users (`admin_demo`, `member_demo`), accounts, grants, and executes the Bible §11 Golden Dataset.
  - Validates exact balances: Cash Dr ₹7,550; Bank Dr ₹22,000; Groceries Dr ₹450; Salary Cr ₹20,000; Opening Equity Cr ₹10,000; Surplus ₹19,550; Cash+Bank ₹29,550.

### Acceptance tests executed

All 51 tests pass cleanly (exit code 0, clean DB teardown).

| ID | Test | Result |
|---|---|---|
| A01–A06 | Posting engine and concurrency guarantees | Pass |
| A07 | Stale draft edit conflicts without losing form input | Pass |
| A08 | Unauthorized IDs in expense/income/transfer/journal fail without financial persistence | Pass |
| A11 | Database immutability triggers on posted headers and lines | Pass |
| A14 | Bible §11 Golden Dataset reproduces exact expected balances | Pass |
| A19 | Database deferred triggers reject unbalanced posted journals directly | Pass |
| Account Admin | Create, update unused, freeze used (D04), protect configured equity (D08) | Pass (5 cases) |
| Workflows | Expense, Income, Transfer, Journal, Opening Balance views | Pass (6 cases) |
| Draft Lifecycle | Concurrency conflict, editing, deletion, posting | Pass (2 cases) |
| Privacy & Reversal | Entry detail line privacy restriction, reversal lines swap, replacement link | Pass (2 cases) |
| Foundation | All 14 foundation tests continue to pass | Pass |


## Milestone 3 — Complete Privacy, Grants, and Administration (8 October 2026)

### Status: Complete

### What was built

- **Household User Administration (`apps/identity/`):**
  - Administrative views for user listing (`user_list`), creation (`user_create`), role & credential updates (`user_edit`), and status toggling (`user_toggle_active`).
  - Strict administrative safeguards prevent administrators from demoting or deactivating their own account.
  - Activity logs atomically record all user creations and permission updates.
- **Granular Account Grants (`apps/accounting/`):**
  - Dedicated administrative grant management view (`account_grants`) and service (`set_account_grants`).
  - Database check constraint `posting_requires_view` enforced: granting post permission automatically mandates view permission.
  - Activity logs capture grant modifications.
- **Posting Lock Date Administration (`settings_lock_date`):**
  - Administrative interface to inspect and configure the posting lock date.
  - Mandatory audit reason enforced: setting or lowering the lock date requires an explanation (`ActivityRecord`).
  - Concurrent posting and lock-date modifications serialize via `SELECT ... FOR UPDATE` on `LedgerSettings`.
- **Account Ledger & Mixed-Visibility Redaction (Bible §9.2 / D03 / A09):**
  - Account ledger view (`account_ledger`) calculates historical opening balance, period debits/credits, and running balances in stable sort order (date, posting number, line number).
  - Mixed-visibility privacy enforcement: if a user lacks visibility on any account involved in an entry, the transaction date and debit/credit amounts remain intact for mathematical ledger reconciliation, while narration and author details are masked (`[Redacted]`), and direct links to the full journal entry are suppressed.
  - Generic HTTP 404 responses for unauthorized accounts prevent leaking private account identifiers.
  - `entry_detail` rejects access with HTTP 403 Forbidden whenever any line touches an account the user cannot see.
- **Single Full Reversal Constraint & Anti-Pattern Protection:**
  - One direct full reversal per original entry enforced via database constraints and service locks.
  - Reversal of a reversal is rejected (`ServiceError`).

### Acceptance tests executed

All 68 tests across accounting and identity suites pass cleanly (exit code 0, isolated PostgreSQL database).

| ID | Test | Result |
|---|---|---|
| A01–A06 | Posting engine and concurrency guarantees | Pass |
| A07 | Stale draft edit conflicts without losing form input | Pass |
| A08 | Unauthorized IDs across forms, URLs, and queries rejected without reading/posting | Pass |
| A09 | Mixed-visibility redaction holds across ledger screens, concealing narration, author, and links | Pass |
| A10 | Independent-connection concurrent reversal race produces exactly 1 reversal; reversal of reversal rejected | Pass |
| A11 | Database immutability triggers on posted headers and lines | Pass |
| A12 | Inactive accounts, locked dates, and unbalanced transactions rejected | Pass |
| A13 | Lock-date lowering requires non-empty reason; concurrent posting and lock-date changes serialize | Pass |
| A14 | Bible §11 Golden Dataset reproduces exact expected balances | Pass |
| A19 | Database deferred triggers reject unbalanced posted journals directly | Pass |
| A20 | Coordinated boundary permission re-checks reject posting upon concurrent actor deactivation or grant revocation | Pass |
| User Admin | User listing, creation, role editing, self-demotion protection, active toggle | Pass (4 cases) |
| Workflows & M2 | All 51 M1/M2 foundation, workflow, and account administration tests continue to pass | Pass |

### Known limitations / Deferred to M4

None. Milestone 4 completed below.


## Milestone 4 — Financial Reports and Export (8 October 2026)

### Status: Complete

### What was built

- **Admin Trial Balance Report (`apps/reporting/`):**
  - View (`trial_balance`) and template (`trial_balance.html`) displaying all active leaf accounts grouped by reporting class (`ASSET`, `LIABILITY`, `EQUITY`, `INCOME`, `EXPENSE`).
  - As-of date filtering; enforces leaf account isolation (`is_group=False`) to avoid double counting parent groupings.
  - Verifies total debit balances match total credit balances (`is_balanced`).
  - Restricted strictly to Admin users (returns HTTP 403 Forbidden to regular members).
- **Admin Household Income & Expenditure Statement (`apps/reporting/`):**
  - View (`income_expenditure`) and template (`income_expenditure.html`) showing periodic operating income, household expenditures, and net surplus/deficit.
  - Indian April–March fiscal year awareness: defaults to current fiscal year start (`current_fiscal_year_start()`) through current date.
  - Restricted strictly to Admin users (returns HTTP 403 Forbidden to regular members).
- **Account Ledger Date Filtering & Opening Balances (A15):**
  - Aggregates pre-period line items to compute initial opening balance prior to `start_date`.
  - Sequences transactions by `date`, `posting_number`, `line_number` and maintains running balances throughout the period.
- **Secure CSV Export & Formula Injection Neutralization (Bible §10 / A09):**
  - Downloadable CSVs for Account Ledgers, Trial Balance, and Income & Expenditure statement (`?export=csv`).
  - Full mixed-visibility parity: unauthorized transaction details (narration, author) are masked to `[Redacted]` in CSV exports just as on screen.
  - Formula injection protection: all free-text CSV cells starting with `=`, `+`, `-`, `@`, `\t`, or `\r` are sanitized by prepending `'` to neutralize formula execution in Excel/Google Sheets.

### Acceptance tests executed

All 75 tests across accounting, identity, and reporting suites pass cleanly (exit code 0, isolated PostgreSQL database).

| ID | Test | Result |
|---|---|---|
| A14 | Golden Dataset balances verified: Trial balance (Dr ₹30,000 / Cr ₹30,000), Surplus (₹19,550), Liquid assets (₹29,550) | Pass |
| A15 | Date-filtered account ledger computes exact opening and running balances | Pass |
| A09 (Complete) | Mixed-visibility redaction holds in CSV exports, suppressing private narration/author | Pass |
| CSV Security | Spreadsheet formula injection neutralized on text cells starting with `=`, `+`, `-`, `@`, `\t` | Pass |
| Authorization | Trial Balance and Income/Expenditure screens and CSVs return 403 Forbidden to non-admin members | Pass |
| Admin CSV Exports | Trial balance and Income/Expenditure CSV exports download successfully with correct headers and sums | Pass |
| All Prior Tests | All 68 M0–M3 tests continue to pass cleanly | Pass |

### Known limitations / Deferred to M5

- Production deployment preparation (Gunicorn, `render.yaml`, production settings, health checks, backup/restore scripts) completed in Milestone 5a below.
- Real-data migration and live hosting remain gated.


## Milestone 5a — Deployment Preparation, Backup/Restore, and Operational Hardening (8 October 2026)

### Status: Complete (M5b Hosted Cloud Provisioning remains gated per user agreement)

### What was built

- **Hardened Production Configuration (`config/settings/production.py` / H01):**
  - Enforces `DEBUG = False`, `SECURE_SSL_REDIRECT = True`, `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`.
  - Rejects unsafe wildcard hosts (`*` in `ALLOWED_HOSTS`) and non-HTTPS CSRF origins at startup.
  - Rejects signing keys shorter than 50 characters.
  - Configures WhiteNoise with `CompressedManifestStaticFilesStorage` for self-contained, cache-busted static asset serving.
  - Reverse-proxy SSL header detection (`TRUST_PROXY_HTTPS=1` enables `HTTP_X_FORWARDED_PROTO` for Render/reverse proxies).
- **Service Deployment Specifications (`Dockerfile`, `render.yaml`):**
  - Multi-stage Linux Dockerfile with non-root runtime user and Python 3.12.
  - Render blueprint specification (`render.yaml`) declaring separate migration release command (`python manage.py migrate --noinput`) and Gunicorn web service.
- **Operational Health Check (`apps/operations/views.py`):**
  - `/health/` endpoint executing lightweight database ping (`SELECT 1`).
  - Returns HTTP 200 `{"status": "ok"}` when database is healthy.
  - Returns HTTP 503 `{"status": "unavailable"}` when database fails, strictly concealing credentials, connection strings, and stack traces.
- **Database Backup & Recovery Engine (`scripts/backup.py`, `scripts/restore.py` / A18):**
  - `scripts/backup.py`: Generates custom-format (`-Fc`) compressed PostgreSQL dumps with SHA-256 integrity checksums in `backups/`. Tested locally: created verified dump file `backups/household_ledger_backup_20261008_194242.dump` (78.4 KB).
  - `scripts/restore.py`: Restores into an explicit target database, guards against accidental overwrite of the primary database without `--force`, verifies schema integrity, and validates debit/credit balance equality post-restore.
- **Operational Runbooks (`docs/operations/`):**
  - `docs/operations/backup_and_recovery.md`: Step-by-step backup, restore, checksum verification, and disaster recovery procedures.
  - `docs/operations/deployment_and_migration.md`: Staging/production deployment procedures, role provisioning, migration rollback strategy, and smoke tests.
- **Continuous Integration Pipeline (`.github/workflows/ci.yml`):**
  - GitHub Actions workflow testing locked dependencies (`requirements.lock`), Django deployment checks (`manage.py check --deploy`), migrations, and all isolated PostgreSQL test suites.

### Acceptance tests executed

All 82 tests across accounting, identity, reporting, and operations suites pass cleanly (exit code 0, isolated PostgreSQL database).

| ID | Test | Result |
|---|---|---|
| A01–A06 | Posting engine and concurrency guarantees | Pass |
| A07 | Stale draft edit conflicts without losing form input | Pass |
| A08 | Unauthorized IDs across forms, URLs, and queries rejected without reading/posting | Pass |
| A09 | Mixed-visibility redaction holds across screens and CSV exports | Pass |
| A10 | Independent-connection concurrent reversal race produces exactly 1 reversal; reversal of reversal rejected | Pass |
| A11 | Database immutability triggers on posted headers and lines | Pass |
| A12 | Inactive accounts, locked dates, and unbalanced transactions rejected | Pass |
| A13 | Lock-date lowering requires non-empty reason; concurrent posting and lock-date changes serialize | Pass |
| A14 | Golden Dataset balances verified across Trial Balance, Income/Expenditure, and Account Ledgers | Pass |
| A15 | Date-filtered account ledger computes exact opening and running balances | Pass |
| A18 | Backup creation tested and verified; restore script validates target isolation and balance parity | Pass |
| A19 | Database deferred triggers reject unbalanced posted journals directly | Pass |
| A20 | Coordinated boundary permission re-checks reject posting upon concurrent actor deactivation or grant revocation | Pass |
| H01 | Production configuration rejects short secret keys, wildcard hosts, and insecure CSRF origins; Django deployment check passes | Pass |
| Health Check | `/health/` returns 200 on healthy database, 503 on database failure without leaking credentials | Pass |
| All Prior Tests | All 75 M0–M4 accounting, identity, and reporting tests continue to pass cleanly | Pass |

### Known limitations / Deferred to M5b & M6

- **M5b (Hosted Cloud Provisioning):** Actual remote provisioning on Render or another managed cloud provider, DNS setup, and live remote multi-device smoke verification remain gated awaiting explicit owner approval and budget selection.
- **M6 (Pilot Release & Real-Data Migration):** Pilot release walkthrough and real-data migration remain gated until user sign-off.

---

## Security Audit Remediation (14 October 2026)

Following a comprehensive read-only security and database architecture audit across 16 areas, all code-level findings have been resolved and manual remediation runbooks established.

### Code & Configuration Remediations Implemented

1. **FIX-2 (Lock Date Audit Log FieldError):** Fixed field name from nonexistent `timestamp` to `created_at` in `apps/accounting/views.py` (`settings_lock_date`).
2. **FIX-3 (Narration & Version Database Immutability):** Created migration `0005_freeze_narration.py` updating trigger function `accounting_posted_entry_immutable()` to freeze `narration` and `version` on all POSTED entries at the PostgreSQL level.
3. **FIX-4 (Login Rate Limiting):** Integrated `django-axes` (v7.1.0), regenerated universal `requirements.lock` with SHA-256 hashes using `uv`, and configured lockout rules (5 attempts, 1-hour cooldown) in `config/settings/production.py`.
4. **FIX-5 (CI Deployment Check):** Enhanced `.github/workflows/ci.yml` to run `python manage.py check --deploy --settings config.settings.production` with strict security verification.
5. **FIX-6 (JournalLine Foreign Key Index):** Added explicit `journalline_entry_idx` index on `JournalLine.entry` in `apps/accounting/models.py` and created migration `0006_journalline_entry_idx.py`.
6. **FIX-7 (Login Attempt Audit Logging):** Implemented `apps/identity/signals.py` connecting `user_logged_in` and `user_login_failed` Django signals to record audit entries in `ActivityRecord` with IP addresses.
7. **FIX-8 (Service Logging Config):** Configured `apps.*` logger to `INFO` level in `config/settings/base.py` LOGGING dictionary.
8. **FIX-9 (Content Security Policy):** Integrated `django-csp` (v3.8) in `config/settings/production.py` enforcing strict source policies, form actions, and frame-ancestors restrictions.
9. **FIX-10 (HSTS Hardening):** Increased `SECURE_HSTS_SECONDS` to `31536000` (1 year) with `SECURE_HSTS_PRELOAD = True` in `config/settings/production.py`.
10. **FIX-11 (Automated Daily Backups):** Created Windows PowerShell task runner `scripts/backup_task.ps1` with 30-day retention pruning and documented Task Scheduler setup in `docs/operations/backup_runbook.md`.
11. **FIX-12 (Database Queryset Scoping):** Replaced Python-level in-memory list filtering in `draft_list`, `entry_list`, and `home` recent entries with DB-level `visible_entries(user)` queryset scoping.
12. **FIX-13 (Automated Dependency Vulnerability Scanning):** Added `pip-audit` automated dependency scanning to `.github/workflows/ci.yml`.
13. **FIX-14 (CI Secrets Sanitization):** Removed hardcoded database passwords from `.github/workflows/ci.yml`, replacing with secret-backed `${{ secrets.CI_PG_PASSWORD }}`.
14. **FIX-15 (Session Expiration Controls):** Added `SESSION_COOKIE_AGE = 28800` (8 hours) and `SESSION_EXPIRE_AT_BROWSER_CLOSE = True` in `config/settings/base.py`.
15. **FIX-16 (Automated Deployment Migrations):** Added `releaseCommand: python manage.py migrate` to `render.yaml`.
16. **FIX-17 (Disaster Recovery Verification):** Enhanced `scripts/restore.py` to assert database integrity triggers presence, sequence integrity, and `ledger_app` role privileges.
17. **FIX-18 (Referrer & Nosniff Security Headers):** Configured `SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"` and `SECURE_CONTENT_TYPE_NOSNIFF = True` in `config/settings/production.py`.
18. **FIX-20 (Admin MFA / TOTP Roadmap):** Documented architecture decision record in `docs/decisions/0007-admin-mfa.md` for `django-otp` TOTP enforcement prior to real-data deployment.
19. **Default Secrets Path Update:** Updated `scripts/backup.py` and `scripts/restore.py` to read credentials by default from `C:\Users\Harshit\ledger_secrets\.env.migration`.
20. **Regression Guardrail Tests:** Added regression tests in `apps/identity/tests.py` and `apps/accounting/tests/test_permissions_m3.py` for login signal recording, `visible_entries` DB scoping, and `settings_lock_date` activity rendering.

### User Action Items (OS / Manual Level)
- **FIX-1:** Move `.env.migration` out of OneDrive into `C:\Users\Harshit\ledger_secrets\.env.migration` and rotate the `ledger_migrator` password.
- **FIX-19:** Move the local working directory outside of OneDrive (e.g. `C:\projects\accounting_ledger`).



