# 0003 — Accounts and Entry Workflows (M2)

Date: 8 October 2026
Status: accepted for POC development baseline; real-data decisions remain gated.

## Context

Following the posting engine and database trigger verification in M1, Milestone 2 establishes the user-facing entry workflows, account administration, and synthetic demo seeding.

## Decisions

- **Admin Account Management & Protection (D04 / D08):** Account creation, editing, and deactivation are restricted to Admin users. When an account has recorded journal lines, frozen fields (`classical_type`, `reporting_class`, `purpose`, `normal_side`, `parent`) cannot be modified (D04); only harmless labels (`name`, `code`) can change. Configured accounts (`opening_equity` in `LedgerSettings`) cannot be deactivated or deleted. Deletion is prohibited for any account with existing journal lines or children.
- **Dedicated Entry Workflows:** Specialized forms for Expense, Income, Transfer, Full Journal, and Opening Balance (Admin only) translate user intent into double-entry lines and invoke the central posting services. Screens never insert financial rows directly outside the posting service.
- **Server-Side Restriction on Pickers:** All account pickers filter accounts based on the active user's permissions (`postable_accounts` and `visible_accounts`). Any submitted payload referencing an unauthorized account fails server-side validation without financial effect (A08).
- **Draft Concurrency & Preservation (A07):** Draft editing verifies the submitted `version` counter against the database. If a conflict occurs (`StaleVersionError`), the user's submitted lines and header values are preserved on the page with a clear conflict notice.
- **Reversal & Corrected Replacement:** Reversal creates an immediate linked offsetting transaction with inverted debits and credits, setting `reversal_of` only upon posting. Corrected replacement creates a new draft pointing to `replacement_of` pre-filled with the original entry's lines.
- **Bible §11 Golden Dataset:** A repeatable management command (`seed_demo`) sets up synthetic accounts, users, and the 6-event transaction sequence through normal service interfaces, verifying exact mathematical balances.

## Consequences & Verification

51 automated tests (foundation, posting concurrency, account management, entry workflows, privacy, and Golden Dataset balances) pass cleanly against isolated PostgreSQL.
