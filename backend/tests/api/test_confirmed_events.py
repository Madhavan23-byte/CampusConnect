"""
CampusConnect - Confirmed Event Creation & Idempotency Test Suite
Verifies that Principal Step 6 approval automatically creates a confirmed Event row,
associates the latest approved EventRequestVersion and venue details,
and guarantees idempotency.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.domain import (
    Club,
    ClubMember,
    Event,
    EventRequest,
    Hall,
    User,
)
from app.models.enums import (
    ClubMemberRole,
    EventStatus,
    UserRole,
)
from app.services.event_service import EventService


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


async def _setup_full_event(client: AsyncClient, db_session, club_name: str):
    admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
    advisor = await _create_user(db_session, UserRole.FACULTY_ADVISOR, "advisor")
    secretary = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec")
    hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
    finance = await _create_user(db_session, UserRole.FINANCE_OFFICER, "finance")
    union_advisor = await _create_user(db_session, UserRole.ADVISOR_STUDENTS_UNION, "union")
    dean = await _create_user(db_session, UserRole.DEAN_STUDENT_AFFAIRS, "dean")
    principal = await _create_user(db_session, UserRole.PRINCIPAL, "principal")

    uid = uuid.uuid4().hex[:6]
    slug = f"{club_name.lower().replace(' ', '-')}-{uid}"
    club = Club(
        name=f"{club_name} {uid}",
        slug=slug,
        description="Test club description",
        academic_year="2026-27",
        faculty_advisor_id=advisor.id,
        created_by=admin.id,
        is_active=True,
    )
    db_session.add(club)
    await db_session.commit()
    await db_session.refresh(club)

    member = ClubMember(
        club_id=club.id,
        user_id=secretary.id,
        member_role=ClubMemberRole.SECRETARY,
        is_active=True,
    )
    db_session.add(member)
    await db_session.commit()

    hall = await _create_test_hall(db_session)

    # 1. Create event draft
    start_time = (datetime.now(UTC) + timedelta(days=20)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    end_time = start_time + timedelta(hours=3)

    create_res = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "National Tech Symposium",
            "description": "Annual technical symposium with industry speakers",
            "event_type": "TECHNICAL",
            "expected_attendees": 350,
            "event_date": start_time.isoformat(),
            "academic_year": "2026-27",
        },
        headers=_auth_header(secretary),
    )
    assert create_res.status_code == 201
    event_id = create_res.json()["id"]

    # 2. Attach venue
    v_res = await client.post(
        f"/api/v1/events/{event_id}/venue",
        json={
            "hall_id": str(hall.id),
            "requested_date": start_time.date().isoformat(),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "expected_audience": 350,
        },
        headers=_auth_header(secretary),
    )
    assert v_res.status_code == 201

    # 3. Attach budget
    b_res = await client.post(
        f"/api/v1/events/{event_id}/budget",
        json={
            "expected_income": 5000.0,
            "institute_contribution": 15000.0,
        },
        headers=_auth_header(secretary),
    )
    assert b_res.status_code == 201

    li_res = await client.post(
        f"/api/v1/events/{event_id}/budget/items",
        json={
            "category": "MATERIALS",
            "description": "Mementos for Chief Guests",
            "estimated_amount": 10000.0,
        },
        headers=_auth_header(secretary),
    )
    assert li_res.status_code == 201

    # 4. Submit proposal
    s_res = await client.post(
        f"/api/v1/events/{event_id}/submit",
        json={"change_summary": "Ready for multi-stage approval"},
        headers=_auth_header(secretary),
    )
    assert s_res.status_code == 200

    approvers = {
        1: advisor,
        2: hall_incharge,
        3: finance,
        4: union_advisor,
        5: dean,
        6: principal,
    }
    return event_id, approvers, secretary, hall, start_time, end_time


@pytest.mark.asyncio
class TestConfirmedEvents:
    """Tests for Confirmed Event creation and idempotency upon Step 6 approval."""

    async def test_01_step6_approval_creates_confirmed_event(
        self, client: AsyncClient, db_session
    ):
        """Principal Step 6 approval successfully creates an Event record with SCHEDULED status."""
        event_id, approvers, secretary, hall, start_time, end_time = await _setup_full_event(
            client, db_session, "Confirmed Event Club 1"
        )

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        steps = {s["step_order"]: s["id"] for s in wf_res.json()["steps"]}

        # Advance Steps 1 to 5
        for order in range(1, 6):
            app_res = await client.post(
                f"/api/v1/workflows/steps/{steps[order]}/approve",
                json={"comments": f"Step {order} approved."},
                headers=_auth_header(approvers[order]),
            )
            assert app_res.status_code == 200

        # Step 6 approval by Principal
        step6_res = await client.post(
            f"/api/v1/workflows/steps/{steps[6]}/approve",
            json={"comments": "Executive sanction granted. Event approved."},
            headers=_auth_header(approvers[6]),
        )
        assert step6_res.status_code == 200

        # Verify Event row created in database
        event_row = await db_session.scalar(
            select(Event).where(Event.event_request_id == uuid.UUID(event_id))
        )
        assert event_row is not None
        assert event_row.title == "National Tech Symposium"
        assert event_row.status == EventStatus.SCHEDULED
        assert event_row.hall_id == hall.id
        assert event_row.start_time.replace(tzinfo=UTC) == start_time.replace(tzinfo=UTC)
        assert event_row.end_time.replace(tzinfo=UTC) == end_time.replace(tzinfo=UTC)

        # Verify secretary received PROPOSAL_APPROVED notification
        sec_notifs = await client.get("/api/v1/notifications", headers=_auth_header(secretary))
        assert any(n["notification_type"] == "PROPOSAL_APPROVED" for n in sec_notifs.json())

    async def test_02_confirmed_event_idempotency(
        self, client: AsyncClient, db_session
    ):
        """Calling create_confirmed_event multiple times produces exactly one Event row."""
        event_id, approvers, secretary, hall, start_time, end_time = await _setup_full_event(
            client, db_session, "Confirmed Event Club 2"
        )

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        steps = {s["step_order"]: s["id"] for s in wf_res.json()["steps"]}

        for order in range(1, 7):
            res = await client.post(
                f"/api/v1/workflows/steps/{steps[order]}/approve",
                json={"comments": f"Step {order} sanctioned."},
                headers=_auth_header(approvers[order]),
            )
            assert res.status_code == 200

        # Now test EventService.create_confirmed_event directly on the same event
        event_req = await db_session.scalar(
            select(EventRequest).where(EventRequest.id == uuid.UUID(event_id))
        )
        second_call_result = await EventService.create_confirmed_event(
            db=db_session, event=event_req, actor=approvers[6]
        )
        assert second_call_result is not None

        # Verify exactly one Event exists
        events = list(
            (
                await db_session.scalars(
                    select(Event).where(Event.event_request_id == uuid.UUID(event_id))
                )
            ).all()
        )
        assert len(events) == 1

    async def test_03_confirmed_event_preserves_version_and_metadata(
        self, client: AsyncClient, db_session
    ):
        """Confirmed event associates the correct EventRequestVersion snapshot."""
        event_id, approvers, secretary, hall, start_time, end_time = await _setup_full_event(
            client, db_session, "Confirmed Event Club 3"
        )

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        steps = {s["step_order"]: s["id"] for s in wf_res.json()["steps"]}

        for order in range(1, 7):
            res = await client.post(
                f"/api/v1/workflows/steps/{steps[order]}/approve",
                json={"comments": f"Step {order} approved."},
                headers=_auth_header(approvers[order]),
            )
            assert res.status_code == 200

        event_row = await db_session.scalar(
            select(Event).where(Event.event_request_id == uuid.UUID(event_id))
        )
        assert event_row.approved_version_id is not None
        assert event_row.expected_attendees == 350
        assert event_row.academic_year is not None

    async def test_04_double_approval_at_step6_prevented(
        self, client: AsyncClient, db_session
    ):
        """Attempting to approve Step 6 a second time is rejected with 403 WorkflowStateError."""
        event_id, approvers, secretary, hall, start_time, end_time = await _setup_full_event(
            client, db_session, "Confirmed Event Club 4"
        )

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        steps = {s["step_order"]: s["id"] for s in wf_res.json()["steps"]}

        for order in range(1, 7):
            await client.post(
                f"/api/v1/workflows/steps/{steps[order]}/approve",
                json={"comments": f"Step {order} approved."},
                headers=_auth_header(approvers[order]),
            )

        # Retry Step 6
        retry_res = await client.post(
            f"/api/v1/workflows/steps/{steps[6]}/approve",
            json={"comments": "Duplicate step 6 call."},
            headers=_auth_header(approvers[6]),
        )
        assert retry_res.status_code == 403
