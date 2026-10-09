# Project instructions

Read implementation_plan.md, ERP_BUILD_BIBLE.md, docs/decisions/, and docs/progress.md before changes.
Current first-release scope is one household, confirmed by the owner on 8 October 2026.
Use the existing Windows PostgreSQL installation for development and disposable PostgreSQL for tests.
Keep money exact, policy checks centralized, and posted journal integrity enforced at the database.
Never use a production or development database as a test target.
Preserve the source documents and user changes. Report executed verification separately from proposals.
Do not print secrets, read local dotenv contents into tool output, or commit credentials.
Use the existing dependency lock; regenerate with the documented universal uv command when needed.
Record milestone results and limitations in docs/progress.md. Hosting and real-data decisions remain gated.
