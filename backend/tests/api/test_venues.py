"""
CampusConnect — Venue & Hall Reservation API & Domain Test Suite

Comprehensive tests for Day 4.2:
- Hall inventory creation & admin restriction
- Hall listing & availability inspection
- Event proposal venue requirement attachment
- Club secretary ownership & cross-club isolation
- Timing interval validation (end_time > start_time)
- Lead-time policy enforcement (HALL_BOOKING_MIN_ADVANCE_DAYS)
- Hall capacity validation
- Conflict pre-checking against confirmed hall bookings
- Proposal lifecycle boundaries (DRAFT / REVISION_REQUIRED vs SUBMITTED immutability)
- Venue request update & deletion
- Audit logging verification & zero secret leakage
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.domain import (
    AuditLog,
    Club,
    ClubMember,
    EventRequest,
    Hall,
    HallBookingConfirmed,
    User,
    VenueRequest,
)
from app.models.enums import (
    AuditAction,
    ClubMemberRole,
    EventRequestStatus,
    EventType,
    UserRole,
    VenueRequestStatus,
)


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------
async def _create_user(
    db,
    role: UserRole | str,
    prefix: str,
    is_active: bool = True,
    is_deleted: bool = False,
) -> User:
    """Create a verified test user."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@college.edu",
        password_hash=hash_password("Pass123!Secure"),
        full_name=f"Test {role} {uid}",
        role=role,
        is_active=is_active,
        deleted_at=datetime.now(timezone.utc) if is_deleted else None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _auth_header(user: User) -> dict[str, str]:
    """Generate authorization header for a test user."""
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token(
        subject=user.id,
        role=role_str,
        email=user.email,
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_club_and_secretary(
    db,
    club_name: str,
    admin: User,
    is_active: bool = True,
    is_deleted: bool = False,
) -> tuple[Club, User]:
    """Create a club and assign an active secretary."""
    uid = uuid.uuid4().hex[:6]
    slug = f"{club_name.lower().replace(' ', '-')}-{uid}"
    club = Club(
        name=f"{club_name} {uid}",
        slug=slug,
        description="A great college club",
        academic_year="2026-27",
        is_active=is_active,
        created_by=admin.id,
        deleted_at=datetime.now(timezone.utc) if is_deleted else None,
    )
    db.add(club)
    await db.commit()
    await db.refresh(club)

    secretary = await _create_user(db, UserRole.CLUB_SECRETARY, f"sec_{uid}")
    member = ClubMember(
        club_id=club.id,
        user_id=secretary.id,
        member_role=ClubMemberRole.SECRETARY,
        is_active=True,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return club, secretary


async def _create_hall(
    db,
    name: str = "Auditorium",
    capacity: int = 200,
    is_active: bool = True,
) -> Hall:
    """Create a campus hall directly in database."""
    uid = uuid.uuid4().hex[:6]
    hall = Hall(
        id=uuid.uuid4(),
        name=f"{name} {uid}",
        location="Main Campus Building",
        capacity=capacity,
        available_facilities=["projector", "audio", "stage"],
        notes="General campus hall",
        is_active=is_active,
    )
    db.add(hall)
    await db.commit()
    await db.refresh(hall)
    return hall


async def _create_event_draft(
    db,
    club: Club,
    secretary: User,
    attendees: int = 50,
) -> EventRequest:
    """Create an event draft directly in database."""
    event = EventRequest(
        id=uuid.uuid4(),
        club_id=club.id,
        submitted_by=secretary.id,
        title="Annual Tech Symposium",
        description="A symposium on modern computing",
        event_type=EventType.SEMINAR,
        expected_attendees=attendees,
        academic_year="2026-27",
        status=EventRequestStatus.DRAFT,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def _create_confirmed_booking(
    db,
    hall: Hall,
    start_time: datetime,
    end_time: datetime,
    admin: User,
) -> HallBookingConfirmed:
    """Create an active confirmed booking with required parent records."""
    club, sec = await _create_club_and_secretary(db, "Booking Club", admin)
    ev = await _create_event_draft(db, club, sec)
    vr = VenueRequest(
        id=uuid.uuid4(),
        event_request_id=ev.id,
        hall_id=hall.id,
        requested_date=start_time,
        start_time=start_time,
        end_time=end_time,
        status=VenueRequestStatus.APPROVED,
    )
    db.add(vr)
    await db.commit()
    await db.refresh(vr)

    booking = HallBookingConfirmed(
        id=uuid.uuid4(),
        hall_id=hall.id,
        event_request_id=ev.id,
        venue_request_id=vr.id,
        booking_date=start_time,
        start_time=start_time,
        end_time=end_time,
        is_active=True,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return booking


# ===========================================================================
# 1. HALL INVENTORY MANAGEMENT & RBAC
# ===========================================================================
@pytest.mark.asyncio
class TestHallManagement:
    """Tests for hall creation, listing, and inspection."""

    async def test_01_admin_can_create_hall(self, client: AsyncClient, db_session):
        """1. SYSTEM_ADMIN can create a new hall facility."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        uid = uuid.uuid4().hex[:6]
        payload = {
            "name": f"Seminar Hall {uid}",
            "location": "Academic Block 3",
            "capacity": 150,
            "available_facilities": ["projector", "ac"],
            "notes": "Renovated 2026",
        }
        res = await client.post("/api/v1/halls", json=payload, headers=_auth_header(admin))
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == payload["name"]
        assert data["capacity"] == 150
        assert data["is_active"] is True

        # Verify audit log
        audit = await db_session.scalar(
            select(AuditLog).where(
                AuditLog.action == AuditAction.HALL_CREATED,
                AuditLog.entity_id == data["id"],
            )
        )
        assert audit is not None
        assert audit.actor_id == admin.id

    async def test_02_non_admin_cannot_create_hall(self, client: AsyncClient, db_session):
        """2. Non-admin roles (CLUB_SECRETARY, etc.) receive 403 when creating a hall."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Music Club", admin)

        payload = {
            "name": "Unauthorized Hall",
            "location": "Nowhere",
            "capacity": 50,
        }
        res = await client.post("/api/v1/halls", json=payload, headers=_auth_header(secretary))
        assert res.status_code == 403

    async def test_03_authenticated_users_can_list_and_view_halls(
        self, client: AsyncClient, db_session
    ):
        """3. Authenticated users can list halls and retrieve hall details."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Dance Club", admin)
        hall = await _create_hall(db_session, "Amphitheatre", 500)

        # List halls
        res = await client.get("/api/v1/halls", headers=_auth_header(secretary))
        assert res.status_code == 200
        data = res.json()
        assert any(h["id"] == str(hall.id) for h in data)

        # Get specific hall
        res_single = await client.get(f"/api/v1/halls/{hall.id}", headers=_auth_header(secretary))
        assert res_single.status_code == 200
        assert res_single.json()["name"] == hall.name

    async def test_04_check_hall_availability(self, client: AsyncClient, db_session):
        """4. Check availability returns booked slots and availability flag."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Art Club", admin)
        hall = await _create_hall(db_session, "Gallery Hall", 80)

        target_date = (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat()
        res = await client.get(
            f"/api/v1/halls/{hall.id}/availability?date={target_date}T00:00:00Z",
            headers=_auth_header(secretary),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["hall_id"] == str(hall.id)
        assert data["is_available"] is True
        assert isinstance(data["booked_slots"], list)


# ===========================================================================
# 2. VENUE REQUEST ATTACHMENT & AUTHORIZATION
# ===========================================================================
@pytest.mark.asyncio
class TestVenueRequestCreation:
    """Tests for attaching venue requests to event proposals."""

    async def test_01_authorized_secretary_can_attach_venue(
        self, client: AsyncClient, db_session
    ):
        """1. Authorized secretary can attach a valid venue request to an event draft."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Coding Club", admin)
        event = await _create_event_draft(db_session, club, secretary, attendees=60)
        hall = await _create_hall(db_session, "Computing Lab", capacity=100)

        req_date = datetime.now(timezone.utc) + timedelta(days=10)
        start_time = req_date.replace(hour=10, minute=0, second=0, microsecond=0)
        end_time = req_date.replace(hour=13, minute=0, second=0, microsecond=0)

        payload = {
            "hall_id": str(hall.id),
            "requested_date": req_date.date().isoformat(),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "expected_audience": 60,
            "requires_lcd": True,
            "requires_audio": True,
            "additional_requirements": "Fast ethernet drops",
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 201
        data = res.json()
        assert data["event_request_id"] == str(event.id)
        assert data["hall_id"] == str(hall.id)
        assert data["status"] == "PENDING"
        assert data["requires_lcd"] is True
        assert data["hall_name"] == hall.name

    async def test_02_cross_club_secretary_cannot_attach_venue(
        self, client: AsyncClient, db_session
    ):
        """2. A secretary from Club B cannot attach a venue to Club A's event proposal."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club_a, sec_a = await _create_club_and_secretary(db_session, "Robotics A", admin)
        club_b, sec_b = await _create_club_and_secretary(db_session, "Astronomy B", admin)
        event_a = await _create_event_draft(db_session, club_a, sec_a)
        hall = await _create_hall(db_session, "Multi Hall", 100)

        req_date = datetime.now(timezone.utc) + timedelta(days=12)
        payload = {
            "hall_id": str(hall.id),
            "requested_date": req_date.date().isoformat(),
            "start_time": (req_date + timedelta(hours=2)).isoformat(),
            "end_time": (req_date + timedelta(hours=4)).isoformat(),
        }
        res = await client.post(
            f"/api/v1/events/{event_a.id}/venue", json=payload, headers=_auth_header(sec_b)
        )
        assert res.status_code == 403

    async def test_03_unauthorized_roles_cannot_attach_venue(
        self, client: AsyncClient, db_session
    ):
        """3. Faculty advisor or student union advisor cannot attach venue requirements (only secretary)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Debate Club", admin)
        event = await _create_event_draft(db_session, club, secretary)
        hall = await _create_hall(db_session, "Council Hall", 100)

        faculty = await _create_user(db_session, UserRole.FACULTY_ADVISOR, "fac")
        req_date = datetime.now(timezone.utc) + timedelta(days=10)
        payload = {
            "hall_id": str(hall.id),
            "requested_date": req_date.date().isoformat(),
            "start_time": (req_date + timedelta(hours=1)).isoformat(),
            "end_time": (req_date + timedelta(hours=3)).isoformat(),
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(faculty)
        )
        assert res.status_code == 403

    async def test_04_cannot_attach_second_venue_to_same_proposal(
        self, client: AsyncClient, db_session
    ):
        """4. 1-to-1 enforcement: Attempting to attach a second venue request returns 409 Conflict."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Quiz Club", admin)
        event = await _create_event_draft(db_session, club, secretary)
        hall = await _create_hall(db_session, "Main Quiz Hall", 100)

        req_date = datetime.now(timezone.utc) + timedelta(days=15)
        payload = {
            "hall_id": str(hall.id),
            "requested_date": req_date.date().isoformat(),
            "start_time": (req_date + timedelta(hours=1)).isoformat(),
            "end_time": (req_date + timedelta(hours=3)).isoformat(),
        }
        res1 = await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )
        assert res1.status_code == 201

        # Second attempt
        res2 = await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )
        assert res2.status_code == 409


# ===========================================================================
# 3. TIMING, ADVANCE NOTICE, & CAPACITY VALIDATION
# ===========================================================================
@pytest.mark.asyncio
class TestTimingAndCapacityValidation:
    """Tests for interval ordering, minimum advance days, and capacity safety."""

    async def test_01_end_time_before_or_equal_to_start_time_rejected(
        self, client: AsyncClient, db_session
    ):
        """1. end_time <= start_time rejected with 422 (Pydantic validation)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Math Club", admin)
        event = await _create_event_draft(db_session, club, secretary)
        hall = await _create_hall(db_session, "Lecture Hall 1", 100)

        req_date = datetime.now(timezone.utc) + timedelta(days=10)
        # end_time earlier than start_time
        payload = {
            "hall_id": str(hall.id),
            "requested_date": req_date.date().isoformat(),
            "start_time": (req_date + timedelta(hours=4)).isoformat(),
            "end_time": (req_date + timedelta(hours=2)).isoformat(),
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code in (400, 422)

    async def test_02_advance_notice_policy_enforcement(
        self, client: AsyncClient, db_session
    ):
        """2. Lead-time violation (< HALL_BOOKING_MIN_ADVANCE_DAYS = 7 days) rejected with 422."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Gaming Club", admin)
        event = await _create_event_draft(db_session, club, secretary)
        hall = await _create_hall(db_session, "Arena Hall", 100)

        # Booking only 3 days in advance (< 7 days)
        req_date = datetime.now(timezone.utc) + timedelta(days=3)
        payload = {
            "hall_id": str(hall.id),
            "requested_date": req_date.date().isoformat(),
            "start_time": (req_date + timedelta(hours=1)).isoformat(),
            "end_time": (req_date + timedelta(hours=3)).isoformat(),
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 422
        body = res.json()
        msg = body.get("message") or body.get("detail", "")
        assert "in advance" in str(msg).lower()

    async def test_03_capacity_violation_rejected(self, client: AsyncClient, db_session):
        """3. When expected audience exceeds hall capacity, request is rejected with 400."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Drama Club", admin)
        event = await _create_event_draft(db_session, club, secretary, attendees=300)
        small_hall = await _create_hall(db_session, "Small Room", capacity=50)

        req_date = datetime.now(timezone.utc) + timedelta(days=10)
        payload = {
            "hall_id": str(small_hall.id),
            "requested_date": req_date.date().isoformat(),
            "start_time": (req_date + timedelta(hours=1)).isoformat(),
            "end_time": (req_date + timedelta(hours=3)).isoformat(),
            "expected_audience": 250,  # 250 > 50
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 400
        body = res.json()
        msg = body.get("message") or body.get("detail", "")
        assert "capacity" in str(msg).lower()

    async def test_04_inactive_hall_rejected(self, client: AsyncClient, db_session):
        """4. Inactive hall cannot be requested (400 Bad Request)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Poetry Club", admin)
        event = await _create_event_draft(db_session, club, secretary)
        inactive_hall = await _create_hall(db_session, "Under Renovation Hall", 100, is_active=False)

        req_date = datetime.now(timezone.utc) + timedelta(days=10)
        payload = {
            "hall_id": str(inactive_hall.id),
            "requested_date": req_date.date().isoformat(),
            "start_time": (req_date + timedelta(hours=1)).isoformat(),
            "end_time": (req_date + timedelta(hours=3)).isoformat(),
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 400
        body = res.json()
        msg = body.get("message") or body.get("detail", "")
        assert "inactive" in str(msg).lower()


# ===========================================================================
# 4. CONFLICT PRE-CHECKING & OCCUPANCY INTERVALS
# ===========================================================================
@pytest.mark.asyncio
class TestHallConflictPreCheck:
    """Tests for conflict pre-checking against confirmed hall bookings."""

    async def test_01_overlapping_confirmed_booking_rejected(
        self, client: AsyncClient, db_session
    ):
        """1. Request overlapping an active confirmed booking returns 409 HallConflictError."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Science Club", admin)
        hall = await _create_hall(db_session, "Convention Center", 300)

        base_time = datetime.now(timezone.utc) + timedelta(days=14)
        t_start = base_time.replace(hour=10, minute=0, second=0, microsecond=0)
        t_end = base_time.replace(hour=12, minute=0, second=0, microsecond=0)

        # Create confirmed active booking for [10:00, 12:00)
        await _create_confirmed_booking(db_session, hall, t_start, t_end, admin)

        # Attempt to create venue request overlapping [11:00, 13:00)
        event = await _create_event_draft(db_session, club, secretary)
        payload = {
            "hall_id": str(hall.id),
            "requested_date": base_time.date().isoformat(),
            "start_time": (base_time.replace(hour=11, minute=0, second=0, microsecond=0)).isoformat(),
            "end_time": (base_time.replace(hour=13, minute=0, second=0, microsecond=0)).isoformat(),
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 409
        body = res.json()
        msg = body.get("message") or body.get("detail", "")
        assert "already confirmed" in str(msg).lower()

    async def test_02_adjacent_booking_succeeds(self, client: AsyncClient, db_session):
        """2. Adjacent back-to-back booking [12:00, 14:00) succeeds without conflict."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Film Club", admin)
        hall = await _create_hall(db_session, "Cinema Hall", 200)

        base_time = datetime.now(timezone.utc) + timedelta(days=14)
        t_start = base_time.replace(hour=10, minute=0, second=0, microsecond=0)
        t_end = base_time.replace(hour=12, minute=0, second=0, microsecond=0)

        # Existing booking [10:00, 12:00)
        await _create_confirmed_booking(db_session, hall, t_start, t_end, admin)

        # Adjacent slot [12:00, 14:00)
        event = await _create_event_draft(db_session, club, secretary)
        payload = {
            "hall_id": str(hall.id),
            "requested_date": base_time.date().isoformat(),
            "start_time": (base_time.replace(hour=12, minute=0, second=0, microsecond=0)).isoformat(),
            "end_time": (base_time.replace(hour=14, minute=0, second=0, microsecond=0)).isoformat(),
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 201
        assert res.json()["status"] == "PENDING"

    async def test_03_different_hall_same_time_succeeds(
        self, client: AsyncClient, db_session
    ):
        """3. Different hall at same time slot succeeds without conflict."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Chess Club", admin)
        hall1 = await _create_hall(db_session, "Hall 1", 100)
        hall2 = await _create_hall(db_session, "Hall 2", 100)

        base_time = datetime.now(timezone.utc) + timedelta(days=14)
        t_start = base_time.replace(hour=10, minute=0, second=0, microsecond=0)
        t_end = base_time.replace(hour=12, minute=0, second=0, microsecond=0)

        # Hall 1 booked [10:00, 12:00)
        await _create_confirmed_booking(db_session, hall1, t_start, t_end, admin)

        # Hall 2 requested for same [10:00, 12:00)
        event = await _create_event_draft(db_session, club, secretary)
        payload = {
            "hall_id": str(hall2.id),
            "requested_date": base_time.date().isoformat(),
            "start_time": t_start.isoformat(),
            "end_time": t_end.isoformat(),
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 201


# ===========================================================================
# 5. VENUE REQUEST LIFECYCLE & PROPOSAL BOUNDARIES
# ===========================================================================
@pytest.mark.asyncio
class TestVenueRequestLifecycle:
    """Tests for modification, deletion, and proposal state immutability."""

    async def test_01_update_and_retrieve_venue_request(
        self, client: AsyncClient, db_session
    ):
        """1. Secretary can update and retrieve venue requirements while in DRAFT state."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Robotics B", admin)
        event = await _create_event_draft(db_session, club, secretary)
        hall1 = await _create_hall(db_session, "Hall Alpha", 150)
        hall2 = await _create_hall(db_session, "Hall Beta", 200)

        req_date = datetime.now(timezone.utc) + timedelta(days=10)
        payload = {
            "hall_id": str(hall1.id),
            "requested_date": req_date.date().isoformat(),
            "start_time": (req_date + timedelta(hours=1)).isoformat(),
            "end_time": (req_date + timedelta(hours=3)).isoformat(),
            "requires_lcd": False,
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 201

        # GET venue
        res_get = await client.get(
            f"/api/v1/events/{event.id}/venue", headers=_auth_header(secretary)
        )
        assert res_get.status_code == 200
        assert res_get.json()["hall_name"] == hall1.name

        # PATCH venue: switch to hall2 and requires_lcd=True
        patch_payload = {
            "hall_id": str(hall2.id),
            "requires_lcd": True,
            "additional_requirements": "High gain microphone",
        }
        res_patch = await client.patch(
            f"/api/v1/events/{event.id}/venue", json=patch_payload, headers=_auth_header(secretary)
        )
        assert res_patch.status_code == 200
        data = res_patch.json()
        assert data["hall_id"] == str(hall2.id)
        assert data["requires_lcd"] is True
        assert data["additional_requirements"] == "High gain microphone"

    async def test_02_delete_venue_request_in_draft(
        self, client: AsyncClient, db_session
    ):
        """2. Secretary can remove venue requirement from draft proposal."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Eco Club", admin)
        event = await _create_event_draft(db_session, club, secretary)
        hall = await _create_hall(db_session, "Green Hall", 100)

        req_date = datetime.now(timezone.utc) + timedelta(days=10)
        payload = {
            "hall_id": str(hall.id),
            "requested_date": req_date.date().isoformat(),
            "start_time": (req_date + timedelta(hours=1)).isoformat(),
            "end_time": (req_date + timedelta(hours=3)).isoformat(),
        }
        await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )

        # DELETE venue
        res_del = await client.delete(
            f"/api/v1/events/{event.id}/venue", headers=_auth_header(secretary)
        )
        assert res_del.status_code == 204

        # Verify it is gone
        res_get = await client.get(
            f"/api/v1/events/{event.id}/venue", headers=_auth_header(secretary)
        )
        assert res_get.status_code == 404

    async def test_03_submitted_event_cannot_modify_or_delete_venue(
        self, client: AsyncClient, db_session
    ):
        """3. Once event proposal is SUBMITTED, venue request is frozen and cannot be modified or deleted."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Sports Club", admin)
        event = await _create_event_draft(db_session, club, secretary)
        hall = await _create_hall(db_session, "Gymnasium", 400)

        req_date = datetime.now(timezone.utc) + timedelta(days=10)
        payload = {
            "hall_id": str(hall.id),
            "requested_date": req_date.date().isoformat(),
            "start_time": (req_date + timedelta(hours=1)).isoformat(),
            "end_time": (req_date + timedelta(hours=3)).isoformat(),
        }
        await client.post(
            f"/api/v1/events/{event.id}/venue", json=payload, headers=_auth_header(secretary)
        )

        # Submit event proposal
        res_submit = await client.post(
            f"/api/v1/events/{event.id}/submit",
            json={"submission_notes": "Ready for institutional review"},
            headers=_auth_header(secretary),
        )
        assert res_submit.status_code == 200
        assert res_submit.json()["status"] == "SUBMITTED"

        # Attempt to PATCH venue request on submitted proposal MUST FAIL with 403 WorkflowStateError
        res_patch = await client.patch(
            f"/api/v1/events/{event.id}/venue",
            json={"additional_requirements": "Late addition"},
            headers=_auth_header(secretary),
        )
        assert res_patch.status_code == 403
        body_patch = res_patch.json()
        msg_patch = body_patch.get("message") or body_patch.get("detail", "")
        assert "submitted" in str(msg_patch).lower()

        # Attempt to DELETE venue request on submitted proposal MUST FAIL with 403 WorkflowStateError
        res_del = await client.delete(
            f"/api/v1/events/{event.id}/venue", headers=_auth_header(secretary)
        )
        assert res_del.status_code == 403
        body_del = res_del.json()
        msg_del = body_del.get("message") or body_del.get("detail", "")
        assert "submitted" in str(msg_del).lower()
