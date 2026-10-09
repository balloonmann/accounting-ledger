# 0004 — Privacy, Grants, and Administration (M3)

Date: 8 October 2026
Status: accepted for POC development baseline; real-data decisions remain gated.

## Context

Following entry workflows in M2, Milestone 3 establishes complete granular authorization, user administration, posting lock period enforcement, and strict mixed-visibility redaction for the single household scope.

## Decisions

- **Granular Account Grants & Database Consistency:** While shared accounts are visible to all members by default, posting rights require explicit administrative grants (`AccountGrant`). A database check constraint (`posting_requires_view`) guarantees that a member cannot possess posting rights without view rights.
- **Mixed-Visibility Redaction (Bible §9.2 / D03 / A09):** When a member accesses an account ledger that contains transactions involving accounts they are not permitted to view:
  - Financial integrity is preserved: the transaction date, authorized debit/credit amounts, and running balances remain exact.
  - Confidential details are redacted: narration and author details are masked to `[Redacted]`, and direct links to the full journal entry are suppressed.
  - Direct access to `entry_detail` for mixed-visibility entries returns HTTP 403 Forbidden. Membership or past authorship alone cannot bypass visibility after grants are revoked.
  - Requests for unauthorized accounts return generic HTTP 404 responses to avoid enumerating private household accounts.
- **Posting Lock Date Administration (A13):** Setting or lowering the posting lock date requires an explicit audit reason. Lowering without a reason is rejected with `ServiceError`. All lock changes and postings serialize via `SELECT ... FOR UPDATE` on `LedgerSettings`.
- **Coordinated Boundary Permission Re-check (A20):** Permissions and actor active status are re-verified inside the coordinated database transaction after acquiring table/row locks. Any race with user deactivation or grant revocation rejects unauthorized postings.
- **Concurrent Reversal Serialization (A10):** Independent connection races attempting to reverse the same original entry serialize via row locks; exactly one succeeds and the other fails with a clean business error. Reversing an existing reversal entry is rejected.
- **Household User Administration:** Administrators manage household member credentials, roles (ADMIN/MEMBER), and active statuses. Safeguards prevent administrators from deactivating or demoting their own account.

## Consequences & Verification

Acceptance criteria A07 through A13 and A20 are automated in `test_permissions_m3.py` and pass alongside M0–M2 tests on isolated PostgreSQL.
