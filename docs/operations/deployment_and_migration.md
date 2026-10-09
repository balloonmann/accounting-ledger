# Deployment and Migration Contract (M5)

## 1. Architecture and Role Separation

The Household Ledger enforces strict principle-of-least-privilege database role separation:
- **`ledger_migrator` (Schema Owner):** Possesses DDL rights, owns the database schema, sequences, and trigger functions. Used exclusively during release migration steps.
- **`ledger_app` (Runtime Web Role):** Restricted to DML (`SELECT`, `INSERT`, `UPDATE`, `DELETE`). Cannot create, alter, or drop tables; cannot alter or disable PostgreSQL triggers; cannot execute `TRUNCATE`.

The web application process **never receives schema-owner credentials**.

---

## 2. Production Configuration ([`config/settings/production.py`](file:///c:/Users/Harshit/OneDrive/Desktop/accounting_ledger/config/settings/production.py))

Production environments require strict security enforcement verified by automated tests (H01):
- `DEBUG = False`
- `ALLOWED_HOSTS`: Explicit exact hostnames (e.g. `ledger.household.example`). Wildcard `*` is strictly rejected.
- `DJANGO_SECRET_KEY`: Minimum 50 characters required.
- `CSRF_TRUSTED_ORIGINS`: Explicit HTTPS origins required (e.g. `https://ledger.household.example`). Wildcards or plaintext HTTP are rejected.
- `SECURE_SSL_REDIRECT = True`
- `SESSION_COOKIE_SECURE = True`
- `CSRF_COOKIE_SECURE = True`
- `SECURE_HSTS_SECONDS = 3600` (HTTP Strict Transport Security)
- `WhiteNoise`: Compressed manifest static storage (`CompressedManifestStaticFilesStorage`).

---

## 3. Container & Process Model ([`Dockerfile`](file:///c:/Users/Harshit/OneDrive/Desktop/accounting_ledger/Dockerfile))

- **Base Image:** Official Python 3.12 slim with locked digest.
- **Dependency Pinning:** Dependencies installed with `--require-hashes -r requirements.lock`.
- **Static Assets:** Collected at container build time (`collectstatic --noinput`) using a build-time placeholder secret key without accessing any live database.
- **Non-Root Execution:** Container runs as non-privileged user `USER 10001`.
- **Process Manager:** `gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 2`.

---

## 4. Release and Migration Lifecycle

Render deployment configuration is defined in [`render.yaml`](file:///c:/Users/Harshit/OneDrive/Desktop/accounting_ledger/render.yaml):
- Auto-deploy trigger is set to `off`.
- Migrations run in a separate controlled pre-deploy release step using `MIGRATION_DATABASE_URL` (`ledger_migrator`).
- Long-lived web service only receives `DATABASE_URL` (`ledger_app`).

### Migration Failure and Rollback Policy:
1. **Backward-Compatible Schema Changes:** Every migration must be forward- and backward-compatible with the currently running application version.
2. **Migration Failure:** If a migration script fails, the release aborts. The web application remains running against the previous intact schema.
3. **Application Rollback:** If a deployment needs to be rolled back to the prior application commit, the database schema remains valid and backward-compatible.

---

## 5. Health Check ([`apps/operations/views.py`](file:///c:/Users/Harshit/OneDrive/Desktop/accounting_ledger/apps/operations/views.py))

- Endpoint: `GET /health/`
- Returns: HTTP 200 `{"status": "ok"}` when the database connection is healthy.
- Failure: Returns HTTP 503 `{"status": "unavailable"}` when database connectivity fails.
- Security: Exposes no credentials, table counts, or financial payloads.
