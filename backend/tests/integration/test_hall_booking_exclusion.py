"""
CampusConnect — Critical Hall Booking Exclusion Constraint Integration Test
Verifies that PostgreSQL database-level exclusion constraint (btree_gist):
1. Rejects overlapping bookings for the same hall (10:00-12:00 vs 11:00-13:00)
2. Allows back-to-back adjacent bookings [start, end) (10:00-12:00 vs 12:00-14:00)
3. Allows overlapping time slots across DIFFERENT halls (Hall A vs Hall B)
4. Enforces check constraint: end_time must be strictly after start_time
"""
import uuid
import os
from datetime import datetime, timezone
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

POSTGRES_TEST_URL = os.getenv("TEST_DATABASE_URL")
if not POSTGRES_TEST_URL or "sqlite" in POSTGRES_TEST_URL:
    db_url = os.getenv("DATABASE_URL", "")
    if "postgres" in db_url:
        POSTGRES_TEST_URL = db_url
    else:
        POSTGRES_TEST_URL = "postgresql+asyncpg://campusconnect:campusconnect_dev_password@localhost:5432/campusconnect"


@pytest.mark.asyncio
async def test_hall_booking_exclusion_constraint():
    """Verify PostgreSQL exclusion constraint prevents double bookings at the database level."""
    engine = create_async_engine(POSTGRES_TEST_URL)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with session_factory() as session:
        # 1. Create two test halls
        hall_a_id = uuid.uuid4()
        hall_b_id = uuid.uuid4()

        await session.execute(
            text(
                "INSERT INTO halls (id, name, location, capacity, is_active, created_at, updated_at) "
                "VALUES (:id, :name, 'Block A', 100, true, now(), now())"
            ),
            [
                {"id": hall_a_id, "name": f"Test Hall A {hall_a_id}"},
                {"id": hall_b_id, "name": f"Test Hall B {hall_b_id}"},
            ],
        )

        # 2. Create required parent records: user, club, event_requests, venue_requests
        user_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role, is_active, created_at, updated_at) "
                "VALUES (:id, :email, 'hash', 'Test User', 'FACULTY_COORDINATOR', true, now(), now())"
            ),
            {"id": user_id, "email": f"testuser_{user_id}@college.edu"},
        )

        club_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO clubs (id, name, slug, academic_year, created_by, is_active, created_at, updated_at) "
                "VALUES (:id, :name, :slug, '2026-27', :user_id, true, now(), now())"
            ),
            {"id": club_id, "name": f"Test Club {club_id}", "slug": f"club-{str(club_id)[:8]}", "user_id": user_id},
        )

        async def create_event_and_venue_request(target_hall_id):
            er_id = uuid.uuid4()
            vr_id = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO event_requests (id, club_id, submitted_by, title, description, event_type, status, academic_year, created_at, updated_at) "
                    "VALUES (:id, :club_id, :user_id, 'Test Event', 'Desc', 'WORKSHOP', 'APPROVED', '2026-27', now(), now())"
                ),
                {"id": er_id, "club_id": club_id, "user_id": user_id},
            )
            req_date = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
            s_time = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)
            e_time = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
            await session.execute(
                text(
                    "INSERT INTO venue_requests (id, event_request_id, hall_id, requested_date, start_time, end_time, created_at, updated_at) "
                    "VALUES (:id, :er_id, :hall_id, :req_date, :start, :end, now(), now())"
                ),
                {"id": vr_id, "er_id": er_id, "hall_id": target_hall_id, "req_date": req_date, "start": s_time, "end": e_time},
            )
            return er_id, vr_id

        # Insert first booking: Hall A, 10:00 -> 12:00
        t1_start = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)
        t1_end = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
        er1, vr1 = await create_event_and_venue_request(hall_a_id)
        b1_id = uuid.uuid4()

        await session.execute(
            text(
                "INSERT INTO hall_bookings_confirmed (id, hall_id, event_request_id, venue_request_id, booking_date, start_time, end_time, is_active, created_at, updated_at) "
                "VALUES (:id, :hall_id, :er_id, :vr_id, :date, :start, :end, true, now(), now())"
            ),
            {"id": b1_id, "hall_id": hall_a_id, "er_id": er1, "vr_id": vr1, "date": t1_start, "start": t1_start, "end": t1_end},
        )
        await session.commit()

        # TEST CASE 1: Overlapping booking for Hall A (11:00 -> 13:00) MUST FAIL with Exclusion / IntegrityError
        t2_start = datetime(2026, 10, 10, 11, 0, tzinfo=timezone.utc)
        t2_end = datetime(2026, 10, 10, 13, 0, tzinfo=timezone.utc)
        er2, vr2 = await create_event_and_venue_request(hall_a_id)
        b2_id = uuid.uuid4()

        with pytest.raises((IntegrityError, DBAPIError)) as exc_info:
            await session.execute(
                text(
                    "INSERT INTO hall_bookings_confirmed (id, hall_id, event_request_id, venue_request_id, booking_date, start_time, end_time, is_active, created_at, updated_at) "
                    "VALUES (:id, :hall_id, :er_id, :vr_id, :date, :start, :end, true, now(), now())"
                ),
                {"id": b2_id, "hall_id": hall_a_id, "er_id": er2, "vr_id": vr2, "date": t2_start, "start": t2_start, "end": t2_end},
            )
            await session.commit()
        await session.rollback()
        assert "excl_hall_bookings_no_overlap" in str(exc_info.value).lower() or "exclusion" in str(exc_info.value).lower()

        # TEST CASE 2: Adjacent back-to-back booking for Hall A (12:00 -> 14:00) MUST SUCCEED (range is [start, end))
        t3_start = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
        t3_end = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)
        er3, vr3 = await create_event_and_venue_request(hall_a_id)
        b3_id = uuid.uuid4()

        await session.execute(
            text(
                "INSERT INTO hall_bookings_confirmed (id, hall_id, event_request_id, venue_request_id, booking_date, start_time, end_time, is_active, created_at, updated_at) "
                "VALUES (:id, :hall_id, :er_id, :vr_id, :date, :start, :end, true, now(), now())"
            ),
            {"id": b3_id, "hall_id": hall_a_id, "er_id": er3, "vr_id": vr3, "date": t3_start, "start": t3_start, "end": t3_end},
        )
        await session.commit()

        # TEST CASE 3: Same time (10:00 -> 12:00) for DIFFERENT HALL (Hall B) MUST SUCCEED
        er4, vr4 = await create_event_and_venue_request(hall_b_id)
        b4_id = uuid.uuid4()

        await session.execute(
            text(
                "INSERT INTO hall_bookings_confirmed (id, hall_id, event_request_id, venue_request_id, booking_date, start_time, end_time, is_active, created_at, updated_at) "
                "VALUES (:id, :hall_id, :er_id, :vr_id, :date, :start, :end, true, now(), now())"
            ),
            {"id": b4_id, "hall_id": hall_b_id, "er_id": er4, "vr_id": vr4, "date": t1_start, "start": t1_start, "end": t1_end},
        )
        await session.commit()

        # TEST CASE 4: Invalid booking where end_time <= start_time MUST FAIL via CHECK constraint
        t5_start = datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)
        t5_end = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)
        er5, vr5 = await create_event_and_venue_request(hall_a_id)
        b5_id = uuid.uuid4()

        with pytest.raises((IntegrityError, DBAPIError)) as exc_info:
            await session.execute(
                text(
                    "INSERT INTO hall_bookings_confirmed (id, hall_id, event_request_id, venue_request_id, booking_date, start_time, end_time, is_active, created_at, updated_at) "
                    "VALUES (:id, :hall_id, :er_id, :vr_id, :date, :start, :end, true, now(), now())"
                ),
                {"id": b5_id, "hall_id": hall_a_id, "er_id": er5, "vr_id": vr5, "date": t5_start, "start": t5_start, "end": t5_end},
            )
            await session.commit()
        await session.rollback()
        assert "ck_hall_bookings_end_after_start" in str(exc_info.value).lower() or "check" in str(exc_info.value).lower()

        # Clean up test data
        await session.execute(text("DELETE FROM hall_bookings_confirmed WHERE hall_id IN (:h1, :h2)"), {"h1": hall_a_id, "h2": hall_b_id})
        await session.execute(text("DELETE FROM venue_requests WHERE hall_id IN (:h1, :h2)"), {"h1": hall_a_id, "h2": hall_b_id})
        await session.execute(text("DELETE FROM event_requests WHERE club_id = :club_id"), {"club_id": club_id})
        await session.execute(text("DELETE FROM clubs WHERE id = :club_id"), {"club_id": club_id})
        await session.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
        await session.execute(text("DELETE FROM halls WHERE id IN (:h1, :h2)"), {"h1": hall_a_id, "h2": hall_b_id})
        await session.commit()

    await engine.dispose()
