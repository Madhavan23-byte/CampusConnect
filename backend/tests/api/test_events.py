"""
CampusConnect — Event Proposal Foundation API & Security Test Suite

Comprehensive tests for Day 4.1:
- Draft creation & validation
- Secretary ownership & cross-club isolation
- Inactive / soft-deleted club rejection
- Draft modification & optimistic version locking
- Proposal submission & immutable version snapshotting
- Submitted proposal immutability (rejection of PATCH on submitted event)
- Idempotency handling
- Audit logging & state snapshots
- Zero credential leakage
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.domain import AuditLog, Club, ClubMember, EventRequest, EventRequestVersion, User
from app.models.enums import AuditAction, ClubMemberRole, EventRequestStatus, EventType, UserRole


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


# ===========================================================================
# 1. EVENT PROPOSAL DRAFT CREATION
# ===========================================================================
@pytest.mark.asyncio
class TestEventDraftCreation:
    """Tests for creating event proposal drafts."""

    async def test_01_authorized_secretary_can_create_draft(self, client: AsyncClient, db_session):
        """1. Authorized club secretary can create an event draft (status=DRAFT, version=0)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Robotics Society", admin)

        payload = {
            "club_id": str(club.id),
            "title": "Autonomous Drone Workshop",
            "description": "Hands-on quadcopter flight controller setup",
            "event_type": "WORKSHOP",
            "expected_attendees": 45,
            "academic_year": "2026-27",
        }
        res = await client.post("/api/v1/events", json=payload, headers=_auth_header(secretary))
        assert res.status_code == 201
        data = res.json()
        assert data["title"] == "Autonomous Drone Workshop"
        assert data["club_id"] == str(club.id)
        assert data["status"] == "DRAFT"
        assert data["current_version"] == 0
        assert data["version_lock"] == 0
        assert data["submitted_by"] == str(secretary.id)

        # Verify audit log
        log = await db_session.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == data["id"], AuditLog.action == AuditAction.PROPOSAL_CREATED
            )
        )
        assert log is not None
        assert log.actor_id == secretary.id
        assert log.new_state["status"] == "DRAFT"

    async def test_02_secretary_cannot_create_event_for_another_club(self, client: AsyncClient, db_session):
        """2. Secretary of Club A cannot create an event proposal for Club B (403 Forbidden)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club_a, sec_a = await _create_club_and_secretary(db_session, "Club Alpha", admin)
        club_b, sec_b = await _create_club_and_secretary(db_session, "Club Beta", admin)

        payload = {
            "club_id": str(club_b.id),
            "title": "Cross-Club Unauthorized Event",
            "event_type": "CULTURAL",
            "academic_year": "2026-27",
        }
        res = await client.post("/api/v1/events", json=payload, headers=_auth_header(sec_a))
        assert res.status_code == 403
        assert res.json()["error"] == "forbidden"

    async def test_03_non_secretary_role_cannot_create_draft(self, client: AsyncClient, db_session):
        """3. Non-secretary user receives 403 Forbidden when creating an event proposal."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        finance = await _create_user(db_session, UserRole.FINANCE_OFFICER, "fin")
        club, _ = await _create_club_and_secretary(db_session, "Finance Non-Sec Club", admin)

        payload = {
            "club_id": str(club.id),
            "title": "Finance Created Event",
            "event_type": "SEMINAR",
            "academic_year": "2026-27",
        }
        res = await client.post("/api/v1/events", json=payload, headers=_auth_header(finance))
        assert res.status_code == 403

    async def test_04_cannot_create_event_for_inactive_club(self, client: AsyncClient, db_session):
        """4. Cannot propose an event for an inactive club (400 Bad Request)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(
            db_session, "Dormant Club", admin, is_active=False
        )

        payload = {
            "club_id": str(club.id),
            "title": "Dormant Club Proposal",
            "event_type": "SPORTS",
            "academic_year": "2026-27",
        }
        res = await client.post("/api/v1/events", json=payload, headers=_auth_header(secretary))
        assert res.status_code == 400
        assert res.json()["error"] == "bad_request"

    async def test_05_cannot_create_event_for_soft_deleted_club(self, client: AsyncClient, db_session):
        """5. Cannot propose an event for a soft-deleted club (404 Not Found)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(
            db_session, "Deleted Club", admin, is_deleted=True
        )

        payload = {
            "club_id": str(club.id),
            "title": "Deleted Club Proposal",
            "event_type": "SPORTS",
            "academic_year": "2026-27",
        }
        res = await client.post("/api/v1/events", json=payload, headers=_auth_header(secretary))
        assert res.status_code == 404

    async def test_06_unauthenticated_request_receives_401(self, client: AsyncClient):
        """6. Unauthenticated request receives 401."""
        payload = {"club_id": str(uuid.uuid4()), "title": "No Auth Event", "event_type": "OTHER", "academic_year": "2026-27"}
        res = await client.post("/api/v1/events", json=payload)
        assert res.status_code == 401


# ===========================================================================
# 2. EVENT RETRIEVAL & LISTING
# ===========================================================================
@pytest.mark.asyncio
class TestEventRetrieval:
    """Tests for reading event proposal details and lists."""

    async def test_07_event_retrieval_by_id_works(self, client: AsyncClient, db_session):
        """7. Authenticated user can view event details."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Astronomy Club", admin)

        create_res = await client.post(
            "/api/v1/events",
            json={
                "club_id": str(club.id),
                "title": "Stargazing Night",
                "event_type": "OUTREACH",
                "academic_year": "2026-27",
            },
            headers=_auth_header(secretary),
        )
        assert create_res.status_code == 201
        event_id = create_res.json()["id"]

        get_res = await client.get(f"/api/v1/events/{event_id}", headers=_auth_header(admin))
        assert get_res.status_code == 200
        assert get_res.json()["title"] == "Stargazing Night"
        assert get_res.json()["club_name"] == club.name

    async def test_08_event_listing_with_filters_works(self, client: AsyncClient, db_session):
        """8. Event listing with club_id and status filters works with pagination."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Debate Club", admin)

        await client.post(
            "/api/v1/events",
            json={
                "club_id": str(club.id),
                "title": "Parliamentary Debate",
                "event_type": "COMPETITION",
                "academic_year": "2026-27",
            },
            headers=_auth_header(secretary),
        )

        res = await client.get(
            f"/api/v1/events?club_id={club.id}&status=DRAFT&skip=0&limit=10",
            headers=_auth_header(secretary),
        )
        assert res.status_code == 200
        events = res.json()
        assert len(events) >= 1
        assert events[0]["club_id"] == str(club.id)


# ===========================================================================
# 3. DRAFT MODIFICATION & CONCURRENCY
# ===========================================================================
@pytest.mark.asyncio
class TestEventDraftModification:
    """Tests for editing event proposals in DRAFT status."""

    async def test_09_authorized_secretary_can_update_draft(self, client: AsyncClient, db_session):
        """9. Secretary can update draft fields, incrementing version_lock."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Coding Club", admin)

        create_res = await client.post(
            "/api/v1/events",
            json={
                "club_id": str(club.id),
                "title": "Hackathon 2026 Draft",
                "event_type": "COMPETITION",
                "academic_year": "2026-27",
            },
            headers=_auth_header(secretary),
        )
        event_id = create_res.json()["id"]

        patch_res = await client.patch(
            f"/api/v1/events/{event_id}",
            json={
                "title": "CampusConnect Annual Hackathon",
                "expected_attendees": 150,
                "description": "Updated detailed prize distribution and problem statements",
            },
            headers=_auth_header(secretary),
        )
        assert patch_res.status_code == 200
        data = patch_res.json()
        assert data["title"] == "CampusConnect Annual Hackathon"
        assert data["expected_attendees"] == 150
        assert data["version_lock"] == 1  # Incremented optimistic concurrency lock

    async def test_10_secretary_cannot_update_another_clubs_draft(self, client: AsyncClient, db_session):
        """10. Secretary of Club A cannot edit a draft belonging to Club B (403 Forbidden)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club_a, sec_a = await _create_club_and_secretary(db_session, "Club Alpha Sec", admin)
        club_b, sec_b = await _create_club_and_secretary(db_session, "Club Beta Sec", admin)

        create_res = await client.post(
            "/api/v1/events",
            json={
                "club_id": str(club_b.id),
                "title": "Club B Event",
                "event_type": "SEMINAR",
                "academic_year": "2026-27",
            },
            headers=_auth_header(sec_b),
        )
        event_id = create_res.json()["id"]

        # Secretary A attempts to modify Club B's draft
        patch_res = await client.patch(
            f"/api/v1/events/{event_id}",
            json={"title": "Hacked Title"},
            headers=_auth_header(sec_a),
        )
        assert patch_res.status_code == 403


# ===========================================================================
# 4. PROPOSAL SUBMISSION & VERSION IMMUTABILITY
# ===========================================================================
@pytest.mark.asyncio
class TestEventProposalSubmission:
    """Tests for proposal submission, version snapshot creation, and immutability."""

    async def test_11_proposal_submission_advances_status_and_snapshots(self, client: AsyncClient, db_session):
        """11. Submitting a proposal advances status to SUBMITTED and creates an immutable snapshot."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Music Club", admin)

        create_res = await client.post(
            "/api/v1/events",
            json={
                "club_id": str(club.id),
                "title": "Acoustic Unplugged Evening",
                "description": "Live acoustic performances by college bands",
                "event_type": "CULTURAL",
                "expected_attendees": 100,
                "academic_year": "2026-27",
            },
            headers=_auth_header(secretary),
        )
        event_id = create_res.json()["id"]

        # Submit proposal
        submit_res = await client.post(
            f"/api/v1/events/{event_id}/submit",
            json={"change_summary": "Initial submission for faculty review"},
            headers=_auth_header(secretary),
        )
        assert submit_res.status_code == 200
        data = submit_res.json()
        assert data["status"] == "SUBMITTED"
        assert data["current_version"] == 1

        # Verify immutable version record was created in event_request_versions table
        version_record = await db_session.scalar(
            select(EventRequestVersion).where(
                EventRequestVersion.event_request_id == uuid.UUID(event_id),
                EventRequestVersion.version_number == 1,
            )
        )
        assert version_record is not None
        assert version_record.snapshot["title"] == "Acoustic Unplugged Evening"
        assert version_record.change_summary == "Initial submission for faculty review"
        assert version_record.submitted_by == secretary.id

    async def test_12_submitted_proposal_is_immutable_to_draft_editing(self, client: AsyncClient, db_session):
        """12. A submitted proposal cannot be modified via PATCH (raises 403 WorkflowStateError)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Locked Club", admin)

        create_res = await client.post(
            "/api/v1/events",
            json={
                "club_id": str(club.id),
                "title": "Frozen Event Proposal",
                "event_type": "WORKSHOP",
                "academic_year": "2026-27",
            },
            headers=_auth_header(secretary),
        )
        event_id = create_res.json()["id"]

        # Submit
        await client.post(
            f"/api/v1/events/{event_id}/submit",
            headers=_auth_header(secretary),
        )

        # Attempt to PATCH submitted proposal
        patch_res = await client.patch(
            f"/api/v1/events/{event_id}",
            json={"title": "Silent Sneaky Edit"},
            headers=_auth_header(secretary),
        )
        assert patch_res.status_code == 403
        assert "cannot edit event proposal" in patch_res.json()["message"].lower()

    async def test_13_submission_idempotency_key_prevents_duplicate_processing(self, client: AsyncClient, db_session):
        """13. Resubmitting with the same X-Idempotency-Key returns the existing proposal idempotently."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Idempotent Club", admin)

        create_res = await client.post(
            "/api/v1/events",
            json={
                "club_id": str(club.id),
                "title": "Idempotent Event",
                "event_type": "SEMINAR",
                "academic_year": "2026-27",
            },
            headers=_auth_header(secretary),
        )
        event_id = create_res.json()["id"]
        key = f"idemp-key-{uuid.uuid4().hex}"

        # First submission with key
        headers = _auth_header(secretary)
        headers["X-Idempotency-Key"] = key
        res1 = await client.post(f"/api/v1/events/{event_id}/submit", headers=headers)
        assert res1.status_code == 200
        assert res1.json()["status"] == "SUBMITTED"

        # Retry with identical key
        res2 = await client.post(f"/api/v1/events/{event_id}/submit", headers=headers)
        assert res2.status_code == 200
        assert res2.json()["status"] == "SUBMITTED"
        assert res2.json()["current_version"] == 1  # Did NOT increment twice!

    async def test_14_zero_sensitive_data_in_event_responses(self, client: AsyncClient, db_session):
        """14. Event endpoints never leak passwords, password hashes, secrets, or internal tokens."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Leak Audit Club", admin)

        res = await client.post(
            "/api/v1/events",
            json={
                "club_id": str(club.id),
                "title": "Security Audit Seminar",
                "event_type": "SEMINAR",
                "academic_year": "2026-27",
            },
            headers=_auth_header(secretary),
        )
        assert res.status_code == 201
        text = res.text.lower()
        assert "password" not in text
        assert "hash" not in text
        assert "client_secret" not in text
        assert "jwt_secret" not in text
        assert "token" not in text
