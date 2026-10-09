# Household Ledger ERP — Build Bible

Version: 1.0 • Prepared: 6 October 2026 • Status: recommended implementation baseline

Audience: the product owner and any coding agent working in the project, including Claude or Gemini in Antigravity.

## 0. Read this first

Build a working household accounting POC in approximately one week. Run it on the owner's laptop, let a few invited users access it, and preserve the accounting core when moving to hosted infrastructure. This document is an implementation reference, not an implemented application or a claim that the requirements have been approved or tested.

Optimize the POC for correct postings, understandable workflows, privacy, recovery, and learning. A complete implementation of the original FRD is outside the seven-day target. Future growth will require migrations and selective refactoring; no design can guarantee zero future changes.

### 0.1 Evidence and decision labels

- **SOURCE PRINCIPLE:** directly supported by the supplied FRD or the user's explicit request.
- **INFERENCE:** a working assumption, not a confirmed user requirement.
- **RECOMMENDATION:** the default proposed by this guide; do not report it as owner-approved.
- **ARCHITECTURAL DECISION REQUIRED:** a material domain or product choice that must be resolved before implementing the affected behavior with real data.

The guide's recommended defaults permit scaffolding and synthetic-data development to start. They do not silently override the source FRD. Record any adopted departures in an ADR and identify their status as proposed or accepted accurately. Ask focused questions only when a remaining ambiguity materially changes correctness, privacy, or irreversible behavior; continue unrelated work.

### 0.2 Source material and precedence

1. The owner's explicit current instructions and subsequent decisions.
2. Accepted, dated decision records resolving specific conflicts.
3. The original `Household_Accounting_ERP_FRD (1).docx` for product intent.
4. This guide for the proposed POC implementation and sequencing.
5. `System Design Components Primer.txt` as a menu of possible infrastructure.
6. `Pasted markdown.md` as the request for a reusable product/engineering reference.

When the FRD and this guide disagree, consult the decision register in section 3. Do not choose whichever instruction is easiest. Infrastructure examples in the primer are not requirements to install those components. The supplied Markdown's original request was for documentation without implementation code; this deliverable contains a specification and intended file layout, not the application.

## 1. Product contract

**SOURCE PRINCIPLE:** one household is one accounting book. Family members have individual logins. Income, expenses, transfers, opening balances, and full journal entries all resolve to the same double-entry ledger.

**SOURCE PRINCIPLE:** the longer-term FRD also includes inventory, bank reconciliation, recurring postings, reporting, and financial-year closing. Multi-company, taxation, statutory compliance, active multi-currency, and receipt uploads are deferred.

**INFERENCE:** initial use is approximately 2–10 invited users, mostly entering small transactions interactively. This is a planning envelope, not a tested capacity claim. Assume one developer with substantial time available and familiarity with Python; revise the schedule if that assumption is false.

**INFERENCE:** family members and an accountant/product owner are the initial users. The eventual paying customer and pricing model remain unvalidated. Do not assume household adoption demonstrates demand from businesses.

### 1.1 POC scope

| Capability | Week-one acceptance |
|---|---|
| Identity | Separate accounts, login/logout, Admin and Member roles; no public registration |
| Chart of accounts | Seeded examples, create/edit unused accounts, shared/personal visibility, deactivate used accounts |
| Entry | Income, expense, transfer, full journal, opening balance |
| Lifecycle | Draft, post, discard draft, reverse posted entry |
| Reports | Account ledger; Admin trial balance and income/expenditure; restricted member activity |
| Operations | CSV export, health check, error logs, backup and verified restore |
| Access | Application runs on laptop; invited users reach it securely from another device |

Optional after all core checks pass: monthly category totals, simple account grouping UI, quantity-only inventory demonstration. Keep the grouping data model simple even if its editing UI is deferred.

### 1.2 Explicitly outside this sprint

No automatic recurring postings; bank CSV import/matching; FIFO or weighted-average inventory accounting; formal year-end closing/reopening; budgeting; complete cash-flow statement; compliance claims; receipts; foreign exchange; multiple households/companies; billing; external integrations; mobile app; public API; approval engine.

These are POC deferrals, not deletion of the FRD requirements. A disabled or absent feature must never return fabricated success or fake data as though it is implemented.

## 2. Architecture and stack

**RECOMMENDATION:** use one modular Django application, one PostgreSQL database, and one deployment definition. The browser talks to the application; the application accesses the database. Users never connect to PostgreSQL directly.

| Concern | Default | Constraint |
|---|---|---|
| Python | A supported Python release compatible with dependencies | Verify and pin the exact version at project creation |
| Web framework | Django 5.2 LTS, current supported patch | Verify support/security status before installation; no prerelease |
| UI | Django templates, ordinary forms, minimal JavaScript | No separate SPA or frontend build pipeline unless justified |
| Database | PostgreSQL, a supported stable major | Same database family in development, tests, and deployment |
| Driver | Compatible psycopg release | Pin in the dependency lock |
| Serving | Gunicorn in the Linux application container | Django development server is for local development only |
| Packaging | Docker Compose | Persistent PostgreSQL volume; production configuration separate |
| Authentication | Django sessions and password hashing | No custom password storage or homemade JWT system |
| Permissions | Central application policy functions | Framework model permissions alone do not implement account visibility |
| Tests | Django test runner; PostgreSQL-backed integration tests | Real transaction tests for locking/races |
| Logs | Structured application/error logs | Do not log passwords, cookies, full financial payloads, or secrets |
| Remote POC access | Tailscale Serve and private network access | Application login and authorization remain mandatory |

Django 5.2 is listed as an LTS release in the official support table checked on the preparation date. Recheck versions at implementation time; do not assume that a moving `latest` image is reproducible.

No Redis, Kafka, Celery, API gateway, service mesh, Kubernetes, or separate authentication service in the initial design. Do not add a generic repository layer around the Django ORM. A small service layer is for business operations, not a framework of interfaces for every database table.

## 3. Decision register: resolve contradictions deliberately

All statuses below begin as **proposed**, unless directly mandated by the source. The owner or a subsequent explicit instruction can accept or change them.

| ID | Source tension or missing rule | Recommended POC default | Resolution gate |
|---|---|---|---|
| D01 | FRD allows edit/delete of transactions | Drafts editable; posted financial fields immutable; linked reversal and replacement | Confirm before real financial use |
| D02 | Three classical account types do not specify report placement fully | Keep classical type and add reporting class plus account purpose | Adopt explicit mapping before reports |
| D03 | Shared expenses may expose information about private counterpart accounts | Restricted account-line views; redact journal-wide details unless all lines visible; explain inference limits | Confirm privacy policy before inviting real users |
| D04 | FRD allows warning-based reclassification of used accounts | Freeze used account type, reporting class, purpose, and parent in POC | Confirm departure before enabling administration |
| D05 | Bank accounts inside the book coexist with member capital | Identify which assets are in the book; internal transfers do not create contributions | Owner selects boundary before importing real opening balances |
| D06 | Inventory can skip ledger posting | Separate quantity-only items from financially valued inventory; no casual skipping for valued stock | Before inventory accounting |
| D07 | Member can view shared accounts; posting rights are underspecified | Viewing does not imply posting; own accounts plus explicit grants determine posting | Confirm before Member posting with real data |
| D08 | Sample accounts are freely editable but opening-equity roles are needed | Configure purpose by stable ID; protect referenced/required accounts from deletion | Before account management |
| D09 | Complete year-end close is in FRD | Defer close; support fiscal-year reporting and enforce a simple posting lock date | Before claiming FRD completeness |
| D10 | Placeholder exchange rate and attachments described as avoiding later redesign | INR only now; use migrations for real future features | No FX/attachment completeness claim |

### 3.1 Important domain clarifications

- A transfer between two bank accounts already included in this book changes the location of an asset; it does not automatically create income, expense, or member capital.
- Salary recognized as household income must not also be counted as a fresh contribution for the same economic event. Distinguish income, transfers, and outside contributions explicitly.
- “Personal account” in classical accounting and “private to a user” are different concepts. Use different field names.
- Members' drawings are an equity-related purpose with a normal debit balance. Do not classify them as household expenses merely because money left a bank account.
- A balanced journal can still be economically wrong. Trial-balance equality is necessary but insufficient evidence of correct accounting.
- Proposed account mapping and example postings are implementation rules for this POC, not a claim of statutory accounting compliance.

## 4. Intended repository layout

Paths below describe the repository the coding agent should create; they are not existing implementation files. Create files when a milestone needs them. Ordinary framework files such as `__init__.py` and `apps.py` are implied.

```text
household-ledger/
  ERP_BUILD_BIBLE.md
  AGENTS.md
  README.md
  .env.example
  .gitignore
  pyproject.toml
  requirements.lock
  Dockerfile
  compose.yaml
  compose.production.yaml
  manage.py
  config/
    settings/
      base.py
      development.py
      production.py
      test.py
    urls.py
    wsgi.py
  apps/
    identity/
      models.py
      services.py
      policies.py
      forms.py
      views.py
      urls.py
      migrations/
      tests/
    accounting/
      models.py
      choices.py
      services/
        accounts.py
        drafts.py
        posting.py
        reversals.py
        period_locks.py
      policies.py
      selectors.py
      forms.py
      views.py
      urls.py
      migrations/
      management/commands/
        seed_demo.py
        check_ledger_integrity.py
      tests/
        test_posting.py
        test_reversals.py
        test_permissions.py
        test_concurrency.py
    reporting/
      selectors.py
      views.py
      urls.py
      exports.py
      tests/
    operations/
      models.py
      services.py
      views.py
      migrations/
      tests/
  templates/
    base.html
    registration/
    accounting/
    reporting/
  static/
    css/
    js/
  tests/
    acceptance/
  scripts/
    backup_db.sh
    restore_db.sh
  docs/
    decisions/
      0001-architecture.md
    progress.md
    runbook.md
    feature-template.md
    sources/
      README.md
```

Use one dependency-management approach. Here `pyproject.toml` declares direct dependencies and the documented locking tool produces `requirements.lock` with exact resolved versions. Do not maintain inconsistent parallel lockfiles.

Create the custom Django user model, even if minimal, before initial migrations. Use ordinary Django relationships; do not build tenant middleware or company hierarchies now. Store source copies in `docs/sources/` only when supplied, and identify missing originals honestly. This guide can support initial scaffolding on its own.

Inventory, reconciliation, scheduling, and file-storage modules are future additions, not empty directories or placeholder services to create on day one.

## 5. Module contracts

| Module | Owns | May depend on | Must not do |
|---|---|---|---|
| Identity | User, role, authentication lifecycle | Django auth | Calculate balances or insert journal lines |
| Accounting | Accounts, access grants, journals, posting rules, lock date, reversals | Identity and activity recording | Let views or other modules bypass posting rules |
| Reporting | Read queries, aggregation, authorized exports | Accounting selectors/policies | Change journals or maintain an independent editable balance |
| Operations | Minimal activity records, health endpoints, operational commands | Minimal shared contracts | Become a bucket for unrelated business logic |
| Inventory, later | Items, movements, valuation | Accounting operation interfaces | Write ledger rows directly or value stock inconsistently |
| Reconciliation, later | Imported bank lines, matches, reconciliation sessions | Accounting read/post operations | Treat an imported bank line as automatically valid accounting |

Dependency rule: identity does not import accounting. Accounting never calls reporting. Read-only joins are acceptable within the monolith when they respect documented ownership and visibility. No module writes another module's tables directly.

An aggregate is the smallest group that must change together to remain valid. For the ledger, one journal header and all its lines form an aggregate. An entire household or all accounts are not one giant aggregate.

## 6. Domain model and persistence contract

### 6.1 Core records

| Record | Essential fields and meaning |
|---|---|
| User | Stable ID, username, framework password hash, role, active state |
| LedgerSettings | One book's name, INR base currency, Asia/Kolkata timezone, fiscal-year start, nullable locked-through date, configured opening-equity account |
| Account | Stable ID, unique code, name, classical type, reporting class, purpose, normal side, optional parent, group/leaf flag, visibility, optional owner, active flag |
| AccountGrant | User, account, can_view, can_post; unique user/account pair; posting requires visibility |
| JournalEntry | Stable ID, date, narration, entry kind, state, creator, created/posted timestamps, optimistic version, unique posting number when posted, nullable unique reversal_of |
| JournalLine | Entry, line number, account, debit amount, credit amount; unique entry/line number |
| PostingRequest | Actor, operation, idempotency key, canonical payload hash, result entry; unique actor/operation/key |
| ActivityRecord | Actor, action, object type/ID, UTC timestamp, minimal safe change metadata |

`LedgerSettings` is a singleton for the existing single-book requirement, not a tenant platform. Future multiple books require an explicit migration and enforced ownership on every affected record; an unused tenant field would not provide isolation.

Use stable surrogate primary keys; do not use names as foreign keys. Names may change. Do not infer purpose from strings such as “Bank” or “Capital.”

### 6.2 Account attributes

- Classical type: PERSONAL, REAL, NOMINAL, preserving the FRD vocabulary.
- Reporting class: ASSET, LIABILITY, EQUITY, INCOME, EXPENSE.
- Purpose: GENERAL, CASH, BANK, INVENTORY, MEMBER_CAPITAL, MEMBER_DRAWINGS, OPENING_EQUITY, as appropriate to the model.
- Normal side: DEBIT or CREDIT. Provide validated defaults; treat contra accounts explicitly.
- Visibility: SHARED or PERSONAL. PERSONAL requires one owner; SHARED has no private owner.
- Parent groups cannot receive postings. All postings go to active leaf accounts. Prevent cycles and incompatible report-class rollups.
- Used accounts cannot be deleted. Deactivation prevents new ordinary postings and retains historical reports.
- Account names and grouping appear as current labels in POC reports; do not claim full historical chart-of-accounts versioning. Classification and grouping of used accounts remain frozen under D04.

Do not require every asset balance to remain positive: the POC does not enforce bank overdraft rules. Inventory's later no-negative-stock policy is a separate invariant.

### 6.3 Precision, dates, and history

- Journal amounts: exact decimal with two fractional digits for INR, e.g. PostgreSQL NUMERIC(18,2), with corresponding Python Decimal arithmetic.
- Parse decimal input directly from text; do not pass monetary values through binary floats. Reject nonfinite values, excess input precision, and out-of-range amounts with clear errors.
- INR must be validated server-side. A currency field does not enable foreign exchange support.
- Entry date is a local accounting DATE. Creation and activity timestamps are timezone-aware UTC instants, displayed in Asia/Kolkata.
- Financial year runs 1 April through 31 March. Determine it from entry/report date rather than the server's UTC date.
- Balances derive from posted journal lines. Do not store an editable `current_balance` as an independent source of truth.
- Use a stable order such as entry date, posting number, line number for running balances. Include earlier posted activity in the opening balance of a filtered view.
- Use a database sequence or generated identifier for posting numbers; gaps are acceptable in the POC. Never use `MAX(number) + 1` under concurrency or claim statutory gapless numbering.

### 6.4 References and deletion

Protect accounts referenced by journal lines. Deactivate users rather than destroying financial attribution. Draft deletion may remove its lines in one transaction and leave an activity record. Do not apply blanket soft deletion to every table. Later retention or anonymization policies need an explicit design that preserves financial integrity and applicable obligations.

## 7. Posting contract: the most important implementation section

All entry modes, imports, inventory integrations, and scheduled jobs must eventually invoke the same accounting service. Screens translate intent into lines; they do not independently post money.

### 7.1 Commands

Use ordinary service functions with explicit inputs and actor context:

- CreateDraft / UpdateDraft / DeleteDraft
- PostEntry
- ReverseEntry
- CreateAccount / UpdateUnusedAccount / DeactivateAccount
- SetPostingLockDate

These names describe operations, not a requirement for command classes, a command bus, event sourcing, or CQRS infrastructure.

### 7.2 Required posting behavior

1. Authenticate the actor and identify the operation and idempotency key.
2. Canonicalize financial input and calculate its payload hash. A client retry must reuse its original key; a new intentional transaction uses a new key.
3. Begin an explicit database transaction. For this small POC, acquire the singleton LedgerSettings row lock to serialize financial mutations and lock-date changes. This simple coarse lock is intentional and must be measured before replacing it.
4. Find or create the uniquely constrained PostingRequest within that transaction. A repeated key and identical payload returns the original authorized result. A repeated key with a different payload is a conflict. Concurrent requests must converge to one committed result.
5. Lock and reload affected accounts in stable ID order, then the draft/original entry as needed. Account administration and draft mutation must follow the documented locking order. Recheck permissions and account state after acquiring locks.
6. Confirm the entry date is later than locked-through. Confirm INR, valid amount precision, active leaf accounts, and posting permission for every account.
7. Require two or more lines, exactly one positive debit or positive credit on each line, total debits equal total credits, and positive total value. A draft may be incomplete, but it cannot post in that state.
8. Lock-check the draft state/version. Assign a unique posting number and freeze financial fields and lines.
9. Persist the journal, request result, and financial activity record in the same transaction. Any failure rolls back the entire operation.
10. Return the committed result. Optional external effects happen after commit. There are no external effects required for POC posting.

If the process dies before commit, the database rolls back. If it dies after commit but before the response reaches the browser, a retry returns the saved result. UI button disabling is useful feedback but is not the duplicate-posting guarantee.

Keep the transaction short: no network calls, file uploads, email, or report generation while locks are held. Django `atomic()` alone does not supply business validation, idempotency, or row locking.

### 7.3 Database protections

- Foreign keys with protective deletion rules; unique line numbers, grant pairs, posting numbers, and idempotency keys.
- Check constraints for line sign/side and finite bounded decimal amounts, plus state consistency where expressible per row.
- Server-side service validation for the complete balanced entry.
- Protect posted headers and lines against financial UPDATE/DELETE through PostgreSQL triggers installed by migrations, including ORM bulk paths. Allow only documented nonfinancial metadata changes, if any.
- Enforce posted-entry balance and minimum-line rules at the transaction boundary through an appropriate deferred constraint trigger. An ordinary row CHECK cannot validate a SUM over all journal lines. Cover insertion, posting, line move/update/delete, and the OLD and NEW entry IDs where applicable.
- Use separate migration and runtime database roles. Runtime is not a superuser and cannot disable integrity protections or alter schema. Triggers protect against bypasses by normal application paths, not a malicious database administrator.

If the agent cannot implement and test a claimed database guarantee, it must report the limitation explicitly and keep that acceptance item open. Never describe an application-only check as a database constraint.

### 7.4 Draft concurrency

Use an integer version for drafts. Update only when the submitted version matches; otherwise show a conflict and reload. All edits/deletes/posting of the same draft coordinate on its row lock and state. Preserve user-entered form data when reporting a conflict. Do not silently overwrite another editor's work.

## 8. Lifecycle and correction rules

| State/action | Rule |
|---|---|
| Draft | Editable/deletable by authorized creator or Admin; no effect on balances |
| Post | Validates and commits once; becomes financially immutable |
| Reverse | Creates another balanced posted entry with debit/credit sides swapped and a unique reference to the original |
| Replace | A new corrected entry; preserve links/narration explaining the correction |
| Close/reopen financial year | Deferred; do not simulate it by deleting or resetting transactions |

Keep the original entry POSTED. Derive the “Reversed” display label from the linked reversal. Reports include both original and reversal on their respective dates. Do not filter out the original or the reversal simply because their relationship exists.

Only one direct full reversal is allowed per original entry in the POC. Partial reversal workflows are deferred. A reversal is itself immutable; corrections to it require an explicit authorized new transaction, not editing history.

For POC reversals, require every involved account to remain active and the actor to have posting rights. If an account was deactivated, Admin must explicitly reactivate it first; do not secretly bypass account checks. A reversal of an old entry may use an open-period date, preserving the original period's history.

SetPostingLockDate is Admin-only, logged, and serialized with posting. It prevents backdated posting through the chosen date. It does not perform year-end closing or capital allocation. Lowering the lock date requires an explicit Admin action with a reason, not an automatic retry.

## 9. Permissions and privacy contract

### 9.1 Recommended permissions

| Action | Admin | Member |
|---|---|---|
| View accounts | All | Shared, owned, or explicitly granted |
| Post to accounts | All valid accounts | Owned accounts and explicit can_post grants |
| Manage accounts/users/grants | Yes | No |
| Edit/delete draft | Any | Own draft, with current permissions on all included accounts |
| Reverse posting | Any permitted posting | Own posting only, if still permitted on every line |
| Full trial balance / household income-expenditure | Yes | No |
| Account activity / own authorized entry workflows | Yes | Authorized subset |
| Change lock date | Yes, with reason | No |

Shared expense accounts need explicit Member posting grants during setup. Do not make all shared accounts writable merely because they are visible.

### 9.2 Redaction policy

For a Member who can see only part of a journal, account activity may show the authorized account's date, debit/credit amount, and running balance. Suppress hidden account IDs/names, creator details, full journal narration, and links or exports exposing the complete entry. Return generic denied/not-found responses that do not enumerate private account details.

Full entry detail is available only when the actor can view every line. A mixed-visibility journal is not rendered as a complete balanced journal with selected lines silently removed. Membership or authorship alone must not bypass visibility after grants are revoked.

**ARCHITECTURAL DECISION REQUIRED:** visible shared amounts may still let members infer that someone made a transaction. This policy protects hidden account details, not perfect secrecy about all economic activity. If that inference is unacceptable, the owner must choose stricter shared-account visibility. Do not promise otherwise.

Enforce policy in queries and services, including exports, dashboard totals, search, object lookup, idempotent replay responses, and error messages. Hiding buttons is not authorization. Django Admin must not be a backdoor for editing posted rows; prefer read-only journal administration.

## 10. UI and report contract

Keep the interface simple and usable on a laptop and phone browser. The POC is a web application, not a desktop executable.

| Screen | Essential behavior |
|---|---|
| Login | Framework authentication; clear invalid-login response; no default shared password |
| Accounts | Allowed accounts, status and balances; Admin management actions |
| Add expense | Amount, date, permitted cash/bank source, expense leaf account, notes |
| Add income | Amount, date, permitted cash/bank destination, income leaf account, notes |
| Transfer | Two different permitted cash/bank accounts, amount, date, notes |
| Journal | Multiple lines, live totals and difference; server validates independently |
| Opening entry | Dated initial balance and explicit offset account; Admin-only for POC |
| Entry detail | Status, lines, allowed actions, correction references, privacy rules |
| Ledger | Opening balance, period activity, ending balance, stable running order |
| Trial balance | Admin only; all posted account balances through selected date |
| Income/expenditure | Admin only; income and expense activity within date range |

Defaults are conveniences, never hidden financial actions. Make Post explicit. Display validation errors without discarding user input. Show success only after commit. Read-only GET routes must not mutate data; use CSRF-protected POST for mutations.

Reports must:

- exclude drafts and include posted originals and reversals according to date;
- aggregate using exact decimals;
- use the same authorized query logic for screen and CSV;
- include opening activity when a date filter starts after account inception;
- distinguish activity over a period from a balance as of a date;
- avoid double-counting both parent rollups and their leaves;
- protect free-text CSV cells against spreadsheet formula injection;
- include sufficient filters and labels to explain what is being shown.

Later net-worth reports must explicitly handle current-year surplus/deficit within equity before formal closing. Later closing entries need an entry kind so operational income/expenditure reports do not incorrectly show zero activity after nominal balances are closed.

## 11. Golden demo dataset and expected results

Use synthetic accounts and dates in an open financial year. These examples are for validating this book's defined boundary.

| Event | Debit | Credit |
|---|---|---|
| Opening household cash ₹10,000 | Household Cash 10,000 | Opening Equity 10,000 |
| Salary recognized inside book ₹20,000 | Member Bank 20,000 | Salary Income 20,000 |
| Groceries paid ₹500 | Groceries Expense 500 | Household Cash 500 |
| Transfer cash into included bank ₹2,000 | Member Bank 2,000 | Household Cash 2,000 |
| Reverse groceries entry | Household Cash 500 | Groceries Expense 500 |
| Correct groceries expense to ₹450 | Groceries Expense 450 | Household Cash 450 |

Expected final balances:

- Household Cash: debit ₹7,550.
- Member Bank: debit ₹22,000.
- Groceries Expense: debit ₹450.
- Salary Income: credit ₹20,000.
- Opening Equity: credit ₹10,000.
- Trial balance: total debit ₹30,000 = total credit ₹30,000.
- Income less expense: ₹19,550.
- Cash and bank combined: ₹29,550.

A transfer alone does not affect surplus. A reversal restores the original economic effect without erasing history. Replaying the same posting request must leave these totals unchanged.

## 12. Verification gates

Use targeted tests that exercise material business guarantees. Do not substitute hundreds of superficial field tests for end-to-end correctness. Run concurrency and locking checks against PostgreSQL using independent connections and appropriate transaction-test support; an ordinary Django TestCase can conceal transaction behavior.

| ID | Test | Required outcome |
|---|---|---|
| A01 | Post balanced entry | One posted entry with all lines |
| A02 | Unequal totals, invalid precision, negative/both-sided/zero lines | Validation error; no posted effect |
| A03 | Inject failure after partial persistence | Complete rollback of financial operation |
| A04 | Same key/payload twice and concurrently | One entry and same authorized result |
| A05 | Same key/different payload | Conflict; no second entry |
| A06 | Two requests post same draft with different keys | One posting; other gets existing result/conflict |
| A07 | Concurrent draft edits | Stale editor receives conflict |
| A08 | Unauthorized IDs in form, URL, query or export | No unauthorized view or posting |
| A09 | Mixed private/shared journal | Redaction policy holds in all output channels |
| A10 | Reverse twice, including concurrently | One linked full reversal |
| A11 | Direct ORM/bulk edit/delete posted money | Database protection rejects it |
| A12 | Post against group, inactive account, non-INR, locked date | Rejected |
| A13 | Lock-date change races with posting | Serialized result; no posting past committed lock policy |
| A14 | Golden dataset | Exact balances from section 11 |
| A15 | Filter ledger to later date | Correct opening and running balances |
| A16 | Two separate device sessions | Independent identity and correct permissions |
| A17 | Restart/recreate application container | Database persists |
| A18 | Backup restored into fresh database | Records, relationships, balances and login usable |
| A19 | Direct invalid posted journal via normal DB role | Database invariant prevents commit |
| A20 | Account permission/state changes vs posting | Current policy is checked at coordinated transaction boundary |

Do not mark a gate passed unless it was executed successfully. Record what ran, environment, result, and remaining limitations in `docs/progress.md`.

## 13. Seven-day build sequence

The order is mandatory unless a documented dependency changes it. Dates are estimates; correctness gates determine readiness. If work slips, drop optional scope rather than calling an unverified ledger complete.

| Milestone | Target | Deliverable and exit gate |
|---|---|---|
| M0 | Day 1 | Inspect workspace; record assumptions/decisions; reproducible Compose start; custom user model, settings, migrations and account model |
| M1 | Day 2 | Posting operation, precision rules, idempotency and database protections; A01–A06 and A19 |
| M2 | Day 3 | Simple entry forms, transfers, opening entries, journal form; each uses M1 service |
| M3 | Day 4 | Permissions, privacy, draft conflicts, reversals, lock date and history; A07–A13 and A20 |
| M4 | Day 5 | Ledger, trial balance, income/expenditure, CSV; A14–A15 |
| M5 | Day 6 | Shared-test deployment, private access, backup/restore runbook; A16–A18 |
| M6 | Day 7 | Family walkthrough, defect fixes, complete critical regression tests, honest completion report |

Each milestone should leave the project runnable. Prefer small vertical changes. Do not generate the entire FRD in a single unreviewable code dump. M0 may proceed while domain decisions are open; affected real-data workflows may not.

## 14. Operational runbook requirements

The coding agent must write exact commands verified against the repository it actually creates. Do not copy commands from this guide as if they already exist.

Document:

1. Prerequisites for the owner's OS, including Docker setup. Do not assume Windows, macOS, or Linux until inspected or confirmed.
2. Environment creation from `.env.example`; placeholders only in source control.
3. Image build, database readiness, explicit migrations, initial Admin creation, and optional synthetic seeding.
4. Start, stop, logs, health status, and application URL.
5. Private remote access and permitted devices/users; keep PostgreSQL unexposed to the public network.
6. Django production settings: DEBUG off, allowed hosts, CSRF trusted origins where needed, secure session cookies, HTTPS handling and correctly trusted proxy headers.
7. Basic login abuse protection appropriate to the private POC; avoid storing identity secrets in logs.
8. Backup creation, off-laptop encrypted copy, retention, failure detection, and restore rehearsal into a separate database.
9. Dependency updates and migration procedure; do not run competing migrations automatically in every app worker.
10. Failure recovery and known availability limits. Laptop sleep, power loss, and network loss interrupt access.

**RECOMMENDATION:** daily backup and another before deployments, with an initial 24-hour recovery-point target and a 2-hour recovery-time target for the pilot. These are goals until demonstrated. A PostgreSQL volume is persistence, not backup; a CSV export is not a complete backup. Restore scripts must require explicit target selection and protect against accidental overwrite of the active database.

Do not execute destructive cleanup such as deleting volumes as a routine troubleshooting step. Never put real data or secrets in demo fixtures or Git.

## 15. Future domain workflows

### 15.1 Inventory

Add items, fixed item units, movement records, optional batches and explicit valuation policy when required. Do not mix arbitrary kg/g or packet conversions without defined conversion rules. Quantity-only movements and valued inventory are different modes, clearly shown in the UI.

For valued inventory, choose one initial costing method and specify rounding, returns, write-offs, negative-stock policy, and backdated movements. Lock affected stock records consistently. Confirmed stock movement and associated balanced journal commit in the same database transaction. Enforce a unique source-operation reference to prevent double posting. A financial valuation report must reconcile to inventory ledger control accounts.

Do not capitalize a purchase into inventory and also immediately expense that same value without an intentional consumption transaction. FIFO and weighted-average are not interchangeable toggles after history exists.

### 15.2 Bank reconciliation

Stage bank imports separately from journal entries. Preserve original source details and identify duplicate imports without assuming date+amount is a unique transaction. Suggest matches; users confirm ambiguous matches. Reconciliation links evidence to existing bank ledger lines. An unmatched bank row requires a deliberate new posting, not silent creation.

### 15.3 Recurring transactions

Store the recurrence rule and scheduled occurrences. Each occurrence has a unique identity derived from rule and scheduled date/time. A retry must not generate another journal. Define behavior while the laptop is asleep, after permission revocation, when dates are locked, and when a rule changes. Begin with reviewable due drafts if automatic posting remains unsettled.

### 15.4 Year-end closing

Treat closing as a distinct, idempotent operation with an accepted allocation policy, rounding handling, preview, explicit confirmation, resulting entries and lock. Specify zero/negative capital handling before proportional allocation. Do not double-count asset/liability carryforward by inserting new opening entries into an already continuous ledger.

Keep accounting closure distinct from report presentation. Reopening requires controlled treatment of existing closing entries before reclosing; do not silently rerun transfers into capital.

### 15.5 Attachments, budgets, multiple books

Add attachments through a storage interface and migrations when needed; enforce access on file downloads. Add budgets as account/period amounts read alongside ledger actuals. Multiple books need book ownership, scoped constraints, authorizations, migrations of existing data, and isolation tests. None is solved by a generic JSON column or unused foreign key.

## 16. Evolution roadmap and business priorities

| Stage | Build now | Do not build yet | Only if needed | Trigger to advance / business aim |
|---|---|---|---|---|
| POC | Correct entry/report loop; invited users; restore | Microservices, public signup, full FRD | Quantity-only inventory demo | Users complete real tasks and identify a reason to return; learn |
| MVP | Better onboarding, account setup, selected FRD workflows, hosted access | Enterprise feature suite | Reconciliation or inventory based on observed demand | Repeated usage beyond supervised demos; validate usefulness |
| First customers | Reliable backups/recovery, privacy policy, support process, migration discipline | Customer-specific forks | Simple billing and customer isolation for the chosen deployment model | Willingness to pay and repeatable onboarding; earn trust |
| Growth | Measure latency, contention, job backlog, support burden | Sharding and service mesh by default | Worker, queue, app replicas, report summaries | Persistent measured bottlenecks or repeatability problems |
| Scale | Capacity planning, failure recovery drills, workload isolation | Automatic split of every module | Service extraction or data partitioning for specific evidence | Independent workload/team needs justify operating cost |
| Enterprise | Customer-required controls, SSO, audit/retention, recovery commitments | Generic enterprise platform without buyers | Dedicated deployments, integrations, isolation tiers | Contracted needs and ability to operate commitments |

The first hosted move keeps the application and PostgreSQL model. Freeze writes, back up, restore to the host, verify counts and golden/accounting totals, configure access, and switch users. Define rollback without two writable copies. After hosted writes begin, restoring an old laptop copy loses new activity; a rollback then needs a fresh consistent data transfer.

Before multiple application instances, externalize per-process session/file state, coordinate background execution, and verify migrations are executed once per release. DB-backed sessions are suitable for the initial design.

Measure before changing architecture. Suggested investigation targets, not guaranteed SLAs: typical interactive reads at p95 under one second and posting at p95 under two seconds on the agreed pilot dataset/network. Separate network delay from app and database time. Investigate sustained target failures, recurring lock waits, backup failures, or growing job queues; there is no universal user-count threshold for microservices.

## 17. Decision framework for new complexity

| Question | Default | Change when | Failure mode to prevent |
|---|---|---|---|
| Synchronous or asynchronous? | Synchronous for posting and validation | Work is long, retryable and outside the immediate invariant | Partial ledger success hidden behind a job |
| Need an event? | Direct service call within monolith | A distinct side effect or consumer benefits | Event emitted before transaction commits |
| Need a queue? | No | Durable background processing/retries are required | Lost jobs and duplicate financial effects |
| Need an outbox? | No external financial side effects in POC | DB commit must reliably lead to message delivery | Assuming `on_commit` alone guarantees eventual delivery after crashes |
| Cache a result? | Query indexed database | Profiling proves recurring expensive reads | Stale money or another user's private data in shared cache |
| New module? | Existing owner handles cohesive behavior | A distinct vocabulary, lifecycle, ownership and tests emerge | Module-per-table fragmentation |
| New service? | Keep one application | Independent scaling/release/failure needs exceed distributed cost | Network calls inside previously atomic accounting changes |
| Another database? | One PostgreSQL database | Demonstrated isolation/workload/technology requirement | Losing referential integrity and easy transactions |
| Denormalize or duplicate? | Normalized source of truth | Measured read bottleneck with rebuildable projection | Two editable balances disagreeing |
| Eventual consistency? | No for ledger posting | Derived analytics or notifications can tolerate lag | Stale balance presented as final posting outcome |
| Transactional operation? | Yes when partial success violates an invariant | Independent effects with explicit recovery contracts | Overlarge transaction including network calls |
| Configurable? | Configure actual household choices | Multiple real users need different valid behavior | Every business rule becoming editable configuration |
| Generic framework? | Explicit domain code | Repeated stable patterns across real use cases justify it | Speculative rules/workflow engine |
| Optimize? | Correctness, indexes, then measurement | Reproducible bottleneck | Unmeasured caching and complexity |
| Add abstraction? | Concrete service/model | Repeated boundary or actual alternative implementation | One interface and factory per class |
| Extract infrastructure? | Small adapter where external system exists | A second implementation or operational need appears | Framework for integrations that do not exist |
| Split a component? | Cohesive module | Ownership and release needs diverge | Splitting the journal header from its lines into services |

Replication is not backup. A queue is not an exactly-once guarantee. Containers are not automatically microservices. PostgreSQL growth does not automatically require sharding. A log of user actions is not a compliant, tamper-proof audit system.

## 18. Feature design protocol

Before significant code, write a short note answering:

1. What user problem and observable outcome justify the feature?
2. Is it in the active milestone? What is explicitly excluded?
3. Which module owns it, and which existing concepts change?
4. What is the aggregate and what invariants must hold?
5. What states/transitions and permissions apply?
6. What data is new, mutable, immutable, derived, or historical?
7. What is the transaction boundary and lock order?
8. What happens on failure, retry, timeout and simultaneous requests?
9. What side effects occur, and can they be reconstructed/retried?
10. Which reports, privacy rules, exports and integrations are affected?
11. What migration, deploy and recovery steps are required?
12. What evidence will establish correctness? Is an ADR needed?

The daily short form is: **Business → Domain → Owner → Aggregate → Invariants → Permissions → Transaction → Persistence → Side effects → Operations → Acceptance.**

Choose representations deliberately: a field describes one object; a value object combines inseparable validated values; an entity has enduring identity; an aggregate enforces one transactional boundary; a workflow coordinates meaningful transitions; a module owns cohesive domain behavior. A new table alone does not justify a module or service.

## 19. AI coding-agent constitution

The agent must:

- Read this guide, the repository's current instructions, decisions and progress before editing.
- Inspect existing files and preserve user changes. Never assume an empty repository or overwrite a working implementation without review.
- Work on the current milestone and produce runnable, reviewable changes.
- Keep posting, permissions, and reporting centralized; do not duplicate their rules in views, JavaScript, imports or tasks.
- Use framework authentication, migrations and database transactions; respect the data model and immutable history.
- Verify APIs against the installed version's official documentation when uncertain.
- Implement and run material acceptance tests, including failures and PostgreSQL concurrency.
- Update progress with changes, executed checks, limitations and next action.
- Record architecture changes openly and explain their trigger.
- Distinguish `implemented`, `tested`, `manually verified`, `proposed`, and `deferred`.
- State **ARCHITECTURAL DECISION REQUIRED** when a material ambiguity cannot be resolved safely; describe the decision and recommended option, then continue independent work.

The agent must not:

- Install speculative scalability infrastructure or create empty future modules.
- Use floats for money, a client-supplied balance, or JavaScript-only validation.
- Permit posted edits through admin, bulk update, scripts or alternative endpoints.
- Treat UI hiding as authorization or leak hidden journal details through reports.
- Use `MAX + 1` numbering, frontend-only deduplication, or automatic unbounded retries.
- Replace PostgreSQL tests with SQLite and claim locking behavior is verified.
- Fake passing tests, screenshots, migrations, backups, or completion.
- Invent accepted business rules or describe this proposal as statutory compliance.
- Deploy publicly, expose ports, create paid resources, send messages, delete volumes, or overwrite real data without the authorization appropriate to that action.
- Treat a recoverable file edit or ordinary development step as needing repeated permission when already authorized.

## 20. ADR, progress, and anti-pattern templates

### 20.1 ADR template

Record: ID/title; status (proposed/accepted/superseded); date; problem; context; options; decision; why; trade-offs; consequences; verification; revisit trigger; who accepted it.

Use ADRs for domain-boundary choices, posted-entry mutability, permission policy, money representation, inventory valuation, customer isolation, major dependencies and deployment topology. Do not create an ADR for every helper function or CSS choice.

### 20.2 Progress record

Each update includes milestone, completed behavior, changed files, migrations, commands actually run, results, known limitations, open decisions, and next executable step. Do not write “all tests pass” without the relevant command/result. Keep the bible authoritative; progress is a factual work log, not a competing specification.

### 20.3 Specific anti-patterns

| Problem | Why it happens | Risk | Better approach |
|---|---|---|---|
| One income/expense table without journal lines | Fast first form | Transfers, splits and balances need a rewrite | One balanced journal model from day one |
| Editable posted transactions | Ordinary CRUD habit | History and reports silently change | Drafts plus reversals |
| Classical type conflated with visibility | Similar word “personal” | Wrong reports and data leaks | Separate classification and access fields |
| User-defined account names drive behavior | Convenient string checks | Rename breaks postings | Stable purpose and IDs |
| Every module updates balances | Local convenience | Conflicting sources of truth | Central accounting operation |
| Shared-account visibility reveals whole journal | Header-level authorization | Private counterpart leakage | Authorized projections and all-lines detail checks |
| Add every primer component | Mistaking catalogue for architecture | One-week scope collapses | Evidence-driven additions |
| Cash transfer counted as income | Ignoring book boundary | Inflated surplus | Explicit transfer semantics |
| Infinite customization for first customer | Trying to satisfy every request | Unmaintainable forks | Validate common needs and bounded configuration |
| AI declares success from compilation | Optimizing for quick completion | Incorrect money despite runnable UI | Domain acceptance tests and restore proof |

## 21. One-page constitution

1. One household book; multiple users; one authoritative ledger.
2. Every posted financial operation is balanced, authorized and atomic.
3. Money uses exact decimals; dates and fiscal periods have explicit meanings.
4. Posted financial history is immutable; corrections preserve links and history.
5. Every entry mode uses the same posting operation.
6. Retries and concurrent requests cannot create duplicate postings.
7. Permissions apply to queries, services, reports, exports and errors.
8. Account balances and reports derive from posted lines.
9. Privacy, classical account type, reporting class and ownership are separate concepts.
10. One modular application and PostgreSQL are sufficient until evidence says otherwise.
11. Keep the POC small; document deferred FRD capabilities honestly.
12. A successful backup is not recovery until a restore has been demonstrated.
13. Migrations and selective refactoring are expected; speculative scaffolding is not future-proofing.
14. New infrastructure needs a measured problem, a decision record and operational ownership.
15. No agent may invent accepted domain decisions or claim unexecuted verification.

## 22. Handoff instruction to paste into a coding agent

> Read `ERP_BUILD_BIBLE.md` completely and use it as the proposed implementation reference for this project. Inspect the existing workspace and its instructions before making changes. Preserve existing work. Begin with milestone M0 and proceed through the milestones in order as the session permits; do not stop merely after presenting a plan. Use the recommended defaults for reversible setup and synthetic-data development, while recording their proposed status accurately. Flag the specific decisions that must be settled before real-data use, without blocking unrelated implementation. Build runnable increments, execute the relevant acceptance tests, and update `docs/progress.md` after each milestone. Do not implement the deferred FRD scope, add speculative infrastructure, or claim anything is tested unless you executed it. At the end of a session, report what works, what was verified, unresolved decisions, and the exact next step. Public deployment, paid resources, destructive data operations, and real-data imports require the appropriate explicit authorization.

## 23. Source and documentation references

User-supplied sources: `Household_Accounting_ERP_FRD (1).docx` (FRD v1.0, July 2026), `System Design Components Primer.txt`, `Pasted markdown.md`; plus the request for a laptop-hosted, multi-user POC within one week. Recommendations in this guide are not claims made by those documents.

Primary technical references checked during preparation or the preceding architecture review:

- Django releases and support: https://www.djangoproject.com/download/
- Django transactions: https://docs.djangoproject.com/en/5.2/topics/db/transactions/
- Django deployment checklist: https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
- PostgreSQL numeric types: https://www.postgresql.org/docs/current/datatype-numeric.html
- Docker Compose production deployment: https://docs.docker.com/compose/how-tos/production/
- Tailscale Serve: https://tailscale.com/docs/features/tailscale-serve

Verify version-specific syntax when implementing. The detailed domain rules, proposed locking design, scope choices and acceptance criteria are recommendations synthesized for this project, not quotations from these references.
