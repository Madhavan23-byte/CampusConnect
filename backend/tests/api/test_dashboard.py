"""
CampusConnect - Dashboard API Test Suite
Covers role-aware aggregation:
- SYSTEM_ADMIN metrics
- CLUB_SECRETARY metrics & club isolation
- Reviewer pending action counts & completed approval tracking
- Unauthenticated protection
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.models.domain import Club, ClubMember, Hall, User
from app.models.enums import ClubMemberRole, UserRole


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


async def _create_club_and_advisor(db, name: str, admin: User):
    uid = uuid.uuid4().hex[:6]
    slug = f"{name.lower().replace(' ', '-')}-{uid}"

    advisor = await _create_user(db, UserRole.FACULTY_ADVISOR, f"fa_{uid}")
    secretary = await _create_user(db, UserRole.CLUB_SECRETARY, f"sec_{uid}")

    club = Club(
        name=f"{name} {uid}",
        slug=slug,
        description="A test club",
        academic_year="2026-27",
        is_active=True,
        faculty_advisor_id=advisor.id,
        created_by=admin.id,
    )
    db.add(club)
    await db.commit()
    await db.refresh(club)

    member = ClubMember(
        club_id=club.id,
        user_id=secretary.id,
        member_role=ClubMemberRole.SECRETARY,
        is_active=True,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)

    return club, secretary, advisor


async def _create_test_hall(db) -> Hall:
    uid = uuid.uuid4().hex[:6]
    hall = Hall(
        name=f"Auditorium {uid}",
        capacity=500,
        location="Campus Center",
        available_facilities=["projector", "ac"],
        is_active=True,
    )
    db.add(hall)
    await db.commit()
    await db.refresh(hall)
    return hall


async def _create_and_submit_proposal(
    client: AsyncClient, db, club: Club, secretary: User, hall: Hall
) -> str:
    create_res = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "Hackathon",
            "description": "Annual Hackathon",
            "event_type": "TECHNICAL",
            "expected_attendees": 200,
            "event_date": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
            "academic_year": "2026-27",
        },
        headers=_auth_header(secretary),
    )
    assert create_res.status_code == 201
    event_id = create_res.json()["id"]

    req_dt = datetime.now(UTC) + timedelta(days=20)
    await client.post(
        f"/api/v1/events/{event_id}/venue",
        json={
            "hall_id": str(hall.id),
            "requested_date": req_dt.date().isoformat(),
            "start_time": req_dt.replace(hour=9, minute=0, second=0, microsecond=0).isoformat(),
            "end_time": req_dt.replace(hour=18, minute=0, second=0, microsecond=0).isoformat(),
            "expected_audience": 200,
        },
        headers=_auth_header(secretary),
    )
    await client.post(
        f"/api/v1/events/{event_id}/budget",
        json={"expected_income": 5000.0, "institute_contribution": 15000.0},
        headers=_auth_header(secretary),
    )
    await client.post(
        f"/api/v1/events/{event_id}/budget/items",
        json={"category": "MATERIALS", "description": "Stationery", "estimated_amount": 5000.0},
        headers=_auth_header(secretary),
    )
    sub_res = await client.post(
        f"/api/v1/events/{event_id}/submit",
        json={"change_summary": "Initial submit"},
        headers=_auth_header(secretary),
    )
    assert sub_res.status_code == 200
    return event_id


@pytest.mark.asyncio
class TestDashboardAPI:
    """Tests for role-aware dashboard aggregation endpoint."""

    async def test_01_admin_dashboard_metrics(self, client: AsyncClient, db_session):
        """SYSTEM_ADMIN dashboard returns system_counts, active_users, and pending_proposals."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_dash")
        res = await client.get("/api/v1/dashboard", headers=_auth_header(admin))
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "SYSTEM_ADMIN"
        assert data["admin"] is not None
        assert "total_users" in data["admin"]["system_counts"]
        assert "total_clubs" in data["admin"]["system_counts"]
        assert "total_events" in data["admin"]["system_counts"]
        assert data["admin"]["active_users"] >= 1

    async def test_02_secretary_dashboard_empty(self, client: AsyncClient, db_session):
        """Secretary with no events sees all zero counts and empty event list."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_dash2")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Empty Dash Club", admin)

        res = await client.get("/api/v1/dashboard", headers=_auth_header(secretary))
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "CLUB_SECRETARY"
        assert data["secretary"] is not None
        sec = data["secretary"]
        assert sec["draft_count"] == 0
        assert sec["submitted_count"] == 0
        assert sec["in_review_count"] == 0
        assert sec["recent_events"] == []

    async def test_03_secretary_dashboard_draft_and_submitted_counts(
        self, client: AsyncClient, db_session
    ):
        """Secretary dashboard correctly tallies draft and submitted proposal counts."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_dash3")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Tally Dash Club", admin)
        hall = await _create_test_hall(db_session)

        # 1 draft
        await client.post(
            "/api/v1/events",
            json={
                "club_id": str(club.id),
                "title": "Draft Event 1",
                "description": "Draft",
                "event_type": "CULTURAL",
                "expected_attendees": 50,
                "event_date": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
                "academic_year": "2026-27",
            },
            headers=_auth_header(secretary),
        )

        # 1 submitted
        await _create_and_submit_proposal(client, db_session, club, secretary, hall)

        res = await client.get("/api/v1/dashboard", headers=_auth_header(secretary))
        assert res.status_code == 200
        sec = res.json()["secretary"]
        assert sec["draft_count"] == 1
        assert sec["submitted_count"] == 1
        assert len(sec["recent_events"]) == 2

    async def test_04_secretary_dashboard_recent_events_metadata(
        self, client: AsyncClient, db_session
    ):
        """Recent events in secretary dashboard includes club name and status."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_dash4")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Meta Dash Club", admin)

        await client.post(
            "/api/v1/events",
            json={
                "club_id": str(club.id),
                "title": "Recent Event Meta",
                "description": "Meta description",
                "event_type": "SPORTS",
                "expected_attendees": 100,
                "event_date": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
                "academic_year": "2026-27",
            },
            headers=_auth_header(secretary),
        )

        res = await client.get("/api/v1/dashboard", headers=_auth_header(secretary))
        assert res.status_code == 200
        events = res.json()["secretary"]["recent_events"]
        assert len(events) >= 1
        assert events[0]["title"] == "Recent Event Meta"
        assert events[0]["status"] == "DRAFT"
        assert events[0]["club_name"] == club.name

    async def test_05_secretary_resource_isolation(self, client: AsyncClient, db_session):
        """Secretary of Club A does not see events from Club B in their metrics."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_dash5")
        club_a, sec_a, _ = await _create_club_and_advisor(db_session, "Club Alpha Dash", admin)
        club_b, sec_b, _ = await _create_club_and_advisor(db_session, "Club Beta Dash", admin)

        # Club A creates draft
        await client.post(
            "/api/v1/events",
            json={
                "club_id": str(club_a.id),
                "title": "Alpha Exclusive Event",
                "description": "Alpha only",
                "event_type": "TECHNICAL",
                "expected_attendees": 50,
                "event_date": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
                "academic_year": "2026-27",
            },
            headers=_auth_header(sec_a),
        )

        # Secretary B checks dashboard
        res_b = await client.get("/api/v1/dashboard", headers=_auth_header(sec_b))
        assert res_b.status_code == 200
        sec_b_data = res_b.json()["secretary"]
        assert sec_b_data["draft_count"] == 0
        assert sec_b_data["recent_events"] == []

    async def test_06_reviewer_dashboard_pending_actions(self, client: AsyncClient, db_session):
        """Reviewer dashboard shows pending actions when a proposal is submitted."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_dash6")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Reviewer Dash Club", admin
        )
        hall = await _create_test_hall(db_session)

        # Before submission
        pre_res = await client.get("/api/v1/dashboard", headers=_auth_header(advisor))
        assert pre_res.status_code == 200
        assert pre_res.json()["reviewer"]["pending_actions"] == 0

        # Submit proposal -> Step 1 assigned to advisor
        await _create_and_submit_proposal(client, db_session, club, secretary, hall)

        # After submission -> advisor has 1 pending action
        post_res = await client.get("/api/v1/dashboard", headers=_auth_header(advisor))
        assert post_res.status_code == 200
        assert post_res.json()["reviewer"]["pending_actions"] >= 1

    async def test_07_reviewer_dashboard_completed_approvals(self, client: AsyncClient, db_session):
        """Reviewer dashboard tracks completed approvals after approving a step."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_dash7")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Approve Dash Club", admin
        )
        hall = await _create_test_hall(db_session)

        event_id = await _create_and_submit_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        step1_id = next(s["id"] for s in wf_res.json()["steps"] if s["step_order"] == 1)

        # Approve step
        await client.post(
            f"/api/v1/workflows/steps/{step1_id}/approve",
            json={"comments": "Academic objectives clear."},
            headers=_auth_header(advisor),
        )

        res = await client.get("/api/v1/dashboard", headers=_auth_header(advisor))
        assert res.status_code == 200
        rev = res.json()["reviewer"]
        assert rev["completed_approvals"] >= 1

    async def test_08_unauthenticated_dashboard_rejected(self, client: AsyncClient):
        """Unauthenticated request to GET /dashboard is rejected with 401."""
        res = await client.get("/api/v1/dashboard")
        assert res.status_code == 401
