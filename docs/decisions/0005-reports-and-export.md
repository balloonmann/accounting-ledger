# 0005 — Financial Reports and Export (M4)

Date: 8 October 2026
Status: accepted for POC development baseline; real-data decisions remain gated.

## Context

Following core posting workflows (M2) and privacy administration (M3), Milestone 4 delivers the primary financial reporting interfaces (Trial Balance, Income & Expenditure statement, and Account Ledgers) and secure CSV exports.

## Decisions

- **Admin Trial Balance (A14):**
  - Balances through an as-of date aggregated strictly over non-group leaf accounts (`is_group=False`) to avoid double counting parent groupings and leaf balances.
  - Verifies cumulative debit balances equal cumulative credit balances (`total_debits == total_credits`).
  - Restricted exclusively to administrators; member access is rejected with HTTP 403 Forbidden.
- **Admin Income & Expenditure Statement (A14):**
  - Computes operational income (credit balances on Income accounts) and expenditures (debit balances on Expense accounts) over a specified date range (defaulting to the start of the Indian April–March fiscal year).
  - Calculates net household surplus or deficit (`Total Income - Total Expenditure`).
  - Restricted exclusively to administrators; member access is rejected with HTTP 403 Forbidden.
- **Account Ledger Aggregation & Date Filtering (A15):**
  - Accurately computes opening balance prior to the start of a period by summing pre-period lines.
  - Sequences transactions in strict order (`date`, `posting_number`, `line_number`) and computes accurate running balances.
- **Authorized CSV Export & Mixed-Visibility Parity (Bible §10 / A09):**
  - CSV exports use the identical authorized query selectors and privacy logic as screen representations.
  - When an account ledger CSV is generated for a user who lacks visibility on all legs of a transaction, private narrations and authors are masked to `[Redacted]`.
- **Formula Injection Neutralization (CSV Injection):**
  - All free-text CSV cells starting with formula trigger characters (`=`, `+`, `-`, `@`, `\t`, `\r`) are sanitized by prepending a single quote (`'`), neutralizing spreadsheet code execution without modifying numeric calculations.

## Consequences & Verification

Acceptance criteria A14, A15, and complete A09 (including CSV export and formula injection neutralization) pass cleanly on isolated PostgreSQL across 75 automated test cases.
