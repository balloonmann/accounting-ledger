# 0002 — M0 foundation

Date: 8 October 2026
Status: implementation scope; domain defaults remain proposed.

User outcome: individual sign-in and an authorized account list, with a PostgreSQL schema ready for the accounting services.

Identity owns the custom User and role. Accounting owns accounts, grants, journals, posting request records, and the singleton book. Operations owns activity records. All domain tables are read-only in Django Admin at this stage.

Row constraints enforce valid account ownership, exact one-sided journal line amounts, role choices, and header state consistency. Full posting balance, immutable posted history, idempotency, and concurrent operations are M1 deliverables. No transaction entry route is exposed by M0.

No test or demo writes are permitted in a real book without the documented setup and decision gates.
