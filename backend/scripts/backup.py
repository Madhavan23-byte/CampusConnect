"""
CampusConnect — Automated Database & File Storage Backup Utility
Performs:
- Native pg_dump of PostgreSQL database in custom compressed format (-Fc)
- SHA-256 integrity checksum generation
- File storage (/app/uploads) tarball archiving
- Retention policy enforcement (pruning backups older than retention limit)
- Zero credentials committed or leaked to stdout/process tables
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

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


def prune_old_backups(backup_dir: Path, retention_days: int) -> None:
    """Delete backup files older than retention limit."""
    now = datetime.now(UTC).timestamp()
    cutoff = now - (retention_days * 86400)

    for item in backup_dir.glob("campusconnect_*.dump"):
        if item.stat().st_mtime < cutoff:
            checksum_file = item.with_suffix(item.suffix + ".sha256")
            if checksum_file.exists():
                checksum_file.unlink()
            item.unlink()
            print(f"[RETENTION] Pruned expired backup: {item.name}")

    for item in backup_dir.glob("uploads_*.tar.gz"):
        if item.stat().st_mtime < cutoff:
            checksum_file = item.with_suffix(item.suffix + ".sha256")
            if checksum_file.exists():
                checksum_file.unlink()
            item.unlink()
            print(f"[RETENTION] Pruned expired uploads backup: {item.name}")


def create_backup(
    output_dir: str | None = None,
    include_uploads: bool = True,
    retention_days: int = 14,
) -> dict[str, str]:
    """
    Creates a full database dump and uploads archive.
    Returns paths to generated backup files and checksums.
    """
    settings = get_settings()

    # Parse connection string
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(db_url)

    db_host = parsed.hostname or "localhost"
    db_port = str(parsed.port or 5432)
    db_user = parsed.username or "postgres"
    db_password = parsed.password or ""
    db_name = parsed.path.lstrip("/")

    # Setup target directory
    base_dir = Path(output_dir) if output_dir else Path(__file__).resolve().parent.parent / "backups"
    base_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    db_backup_path = base_dir / f"campusconnect_db_{timestamp}.dump"
    db_checksum_path = base_dir / f"campusconnect_db_{timestamp}.dump.sha256"

    print(f"[BACKUP] Starting database backup: {db_name}@{db_host}:{db_port}...")
    pg_dump_bin = find_pg_binary("pg_dump")

    # Pass password via environment to avoid command line process table leakage
    env = os.environ.copy()
    if db_password:
        env["PGPASSWORD"] = db_password

    dump_cmd = [
        pg_dump_bin,
        "-h", db_host,
        "-p", db_port,
        "-U", db_user,
        "-F", "c",          # Custom compressed archive format
        "-b",               # Include large objects
        "-v",               # Verbose
        "-f", str(db_backup_path),
        db_name,
    ]

    result = subprocess.run(dump_cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed with exit code {result.returncode}: {result.stderr}")

    db_checksum = compute_sha256(str(db_backup_path))
    db_checksum_path.write_text(f"{db_checksum}  {db_backup_path.name}\n", encoding="utf-8")
    file_size_kb = db_backup_path.stat().st_size / 1024
    print(f"[SUCCESS] Database backup created: {db_backup_path.name} ({file_size_kb:.1f} KB)")
    print(f"[SUCCESS] SHA-256 Checksum: {db_checksum}")

    results = {
        "db_dump": str(db_backup_path),
        "db_checksum": str(db_checksum_path),
        "db_sha256": db_checksum,
    }

    # Backup uploads directory if it exists and has files
    if include_uploads:
        uploads_dir = Path(settings.UPLOAD_BASE_DIR)
        if not uploads_dir.is_absolute():
            uploads_dir = Path(__file__).resolve().parent.parent / settings.UPLOAD_BASE_DIR

        if uploads_dir.exists() and any(uploads_dir.iterdir()):
            uploads_tar_path = base_dir / f"uploads_{timestamp}.tar.gz"
            uploads_checksum_path = base_dir / f"uploads_{timestamp}.tar.gz.sha256"

            with tarfile.open(uploads_tar_path, "w:gz") as tar:
                tar.add(uploads_dir, arcname="uploads")

            up_checksum = compute_sha256(str(uploads_tar_path))
            uploads_checksum_path.write_text(f"{up_checksum}  {uploads_tar_path.name}\n", encoding="utf-8")
            print(f"[SUCCESS] Uploads archive created: {uploads_tar_path.name}")
            results["uploads_tar"] = str(uploads_tar_path)
            results["uploads_sha256"] = up_checksum

    # Prune old backups
    prune_old_backups(base_dir, retention_days)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CampusConnect Database and Uploads Backup")
    parser.add_argument("--dir", dest="output_dir", help="Target backup directory")
    parser.add_argument("--no-uploads", dest="uploads", action="store_false", help="Skip uploads archiving")
    parser.add_argument("--retention", dest="retention", type=int, default=14, help="Retention period in days")
    args = parser.parse_args()

    create_backup(output_dir=args.output_dir, include_uploads=args.uploads, retention_days=args.retention)
