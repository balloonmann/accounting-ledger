"""Apply reviewed local migrations with the separate schema-owner credential."""
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

from dotenv import dotenv_values
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]


def main():
    runtime = dotenv_values(ROOT / ".env")
    migration = dotenv_values(ROOT / ".env.migration")
    url = migration.get("MIGRATION_DATABASE_URL", "")
    parsed = urlparse(url)
    app_url = urlparse(runtime.get("DATABASE_URL", ""))
    if (
        parsed.hostname != "127.0.0.1" or parsed.port != 5432
        or parsed.path != "/household_ledger" or parsed.username != "ledger_migrator"
        or app_url.username != "ledger_app" or app_url.hostname != parsed.hostname
        or app_url.port != parsed.port or app_url.path != parsed.path
    ):
        raise SystemExit("Run scripts/configure_local.py first; migration target validation failed.")
    env = os.environ.copy()
    env.update({k: v for k, v in runtime.items() if v is not None})
    env["DATABASE_URL"] = url
    env["DJANGO_SETTINGS_MODULE"] = "config.settings.development"
    with psycopg.connect(url, autocommit=True) as conn:
        locked = conn.execute("SELECT pg_try_advisory_lock(728411902)").fetchone()[0]
        if not locked:
            raise SystemExit("Another migration is running.")
        try:
            tables = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            ).fetchall()
            if tables and not any(row[0] == "django_migrations" for row in tables):
                raise SystemExit("Database contains unrecognized existing tables; stopping for review.")
            subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], cwd=ROOT, env=env, check=True)
            role = sql.Identifier("ledger_app")
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            conn.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(role))
            conn.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role))
            conn.execute(sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE ledger_migrator IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(role))
            conn.execute(sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE ledger_migrator IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(role))
        finally:
            conn.execute("SELECT pg_advisory_unlock(728411902)")
    print("Local migrations and runtime grants applied.")


if __name__ == "__main__":
    main()
