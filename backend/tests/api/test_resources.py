"""
CampusConnect - Resource Requests Test Suite
Covers:
- Declaring resource requirements (CHAIRS, PROJECTOR, etc.)
- Quantity validation (> 0)
- Listing resources
- Deleting resources
- State machine enforcement (DRAFT / REVISION_REQUIRED vs SUBMITTED)
- Cross-club authorization protection
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.models.domain import Club, ClubMember, Hall, User
from app.models.enums import ClubMemberRole, ResourceType, UserRole


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


async def _create_draft_event(client: AsyncClient, club: Club, secretary: User) -> str:
    create_res = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "Resource Event",
            "description": "Event with resources",
            "event_type": "TECHNICAL",
            "expected_attendees": 100,
            "event_date": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
            "academic_year": "2026-27",
        },
        headers=_auth_header(secretary),
    )
    assert create_res.status_code == 201
    return create_res.json()["id"]


@pytest.mark.asyncio
class TestResourceRequests:
    """Tests for declaring equipment/resource requests."""

    async def test_01_create_resource_request(self, client: AsyncClient, db_session):
        """Secretary can declare a resource requirement in DRAFT status."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_res1")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Res Club 1", admin)
        event_id = await _create_draft_event(client, club, secretary)

        res = await client.post(
            f"/api/v1/events/{event_id}/resources",
            json={
                "resource_type": ResourceType.PROJECTOR.value,
                "quantity": 2,
                "notes": "High definition 4K projector needed",
            },
            headers=_auth_header(secretary),
        )
        assert res.status_code == 201
        data = res.json()
        assert data["resource_type"] == "PROJECTOR"
        assert data["quantity"] == 2
        assert data["status"] == "PENDING"

    async def test_02_list_resource_requests(self, client: AsyncClient, db_session):
        """GET /events/{id}/resources lists all declared resources."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_res2")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Res Club 2", admin)
        event_id = await _create_draft_event(client, club, secretary)

        await client.post(
            f"/api/v1/events/{event_id}/resources",
            json={
                "resource_type": ResourceType.CHAIRS.value,
                "quantity": 50,
                "notes": "Plastic chairs",
            },
            headers=_auth_header(secretary),
        )
        await client.post(
            f"/api/v1/events/{event_id}/resources",
            json={
                "resource_type": ResourceType.MICROPHONE.value,
                "quantity": 4,
                "notes": "Wireless mics",
            },
            headers=_auth_header(secretary),
        )

        res = await client.get(
            f"/api/v1/events/{event_id}/resources", headers=_auth_header(secretary)
        )
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 2
        types = [it["resource_type"] for it in items]
        assert "CHAIRS" in types
        assert "MICROPHONE" in types

    async def test_03_delete_resource_request(self, client: AsyncClient, db_session):
        """Secretary can delete a declared resource requirement in DRAFT status."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_res3")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Res Club 3", admin)
        event_id = await _create_draft_event(client, club, secretary)

        create_res = await client.post(
            f"/api/v1/events/{event_id}/resources",
            json={"resource_type": ResourceType.TABLES.value, "quantity": 10},
            headers=_auth_header(secretary),
        )
        rid = create_res.json()["id"]

        del_res = await client.delete(
            f"/api/v1/events/{event_id}/resources/{rid}",
            headers=_auth_header(secretary),
        )
        assert del_res.status_code == 200

        # Verify list is empty
        list_res = await client.get(
            f"/api/v1/events/{event_id}/resources", headers=_auth_header(secretary)
        )
        assert len(list_res.json()) == 0

    async def test_04_reject_modification_in_submitted_status(
        self, client: AsyncClient, db_session
    ):
        """Declaring or deleting resources in SUBMITTED status is rejected."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_res4")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Res Club 4", admin)
        hall = await _create_test_hall(db_session)
        event_id = await _create_draft_event(client, club, secretary)

        # Attach venue & budget, then submit
        req_dt = datetime.now(UTC) + timedelta(days=20)
        await client.post(
            f"/api/v1/events/{event_id}/venue",
            json={
                "hall_id": str(hall.id),
                "requested_date": req_dt.date().isoformat(),
                "start_time": req_dt.replace(hour=9, minute=0, second=0, microsecond=0).isoformat(),
                "end_time": req_dt.replace(hour=18, minute=0, second=0, microsecond=0).isoformat(),
                "expected_audience": 100,
            },
            headers=_auth_header(secretary),
        )
        await client.post(
            f"/api/v1/events/{event_id}/budget",
            json={"expected_income": 5000.0, "institute_contribution": 10000.0},
            headers=_auth_header(secretary),
        )
        await client.post(
            f"/api/v1/events/{event_id}/budget/items",
            json={"category": "MATERIALS", "description": "Stationery", "estimated_amount": 5000.0},
            headers=_auth_header(secretary),
        )
        await client.post(
            f"/api/v1/events/{event_id}/submit",
            json={"change_summary": "Ready"},
            headers=_auth_header(secretary),
        )

        # Attempt to add resource post-submission
        res = await client.post(
            f"/api/v1/events/{event_id}/resources",
            json={"resource_type": ResourceType.PODIUM.value, "quantity": 1},
            headers=_auth_header(secretary),
        )
        assert res.status_code in (400, 403)

    async def test_05_reject_invalid_quantity(self, client: AsyncClient, db_session):
        """Non-positive quantity (0 or negative) is rejected with 422."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_res5")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Res Club 5", admin)
        event_id = await _create_draft_event(client, club, secretary)

        res0 = await client.post(
            f"/api/v1/events/{event_id}/resources",
            json={"resource_type": ResourceType.CHAIRS.value, "quantity": 0},
            headers=_auth_header(secretary),
        )
        assert res0.status_code == 422

        res_neg = await client.post(
            f"/api/v1/events/{event_id}/resources",
            json={"resource_type": ResourceType.CHAIRS.value, "quantity": -5},
            headers=_auth_header(secretary),
        )
        assert res_neg.status_code == 422

    async def test_06_cross_club_modification_rejected(self, client: AsyncClient, db_session):
        """Secretary of Club B cannot declare resources for Club A's proposal."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_res6")
        club_a, sec_a, _ = await _create_club_and_advisor(db_session, "Club Alpha Res", admin)
        club_b, sec_b, _ = await _create_club_and_advisor(db_session, "Club Beta Res", admin)
        event_id = await _create_draft_event(client, club_a, sec_a)

        res = await client.post(
            f"/api/v1/events/{event_id}/resources",
            json={"resource_type": ResourceType.CAMERA.value, "quantity": 1},
            headers=_auth_header(sec_b),
        )
        assert res.status_code == 403
