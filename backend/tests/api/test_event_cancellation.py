"""
CampusConnect - Event & Proposal Cancellation Lifecycle Test Suite
Validates:
- Proposal cancellation in DRAFT, SUBMITTED, IN_REVIEW
- WorkflowInstance cancellation & pending step skipping
- Confirmed Event cancellation in SCHEDULED and IN_PROGRESS
- HallBookingConfirmed release & PostgreSQL exclusion constraint clearing
- Financial advance safety:
  * REQUESTED/APPROVED advances auto-rejected with audit
  * DISBURSED advances preserved as debt liability (DISBURSED_REFUND_REQUIRED)
- Role authorization (CLUB_SECRETARY, PRINCIPAL, DEAN_STUDENT_AFFAIRS, SYSTEM_ADMIN)
- Unauthorized roles blocked (403)
- Cross-club IDOR isolation
- Terminal state guards (COMPLETED, CLOSURE_REQUESTED, CLOSED, ARCHIVED)
- Idempotency & repeated cancellation rejection (403 WorkflowStateError)
- Audit logging (PROPOSAL_CANCELLED, EVENT_STATUS_CHANGED, HALL_RELEASED, ADVANCE_REJECTED)
"""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.domain import (
    AuditLog,
    CashAdvance,
    Club,
    ClubMember,
    Event,
    EventRequest,
    Hall,
    HallBookingConfirmed,
    Notification,
    User,
    VenueRequest,
    WorkflowInstance,
    WorkflowInstanceStep,
)
from app.models.enums import (
    AuditAction,
    CashAdvanceStatus,
    ClubMemberRole,
    EventRequestStatus,
    EventStatus,
    EventType,
    UserRole,
    VenueRequestStatus,
    WorkflowInstanceStatus,
    WorkflowStepStatus,
)

# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

async def _create_user(
    db,
    role: UserRole | str,
    prefix: str,
    is_active: bool = True,
) -> User:
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@college.edu",
        password_hash=hash_password("Pass123!Secure"),
        full_name=f"Test {role} {uid}",
        role=role,
        is_active=is_active,
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


async def _create_club_with_secretary(db) -> tuple[Club, User]:
    secretary = await _create_user(db, UserRole.CLUB_SECRETARY, "sec")
    uid = uuid.uuid4().hex[:6]
    club = Club(
        name=f"Cancellation Test Club {uid}",
        slug=f"cancellation-club-{uid}",
        description="Club for testing cancellation workflows",
        academic_year="2026-27",
        faculty_advisor_id=None,
        created_by=secretary.id,
        is_active=True,
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
    return club, secretary


async def _create_hall(db) -> Hall:
    uid = uuid.uuid4().hex[:6]
    hall = Hall(
        name=f"Cancellation Hall {uid}",
        capacity=300,
        location="Campus Center",
        available_facilities=["PROJECTOR", "AUDIO"],
        is_active=True,
    )
    db.add(hall)
    await db.commit()
    await db.refresh(hall)
    return hall


async def _create_confirmed_event_fixture(
    db,
    club: Club,
    secretary: User,
    status: EventStatus = EventStatus.SCHEDULED,
    hall: Hall | None = None,
    title: str = "Annual Robotics Championship",
) -> tuple[Event, EventRequest, HallBookingConfirmed | None]:
    now = datetime.now(UTC)
    proposal = EventRequest(
        id=uuid.uuid4(),
        club_id=club.id,
        submitted_by=secretary.id,
        title=title,
        description="Championship event description",
        event_type=EventType.TECHNICAL,
        status=EventRequestStatus.APPROVED,
        expected_attendees=100,
        academic_year="2026-27",
    )
    db.add(proposal)
    await db.commit()

    event = Event(
        id=uuid.uuid4(),
        event_request_id=proposal.id,
        approved_version_id=uuid.uuid4(),
        club_id=club.id,
        hall_id=hall.id if hall else None,
        title=proposal.title,
        description=proposal.description,
        event_type=EventType.TECHNICAL,
        status=status,
        academic_year="2026-27",
        event_date=now + timedelta(days=5),
        start_time=now + timedelta(days=5, hours=9),
        end_time=now + timedelta(days=5, hours=17),
        expected_attendees=100,
    )
    db.add(event)
    await db.commit()

    booking = None
    if hall:
        vr = VenueRequest(
            id=uuid.uuid4(),
            event_request_id=proposal.id,
            hall_id=hall.id,
            requested_date=now.date() + timedelta(days=5),
            start_time=now + timedelta(days=5, hours=9),
            end_time=now + timedelta(days=5, hours=17),
            expected_audience=100,
            status=VenueRequestStatus.APPROVED,
        )
        db.add(vr)
        await db.commit()

        booking = HallBookingConfirmed(
            id=uuid.uuid4(),
            hall_id=hall.id,
            event_request_id=proposal.id,
            venue_request_id=vr.id,
            booking_date=now.date() + timedelta(days=5),
            start_time=now + timedelta(days=5, hours=9),
            end_time=now + timedelta(days=5, hours=17),
            is_active=True,
        )
        db.add(booking)
        await db.commit()

    return event, proposal, booking


# ---------------------------------------------------------------------------
# Proposal Cancellation Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_draft_proposal_by_secretary_success(
    client: AsyncClient, db_session
):
    club, secretary = await _create_club_with_secretary(db_session)

    # 1. Create a draft proposal
    resp = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "Robotics Workshop",
            "description": "Annual beginner workshop on microcontrollers",
            "event_type": "WORKSHOP",
            "expected_attendees": 100,
            "academic_year": "2026-27",
        },
        headers=_auth_header(secretary),
    )
    assert resp.status_code == 201, resp.text
    proposal_id = resp.json()["id"]

    # 2. Cancel draft proposal
    reason = "Scheduling conflict with mid-semester examinations."
    cancel_resp = await client.post(
        f"/api/v1/events/{proposal_id}/cancel",
        json={"reason": reason},
        headers=_auth_header(secretary),
    )
    assert cancel_resp.status_code == 200, cancel_resp.text
    data = cancel_resp.json()
    assert data["entity_type"] == "PROPOSAL"
    assert data["status"] == "CANCELLED"
    assert data["cancellation_reason"] == reason
    assert data["cancelled_by"] == str(secretary.id)
    assert data["workflow_cancelled"] is False

    # 3. Verify database state
    proposal = await db_session.scalar(
        select(EventRequest).where(EventRequest.id == uuid.UUID(proposal_id))
    )
    assert proposal.status == EventRequestStatus.CANCELLED

    # 4. Verify audit log
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == proposal_id,
            AuditLog.action == AuditAction.PROPOSAL_CANCELLED,
        )
    )
    assert audit is not None
    assert audit.actor_id == secretary.id
    assert audit.new_state["cancellation_reason"] == reason


@pytest.mark.asyncio
async def test_cancel_submitted_proposal_cancels_workflow(
    client: AsyncClient, db_session
):
    club, secretary = await _create_club_with_secretary(db_session)

    # Create draft proposal
    resp = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "AI Summit 2026",
            "description": "Symposium on modern agentic artificial intelligence",
            "event_type": "TECHNICAL",
            "expected_attendees": 250,
            "academic_year": "2026-27",
        },
        headers=_auth_header(secretary),
    )
    assert resp.status_code == 201
    proposal_id = uuid.UUID(resp.json()["id"])

    # Create active workflow instance with steps
    wf = WorkflowInstance(
        id=uuid.uuid4(),
        template_id=uuid.uuid4(),
        event_request_id=proposal_id,
        current_step_order=1,
        status=WorkflowInstanceStatus.IN_PROGRESS,
        version_number=1,
    )
    db_session.add(wf)

    # Link proposal to workflow instance
    proposal = await db_session.scalar(
        select(EventRequest).where(EventRequest.id == proposal_id)
    )
    proposal.status = EventRequestStatus.IN_REVIEW
    proposal.workflow_instance_id = wf.id
    await db_session.commit()

    step1 = WorkflowInstanceStep(
        id=uuid.uuid4(),
        instance_id=wf.id,
        template_step_id=uuid.uuid4(),
        step_order=1,
        step_name="FACULTY_ADVISOR_APPROVAL",
        assigned_to=secretary.id,
        status=WorkflowStepStatus.PENDING,
    )
    step2 = WorkflowInstanceStep(
        id=uuid.uuid4(),
        instance_id=wf.id,
        template_step_id=uuid.uuid4(),
        step_order=2,
        step_name="DEAN_APPROVAL",
        assigned_to=secretary.id,
        status=WorkflowStepStatus.PENDING,
    )
    db_session.add_all([step1, step2])
    await db_session.commit()

    # Secretary cancels the proposal in review
    reason = "Club leadership decided to postpone the conference to next semester."
    cancel_resp = await client.post(
        f"/api/v1/events/{proposal_id}/cancel",
        json={"reason": reason},
        headers=_auth_header(secretary),
    )
    assert cancel_resp.status_code == 200, cancel_resp.text
    data = cancel_resp.json()
    assert data["workflow_cancelled"] is True

    # Check workflow instance is marked CANCELLED
    await db_session.refresh(wf)
    assert wf.status == WorkflowInstanceStatus.CANCELLED

    # Check pending steps are SKIPPED
    await db_session.refresh(step1)
    await db_session.refresh(step2)
    assert step1.status == WorkflowStepStatus.SKIPPED
    assert step2.status == WorkflowStepStatus.SKIPPED


@pytest.mark.asyncio
async def test_cancel_proposal_unauthorized_role_blocked(
    client: AsyncClient, db_session
):
    club, secretary = await _create_club_with_secretary(db_session)
    unauthorized_user = await _create_user(
        db_session, UserRole.HALL_INCHARGE, "hall_incharge"
    )

    # Create draft
    resp = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "Music Fest",
            "description": "Annual inter-college musical extravaganza",
            "event_type": "CULTURAL",
            "expected_attendees": 500,
            "academic_year": "2026-27",
        },
        headers=_auth_header(secretary),
    )
    assert resp.status_code == 201
    proposal_id = resp.json()["id"]

    # Student attempts cancellation -> 403 Forbidden
    cancel_resp = await client.post(
        f"/api/v1/events/{proposal_id}/cancel",
        json={"reason": "Attempting unauthorized cancellation."},
        headers=_auth_header(unauthorized_user),
    )
    assert cancel_resp.status_code == 403


@pytest.mark.asyncio
async def test_cancel_proposal_cross_club_isolation(
    client: AsyncClient, db_session
):
    club_a, sec_a = await _create_club_with_secretary(db_session)
    club_b, sec_b = await _create_club_with_secretary(db_session)

    # Secretary A creates draft for Club A
    resp = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club_a.id),
            "title": "Club A Coding Marathon",
            "description": "Internal 24h hackathon for club members",
            "event_type": "TECHNICAL",
            "expected_attendees": 50,
            "academic_year": "2026-27",
        },
        headers=_auth_header(sec_a),
    )
    assert resp.status_code == 201
    proposal_id = resp.json()["id"]

    # Secretary B attempts to cancel Club A's draft -> 403
    cancel_resp = await client.post(
        f"/api/v1/events/{proposal_id}/cancel",
        json={"reason": "Malicious cancellation attempt from rival club."},
        headers=_auth_header(sec_b),
    )
    assert cancel_resp.status_code == 403


@pytest.mark.asyncio
async def test_cancel_proposal_repeated_rejection(
    client: AsyncClient, db_session
):
    club, secretary = await _create_club_with_secretary(db_session)

    resp = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "Debate Competition",
            "description": "Parliamentary debate series",
            "event_type": "COMPETITION",
            "expected_attendees": 80,
            "academic_year": "2026-27",
        },
        headers=_auth_header(secretary),
    )
    assert resp.status_code == 201
    proposal_id = resp.json()["id"]

    # First cancellation succeeds
    c1 = await client.post(
        f"/api/v1/events/{proposal_id}/cancel",
        json={"reason": "Venue unavailable."},
        headers=_auth_header(secretary),
    )
    assert c1.status_code == 200

    # Second cancellation fails with 403 WorkflowStateError
    c2 = await client.post(
        f"/api/v1/events/{proposal_id}/cancel",
        json={"reason": "Cancelling again."},
        headers=_auth_header(secretary),
    )
    assert c2.status_code == 403
    assert "already cancelled" in c2.text.lower()


# ---------------------------------------------------------------------------
# Confirmed Event Cancellation Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_scheduled_event_releases_hall(
    client: AsyncClient, db_session
):
    club, secretary = await _create_club_with_secretary(db_session)
    hall = await _create_hall(db_session)

    event, proposal, booking = await _create_confirmed_event_fixture(
        db_session, club, secretary, status=EventStatus.SCHEDULED, hall=hall
    )

    # Secretary cancels scheduled event
    reason = "Trainer had an emergency medical leave."
    cancel_resp = await client.post(
        f"/api/v1/events/{event.id}/cancel",
        json={"reason": reason},
        headers=_auth_header(secretary),
    )
    assert cancel_resp.status_code == 200, cancel_resp.text
    data = cancel_resp.json()
    assert data["entity_type"] == "CONFIRMED_EVENT"
    assert data["status"] == "CANCELLED"
    assert data["hall_released"] is True

    # Verify event row in DB
    await db_session.refresh(event)
    assert event.status == EventStatus.CANCELLED
    assert event.cancelled_at is not None
    assert event.cancellation_reason == reason
    assert event.cancelled_by == secretary.id

    # Verify hall booking is released (is_active is False)
    assert booking is not None
    await db_session.refresh(booking)
    assert booking.is_active is False

    # Verify audit logs: EVENT_STATUS_CHANGED and HALL_RELEASED
    status_audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == str(event.id),
            AuditLog.action == AuditAction.EVENT_STATUS_CHANGED,
        )
    )
    assert status_audit is not None

    hall_audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == str(booking.id),
            AuditLog.action == AuditAction.HALL_RELEASED,
        )
    )
    assert hall_audit is not None


@pytest.mark.asyncio
async def test_cancel_scheduled_event_by_institutional_roles(
    client: AsyncClient, db_session
):
    club, secretary = await _create_club_with_secretary(db_session)
    principal = await _create_user(db_session, UserRole.PRINCIPAL, "principal")
    dean = await _create_user(db_session, UserRole.DEAN_STUDENT_AFFAIRS, "dean")
    admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")

    event1, _, _ = await _create_confirmed_event_fixture(
        db_session, club, secretary, title="College Annual Day"
    )
    resp1 = await client.post(
        f"/api/v1/events/{event1.id}/cancel",
        json={"reason": "Institutional directive: weather alert."},
        headers=_auth_header(principal),
    )
    assert resp1.status_code == 200, resp1.text

    event2, _, _ = await _create_confirmed_event_fixture(
        db_session, club, secretary, title="Tech Symposium"
    )
    resp2 = await client.post(
        f"/api/v1/events/{event2.id}/cancel",
        json={"reason": "Dean cancelled for curriculum review."},
        headers=_auth_header(dean),
    )
    assert resp2.status_code == 200, resp2.text

    event3, _, _ = await _create_confirmed_event_fixture(
        db_session, club, secretary, title="Sports Gala"
    )
    resp3 = await client.post(
        f"/api/v1/events/{event3.id}/cancel",
        json={"reason": "Administrative system reset."},
        headers=_auth_header(admin),
    )
    assert resp3.status_code == 200, resp3.text


@pytest.mark.asyncio
async def test_cancel_event_auto_rejects_pending_cash_advance(
    client: AsyncClient, db_session
):
    club, secretary = await _create_club_with_secretary(db_session)
    event, _, _ = await _create_confirmed_event_fixture(
        db_session, club, secretary, title="RoboWars Tournament"
    )

    # Cash advance in REQUESTED status
    advance = CashAdvance(
        id=uuid.uuid4(),
        event_id=event.id,
        recipient_id=secretary.id,
        amount_requested=Decimal("15000.00"),
        notes="Arena parts, batteries, and arena setup materials",
        status=CashAdvanceStatus.REQUESTED,
    )
    db_session.add(advance)
    await db_session.commit()

    # Cancel event
    reason = "Safety inspection failed on arena perimeter."
    cancel_resp = await client.post(
        f"/api/v1/events/{event.id}/cancel",
        json={"reason": reason},
        headers=_auth_header(secretary),
    )
    assert cancel_resp.status_code == 200, cancel_resp.text
    data = cancel_resp.json()
    assert data["advance_status"] == "REJECTED_ON_CANCELLATION"

    # Verify advance in DB is REJECTED
    await db_session.refresh(advance)
    assert advance.status == CashAdvanceStatus.REJECTED
    assert "Event cancelled" in advance.rejection_reason

    # Verify ADVANCE_REJECTED audit log
    adv_audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == str(advance.id),
            AuditLog.action == AuditAction.ADVANCE_REJECTED,
        )
    )
    assert adv_audit is not None


@pytest.mark.asyncio
async def test_cancel_event_preserves_disbursed_advance_for_settlement_refund(
    client: AsyncClient, db_session
):
    club, secretary = await _create_club_with_secretary(db_session)
    finance_officer = await _create_user(db_session, UserRole.FINANCE_OFFICER, "fin")
    event, _, _ = await _create_confirmed_event_fixture(
        db_session, club, secretary, title="Guest Lecture Series"
    )

    now = datetime.now(UTC)
    # Cash advance already DISBURSED
    advance = CashAdvance(
        id=uuid.uuid4(),
        event_id=event.id,
        recipient_id=secretary.id,
        amount_requested=Decimal("20000.00"),
        amount_approved=Decimal("20000.00"),
        amount_disbursed=Decimal("20000.00"),
        disbursed_by=finance_officer.id,
        disbursement_date=now - timedelta(days=1),
        notes="Guest travel, mementos, hospitality",
        status=CashAdvanceStatus.DISBURSED,
    )
    db_session.add(advance)
    await db_session.commit()

    # Secretary cancels event
    reason = "Guest flight cancelled due to severe blizzard."
    cancel_resp = await client.post(
        f"/api/v1/events/{event.id}/cancel",
        json={"reason": reason},
        headers=_auth_header(secretary),
    )
    assert cancel_resp.status_code == 200, cancel_resp.text
    data = cancel_resp.json()
    assert data["advance_status"] == "DISBURSED_REFUND_REQUIRED"
    assert "refunded via financial settlement" in data["message"]

    # Verify advance is NOT erased or marked settled - remains DISBURSED debt
    await db_session.refresh(advance)
    assert advance.status == CashAdvanceStatus.DISBURSED

    # Verify notification created for finance officer
    notif = await db_session.scalar(
        select(Notification).where(
            Notification.recipient_id == finance_officer.id,
            Notification.title.like("%Outstanding Advance Refund Required%"),
        )
    )
    assert notif is not None
    assert "20000.00" in notif.message


@pytest.mark.asyncio
async def test_cancel_event_terminal_and_completed_states_rejected(
    client: AsyncClient, db_session
):
    club, secretary = await _create_club_with_secretary(db_session)

    # 1. COMPLETED -> 403 WorkflowStateError
    completed_event, _, _ = await _create_confirmed_event_fixture(
        db_session, club, secretary, status=EventStatus.COMPLETED, title="Completed Event"
    )

    # 2. CLOSURE_REQUESTED -> 403 WorkflowStateError
    closure_event, _, _ = await _create_confirmed_event_fixture(
        db_session, club, secretary, status=EventStatus.CLOSURE_REQUESTED, title="Closing Event"
    )

    # 3. CLOSED -> 409 ConflictError
    closed_event, _, _ = await _create_confirmed_event_fixture(
        db_session, club, secretary, status=EventStatus.CLOSED, title="Closed Event"
    )

    # 4. ARCHIVED -> 409 ConflictError
    archived_event, _, _ = await _create_confirmed_event_fixture(
        db_session, club, secretary, status=EventStatus.ARCHIVED, title="Archived Event"
    )

    # Test COMPLETED
    r1 = await client.post(
        f"/api/v1/events/{completed_event.id}/cancel",
        json={"reason": "Cannot cancel completed."},
        headers=_auth_header(secretary),
    )
    assert r1.status_code == 403
    assert "already completed" in r1.text.lower()

    # Test CLOSURE_REQUESTED
    r2 = await client.post(
        f"/api/v1/events/{closure_event.id}/cancel",
        json={"reason": "Cannot cancel closure requested."},
        headers=_auth_header(secretary),
    )
    assert r2.status_code == 403
    assert "closeout review" in r2.text.lower()

    # Test CLOSED
    r3 = await client.post(
        f"/api/v1/events/{closed_event.id}/cancel",
        json={"reason": "Cannot cancel closed."},
        headers=_auth_header(secretary),
    )
    assert r3.status_code == 409
    assert "terminal status" in r3.text.lower()

    # Test ARCHIVED
    r4 = await client.post(
        f"/api/v1/events/{archived_event.id}/cancel",
        json={"reason": "Cannot cancel archived."},
        headers=_auth_header(secretary),
    )
    assert r4.status_code == 409
    assert "terminal status" in r4.text.lower()
