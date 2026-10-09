# 0001 — Local development and later managed hosting

Date: 8 October 2026
Status: local implementation authorized; one-household first release accepted; Render proposed.

## Context

The owner installed PostgreSQL, created household_ledger, ledger_migrator, and ledger_app, and asked to revise the plan for later hosting and growth. They have now authorized implementation and explicitly confirmed one household first.

## Decisions

- Use the existing repository root and a Python virtual environment with native local PostgreSQL.
- Use disposable Docker PostgreSQL 18 for tests; never test against the owner's database.
- Separate runtime and migration credentials; keep dotenv files out of Git.
- Pin a universal dependency lock. Local Python 3.12.9 is observed; the Linux build uses Python 3.12.15. This patch difference is explicit; update local Python before real-data launch.
- Render is the proposed first hosting provider. No account, paid resource, domain, or deployment is approved by this ADR.
- Tailscale is optional for laptop access and not required for the hosted path.
- One household is the accepted initial scope. A future customer-isolation design remains a separate decision.

## Consequences and verification

Django custom users precede initial migrations. Applications use ledger_app; controlled migrations use ledger_migrator. Current checks and remaining gates are recorded in ../progress.md.

Original accounting decisions D01–D10 remain proposed except source principles; implementation uses synthetic-data defaults. Further hosting changes require an updated decision record.
