# CampusConnect — Disaster Recovery & Backup/Restore Architecture

## 1. Overview & Objectives
This document establishes the Disaster Recovery (DR) and business continuity procedures for CampusConnect. It defines automated backup generation, cryptographic checksum verification, retention policies, and an isolated restore drill procedure.

---

## 2. Backup Strategy & Procedure

### A. Database Backup (`scripts/backup.py`)
- **Engine**: PostgreSQL 16 `pg_dump`
- **Format**: Custom compressed archive (`-Fc`), enabling parallel restoration, selective table restoration, and blob integrity.
- **Credential Protection**: Passwords are supplied strictly via environment variables (`PGPASSWORD`) and parsed database URLs. No credentials are leaked to command-line argument lists (`ps` / Task Manager).
- **Integrity**: Every backup artifact produces a companion `.sha256` checksum file.
- **Retention**: Automated pruning of database dumps and upload tarballs older than configurable threshold (default: 14 days).

**Execution Command**:
```bash
python scripts/backup.py --retention 14
```

### B. Document Storage Backup
- Uploads directory (`/app/uploads`) is bundled into a timestamped compressed tarball (`uploads_YYYYMMDD_HHMMSS.tar.gz`) with a companion SHA-256 checksum.

---

## 3. Restore Strategy & Procedure

### A. Target Isolation
- Restore operations target an isolated staging or recovery database (e.g. `campusconnect_dr_test` or a new cluster) before cutting over traffic.
- Pre-restore verification validates the backup file's SHA-256 checksum.

**Execution Command**:
```bash
python scripts/restore.py backups/campusconnect_db_20260929_032916.dump --target-db campusconnect_dr_test
```

### B. Post-Restore Verification Checks
Every restore execution validates:
1. **Schema Head**: Alembic version table matches current migration head `0006_foreign_key_indexes`.
2. **Entity Consistency**: Row counts for `users`, `clubs`, `workflow_templates`, and `event_requests`.
3. **Index Completeness**: Verification that all 68+ foreign key and domain indexes are rebuilt and functional.
4. **Application Connectivity**: Async connection verification via SQLAlchemy/asyncpg to ensure active queries execute without permission or constraint faults.

---

## 4. Disaster Recovery Drill Verification Results

A complete, live DR drill was performed on the active PostgreSQL instance:

| Step | Action Performed | Result | Verification Status |
| :--- | :--- | :--- | :--- |
| **1. Backup Creation** | `python scripts/backup.py` | Generated `campusconnect_db_20260929_032916.dump` (140.2 KB) | **VERIFIED** |
| **2. Checksum Calc** | SHA-256 hash generated | `143eca12adc094d9861aea2ae77598e474ca8961483b2e1dc2896b0601000240` | **VERIFIED** |
| **3. Checksum Match** | Pre-restore integrity check | Expected == Computed SHA-256 | **VERIFIED** |
| **4. Database Creation**| Automated creation of target DB | `campusconnect_dr_test` created | **VERIFIED** |
| **5. Database Restore** | Native `pg_restore` execution | Restored schema and records with exit code 0 | **VERIFIED** |
| **6. Alembic Head** | Query `alembic_version` | `0006_foreign_key_indexes` | **VERIFIED** |
| **7. Entity Counts** | Query core entities | Users: 10, Clubs: 2, Events: 1, Templates: 1 | **VERIFIED** |
| **8. Index Verification**| Query `pg_indexes` | 68 indexes verified | **VERIFIED** |
| **9. App Connectivity**| Asyncpg query execution | Query returned expected record set | **VERIFIED** |
| **10. Production Safety**| Inspect production DB | `campusconnect` live DB remained isolated & unmodified | **VERIFIED** |
| **11. Teardown** | Clean up drill target DB | `campusconnect_dr_test` cleanly dropped | **VERIFIED** |

**DR Drill Status**: **100% VERIFIED**

---

## 5. Rollback & Emergency Incident Procedures

1. **Database Migration Failure**:
   - If a migration fails during deployment, restore the pre-migration dump to an isolated database, verify data integrity, point application connection pool to the restored instance, and restart backend containers.
2. **Container or Host Failure**:
   - Re-provision the Docker Compose stack using `docker-compose.prod.yml`.
   - Mount the persistent volumes (`postgres_prod_data`, `uploads_prod_data`).
   - If volume data was lost, run `restore.py` using the latest verified dump from offsite storage.
