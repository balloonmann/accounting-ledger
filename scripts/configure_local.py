"""Interactively verify existing local roles and save ignored development credentials."""
from getpass import getpass
from pathlib import Path
import secrets
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def main():
    import psycopg

    targets = (ROOT / ".env", ROOT / ".env.migration")
    if any(p.exists() for p in targets):
        raise SystemExit("Local configuration already exists. Preserve it; edit it deliberately.")
    print("Passwords are entered locally and are not displayed. Do not paste them into chat.")
    values = {}
    for role in ("ledger_migrator", "ledger_app"):
        password = getpass(f"PostgreSQL password for {role}: ")
        if not password:
            raise SystemExit("A password is required; no files have been written.")
        try:
            with psycopg.connect(
                host="127.0.0.1", port=5432, dbname="household_ledger",
                user=role, password=password, connect_timeout=5,
            ) as conn:
                row = conn.execute(
                    "SELECT current_user, current_database(), "
                    "(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()), "
                    "current_setting('server_encoding'), current_setting('listen_addresses')"
                ).fetchone()
                flags = conn.execute(
                    "SELECT rolsuper, rolcreatedb, rolcreaterole "
                    "FROM pg_roles WHERE rolname=current_user"
                ).fetchone()
                if row[:4] != (role, "household_ledger", "ledger_migrator", "UTF8"):
                    raise SystemExit("Database identity, owner, or encoding differs from the plan.")
                if row[4] != "localhost" or any(flags):
                    raise SystemExit("Verify localhost binding and non-administrative role privileges first.")
        except psycopg.Error:
            raise SystemExit(f"Connection check failed for {role}. Verify its password in pgAdmin.")
        values[role] = (
            f"postgresql://{role}:{quote(password, safe='')}@127.0.0.1:5432/household_ledger"
        )
        print(f"{role}: connection and role checks passed.")
    key = secrets.token_urlsafe(64)
    targets[0].write_text(
        f"DATABASE_URL={values['ledger_app']}\nDJANGO_SECRET_KEY={key}\n"
        "DJANGO_SETTINGS_MODULE=config.settings.development\n", encoding="utf-8"
    )
    targets[1].write_text(
        f"MIGRATION_DATABASE_URL={values['ledger_migrator']}\n", encoding="utf-8"
    )
    print("Saved ignored local configuration. No tables or grants were changed.")


if __name__ == "__main__":
    main()
