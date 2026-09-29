"""
Phase 2.5.6 Disaster Recovery Integration Test
Tests:
- Live database backup creation using pg_dump
- SHA-256 checksum generation and validation
- Database restore into an isolated environment (campusconnect_dr_test)
- Verification of Alembic head (0006_foreign_key_indexes)
- Verification of data entities, indexes, and relations in restored DB
- Clean teardown of DR test database
"""

import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
from dotenv import dotenv_values
import pytest

from scripts.backup import create_backup
from scripts.restore import restore_database


class TestDisasterRecoveryEndToEnd:
    """Verifies that the entire backup and restore cycle works cleanly on live PostgreSQL."""

    @pytest.mark.asyncio
    async def test_backup_and_restore_cycle(self):
        # Read real postgres URL from .env
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        env_vars = dotenv_values(str(env_path)) if env_path.exists() else {}
        db_url = env_vars.get("DATABASE_URL") or "postgresql+asyncpg://campusconnect:campusconnect_dev_password@localhost:5432/campusconnect"

        if "postgresql" not in db_url:
            pytest.skip("Disaster recovery test requires real PostgreSQL instance.")

        temp_dir = Path(tempfile.mkdtemp(prefix="cc_dr_test_"))
        target_db = "campusconnect_dr_test"

        try:
            # 1. Perform backup
            backup_result = create_backup(
                output_dir=str(temp_dir),
                include_uploads=False,
                retention_days=1,
            )

            dump_file = backup_result["db_dump"]
            checksum_file = backup_result["db_checksum"]

            assert Path(dump_file).exists()
            assert Path(checksum_file).exists()
            assert len(backup_result["db_sha256"]) == 64

            # 2. Perform restore into isolated database
            report = restore_database(
                backup_file=dump_file,
                target_database=target_db,
            )

            # 3. Validate restored schema and data
            assert report["alembic_version"] == "0006_foreign_key_indexes"
            assert report["users_count"] >= 1
            assert report["clubs_count"] >= 1
            assert report["templates_count"] >= 1
            assert report["fk_indexes_count"] >= 10

        finally:
            # 4. Clean up isolated test database
            parsed = urlparse(db_url.replace("postgresql+asyncpg://", "postgresql://"))
            db_host = parsed.hostname or "localhost"
            db_port = int(parsed.port or 5432)
            db_user = parsed.username or "postgres"
            db_pass = parsed.password or ""

            try:
                conn = await asyncpg.connect(
                    host=db_host,
                    port=db_port,
                    user=db_user,
                    password=db_pass,
                    database="campusconnect",
                )
                await conn.execute(f'DROP DATABASE IF EXISTS "{target_db}"')
                await conn.close()
            except Exception as e:
                print(f"[CLEANUP ERROR] Failed to drop {target_db}: {e}")

            # Remove temporary directory
            shutil.rmtree(temp_dir, ignore_errors=True)
