"""Run PostgreSQL tests in a newly created, loopback-only Docker database."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.parse import quote

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "postgres:18.6@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336"


def run():
    name = "household-ledger-tests-" + secrets.token_hex(5)
    env = os.environ.copy()
    passwords = {role: secrets.token_urlsafe(32) for role in ("postgres", "ledger_test_owner", "ledger_test_app")}
    env["POSTGRES_PASSWORD"] = passwords["postgres"]
    subprocess.run([
        "docker", "run", "--detach", "--rm", "--name", name,
        "--label", "org.household-ledger.purpose=isolated-test",
        "--publish", "127.0.0.1:55432:5432", "--tmpfs", "/var/lib/postgresql",
        "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_DB=ledger_test_control", IMAGE,
    ], env=env, check=True, stdout=subprocess.DEVNULL)
    try:
        for attempt in range(60):
            try:
                conn = psycopg.connect(host="127.0.0.1", port=55432, dbname="ledger_test_control",
                                       user="postgres", password=passwords["postgres"], connect_timeout=2,
                                       autocommit=True)
                break
            except psycopg.OperationalError:
                time.sleep(0.5)
        else:
            raise SystemExit("Isolated test database did not become ready.")
        with conn:
            for role in ("ledger_test_owner", "ledger_test_app"):
                createdb = sql.SQL("CREATEDB") if role.endswith("owner") else sql.SQL("NOCREATEDB")
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEROLE {} PASSWORD {}").format(
                    sql.Identifier(role), createdb, sql.Literal(passwords[role])
                ))
            conn.execute("ALTER DATABASE ledger_test_control OWNER TO ledger_test_owner")
        conn.close()
        env.pop("DATABASE_URL", None)
        env.pop("MIGRATION_DATABASE_URL", None)
        env["TEST_DATABASE_URL"] = (
            "postgresql://ledger_test_owner:" + quote(passwords["ledger_test_owner"], safe="")
            + "@127.0.0.1:55432/ledger_test_control"
        )
        env["TEST_RUNTIME_DATABASE_URL"] = (
            "postgresql://ledger_test_app:" + quote(passwords["ledger_test_app"], safe="")
            + "@127.0.0.1:55432/test_household_ledger"
        )
        env["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
        command = [sys.executable, "manage.py", "test", "--noinput", "--verbosity", "2"] + sys.argv[1:]
        return subprocess.run(command, cwd=ROOT, env=env).returncode
    finally:
        subprocess.run(["docker", "stop", name], check=False, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    raise SystemExit(run())
