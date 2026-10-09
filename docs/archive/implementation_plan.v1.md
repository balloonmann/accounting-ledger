# Household Ledger ERP — Implementation Plan

> Synthesized from `ERP_BUILD_BIBLE.md` (v1.0, Oct 2026) and `Household_Accounting_ERP_FRD (1).docx` (v1.0, July 2026)

---

## Part A — Pre-Implementation Requirements & Access Checklist

Before any core code is written, the following must be confirmed or granted. Items marked **🔴 BLOCKER** will stall specific milestones if unresolved.

### A1. Owner Decisions Required (Architectural Decisions — from Bible §3)

These are open `ARCHITECTURAL DECISION REQUIRED` items in the Bible. They must be answered before the affected milestone begins, but do **not** block M0 scaffolding.

| ID | Decision Needed | Blocks | Default I Will Use Until Resolved |
|----|----------------|--------|-----------------------------------|
| D01 | Confirm that posted financial fields are **immutable** (draft-edit + reversal model only) | M1 | Immutable posted entries |
| D03 | Privacy policy: is it acceptable that a Member can **infer** that *some* transaction happened on a shared account, even if details are hidden? | M3 | Inference allowed; only account details redacted |
| D05 | Which assets/bank accounts are "inside the book"? Owner must decide the opening boundary before importing real balances | M4 | Synthetic data only until decided |
| D07 | Can a Member **post** to shared accounts, or only view them? | M3 | View-only by default; posting requires explicit Admin grant |
| D09 | Full year-end close is deferred — confirm a simple **posting lock date** is acceptable for POC | M4 | Lock date only, no year-end closing |

> [!IMPORTANT]
> Please answer these 5 questions before the first real-data session (after M0 demo). Code will use the defaults above in the meantime.

---

### A2. Software & Environment Access You Must Provide

#### 🔴 BLOCKER — Docker Desktop
- **What:** Docker Desktop installed and running on your Windows laptop.
- **Why:** The entire stack (Django + PostgreSQL) runs in Docker Compose. Nothing else needs to be installed manually.
- **How to check:** Open PowerShell and run `docker --version`. If it prints a version, you're good.
- **Download:** https://www.docker.com/products/docker-desktop/

#### 🔴 BLOCKER — Tailscale Account & Client
- **What:** A free Tailscale account + the Tailscale client installed on your laptop AND on any other device that needs remote access (phone, another laptop).
- **Why:** The Bible mandates Tailscale Serve as the private remote-access method (no public internet exposure).
- **Steps:**
  1. Sign up at https://tailscale.com (free for personal use)
  2. Install client on your laptop: https://tailscale.com/download
  3. Log in on the laptop — give me your **Tailscale machine hostname** (e.g., `harshit-laptop.tailnet-name.ts.net`) so I can configure `ALLOWED_HOSTS` and CSRF origins correctly.
  4. Install and log in on any other device that will access the app.

#### 🟡 NEEDED SOON — Git & Repository Location
- **What:** Confirm where you want the project repository created. Options:
  - `C:\Users\Harshit\OneDrive\Desktop\accounting_ledger\household-ledger\` (inside this workspace)
  - A different path you specify
- **Why:** All code will be written there. It becomes a Git repository.
- **Action:** Tell me the preferred path (or confirm the default above).

#### 🟡 NEEDED SOON — Python (optional, for running management commands outside Docker)
- Docker will handle Python inside containers. But if you want to run `manage.py` commands directly on Windows (not strictly necessary), Python 3.12 should be installed.
- **How to check:** `python --version` in PowerShell.

#### 🔵 NICE TO HAVE — VS Code or preferred editor
- No specific requirement, but VS Code with the Docker extension makes viewing logs and containers easier.

---

### A3. Information I Need From You

| Item | Why I need it | When |
|------|--------------|------|
| Tailscale machine hostname | Set `ALLOWED_HOSTS`, CSRF, Tailscale Serve config | Before M5 deployment |
| Initial Admin username & email | Seed the first superuser non-interactively | Before M0 demo |
| Household name (for `LedgerSettings`) | Display name in the app | M0 |
| Financial year start (confirm April 1) | `LedgerSettings.fiscal_year_start` | M0 |
| List of family members who will use the app (usernames only, no passwords) | Seed demo users | M2 |
| Which bank/cash accounts exist in real life (names only, no amounts) | Seed realistic Chart of Accounts | M2 (optional for demo) |

---

## Part B — Implementation Plan (7-Day Milestones)

### Overview

```
M0 (Day 1) ──► M1 (Day 2) ──► M2 (Day 3) ──► M3 (Day 4) ──► M4 (Day 5) ──► M5 (Day 6) ──► M6 (Day 7)
  Scaffold        Ledger Core    Entry Forms    Permissions    Reports        Deployment     Walkthrough
```

---

### M0 — Day 1: Scaffold & Foundation

**Goal:** A reproducible, running Docker Compose stack with the correct data model. No real accounting logic yet.

**What gets built:**

1. **Repository skeleton** — exact layout from Bible §4:
   ```
   household-ledger/
     config/settings/{base,development,production,test}.py
     apps/{identity,accounting,reporting,operations}/
     templates/, static/, tests/acceptance/, scripts/, docs/
   ```
2. **Django project init** — Django 5.2 LTS, pinned in `pyproject.toml` + `requirements.lock`
3. **Custom User model** (`apps/identity/models.py`) — created *before* any migrations, per Bible §4 rule
4. **Core data models** (`apps/accounting/models.py`):
   - `LedgerSettings` (singleton)
   - `Account` (type, reporting class, purpose, normal side, visibility, parent, active)
   - `AccountGrant` (user ↔ account, can_view, can_post)
   - `JournalEntry` (state machine: DRAFT → POSTED; optimistic version)
   - `JournalLine` (debit/credit as `NUMERIC(18,2)`)
   - `PostingRequest` (idempotency table)
   - `ActivityRecord` (audit log)
5. **`compose.yaml`** — Django + PostgreSQL with persistent named volume
6. **`.env.example`** — all secrets as placeholders
7. **Initial migrations** — applied and verified
8. **Django Admin** — registered as read-only for journals
9. **`AGENTS.md`** — agent constitution for this repo

**Exit gate:** `docker compose up` starts without errors; `manage.py check` passes; migrations applied; custom user model confirmed in `auth_user` equivalent.

**FRD sections covered:** §2 (accounting foundations drive the model), §3 (user/role structure), §4 (CoA structure), §4.4 (Capital/Drawings pattern)

---

### M1 — Day 2: Posting Operation & Database Protections

**Goal:** The accounting engine. Every entry mode in later milestones will call this. Must be rock-solid before UI.

**What gets built:**

1. **`apps/accounting/services/posting.py`** — the central `PostEntry` service implementing the full 10-step posting protocol (Bible §7.2):
   - Idempotency key lookup → `PostingRequest` table
   - `SELECT FOR UPDATE` on `LedgerSettings` (coarse serialization lock)
   - Account locks in stable ID order
   - Full validation: balanced, ≥2 lines, INR only, active leaf accounts, exact decimal
   - Assign posting number via DB sequence (never `MAX+1`)
   - Single atomic transaction commit
2. **`apps/accounting/services/drafts.py`** — `CreateDraft`, `UpdateDraft`, `DeleteDraft` with optimistic version check
3. **`apps/accounting/services/reversals.py`** — `ReverseEntry` (one reversal per original, immutable)
4. **`apps/accounting/services/accounts.py`** — `CreateAccount`, `UpdateUnusedAccount`, `DeactivateAccount`
5. **PostgreSQL database protections** (via migrations):
   - Triggers: prevent `UPDATE`/`DELETE` on posted journal headers and lines for financial fields
   - Deferred constraint trigger: enforce balanced entry (total debits = total credits) at transaction commit
   - Check constraints: line sign validity, decimal bounds, state consistency
6. **`apps/accounting/choices.py`** — enums for `AccountType`, `ReportingClass`, `AccountPurpose`, `NormalSide`, `Visibility`, `EntryKind`, `EntryState`

**Acceptance tests run:** A01–A06, A19
- A01: Post balanced entry → one posted entry, all lines committed
- A02: Unequal totals, bad precision, negative/zero lines → validation error, no posting
- A03: Simulated failure mid-transaction → full rollback
- A04: Same key/payload twice (concurrent) → one entry, same result returned
- A05: Same key, different payload → conflict error
- A06: Two requests posting same draft → one succeeds, other gets conflict
- A19: Direct ORM bulk-edit of posted line → DB trigger rejects it

---

### M2 — Day 3: Entry Forms & UI

**Goal:** Family members can log income, expenses, transfers, and opening balances through a browser.

**What gets built:**

1. **Login/logout screens** — Django auth, session-based, CSRF protected
2. **`Add Expense` form** — amount, date, cash/bank source, expense category, notes → calls `PostEntry` or `CreateDraft`
3. **`Add Income` form** — same pattern, income direction
4. **`Transfer` form** — two cash/bank accounts, amount, date, notes
5. **`Full Journal Entry` form** — multi-line, live running debit/credit difference (minimal JS), server validates independently
6. **`Opening Balance` form** — Admin only; dated, with explicit offset account picker
7. **`Entry Detail` view** — status, lines, allowed actions (post draft, discard, reverse)
8. **`Account list` view** — accounts visible to the current user, with current balance and status
9. **Chart of Accounts seeding** — `management/commands/seed_demo.py` loads FRD §4.6 starter accounts + golden dataset from Bible §11
10. **Base templates** — `base.html`, responsive layout, simple navigation

**FRD sections covered:** §6.1 (two entry modes), §6.2 (transfer entries), §5 (opening balances), §4.1–4.3 (CoA browsing)

> [!NOTE]
> Recurring transactions (FRD §6.3) are **deferred** per Bible §1.2. Forms will not include a recurrence option.

---

### M3 — Day 4: Permissions, Privacy, Draft Conflicts, Lock Date

**Goal:** The system enforces who can see and do what. Privacy holds across all output channels.

**What gets built:**

1. **`apps/accounting/policies.py`** — central permission functions:
   - `can_view_account(user, account)`
   - `can_post_to_account(user, account)`
   - `can_view_entry(user, entry)` — requires visibility on ALL lines
   - `can_edit_draft(user, draft)`
   - `can_reverse_entry(user, entry)`
2. **`apps/identity/policies.py`** — role checks (Admin/Member)
3. **Redaction logic** (Bible §9.2): mixed-visibility journal shows only authorized account's debit/credit/balance; suppresses hidden account names, narration, creator, links
4. **Draft conflict UI** — stale version → conflict message + form data preserved (no silent overwrite)
5. **`SetPostingLockDate` service** — Admin-only, serialized with posting, logged, requires reason to lower
6. **`AccountGrant` management UI** — Admin can grant/revoke can_view / can_post per member per account
7. **`ActivityRecord` writes** — all financial operations log actor, action, object, timestamp

**Acceptance tests run:** A07–A13, A20
- A07: Concurrent draft edits → stale editor gets conflict
- A08: Unauthorized IDs in forms/URLs/exports → no unauthorized access
- A09: Mixed private/shared journal → redaction holds in screen, CSV, error messages
- A10: Reverse twice (including concurrent) → only one reversal linked
- A11: Direct ORM edit of posted money → DB trigger rejects
- A12: Post to group account / inactive account / non-INR / locked date → rejected
- A13: Lock-date change races with posting → serialized; no posting past committed lock
- A20: Permission/state changes vs posting → current policy checked at transaction boundary

---

### M4 — Day 5: Reports & CSV Export

**Goal:** Admin sees trial balance and income/expenditure; all users see their authorized ledger.

**What gets built:**

1. **`apps/reporting/selectors.py`** — authorized read queries:
   - Account ledger with running balance (stable order: date, posting number, line number)
   - Opening balance calculation for filtered date ranges (includes pre-period activity)
   - Trial balance (Admin only) — all posted account balances to a selected date
   - Income/Expenditure (Admin only) — income and expense activity within a date range
2. **Report views** — screen rendering with date filters and account filters
3. **`apps/reporting/exports.py`** — CSV export using identical authorized query logic; formula injection protection
4. **Report rules enforced** (Bible §10):
   - Drafts excluded; posted originals AND reversals included on their respective dates
   - Exact decimal aggregation (no float)
   - No double-counting of parent rollups and their leaves
   - Opening balance of filtered view includes all pre-period posted activity

**Acceptance tests run:** A14–A15
- A14: Golden dataset (Bible §11) → exact balances: Cash ₹7,550, Bank ₹22,000, Expense ₹450, Income ₹20,000, Equity ₹10,000; TB totals ₹30,000 each side
- A15: Filter ledger to later date → correct opening and running balances

**FRD sections covered:** §9 (all required reports), §6.7 (cash book / bank book views)

> [!NOTE]
> Dashboards (FRD §10), budgeting (FRD §11), bank reconciliation (FRD §6.8), and year-end closing (FRD §8) are deferred per Bible §1.2.

---

### M5 — Day 6: Deployment, Remote Access & Backup

**Goal:** Invited users can reach the app from another device. Backup and restore are demonstrated, not just scripted.

**What gets built:**

1. **`compose.production.yaml`** — Gunicorn, `DEBUG=False`, `ALLOWED_HOSTS` set, secure session cookies, HTTPS headers, non-superuser runtime DB role
2. **Tailscale Serve configuration** — documented exact commands for your machine; HTTPS termination via Tailscale; PostgreSQL port NOT exposed outside Tailscale network
3. **`scripts/backup_db.sh`** — `pg_dump` to timestamped file, off-laptop encrypted copy note, retention policy
4. **`scripts/restore_db.sh`** — requires explicit target database name; protects against accidental overwrite of active DB
5. **`docs/runbook.md`** — exact verified commands for: prerequisites, first run, start/stop/logs, health check, remote access setup, backup, restore, dependency updates, failure recovery
6. **Health check endpoint** — `GET /health/` returns 200 with DB connectivity status
7. **Error log configuration** — structured logs; no passwords, cookies, or financial payloads logged

**Acceptance tests run:** A16–A18
- A16: Two separate device sessions → independent identity, correct permissions
- A17: Restart/recreate application container → database persists (named volume)
- A18: Backup restored into fresh database → records, relationships, balances, and login all usable

---

### M6 — Day 7: Walkthrough, Defect Fixes & Completion Report

**Goal:** A family member who has never used the system can complete real tasks. Honest completion report.

**What happens:**

1. **Family walkthrough** — guided session through: login, add expense, add income, transfer, view ledger, view trial balance (Admin)
2. **Defect triage** — fix any blockers found; defer cosmetic issues with documentation
3. **Full regression** — re-run all A01–A20 acceptance tests; record each result
4. **`docs/progress.md` update** — milestone-by-milestone: what works, what was verified, what is limited, what is deferred
5. **Honest completion report** — explicitly lists: implemented & tested, manually verified, proposed/unresolved decisions, deferred FRD capabilities (recurring transactions, bank reconciliation, year-end close, dashboards, budgeting, inventory accounting, attachments)

---

## Part C — What Is Deliberately NOT Built (POC Scope)

The following FRD features are real requirements but are **deferred** in this 7-day POC. They will not be scaffolded as empty stubs.

| FRD Feature | Section | Reason for Deferral |
|-------------|---------|---------------------|
| Recurring transactions | §6.3 | Requires scheduler, laptop-sleep handling, idempotency per occurrence |
| Bank CSV reconciliation | §6.8 | Separate staging pipeline; ambiguous match logic |
| Inventory module (valued) | §7 | FIFO/weighted-average costing; complex journal integration |
| Year-end closing | §8.2 | Capital allocation policy unresolved; closing entries need distinct kind |
| Dashboards | §10 | Built after reports are solid |
| Budgeting | §11 | No transaction pipeline needed; add later alongside dashboards |
| Tags / cross-cutting analysis | §6.5 | Cosmetic; no accounting impact |
| Attachments | §6.4 | Schema provision deferred; storage interface not designed |
| Multi-currency | §6.6 | INR only; schema field deferred to migration |
| Multi-company / multi-book | §12 | Explicitly out of scope for Phase 1 |

> [!WARNING]
> None of these deferred features will be faked or shown as working. If a user clicks something that is deferred, they will see a clear "not yet available" message.

---

## Part D — Technology Decisions Summary

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Language | Python 3.12 | Stable, widely supported |
| Framework | Django 5.2 LTS | LTS support, Django ORM, admin, sessions out of the box |
| Database | PostgreSQL (latest stable) | Required for locking, triggers, NUMERIC(18,2), sequences |
| UI | Django templates + minimal vanilla JS | No SPA build pipeline; works on laptop and phone browser |
| Containerization | Docker Compose | Reproducible; persistent volume for PostgreSQL |
| App server | Gunicorn (production) | Django dev server for local only |
| Remote access | Tailscale Serve | Private network; no public exposure |
| Auth | Django sessions + password hashing | No custom JWT or homemade auth |
| Money precision | `NUMERIC(18,2)` / Python `Decimal` | Never floats |
| Posting numbers | PostgreSQL sequence | Never `MAX+1` |
| Dependency management | `pyproject.toml` + `requirements.lock` | Single pinned lockfile |

---

## Part E — Open Decisions Register

Tracked here until resolved. See Bible §3 for full context.

| ID | Status | Question | My Default |
|----|--------|----------|------------|
| D01 | **Proposed** | Confirm immutable posted entries + reversal model | Immutable |
| D02 | **Proposed** | Confirm reporting class mapping (Asset/Liability/Equity/Income/Expense alongside Personal/Real/Nominal) | Adopted |
| D03 | **Needs owner decision** | Acceptable that Members can infer some transaction happened on shared account? | Yes, inference allowed |
| D04 | **Proposed** | Freeze used account type/class/purpose/parent | Frozen |
| D05 | **Needs owner decision** | Which real bank/cash accounts are inside the book? | Synthetic demo only |
| D06 | **Proposed** | Quantity-only inventory separate from valued | Separate |
| D07 | **Needs owner decision** | Can Members post to shared accounts or only view? | View only; posting needs explicit grant |
| D08 | **Proposed** | Opening-equity account protected from deletion by stable ID | Protected |
| D09 | **Proposed** | Posting lock date only; no full year-end close in POC | Lock date only |
| D10 | **Proposed** | INR only; no FX in POC | INR only |
