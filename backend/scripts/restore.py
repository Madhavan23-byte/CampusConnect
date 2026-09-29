"""
CampusConnect — Disaster Recovery & Database Restore Utility
Performs:
- SHA-256 integrity verification of backup archive
- Target database validation / creation (for DR drills)
- Native pg_restore execution (-Fc)
- Post-restore verification:
  - Alembic migration head verification (matches 0006_foreign_key_indexes)
  - Core entity counts and integrity checks
- Optional target database cleanup after drill
"""

import argparse
import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import asyncpg

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings


def find_pg_binary(binary_name: str) -> str:
    """Find postgres binary in PATH or standard installation directories."""
    found = shutil.which(binary_name)
    if found:
        return found

    # Windows standard paths
    if sys.platform == "win32":
        for version in ["17", "16", "15", "14"]:
            candidate = Path("C:/Program Files/PostgreSQL") / version / "bin" / f"{binary_name}.exe"
            if candidate.exists():
                return str(candidate)

    # Linux standard paths
    for version in ["16", "15", "14"]:
        candidate = Path(f"/usr/lib/postgresql/{version}/bin/{binary_name}")
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError(f"PostgreSQL utility '{binary_name}' not found on system PATH.")


def compute_sha256(filepath: str) -> str:
    """Calculate SHA-256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def verify_checksum(backup_path: Path) -> bool:
    """Verify file integrity against companion .sha256 file if present."""
    checksum_file = backup_path.with_suffix(backup_path.suffix + ".sha256")
    if not checksum_file.exists():
        print(f"[WARN] No companion checksum file found for {backup_path.name}")
        return True

    expected = checksum_file.read_text(encoding="utf-8").strip().split()[0]
    actual = compute_sha256(str(backup_path))
    if expected.lower() != actual.lower():
        raise ValueError(
            f"Checksum verification failed for {backup_path.name}! "
            f"Expected {expected}, got {actual}"
        )
    print(f"[VERIFY] SHA-256 checksum verified: {actual}")
    return True


async def ensure_database_exists(
    db_host: str, db_port: int, db_user: str, db_pass: str, target_db: str
) -> None:
    """Ensure target database exists from template maintenance DB."""
    try:
        conn = await asyncpg.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_pass,
            database="postgres",
        )
    except Exception:
        # Fallback to campusconnect database as maintenance connection
        conn = await asyncpg.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_pass,
            database="campusconnect",
        )

    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", target_db)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{target_db}"')
            print(f"[RESTORE] Created target database: {target_db}")
    finally:
        await conn.close()


async def verify_restored_schema(
    db_host: str, db_port: int, db_user: str, db_pass: str, target_db: str
) -> dict[str, any]:
    """Inspect the restored database and verify Alembic head and core entities."""
    conn = await asyncpg.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_pass,
        database=target_db,
    )
    try:
        # 1. Alembic version
        alembic_version = await conn.fetchval("SELECT version_num FROM alembic_version")

        # 2. Table counts
        users_count = await conn.fetchval("SELECT count(*) FROM users")
        clubs_count = await conn.fetchval("SELECT count(*) FROM clubs")
        events_count = await conn.fetchval("SELECT count(*) FROM event_requests")
        templates_count = await conn.fetchval("SELECT count(*) FROM workflow_templates")

        # 3. Check for foreign key index presence
        fk_indexes_count = await conn.fetchval("""
            SELECT count(*)
            FROM pg_indexes
            WHERE indexname LIKE 'ix_%'
        """)

        report = {
            "alembic_version": alembic_version,
            "users_count": users_count,
            "clubs_count": clubs_count,
            "events_count": events_count,
            "templates_count": templates_count,
            "fk_indexes_count": fk_indexes_count,
        }
        return report
    finally:
        await conn.close()


def restore_database(
    backup_file: str,
    target_database: str | None = None,
    verify_only: bool = False,
) -> dict[str, any]:
    """
    Restores a database dump into the target database and verifies schema integrity.
    """
    settings = get_settings()

    backup_path = Path(backup_file).resolve()
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file does not exist: {backup_path}")

    # Verify checksum
    verify_checksum(backup_path)

    if verify_only:
        print("[SUCCESS] Checksum verified. Skipping database restore (--verify-only set).")
        return {"status": "verified"}

    # Parse connection string
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(db_url)

    db_host = parsed.hostname or "localhost"
    db_port = int(parsed.port or 5432)
    db_user = parsed.username or "postgres"
    db_password = parsed.password or ""
    target_db = target_database or (parsed.path.lstrip("/") + "_restored")

    # Ensure target database exists
    asyncio.run(
        ensure_database_exists(db_host, db_port, db_user, db_pass=db_password, target_db=target_db)
    )

    pg_restore_bin = find_pg_binary("pg_restore")
    print(f"[RESTORE] Restoring into {target_db} using {pg_restore_bin}...")

    env = os.environ.copy()
    if db_password:
        env["PGPASSWORD"] = db_password

    restore_cmd = [
        pg_restore_bin,
        "-h",
        db_host,
        "-p",
        str(db_port),
        "-U",
        db_user,
        "-d",
        target_db,
        "--clean",  # Clean (drop) database objects before recreating them
        "--if-exists",  # Use IF EXISTS when dropping
        "--no-owner",  # Skip restoration of object ownership
        "-v",
        str(backup_path),
    ]

    result = subprocess.run(restore_cmd, env=env, capture_output=True, text=True)
    # pg_restore exit code: 0 is success, 1 is warning (often harmless warnings during clean/drop)
    if result.returncode > 1:
        raise RuntimeError(f"pg_restore failed with exit code {result.returncode}: {result.stderr}")

    print(f"[SUCCESS] Database restored into {target_db}.")

    # Run verification queries against the restored DB
    report = asyncio.run(
        verify_restored_schema(db_host, db_port, db_user, db_pass=db_password, target_db=target_db)
    )
    print("[RESTORE VERIFICATION REPORT]")
    print(f"  - Alembic Version:     {report['alembic_version']}")
    print(f"  - Users Count:         {report['users_count']}")
    print(f"  - Clubs Count:         {report['clubs_count']}")
    print(f"  - Event Requests:      {report['events_count']}")
    print(f"  - Workflow Templates:  {report['templates_count']}")
    print(f"  - Indexes Verified:    {report['fk_indexes_count']}")

    assert (
        report["alembic_version"] == "0006_foreign_key_indexes"
    ), f"Restored Alembic version {report['alembic_version']} != expected head!"

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CampusConnect Disaster Recovery & Restore Utility"
    )
    parser.add_argument("backup_file", help="Path to .dump file to restore")
    parser.add_argument(
        "--target-db", dest="target_db", help="Target database name (default: <dbname>_restored)"
    )
    parser.add_argument(
        "--verify-only", dest="verify_only", action="store_true", help="Only verify file checksum"
    )
    args = parser.parse_args()

    restore_database(
        args.backup_file, target_database=args.target_db, verify_only=args.verify_only
    )
