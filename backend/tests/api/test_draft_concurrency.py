"""
Integration Tests for Event Proposal Draft Optimistic Concurrency Control (GAP-04)

Covers:
1. Matching expected_version succeeds and increments version_lock
2. Stale expected_version returns HTTP 409 Conflict
3. Concurrent update simulation prevents silent overwrites
4. Editing in REVISION_REQUIRED status enforces optimistic locking
5. Backward compatibility for clients omitting expected_version
6. Unauthorized user cannot update draft (401 / 403)
7. Cross-club IDOR attempt is blocked (403 Forbidden)
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.models.domain import Club, ClubMember, EventRequest, User
from app.models.enums import ClubMemberRole, EventRequestStatus, UserRole


async def _create_user(db, role: UserRole, prefix: str) -> User:
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@college.edu",
        password_hash=hash_password("Pass123!Secure"),
        full_name=f"Test {role} {uid}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _auth_header(user: User) -> dict[str, str]:
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token(
        subject=user.id,
        role=role_str,
        email=user.email,
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_club_and_secretary(db, club_name: str, admin: User) -> tuple[Club, User]:
    uid = uuid.uuid4().hex[:6]
    slug = f"{club_name.lower().replace(' ', '-')}-{uid}"
    advisor = await _create_user(db, UserRole.FACULTY_ADVISOR, f"fa_{uid}")

    club = Club(
        name=f"{club_name} {uid}",
        slug=slug,
        description="Test club for optimistic concurrency",
        academic_year="2026-27",
        is_active=True,
        faculty_advisor_id=advisor.id,
        created_by=admin.id,
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

    return club, secretary


async def _create_draft_event(client: AsyncClient, club: Club, secretary: User) -> dict:
    res = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "Initial Concurrency Draft",
            "description": "Baseline description for concurrency tests",
            "event_type": "TECHNICAL",
            "expected_attendees": 100,
            "event_date": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
            "academic_year": "2026-27",
        },
        headers=_auth_header(secretary),
    )
    assert res.status_code == 201
    return res.json()


@pytest.mark.asyncio
class TestDraftOptimisticConcurrency:
    async def test_01_matching_expected_version_succeeds_and_increments(
        self, client: AsyncClient, db_session
    ):
        """Updating with expected_version equal to current version_lock succeeds."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_occ1")
        club, secretary = await _create_club_and_secretary(db_session, "OCC Club 1", admin)
        draft = await _create_draft_event(client, club, secretary)
        event_id = draft["id"]
        assert draft["version_lock"] == 0

        # Update 1: expected_version = 0 -> 200, version_lock becomes 1
        res1 = await client.patch(
            f"/api/v1/events/{event_id}",
            json={
                "title": "First Valid Update",
                "expected_version": 0,
            },
            headers=_auth_header(secretary),
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["title"] == "First Valid Update"
        assert data1["version_lock"] == 1

        # Update 2: expected_version = 1 -> 200, version_lock becomes 2
        res2 = await client.patch(
            f"/api/v1/events/{event_id}",
            json={
                "title": "Second Valid Update",
                "expected_version": 1,
            },
            headers=_auth_header(secretary),
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["title"] == "Second Valid Update"
        assert data2["version_lock"] == 2

    async def test_02_stale_expected_version_returns_409_conflict(
        self, client: AsyncClient, db_session
    ):
        """Updating with a stale expected_version triggers HTTP 409 Conflict."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_occ2")
        club, secretary = await _create_club_and_secretary(db_session, "OCC Club 2", admin)
        draft = await _create_draft_event(client, club, secretary)
        event_id = draft["id"]

        # Advance version_lock to 1
        await client.patch(
            f"/api/v1/events/{event_id}",
            json={"title": "Advancement Update", "expected_version": 0},
            headers=_auth_header(secretary),
        )

        # Attempt update with stale version 0
        stale_res = await client.patch(
            f"/api/v1/events/{event_id}",
            json={"title": "Stale Attempt", "expected_version": 0},
            headers=_auth_header(secretary),
        )
        assert stale_res.status_code == 409
        err = stale_res.json()
        assert err.get("error") == "conflict"
        assert "modified concurrently" in err.get("message", "").lower()

    async def test_03_concurrent_updates_prevent_silent_overwrites(
        self, client: AsyncClient, db_session
    ):
        """Simulate two users fetching draft v0: User A succeeds, User B gets 409."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_occ3")
        club, secretary = await _create_club_and_secretary(db_session, "OCC Club 3", admin)
        draft = await _create_draft_event(client, club, secretary)
        event_id = draft["id"]

        # Both users read version_lock = 0
        user_a_version = 0
        user_b_version = 0

        # User A submits first
        res_a = await client.patch(
            f"/api/v1/events/{event_id}",
            json={"description": "User A change", "expected_version": user_a_version},
            headers=_auth_header(secretary),
        )
        assert res_a.status_code == 200

        # User B submits afterwards with their stale read
        res_b = await client.patch(
            f"/api/v1/events/{event_id}",
            json={"description": "User B overwrite attempt", "expected_version": user_b_version},
            headers=_auth_header(secretary),
        )
        assert res_b.status_code == 409

    async def test_04_revision_required_editing_optimistic_locking(
        self, client: AsyncClient, db_session
    ):
        """Events returned for revision enforce optimistic locking on modifications."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_occ4")
        club, secretary = await _create_club_and_secretary(db_session, "OCC Club 4", admin)
        draft = await _create_draft_event(client, club, secretary)
        event_id = draft["id"]

        # Directly set state to REVISION_REQUIRED for test setup
        event_obj = await db_session.get(EventRequest, uuid.UUID(event_id))
        event_obj.status = EventRequestStatus.REVISION_REQUIRED
        event_obj.version_lock = 3
        await db_session.commit()

        # Update with stale expected_version
        stale_res = await client.patch(
            f"/api/v1/events/{event_id}",
            json={"title": "Revision Title", "expected_version": 2},
            headers=_auth_header(secretary),
        )
        assert stale_res.status_code == 409

        # Update with matching expected_version
        valid_res = await client.patch(
            f"/api/v1/events/{event_id}",
            json={"title": "Revision Title Corrected", "expected_version": 3},
            headers=_auth_header(secretary),
        )
        assert valid_res.status_code == 200
        assert valid_res.json()["version_lock"] == 4

    async def test_05_update_without_expected_version_remains_backward_compatible(
        self, client: AsyncClient, db_session
    ):
        """Omitting expected_version updates successfully and increments version_lock."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_occ5")
        club, secretary = await _create_club_and_secretary(db_session, "OCC Club 5", admin)
        draft = await _create_draft_event(client, club, secretary)
        event_id = draft["id"]
        assert draft["version_lock"] == 0

        res = await client.patch(
            f"/api/v1/events/{event_id}",
            json={"title": "Backward Compatible Update"},
            headers=_auth_header(secretary),
        )
        assert res.status_code == 200
        assert res.json()["version_lock"] == 1

    async def test_06_unauthorized_user_cannot_update_draft(
        self, client: AsyncClient, db_session
    ):
        """Unauthenticated or unauthorized user receives 401/403."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_occ6")
        club, secretary = await _create_club_and_secretary(db_session, "OCC Club 6", admin)
        draft = await _create_draft_event(client, club, secretary)
        event_id = draft["id"]

        # Unauthenticated -> 401
        res_unauth = await client.patch(
            f"/api/v1/events/{event_id}",
            json={"title": "Unauthenticated Update"},
        )
        assert res_unauth.status_code == 401

    async def test_07_cross_club_draft_update_blocked_idor(
        self, client: AsyncClient, db_session
    ):
        """Secretary of Club A cannot update draft of Club B."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_occ7")
        club_a, sec_a = await _create_club_and_secretary(db_session, "Club Alpha OCC", admin)
        club_b, sec_b = await _create_club_and_secretary(db_session, "Club Beta OCC", admin)

        draft_b = await _create_draft_event(client, club_b, sec_b)
        event_b_id = draft_b["id"]

        # Secretary A attempts to modify Club B draft
        res = await client.patch(
            f"/api/v1/events/{event_b_id}",
            json={"title": "IDOR overwrite attempt", "expected_version": 0},
            headers=_auth_header(sec_a),
        )
        assert res.status_code == 403
