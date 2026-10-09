# Household Ledger ERP — Implementation Plan

Version: 2.0  
Revised: 8 October 2026  
Status: proposed implementation baseline; documentation only  
Direction: local Windows development → hosted pilot → measured growth

## 1. Purpose, sources, and decision status

Build a correct household accounting POC locally using the PostgreSQL installation already prepared, then deploy the same Django application to managed hosting. Preserve the build guide's accounting, authorization, and recovery guarantees.

This revision follows the owner's request to prepare for later hosting on Vercel or a similar service and eventual growth. **Render is the recommended first host in this plan; the owner has not yet explicitly selected a provider or approved a hosting budget.** Local implementation and deployment preparation can proceed independently of that choice. Provisioning paid resources, publishing the application, and transferring real data require the appropriate user authorization.

Source order:

1. The owner's current instructions and subsequently accepted decisions.
2. Accepted, dated architecture decision records (ADRs) resolving specific conflicts.
3. [Original FRD](Household_Accounting_ERP_FRD%20%281%29.docx), v1.0, July 2026, for product intent.
4. [Build Bible](ERP_BUILD_BIBLE.md), v1.0, 6 October 2026, for proposed domain rules and POC boundaries.
5. This plan for execution, deployment preparation, and the explicitly documented revisions below.

The Bible's references to `System Design Components Primer.txt` and `Pasted markdown.md` cannot be checked because those files are absent. No application, migrations, tests, or deployment currently exist. Environment observations and owner-reported setup are distinguished below.

### Changes from the previous plan

| Area | Revised approach | Reason/status |
|---|---|---|
| Local runtime | Python virtual environment and native Windows PostgreSQL | Uses the installed software and completed owner setup |
| Docker | Available for isolated PostgreSQL tests and Linux checks; not mandatory for everyday development | No need to run a second development database |
| First hosted pilot | Recommend one Render web service and managed PostgreSQL | Proposed provider choice; supports the Django service model |
| Tailscale | Optional only for an interim laptop-hosted pilot | Not required for ordinary access to the hosted application |
| Hosting delivery | Prepare and rehearse before provisioning; verify hosted behavior once access and budget are settled | Hosting is a separate readiness gate |
| Report coverage | Ledger, trial balance, income/expenditure only in POC | Net worth and cash flow remain deferred FRD requirements |
| A19 | Test direct invalid posted journals through the normal database role | Restores the Bible's test definition; A11 covers posted edits/deletes |
| Implementation sequence | Enforce foundational permissions and atomic audit writes with the core services | Later permission UI work must not imply earlier insecure service behavior |
| Growth | Keep one book in POC; explicitly decide future customer isolation | More application instances alone do not provide multiple household books |

Record these departures in `docs/decisions/0001-development-and-hosting.md` during M0, with local setup facts, proposed provider choice, and accepted decisions labeled accurately. The original FRD and Bible remain source documents; this revision does not silently resolve their domain conflicts.

## 2. Current readiness and prerequisites

### 2.1 Observed and reported setup

| Item | Evidence as of 8 October 2026 | Next action |
|---|---|---|
| Windows workspace | Three source documents; no Git metadata or application code observed | Scaffold after implementation is requested |
| PostgreSQL | 18.6 installed; Windows service and localhost:5432 readiness verified earlier | Verify authenticated connections during M0 |
| Local listening/authentication | Earlier configuration used all interfaces and local SCRAM rules; owner reports changing listening to localhost and restarting | Verify effective setting; do not assume the original observation still applies |
| Database | `household_ledger` visible in supplied screenshot; owner reports owner/encoding checks complete | Verify UTF-8, ownership, and grants |
| Roles | `ledger_migrator` and `ledger_app` visible; owner reports setup complete | Test passwords locally and actual privilege boundaries |
| Database access | Owner reports PUBLIC access revoked and application CONNECT granted | Tables and their grants have not yet been created |
| Python | 3.12.9 observed | Select a maintained compatible 3.12 patch and pin it for development/hosting |
| Git | 2.52.0 observed | Initialize repository in M0 |
| Docker / WSL | Docker engine 29.3.0 responding; WSL 2 available | Use for isolated tests when needed |
| pgAdmin | Owner is using it successfully | Administration remains available |
| Tailscale | Not found during earlier inspection | No installation required for hosted path |
| Hosting / Git remote | Not established in this workspace | Needed before publishing, not to begin local work |

Observed versions are an inventory, not a promise that each is the latest security patch. Recheck compatible maintained versions when locking dependencies. Do not reinstall functioning tools merely to match a document.

### 2.2 Owner information needed at the appropriate time

| Input | When needed | Interim behavior |
|---|---|---|
| Database role passwords | M0 authenticated connection setup | Owner enters/stores them locally; never paste them into chat or source |
| Household display name and initial Admin username | First usable demo | Synthetic household name and locally created demo identity |
| Admin email | If email-based account recovery is enabled | No email integration required for the initial POC |
| Real book boundary and domain decisions in section 5 | Before affected real-data workflows | Synthetic accounts and transactions |
| Hosting provider, region, budget, account access, Git remote destination | Before provisioning/publishing | Prepare Render configuration as proposed |
| Domain name | Optional before public launch | Provider-assigned hostname is sufficient for pilot |
| Meaning of “scale up” | Before committing to a multiple-customer schema or accepting another household | One household with invited users |

No external API keys are required for local accounting. Cloud credentials belong in provider secret storage when hosting begins.

## 3. Architecture and environment contract

### 3.1 Proposed environments

| Environment | Application | Database and data |
|---|---|---|
| Local development | Django in Windows `.venv`; development server bound to loopback | Existing PostgreSQL 18, `household_ledger`; synthetic data initially |
| Automated tests | Same application and dependency versions; PostgreSQL transaction tests | Disposable PostgreSQL 18 instance/database; never the development or hosted database |
| Hosted staging | Linux Django/Gunicorn web service; same release artifact | Separate managed PostgreSQL database and credentials; synthetic data |
| Hosted production pilot | One Linux Django/Gunicorn web service, HTTPS, invited accounts | Managed PostgreSQL 18; actual records only after domain/recovery gates |

Render documents Django web services and managed PostgreSQL. Its current database guidance supports PostgreSQL 18 and recommends keeping app and database in the same region. Use this as the proposed hosting path and recheck availability before provisioning. [Render Django guide](https://render.com/docs/deploy-django), [Render database connections](https://render.com/docs/postgresql-creating-connecting)

A staging environment may be provisioned temporarily if budget requires it; it must still have a separate database. Preview builds and automated tests must never receive production database credentials. The production app must work while the owner's laptop is off.

### 3.2 Stack and portability

- Python 3.12, Django 5.2 LTS, PostgreSQL 18, and psycopg 3; verify and pin exact supported versions during M0.
- Django templates, ordinary forms, and minimal JavaScript. No separate frontend is needed for the POC.
- One modular application: identity, accounting, reporting, operations.
- Django sessions stored in PostgreSQL. Application instances hold no authoritative financial or session state in memory.
- Gunicorn is the proposed Linux hosting server; do not require it to run natively on Windows.
- WhiteNoise plus collected versioned static assets for the proposed Render service. Future user uploads require object storage with download authorization.
- `pyproject.toml` declares dependencies; one documented locking tool generates `requirements.lock`. Validate installation on Windows and Linux, including platform-specific server dependencies.
- Configuration comes from environment variables. No embedded laptop paths, localhost fallbacks in production, or credentials in source.
- Docker Compose may provide isolated tests or a production-runtime rehearsal. Use a separate test volume/port; keep the owner's native database untouched.
- Node.js, a Vercel CLI, Redis, Celery, Kubernetes, and a separate API are not prerequisites for the chosen POC.

The project remains one deployable Django application. Hosting-specific files configure the environment and must not contain accounting rules.

### 3.3 Database roles, credentials, and testing

The existing local `ledger_migrator` owns the database and applies schema migrations. `ledger_app` runs normal application requests and must not own the ledger tables, inherit the migration role, create schema objects, disable triggers, or become a superuser.

M0 must establish CONNECT, schema USAGE, necessary table DML, and sequence privileges for the runtime role. Configure default privileges for objects created by the migration role and verify existing objects after migrations. Avoid blanket ownership or schema-control grants. The `postgres` superuser is used only for explicit local administration.

Hosted provisioning must reproduce these privilege boundaries using the provider's supported roles. Test constraint triggers, sequences, grants, and ordinary-role behavior on the actual managed database before declaring it compatible.

The supplied roles have NOCREATEDB. Django's test runner normally creates a test database, so testing needs an explicit arrangement: use a disposable PostgreSQL instance with a test-only migration/owner credential permitted to create test databases, plus a restricted test runtime role. Scope those credentials to that disposable instance. Do not grant database-creation rights to the production application role. Test configuration must reject the development database name and production hosts. [Django test database guidance](https://docs.djangoproject.com/en/5.2/topics/testing/overview/)

Proposed configuration names:

| Variable | Purpose | Handling |
|---|---|---|
| `DATABASE_URL` | Runtime connection using `ledger_app` or hosted equivalent | Secret; required explicitly outside local defaults |
| `MIGRATION_DATABASE_URL` | Schema-owner connection | Secret available only to the dedicated migration process |
| `TEST_DATABASE_URL` | Disposable test database setup | Test-only credential; reject unsafe targets |
| `DJANGO_SECRET_KEY` | Session and application signing | Generate separately for each environment |
| `DJANGO_SETTINGS_MODULE` | Explicit local, test, or production settings | Production configuration must fail closed on missing required values |
| `ALLOWED_HOSTS` | Exact served hostnames | No wildcard in production |
| `CSRF_TRUSTED_ORIGINS` | Required HTTPS origins, where applicable | Exact origins; no broad wildcard |
| `PORT` | Host-provided web port | Read by the Linux start command |

Only load migration credentials in a controlled process whose Django database connection uses them; ordinary web startup uses the runtime URL. A separate variable in the same long-lived web environment is not secret isolation. If the chosen platform cannot isolate migration credentials within its deployment hook, run migrations through a separate controlled release job.

No tables need to be created manually in pgAdmin. Django migrations and reviewed SQL migrations create the schema and integrity protections.

## 4. POC scope and source traceability

| Capability | Initial acceptance | Source |
|---|---|---|
| Identity | Admin/Member, individual logins, logout, user activation/deactivation, no public registration | FRD §3; Bible §9 |
| Accounts | Starter examples, classical type plus reporting class/purpose, groups/leaves, shared/personal visibility, safe editing/deactivation | FRD §4; D02/D04/D08 |
| Entry | Income, expense, transfer, full journal, dated opening balance with explicit offset | FRD §§5–6.2 |
| Lifecycle | Editable drafts, explicit posting, linked full reversal and corrected replacement | Bible §§7–8; D01 |
| Reports | Authorized account ledger, Admin trial balance, Admin income/expenditure, CSV | FRD §6.7 and subset of §9 |
| Operations | Minimal activity records, health check, error reporting, backup and verified restore | Bible §§12–14 |
| Hosting | Deployment configuration, synthetic staging rehearsal, then hosted pilot after release gates | Owner's current direction |

Classical PERSONAL/REAL/NOMINAL, private visibility, ownership, reporting class, and account purpose are separate concepts. Transfers between included assets do not become income or capital. Drawings are equity-related; salary and outside contributions must not double-count the same event.

Deferred FRD capabilities remain real requirements:

| Capability | Reason / future contract |
|---|---|
| Balance sheet / household net worth | Define treatment of current-year surplus and report classification before adding it |
| Cash flow statement | Define household, investing, and financing classifications |
| Recurring postings | Durable occurrence identity, retries, permission/lock checks, and missed-run behavior |
| Bank reconciliation | Staged imports, duplicate detection, confirmed matches, deliberate new postings |
| Inventory, vendors, expiry/reorder features | Separate quantity-only from valued stock; costing and ledger reconciliation need their own design |
| Year-end closing/reopening | Accepted capital allocation, closing entry kind, preview, idempotency, and controlled reopening |
| Dashboards, category trends | Read the existing report calculations; optional basic monthly totals only after core gates |
| Tags | Additional analysis feature outside the first acceptance scope |
| Budgets | Future account/period amounts compared with ledger actuals |
| Receipts/attachments | Storage/access design and migration; no unused file relationship claimed as implementation |
| Foreign exchange | INR only now; no active FX or placeholder rate claimed as future-proofing |
| Multiple books, companies, billing, public signup | Separate scope and isolation decision; no implied support |

The FRD's requests for advance attachment, budget, and exchange-rate schema provision differ from the Bible's recommendation to add them through migrations. Preserve that difference as proposed scope under D10; do not call the full FRD complete.

## 5. Decision register and gates

Current planning defaults support reversible scaffolding and synthetic-data development. They are not owner approval of accounting policy.

| ID | Status | Proposed rule / question | Required resolution |
|---|---|---|---|
| D01 | Proposed | Posted money is immutable; corrections use reversal/replacement | Before real financial posting |
| D02 | Proposed | Add Asset/Liability/Equity/Income/Expense reporting class and explicit account mapping | Before interpreting reports as accepted accounting output |
| D03 | Owner decision pending | Redact hidden counterpart details; shared amounts may still reveal activity | Before inviting real users with private records |
| D04 | Proposed departure from FRD | Freeze type, reporting class, purpose, normal-side semantics, and parent of used accounts; permit harmless label edits | Before real account administration |
| D05 | Owner decision pending | Which bank/cash/assets belong inside the household book? | Before real opening balances or imports |
| D06 | Proposed | Quantity-only inventory separate from valued inventory | Before inventory design |
| D07 | Owner decision pending | Members post to owned accounts and explicit grants; shared viewing alone gives no posting right | Before member posting with real data |
| D08 | Proposed | Protect used/configured accounts, including opening equity, by stable ID | Before real account deletion/administration |
| D09 | Proposed scope reduction | Posting lock date now; formal closing/reopening later | Before real pilot scope is accepted |
| D10 | Proposed scope reduction | INR only; future FX, attachments, and budgets use explicit migrations | Before claiming source-scope acceptance |
| D11 | Proposed hosting choice | Render web service plus managed PostgreSQL; Vercel remains an alternative | Provider, region, plan, and budget before provisioning |
| D12 | One-household first release accepted by owner on 8 October 2026 | Begin with one household and invited family members; future customer isolation is a separate decision | Before a multiple-customer schema or onboarding a second household |

April–March financial years and one household book are source requirements, not new questions. Do not silently change them because cloud hosting is introduced. If near-term multiple-household SaaS becomes a requirement, revisit the single-book schema before building the affected models.

## 6. Intended repository layout

Recommended implementation location: the existing workspace root, `C:/Users/Harshit/OneDrive/Desktop/accounting_ledger`, so source documents and application have one repository. This replaces the earlier proposed nested `household-ledger/` directory. Create files as their milestones need them.

```text
accounting_ledger/
  ERP_BUILD_BIBLE.md
  Household_Accounting_ERP_FRD (1).docx
  implementation_plan.md
  AGENTS.md
  README.md
  .gitignore
  .env.example
  pyproject.toml
  requirements.lock
  manage.py
  config/settings/{base,development,test,production}.py
  config/{urls,wsgi}.py
  apps/identity/
  apps/accounting/{services,management/commands,migrations,tests}/
  apps/reporting/
  apps/operations/
  templates/
  static/
  tests/acceptance/
  scripts/
  render.yaml
  docs/decisions/
  docs/archive/
  docs/progress.md
  docs/runbook.md
  docs/feature-template.md
```

`.venv`, `.env`, dumps, logs, generated assets, and credentials are excluded from Git. Keep live PostgreSQL data in its installed data directory, outside the OneDrive project. Do not commit real financial fixtures. Any production secret file should also be kept outside synchronized folders.

Identity owns users/authentication; accounting owns accounts, grants, journals, and posting; reporting reads authorized accounting data; operations owns ActivityRecord and operational behavior. Accounting does not depend on reporting. Other modules never insert ledger rows outside accounting services.

## 7. Milestones and executable exit gates

Seven days remains an indicative effort sequence for the local POC, not a delivery guarantee. Hosted provisioning, owner decisions, restore work, and defects can extend it. Prepare cloud configuration early and avoid deferring hosting compatibility discovery until the last day. Record every actual result in `docs/progress.md`.

### M0 — Foundation and database verification (target Day 1)

1. Inspect current workspace and preserve changes; initialize Git only when implementation begins.
2. Create the virtual environment, dependency lock, environment-specific settings, and README.
3. Verify both local logins, database ownership/encoding, localhost binding, and permissions without printing secrets.
4. Set up the custom User before initial migrations. Define Account, AccountGrant, singleton LedgerSettings, JournalEntry, JournalLine, PostingRequest, and Operations.ActivityRecord.
5. Preserve exact Decimal/NUMERIC(18,2), stable IDs, INR validation, local accounting dates, UTC timestamps displayed in Asia/Kolkata, and April–March reporting.
6. Establish login/session handling, central policy interfaces, and restricted administration. No writable journal admin.
7. Provision disposable PostgreSQL tests with distinct migration/runtime roles.
8. Add a minimal Linux runtime/build rehearsal using the same lock; outline Render configuration and a health endpoint. No cloud account is needed for local rehearsal.
9. Write the development/hosting ADR and honest initial progress record.

**Exit:** application starts locally, checks/migrations succeed, custom user exists, runtime can perform permitted operations but cannot alter schema, isolated test target is proven, and Linux dependencies install. No real-data readiness claim.

### M1 — Posting engine and database guarantees (target Day 2)

Implement the full Bible §7 transaction protocol:

- Canonical input and idempotency hash; unique actor/operation/key.
- Lock LedgerSettings, then affected accounts in stable ID order, then relevant draft/original. Coordinate financial changes, account/grant/role changes, and posting locks under a documented order.
- Reload current actor/account/permission state inside the coordinated transaction.
- Require open date, INR, active leaf accounts, posting permission on every line, at least two valid lines, positive equal totals, finite bounded two-decimal amounts.
- Post once; assign a database-sequence number; commit entry, lines, request result, and activity record together.
- Implement draft version conflicts, account management, reversal service, and lock-date service foundations.
- Add protection of posted financial headers/lines against insert/update/delete bypasses as appropriate, plus deferred validation of posted balance/minimum lines at transaction end. Cover both OLD and NEW journal IDs when a line moves.
- Keep the runtime role unable to bypass protections. No network calls inside financial transactions.

**Exit:** A01–A06 and A19 pass on PostgreSQL; perform A11 database immutability checks as soon as protections exist. Implement policy and audit enforcement now; M3 adds its complete UI and adversarial coverage.

### M2 — Accounts and entry workflows (target Day 3)

1. Build Admin account creation/editing/deactivation and safe grouping; protect used/configured accounts.
2. Build income, expense, transfer, full journal, opening balance, draft, entry detail, and reversal/replacement flows on the central services.
3. Restrict every account picker and request server-side. Full journal detail requires visibility of all lines from its first implementation.
4. Preserve form input on errors; show success only after commit; live totals supplement server validation.
5. Seed synthetic users/accounts and the Bible §11 dataset through normal services. No shared default password or real account values.
6. Use responsive templates for laptop and phone.

**Exit:** an Admin and a limited Member complete permitted workflows locally; drafts do not affect balances; invalid or unauthorized submissions fail without financial effect.

### M3 — Complete privacy, grants, and administration (target Day 4)

1. Complete user activation/deactivation, role administration, and account view/post grants.
2. Verify members' own-draft editing and own-entry reversal under current permissions.
3. For mixed-visibility activity, show only authorized line date/amount/balance; suppress narration, hidden identities, creator data, and complete-entry links.
4. Apply the same policy to lookup, search, CSV, errors, and idempotent replay. Revoked visibility cannot be bypassed by authorship.
5. Complete stale-draft UI, locked-period feedback, and reasoned Admin lock-date lowering.
6. Keep the original POSTED after reversal; only the derived display label changes. One direct full reversal per original; all involved accounts must remain active and authorized.
7. Audit financial changes atomically and administrative changes with minimal safe metadata.

**Exit:** A07–A13 and A20 pass, including independent-connection races. A09 export coverage is completed when M4 creates CSV export.

### M4 — Reports and export (target Day 5)

- Account ledger: opening balance, period activity, closing balance; order by accounting date, posting number, line number.
- Admin trial balance: balances through an as-of date.
- Admin income/expenditure: income and expenses within a date range.
- Authorized CSV uses the same selectors and neutralizes formula interpretation in free-text cells.
- Exclude drafts; include originals and reversals at their actual accounting dates.
- Aggregate exact decimals; include pre-period opening activity; do not double-count parent rollups and leaves.

Golden dataset expected results: Cash Dr ₹7,550; Bank Dr ₹22,000; Groceries Expense Dr ₹450; Salary Income Cr ₹20,000; Opening Equity Cr ₹10,000. Trial balance totals ₹30,000 each; surplus ₹19,550; cash plus bank ₹29,550. Retrying identical requests leaves totals unchanged.

**Exit:** A14–A15 and complete A09 pass. This covers three FRD §9 reports, not net worth or cash flow.

### M5 — Deployment preparation, hosted rehearsal, and recovery (target Day 6+)

**M5a: prepare locally**

- Implement production settings, Linux Gunicorn startup, static collection, health checks, and structured logs.
- Prepare `render.yaml`, a build step, and a controlled migration/release job.
- Build/install and collect static files without modifying the live database. Apply migrations exactly once per release with schema credentials; start web processes using runtime credentials.
- Document migration failure, incompatible schema, and rollback behavior. Backward-compatible migrations must allow the old app to remain live during rollout.
- Prepare Windows-friendly backup/restore instructions and scripts using PostgreSQL utilities; provide Linux equivalents where used. Require explicit safe restore targets.
- Add CI for locked dependencies, Django checks, migrations, and material PostgreSQL tests; pushing and connecting a remote occur when authorized.

**M5b: execute once hosting details and access are settled**

- Provision staging app/database with synthetic data, then production resources when the release gate permits.
- Verify managed-role privileges and database triggers, schema ownership, connection limits, TLS/network settings, and the exact PostgreSQL version.
- Run hosted posting/privacy/report smoke checks and the database bypass checks against staging.
- Verify sessions and data survive restart/redeploy and access works from two devices with the laptop off.
- Rehearse backup restoration into a different database and test application login, grants, sequences, counts, and balances.

Render supports a separate pre-deploy migration hook on paid web services. If unavailable, use a serialized release job with its own credentials; never hide migrations in every web-worker startup. Build success alone does not prove database or deployment correctness. [Render deployment lifecycle](https://render.com/docs/deploys)

**Exit:** local preparation can finish independently; M5 remains partially complete until hosted A16–A18 and H01–H06 below execute successfully. No local check substitutes for actual hosted verification.

### M6 — Walkthrough and pilot release (target Day 7+)

1. Resolve required real-data decisions and record their acceptance.
2. Have a family member complete login, expense, income, transfer, correction, and permitted reports.
3. Fix blocking defects; run the final relevant regression suite with A01–A20 accounted for.
4. Complete hosted/recovery gates before declaring a hosted pilot ready.
5. Report implemented, tested, manually verified, proposed, and deferred behavior separately.
6. Record release commit, environment, operational owner, open limitations, and next scope.

No calendar deadline overrides an unpassed financial, privacy, or recovery gate.

## 8. Acceptance matrix

Preserve the Bible's A01–A20 IDs so earlier references stay meaningful.

| ID | Required evidence |
|---|---|
| A01 | Balanced posting commits one entry and all lines |
| A02 | Unequal totals, invalid precision, nonfinite/out-of-range amounts, negative/zero/both-sided lines reject |
| A03 | Injected failure rolls back all financial persistence |
| A04 | Repeated/concurrent same key and payload yields one authorized result |
| A05 | Same key with changed payload conflicts |
| A06 | Competing posts of one draft produce one posting |
| A07 | Stale draft edit conflicts without losing submitted form input |
| A08 | Unauthorized IDs across forms, URLs, queries, and exports cannot read/post |
| A09 | Mixed-visibility redaction holds across screen, CSV, and errors |
| A10 | Repeated/concurrent reversal yields one linked full reversal |
| A11 | Direct ordinary-role ORM/bulk edit or delete of posted money fails |
| A12 | Group/inactive accounts, non-INR, and locked dates reject |
| A13 | Lock-date changes and posting serialize under the defined policy |
| A14 | Golden dataset produces exact expected balances |
| A15 | Date-filtered ledger has correct opening and running balances |
| A16 | Two hosted device sessions retain independent identity and permissions |
| A17 | Hosted application restart/redeploy preserves database state; container persistence checked if that path is used |
| A18 | Backup restores into a separate database with relationships, balances, login, and grants usable |
| A19 | Direct invalid posted journal via ordinary database role cannot commit, including unbalanced or too-few-line cases |
| A20 | Coordinated permission/account/actor-state changes are respected at posting boundary |
| H01 | Production rejects unsafe configuration; HTTPS, secure cookies, CSRF, and static assets work |
| H02 | Runtime role cannot change schema or bypass posted-entry protections on managed PostgreSQL |
| H03 | Staging/preview/test credentials and data remain separate from production |
| H04 | Migration failure stops release; documented application rollback remains compatible with schema |
| H05 | Hosted service works with owner laptop off; logs and health responses expose no secrets/financial payloads |
| H06 | Representative load stays within database connection budget; latency and posting lock waits are measured |

All gates start **not run**. Tests must identify environment, command, result, and remaining limitations. Concurrent transaction behavior requires real PostgreSQL and independent connections. Test database enforcement using restricted roles, not only the privileged migration/test owner.

## 9. Hosted release and data transfer contract

For Render, place app/database in the same region and use the private database address where available. Configure database TLS according to the provider's supported modes, and restrict external database access to deliberate administration paths. Do not tunnel the production app to the laptop's PostgreSQL. [Render connection and network guidance](https://render.com/docs/postgresql-creating-connecting)

Before real financial use:

- Set DEBUG off, precise host/origin rules, HTTPS handling, secure cookies, and deliberate trusted-proxy settings; run Django deployment checks.
- Authenticate all financial routes; provision invited users and provide basic login abuse protection and a documented Admin recovery method.
- Keep health responses minimal; log errors and operational identifiers without credentials or financial payloads.
- Store sessions in PostgreSQL; application disk is disposable. Static assets are reproducible; user uploads later use durable object storage.
- Select backup retention, failure alerts, and a restore process. Proposed initial recovery targets remain 24 hours of maximum data loss and 2 hours to restore, until demonstrated.
- Review actual hosting costs, sleep/expiry behavior, connection quotas, and recovery features before approving a plan. Recommend paid resources for real financial use; no specific price is assumed.

Paid Render Postgres offers point-in-time recovery; free database compute does not include provider recovery. Choose and verify the recovery arrangement rather than assuming every plan provides backups. Keep an independently retained logical export as appropriate, and rehearse restoring it. [Render recovery documentation](https://render.com/docs/postgresql-backups)

If local data is only synthetic, start the hosted production book clean through migrations and approved account setup. If real data must move, freeze local writes, take a consistent backup, restore with explicit ownership/role mapping, verify record counts and accounting totals, then switch users. PostgreSQL database dumps do not automatically recreate cluster roles; provision target roles and validate grants separately.

Maintain one writable production book. After hosted writes begin, switching back to an old laptop copy would lose transactions. A later return requires a fresh consistent transfer and another verification. Rolling application code back does not roll database schema or data back automatically.

## 10. Vercel alternative

Vercel supports Django, including framework detection and static delivery. It is a viable alternative; this plan does not require a frontend rewrite to use it. [Vercel Django support](https://vercel.com/changelog/zero-configuration-django-support)

If selected instead of Render, revise the hosting ADR and M5 deployment files:

1. Deploy Django through Vercel's Python runtime; do not expect a Docker Compose/Gunicorn service definition to deploy unchanged.
2. Connect a separate managed PostgreSQL provider, with app and data in nearby regions. Configure a bounded connection/pooling strategy and verify it with Django, psycopg, and transaction tests. [Vercel database guidance](https://vercel.com/docs/marketplace-storage)
3. Keep migrations in a separate controlled release operation, separate preview databases, and the same role/trigger/recovery gates.
4. Respect function duration/payload limits and temporary writable storage. Long exports/imports or future background work need bounded jobs and durable progress. [Vercel function limits](https://vercel.com/docs/functions/limitations), [runtime filesystem](https://vercel.com/docs/functions/runtimes)
5. For future recurring accounting, use unique occurrence IDs, retry handling, and current permission/date checks regardless of scheduler. Do not assume exactly-once delivery. [Vercel cron behavior](https://vercel.com/docs/cron-jobs/manage-cron-jobs)

Provider support and plan limits were checked on 8 October 2026 and must be rechecked when selecting paid resources. Vercel configuration is not a parallel POC deliverable unless the owner selects it.

## 11. Growth beyond the pilot

The first release serves one household. More users or journal rows within that book can be handled through measured database/query improvements and application capacity. Hosting does not establish a performance guarantee.

The Bible's singleton LedgerSettings lock serializes financial mutations. This is intentional for a small POC. Adding app replicas can improve read capacity but does not increase serialized posting throughput. Measure transaction time, lock waits, and database connections; revise locking only with a specific contention finding and regression evidence.

| Observed need | Next change | Required evidence |
|---|---|---|
| Slow reports as history grows | Inspect query plans, indexes, pagination; optimize authorized selectors | Representative data and measured improvement without privacy/accounting regressions |
| App CPU/memory pressure | Increase resources, then additional stateless instances if needed | Bounded connection budget, shared sessions, restart/load verification |
| Sustained posting lock contention | Redesign lock scope while preserving period/permission races and idempotency | PostgreSQL concurrency and failure tests pass |
| Long imports/exports or recurring work | Add a durable worker/queue when that feature enters scope | Retry, duplicate, failure-recovery, and permission/date behavior verified |
| Independent households become customers | Choose isolated deployments or explicitly scoped multiple-book design | Accepted D12, ownership/scoped constraints, migrations, and isolation tests |
| Recovery/support expectations increase | Monitoring, backup retention, restore drills, release controls | Measured recovery and documented operational ownership |

For shared multiple-household hosting, the present singleton book model must change deliberately. Scope accounts, journals, grants, settings, posting numbers/idempotency, and queries to the appropriate book; test cross-household denial everywhere. A dormant household field alone does not provide isolation. Do not promise a zero-migration transition.

Avoid speculative caches, microservices, or a separate frontend until an observed product or operating need justifies them.

## 12. Next implementation action and completion status

**Next action when implementation is requested:** begin M0 in the existing workspace, validate the already-created database and roles, establish the environment and custom user model, then run checks against disposable PostgreSQL. Ask only for unavailable secrets through local entry and decisions that affect the work at hand.

This document revision is complete when its source references, deferred scope, test IDs, and hosting assumptions are consistent. It does not indicate that any application milestone or acceptance test has passed.

The previous plan is preserved at [docs/archive/implementation_plan.v1.md](docs/archive/implementation_plan.v1.md).
