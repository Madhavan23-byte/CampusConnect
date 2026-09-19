"""
CampusConnect — Development Seed Script
Seeds the database with clearly labeled DEVELOPMENT DATA for local testing.

IMPORTANT:
- This is NOT production data.
- Hall names are generic placeholders. Replace via Admin UI before deployment.
- Admin user credentials must be changed before any real use.
- Run ONLY in development environment.
- Run with: python scripts/seed_dev_data.py

Requires DATABASE_URL to be set in environment or .env file.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env file for development
from dotenv import load_dotenv  # type: ignore[import-untyped]  # optional dep
load_dotenv()

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# DEVELOPMENT SEED DATA — clearly labeled
# Replace hall names, admin email, etc. via Admin UI before real deployment.
# ---------------------------------------------------------------------------

DEVELOPMENT_HALLS = [
    {
        "name": "Main Auditorium",  # DEVELOPMENT DATA — replace via Admin UI
        "location": "Main Building, Ground Floor",
        "capacity": 500,
        "available_facilities": ["stage", "sound_system", "lcd", "ac", "projector"],
        "notes": "DEVELOPMENT SEED DATA — configure actual hall details via Admin panel.",
    },
    {
        "name": "Seminar Hall",  # DEVELOPMENT DATA — replace via Admin UI
        "location": "Block B, First Floor",
        "capacity": 150,
        "available_facilities": ["projector", "sound_system", "ac"],
        "notes": "DEVELOPMENT SEED DATA — configure actual hall details via Admin panel.",
    },
    {
        "name": "Conference Hall",  # DEVELOPMENT DATA — replace via Admin UI
        "location": "Admin Block, Second Floor",
        "capacity": 50,
        "available_facilities": ["projector", "ac"],
        "notes": "DEVELOPMENT SEED DATA — configure actual hall details via Admin panel.",
    },
]

from app.core.config import get_settings
_settings = get_settings()

DEVELOPMENT_ADMIN = {
    "email": os.environ.get("ADMIN_SEED_EMAIL", f"admin@{_settings.ALLOWED_EMAIL_DOMAIN}"),  # DEVELOPMENT DATA — change on first login
    "full_name": "System Administrator",
    "role": "SYSTEM_ADMIN",
    # Password: Admin@123! — MUST BE CHANGED BEFORE REAL USE
    # This is hashed below using Argon2id
    "raw_password": "Admin@123!",
}


async def hash_password(password: str) -> str:
    """Hash password using Argon2id."""
    from argon2 import PasswordHasher
    ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
    return ph.hash(password)


async def seed(session: AsyncSession) -> None:
    """Insert development seed data."""

    print("=" * 60)
    print("DEVELOPMENT SEED DATA — CampusConnect")
    print("=" * 60)
    print()

    # -----------------------------------------------------------------------
    # Create admin user
    # -----------------------------------------------------------------------
    existing_admin = await session.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": DEVELOPMENT_ADMIN["email"]},
    )
    if existing_admin.fetchone():
        print(f"[SKIP] Admin user '{DEVELOPMENT_ADMIN['email']}' already exists.")
    else:
        admin_id = str(uuid.uuid4())
        password_hash = await hash_password(DEVELOPMENT_ADMIN["raw_password"])
        await session.execute(
            text("""
                INSERT INTO users (id, email, email_verified, password_hash, full_name, role, is_active, created_at, updated_at)
                VALUES (:id, :email, true, :password_hash, :full_name, :role, true, NOW(), NOW())
            """),
            {
                "id": admin_id,
                "email": DEVELOPMENT_ADMIN["email"],
                "password_hash": password_hash,
                "full_name": DEVELOPMENT_ADMIN["full_name"],
                "role": DEVELOPMENT_ADMIN["role"],
            },
        )
        print(f"[SUCCESS] Created admin user: {DEVELOPMENT_ADMIN['email']}")
        print(f"          Password: {DEVELOPMENT_ADMIN['raw_password']} - CHANGE THIS IMMEDIATELY")
        admin_user_id = admin_id

    # -----------------------------------------------------------------------
    # Create development halls
    # -----------------------------------------------------------------------
    for hall_data in DEVELOPMENT_HALLS:
        existing_hall = await session.execute(
            text("SELECT id FROM halls WHERE name = :name"), {"name": hall_data["name"]}
        )
        if existing_hall.fetchone():
            print(f"[SKIP] Hall '{hall_data['name']}' already exists.")
            continue

        import json
        await session.execute(
            text("""
                INSERT INTO halls (id, name, location, capacity, available_facilities, is_active, notes, created_at, updated_at)
                VALUES (:id, :name, :location, :capacity, CAST(:facilities AS jsonb), true, :notes, NOW(), NOW())
            """),
            {
                "id": str(uuid.uuid4()),
                "name": hall_data["name"],
                "location": hall_data["location"],
                "capacity": hall_data["capacity"],
                "facilities": json.dumps(hall_data["available_facilities"]),
                "notes": hall_data["notes"],
            },
        )
        print(f"[SUCCESS] Created hall: {hall_data['name']} (capacity: {hall_data['capacity']})")

    await session.commit()
    print()
    print("=" * 60)
    print("Seed complete.")
    print("REMEMBER: Change admin password and hall details before real use.")
    print("=" * 60)


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL", _settings.DATABASE_URL)

    if "sqlite" in db_url:
        print("ERROR: Seed script requires PostgreSQL, not SQLite.")
        sys.exit(1)

    # Safety check — only run in development
    env = os.environ.get("ENV", "development")
    if env == "production":
        print("ERROR: Seed script must not run in production.")
        sys.exit(1)

    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        await seed(session)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
