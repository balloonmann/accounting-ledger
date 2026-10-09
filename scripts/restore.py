"""
Database restore and rehearsal utility for Household Ledger PostgreSQL.
Restores a custom-format dump into an explicitly designated target database.
Verifies restored data integrity, counts, and balance math.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlparse

from dotenv import dotenv_values
import psycopg

ROOT = Path(__file__).resolve().parents[1]


def find_pg_tool(tool_name: str) -> str:
    """Finds a PostgreSQL command line utility on PATH or standard install locations."""
    found = shutil.which(tool_name)
    if found:
        return found

    win_paths = [
        Path(r"C:\Program Files\PostgreSQL\18\bin"),
        Path(r"C:\Program Files\PostgreSQL\17\bin"),
        Path(r"C:\Program Files\PostgreSQL\16\bin"),
    ]
    for p in win_paths:
        candidate = p / f"{tool_name}.exe"
        if candidate.exists():
            return str(candidate)

    return tool_name


def get_server_config(env_file_path: Path):
    """Loads server connection configuration."""
    if not env_file_path.exists():
        db_url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    else:
        values = dotenv_values(env_file_path)
        db_url = values.get("MIGRATION_DATABASE_URL") or values.get("DATABASE_URL")

    if not db_url:
        raise ValueError("No database URL found in environment or specified env file.")

    parsed = urlparse(db_url)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
    }


def restore_database(
    dump_file: Path,
    target_db: str,
    env_file: Path = ROOT / ".env.migration",
    allow_primary_overwrite: bool = False,
):
    """Restores database from dump file into target_db and verifies integrity."""
    if not dump_file.exists():
        raise FileNotFoundError(f"Dump file '{dump_file}' does not exist.")

    if target_db.lower() in ("household_ledger", "production", "prod") and not allow_primary_overwrite:
        raise ValueError(
            f"Safety guard: Target '{target_db}' is a protected primary database name. "
            "Use a separate test/recovery target (e.g., 'household_ledger_recovery_test') "
            "or specify --dangerously-allow-primary-db-overwrite."
        )

    cfg = get_server_config(env_file)
    pg_restore_bin = find_pg_tool("pg_restore")

    # 1. Connect to administrative DB to check/create target database
    admin_conn_str = f"host={cfg['host']} port={cfg['port']} user={cfg['user']} dbname=postgres"
    if cfg["password"]:
        admin_conn_str += f" password={cfg['password']}"

    print(f"Ensuring target database '{target_db}' exists on {cfg['host']}:{cfg['port']}...")
    try:
        with psycopg.connect(admin_conn_str, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
                exists = cur.fetchone() is not None
                if not exists:
                    print(f"Attempting to create database '{target_db}'...")
                    cur.execute(f'CREATE DATABASE "{target_db}" OWNER "{cfg["user"]}"')
                else:
                    print(f"Target database '{target_db}' already exists.")
    except psycopg.errors.InsufficientPrivilege:
        raise RuntimeError(
            f"Role '{cfg['user']}' does not have CREATEDB privileges to create '{target_db}'. "
            f"Please pre-create the target database using your PostgreSQL admin account:\n"
            f"  CREATE DATABASE \"{target_db}\" OWNER \"{cfg['user']}\";\n"
            f"Then re-run this restore script."
        )

    # 2. Run pg_restore
    env = os.environ.copy()
    if cfg["password"]:
        env["PGPASSWORD"] = cfg["password"]

    cmd = [
        pg_restore_bin,
        "-h", cfg["host"],
        "-p", cfg["port"],
        "-U", cfg["user"],
        "-d", target_db,
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        str(dump_file),
    ]

    print(f"Restoring dump '{dump_file.name}' into '{target_db}'...")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)

    # Note: pg_restore returns 0 on complete success, or 1 if warnings (e.g. drop if exists on fresh db) occurred.
    if result.returncode not in (0, 1):
        err_msg = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Restore failed with exit code {result.returncode}: {err_msg}")

    print("Restore completed. Verifying data integrity in target database...")

    # 3. Verify integrity
    target_conn_str = f"host={cfg['host']} port={cfg['port']} user={cfg['user']} dbname={target_db}"
    if cfg["password"]:
        target_conn_str += f" password={cfg['password']}"

    with psycopg.connect(target_conn_str, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM accounting_account")
            accounts_count = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM accounting_journalentry WHERE state = 'POSTED'")
            posted_entries_count = cur.fetchone()[0]

            cur.execute("SELECT sum(debit), sum(credit) FROM accounting_journalline")
            total_dr, total_cr = cur.fetchone()

            cur.execute("SELECT count(*) FROM identity_user WHERE is_active = true")
            users_count = cur.fetchone()[0]

    print("=" * 60)
    print("RESTORATION INTEGRITY VERIFICATION:")
    print(f"  Target Database:        {target_db}")
    print(f"  Active Users:           {users_count}")
    print(f"  Chart of Accounts:      {accounts_count} accounts")
    print(f"  Posted Journal Entries: {posted_entries_count} entries")
    print(f"  Total Debits:           INR {total_dr}")
    print(f"  Total Credits:          INR {total_cr}")
    is_balanced = (total_dr == total_cr)
    print(f"  Debits == Credits:      {'✓ BALANCED' if is_balanced else '✗ IMBALANCED'}")
    print("=" * 60)

    if not is_balanced:
        raise RuntimeError("Restored database verification failed: Debits do not equal Credits!")
    if accounts_count == 0:
        raise RuntimeError("Restored database verification failed: No accounts found!")

    print(f"Restore rehearsal to '{target_db}' passed all integrity checks.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore a PostgreSQL database dump for Household Ledger.")
    parser.add_argument("--dump-file", type=Path, required=True, help="Path to the .dump file to restore.")
    parser.add_argument("--target-db", type=str, required=True, help="Target database name (must be a test/recovery database).")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.migration", help="Path to env file.")
    parser.add_argument(
        "--dangerously-allow-primary-db-overwrite",
        action="store_true",
        help="Explicitly permit restoring into primary database name.",
    )

    args = parser.parse_args()
    try:
        restore_database(
            args.dump_file,
            args.target_db,
            args.env_file,
            args.dangerously_allow_primary_db_overwrite,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
