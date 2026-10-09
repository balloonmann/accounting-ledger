"""
Backup utility for Household Ledger PostgreSQL database.
Creates a compressed, custom-format dump (.dump) suitable for pg_restore.
Secrets are never printed to stdout or logged.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime
from urllib.parse import urlparse

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def find_pg_tool(tool_name: str) -> str:
    """Finds a PostgreSQL command line utility on PATH or standard install locations."""
    # 1. Check PATH
    found = shutil.which(tool_name)
    if found:
        return found

    # 2. Check standard Windows PostgreSQL install paths
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


def get_db_config(env_file_path: Path):
    """Loads database connection configuration without exposing credentials."""
    if not env_file_path.exists():
        # Fall back to environment variable
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
        "dbname": parsed.path.lstrip("/"),
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
    }


def create_backup(output_dir: Path, env_file: Path = ROOT / ".env.migration") -> Path:
    """Executes pg_dump in custom format and returns the backup file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cfg = get_db_config(env_file)

    pg_dump_bin = find_pg_tool("pg_dump")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = output_dir / f"household_ledger_backup_{timestamp}.dump"

    env = os.environ.copy()
    if cfg["password"]:
        env["PGPASSWORD"] = cfg["password"]

    cmd = [
        pg_dump_bin,
        "-Fc",  # Custom format (compressed, flexible restore)
        "-h", cfg["host"],
        "-p", cfg["port"],
        "-U", cfg["user"],
        "-d", cfg["dbname"],
        "-f", str(backup_file),
    ]

    print(f"Starting database backup of '{cfg['dbname']}' to '{backup_file.name}'...")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)

    if result.returncode != 0:
        err_msg = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Backup failed (exit {result.returncode}): {err_msg}")

    if not backup_file.exists() or backup_file.stat().st_size == 0:
        raise RuntimeError("Backup completed but the target file is missing or empty.")

    # Compute sha256 checksum
    h = hashlib.sha256()
    with open(backup_file, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    checksum = h.hexdigest()

    file_size_kb = backup_file.stat().st_size / 1024
    print(f"Backup successfully created: {backup_file}")
    print(f"Size: {file_size_kb:.2f} KB | SHA256: {checksum[:16]}...{checksum[-16:]}")

    return backup_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a PostgreSQL database backup for Household Ledger.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "backups", help="Directory where backup is stored.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.migration", help="Path to env file containing DB URL.")

    args = parser.parse_args()
    try:
        create_backup(args.output_dir, args.env_file)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
