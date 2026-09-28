"""
Integration Tests for Authorization Hardening (GAP-10)

Covers:
1. Mutating endpoints require authentication (401 Unauthorized for missing / invalid credentials)
2. Declarative router role guards reject unauthorized institutional roles (403 Forbidden)
3. Database authoritative role validation (tampered/forged JWT role claim is rejected)
4. System Admin financial restrictions remain intact (Statutory SOD Guard)
5. Cross-club IDOR mutation attempts are rejected (403 Forbidden)
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.models.domain import Club, ClubMember, User
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


def _auth_header(user: User, forged_role: str | None = None) -> dict[str, str]:
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    role_str = forged_role if forged_role else role_val
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

    return club, secretary, advisor


async def _create_draft_event(client: AsyncClient, club: Club, secretary: User) -> str:
    create_res = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "Auth Hardening Event",
            "description": "Event for authorization testing",
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
class TestAuthorizationHardening:
    async def test_01_mutating_endpoints_unauthenticated_returns_401(self, client: AsyncClient):
        """Mutating endpoints reject requests missing authentication credentials with 401."""
        dummy_id = uuid.uuid4()

        # Resource request creation
        res1 = await client.post(
            f"/api/v1/events/{dummy_id}/resources",
            json={"resource_type": ResourceType.PROJECTOR.value, "quantity": 1},
        )
        assert res1.status_code == 401

        # Expense creation
        res2 = await client.post(
            f"/api/v1/events/{dummy_id}/expenses",
            json={"category": "MATERIALS", "claimed_amount": "100.00"},
        )
        assert res2.status_code == 401

        # Event start
        res3 = await client.post(f"/api/v1/events/{dummy_id}/start")
        assert res3.status_code == 401

        # Report certification
        res4 = await client.post(f"/api/v1/events/{dummy_id}/post-event-report/certify")
        assert res4.status_code == 401

    async def test_02_resource_requests_unauthorized_role_rejected_at_router_403(
        self, client: AsyncClient, db_session
    ):
        """Roles without resource permission (e.g. HALL_INCHARGE) are rejected with 403."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_auth")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Res Auth Club", admin)
        event_id = await _create_draft_event(client, club, secretary)
        hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_auth")

        # HALL_INCHARGE attempts to declare resource requirements
        res = await client.post(
            f"/api/v1/events/{event_id}/resources",
            json={"resource_type": ResourceType.PROJECTOR.value, "quantity": 2},
            headers=_auth_header(hall_incharge),
        )
        assert res.status_code == 403
        data = res.json()
        detail = data.get("detail", "").lower() or data.get("message", "").lower()
        assert "not authorized" in detail

    async def test_03_forged_jwt_claim_rejected_via_db_authoritative_check(
        self, client: AsyncClient, db_session
    ):
        """Tampered JWT role claim is defeated by DB verification."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_jwt")
        club, secretary, _ = await _create_club_and_advisor(db_session, "JWT Club", admin)
        event_id = await _create_draft_event(client, club, secretary)
        hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_jwt")

        # HALL_INCHARGE creates a token with forged role 'CLUB_SECRETARY'
        forged_header = _auth_header(hall_incharge, forged_role=UserRole.CLUB_SECRETARY.value)

        res = await client.post(
            f"/api/v1/events/{event_id}/resources",
            json={"resource_type": ResourceType.PROJECTOR.value, "quantity": 1},
            headers=forged_header,
        )
        # Router validates against actual DB user record, rejecting with 403
        assert res.status_code == 403

    async def test_04_system_admin_financial_restrictions_preserved(
        self, client: AsyncClient, db_session
    ):
        """SYSTEM_ADMIN is prohibited from verifying expenses (statutory SOD separation)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_fin")
        dummy_event_id = uuid.uuid4()
        dummy_expense_id = uuid.uuid4()

        res = await client.post(
            f"/api/v1/events/{dummy_event_id}/expenses/{dummy_expense_id}/verify",
            json={"remarks": "Admin attempt to approve"},
            headers=_auth_header(admin),
        )
        # Must be 403 Forbidden
        assert res.status_code == 403

    async def test_05_cross_club_mutation_idor_blocked(
        self, client: AsyncClient, db_session
    ):
        """Secretary of Club A cannot create resource requests for Club B's event."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_idor")
        club_a, sec_a, _ = await _create_club_and_advisor(db_session, "Club Alpha", admin)
        club_b, sec_b, _ = await _create_club_and_advisor(db_session, "Club Beta", admin)

        event_b_id = await _create_draft_event(client, club_b, sec_b)

        # Secretary A attempts to mutate resources of Club B's event
        res = await client.post(
            f"/api/v1/events/{event_b_id}/resources",
            json={"resource_type": ResourceType.PROJECTOR.value, "quantity": 1},
            headers=_auth_header(sec_a),
        )
        assert res.status_code == 403
