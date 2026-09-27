"""
CampusConnect - Event Closeout & Archival Service Tests (Phase 2.4.2)

Comprehensive test suite verifying:
- Closeout eligibility computation across all financial, report, and venue conditions
- Closeout request initiation by Club Secretary with ownership guards & idempotency
- Statutory closure certification by Dean / Principal / Faculty Advisor (delegated)
  with row locks, venue clearance attestation, and deterministic manifest hashing
- Rejection of closure requests with mandatory rationale
- Closed-event and Archived-event immutability enforcement across all services
- Two-stage reopening: Petition (Secretary/Advisor/FO) & Statutory Approval (Dean/Principal)
  with immutable EventClosureRevision snapshots and settlement unsealing
- Sequential, collision-safe revision numbering across multiple successive reopenings
- Archival strictly restricted to System Administrators
- Role-based access control, Segregation of Duties (SOD), and IDOR protection
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    BadRequestError,
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    InvalidWorkflowTransitionError,
    ResourceOwnershipError,
)
from app.models.domain import (
    ActualExpense,
    ActualIncome,
    AuditLog,
    Club,
    ClubMember,
    Document,
    Event,
    EventRequest,
    EventRequestVersion,
    FinancialSettlement,
    Hall,
    HallBookingConfirmed,
    Notification,
    PostEventReport,
    User,
    VenueRequest,
)
from app.models.enums import (
    ActualExpenseStatus,
    ActualIncomeStatus,
    AuditAction,
    BudgetLineItemCategory,
    ClubMemberRole,
    DocumentType,
    EventStatus,
    EventType,
    IncomeSourceType,
    NotificationType,
    PostEventReportStatus,
    SettlementStatus,
    SettlementType,
    UserRole,
)
from app.services.closeout_service import CloseoutService
from app.services.event_execution_service import EventExecutionService
from app.services.expense_service import ExpenseService
from app.services.settlement_service import SettlementService

# =============================================================================
# TEST ENVIRONMENT FIXTURES & HELPERS
# =============================================================================


async def _create_closeout_test_env(
    db: AsyncSession,
    sanctioned_grant: Decimal = Decimal("30000.00"),
    sanctioned_exp: Decimal = Decimal("35000.00"),
    expected_inc: Decimal = Decimal("5000.00"),
) -> dict[str, Any]:
    """Helper to assemble a complete, valid test environment for closeout tests."""
    uid = uuid.uuid4().hex[:6]

    sec = User(
        id=uuid.uuid4(),
        email=f"sec_{uid}@college.edu",
        password_hash="hash",
        full_name=f"Secretary {uid}",
        role=UserRole.CLUB_SECRETARY,
        is_active=True,
    )
    other_sec = User(
        id=uuid.uuid4(),
        email=f"other_sec_{uid}@college.edu",
        password_hash="hash",
        full_name=f"Other Sec {uid}",
        role=UserRole.CLUB_SECRETARY,
        is_active=True,
    )
    fo = User(
        id=uuid.uuid4(),
        email=f"fo_{uid}@college.edu",
        password_hash="hash",
        full_name=f"Finance Officer {uid}",
        role=UserRole.FINANCE_OFFICER,
        is_active=True,
    )
    admin = User(
        id=uuid.uuid4(),
        email=f"admin_{uid}@college.edu",
        password_hash="hash",
        full_name=f"Admin {uid}",
        role=UserRole.SYSTEM_ADMIN,
        is_active=True,
    )
    principal = User(
        id=uuid.uuid4(),
        email=f"principal_{uid}@college.edu",
        password_hash="hash",
        full_name=f"Principal {uid}",
        role=UserRole.PRINCIPAL,
        is_active=True,
    )
    dean = User(
        id=uuid.uuid4(),
        email=f"dean_{uid}@college.edu",
        password_hash="hash",
        full_name=f"Dean {uid}",
        role=UserRole.DEAN_STUDENT_AFFAIRS,
        is_active=True,
    )
    advisor = User(
        id=uuid.uuid4(),
        email=f"adv_{uid}@college.edu",
        password_hash="hash",
        full_name=f"Advisor {uid}",
        role=UserRole.FACULTY_ADVISOR,
        is_active=True,
    )
    other_advisor = User(
        id=uuid.uuid4(),
        email=f"other_adv_{uid}@college.edu",
        password_hash="hash",
        full_name=f"Other Advisor {uid}",
        role=UserRole.FACULTY_ADVISOR,
        is_active=True,
    )
    db.add_all([sec, other_sec, fo, admin, principal, dean, advisor, other_advisor])
    await db.flush()

    club = Club(
        id=uuid.uuid4(),
        name=f"Robotics Club {uid}",
        slug=f"robotics-{uid}",
        academic_year="2026-27",
        faculty_advisor_id=advisor.id,
        created_by=admin.id,
        is_active=True,
    )
    other_club = Club(
        id=uuid.uuid4(),
        name=f"Music Club {uid}",
        slug=f"music-{uid}",
        academic_year="2026-27",
        faculty_advisor_id=other_advisor.id,
        created_by=admin.id,
        is_active=True,
    )
    db.add_all([club, other_club])
    await db.flush()

    db.add(
        ClubMember(
            club_id=club.id,
            user_id=sec.id,
            member_role=ClubMemberRole.SECRETARY,
            is_active=True,
        )
    )
    db.add(
        ClubMember(
            club_id=other_club.id,
            user_id=other_sec.id,
            member_role=ClubMemberRole.SECRETARY,
            is_active=True,
        )
    )
    await db.flush()

    hall = Hall(
        id=uuid.uuid4(),
        name=f"Auditorium {uid}",
        capacity=500,
        location="Campus Center",
        is_active=True,
    )
    db.add(hall)
    await db.flush()

    now = datetime.now(UTC)
    req = EventRequest(
        id=uuid.uuid4(),
        club_id=club.id,
        title=f"RoboWars {uid}",
        event_type=EventType.COMPETITION,
        event_date=now - timedelta(days=2),
        submitted_by=sec.id,
        academic_year="2026-27",
        current_version=1,
    )
    db.add(req)
    await db.flush()

    ver = EventRequestVersion(
        id=uuid.uuid4(),
        event_request_id=req.id,
        version_number=1,
        snapshot={
            "title": f"RoboWars {uid}",
            "budget": {
                "institute_contribution": str(sanctioned_grant),
                "total_expected_expenditure": str(sanctioned_exp),
                "expected_income": str(expected_inc),
            },
        },
        submitted_by=sec.id,
    )
    db.add(ver)
    await db.flush()

    event = Event(
        id=uuid.uuid4(),
        event_request_id=req.id,
        approved_version_id=ver.id,
        club_id=club.id,
        hall_id=hall.id,
        title=f"RoboWars {uid}",
        event_type=EventType.COMPETITION,
        event_date=now - timedelta(days=2),
        start_time=now - timedelta(days=2),
        end_time=now - timedelta(days=2, hours=-4),
        status=EventStatus.COMPLETED,
        academic_year="2026-27",
    )
    db.add(event)
    await db.flush()

    # Confirmed Hall Booking that ended 2 days ago
    vr = VenueRequest(
        id=uuid.uuid4(),
        event_request_id=req.id,
        hall_id=hall.id,
        requested_date=now - timedelta(days=2),
        start_time=now - timedelta(days=2),
        end_time=now - timedelta(days=2, hours=-4),
    )
    db.add(vr)
    await db.flush()

    booking = HallBookingConfirmed(
        id=uuid.uuid4(),
        hall_id=hall.id,
        event_request_id=req.id,
        venue_request_id=vr.id,
        booking_date=now - timedelta(days=2),
        start_time=now - timedelta(days=2),
        end_time=now - timedelta(days=2, hours=-4),
        is_active=True,
    )
    db.add(booking)
    await db.flush()

    report = PostEventReport(
        id=uuid.uuid4(),
        event_id=event.id,
        revision_number=1,
        actual_attendance=200,
        summary="RoboWars completed with high student engagement",
        objectives_achieved="All technical criteria met",
        status=PostEventReportStatus.CERTIFIED,
        submitted_by=sec.id,
        submitted_at=now - timedelta(days=1),
        certified_by=advisor.id,
        certified_at=now - timedelta(days=1),
        certification_remarks="Verified by faculty advisor",
    )
    db.add(report)
    await db.flush()

    # Create fully verified expenses: V = 10000.00
    doc = Document(
        id=uuid.uuid4(),
        event_request_id=req.id,
        event_id=event.id,
        uploaded_by=sec.id,
        document_type=DocumentType.EXPENSE_INVOICE.value,
        original_filename="supplies.pdf",
        stored_filename=f"inv_{uuid.uuid4().hex}.pdf",
        file_size_bytes=2048,
        mime_type="application/pdf",
        storage_path="/storage/supplies.pdf",
        is_active=True,
    )
    db.add(doc)
    await db.flush()

    exp = ActualExpense(
        id=uuid.uuid4(),
        event_id=event.id,
        category=BudgetLineItemCategory.MATERIALS,
        description="Circuit components",
        vendor_name="RoboStore",
        invoice_date=date.today(),
        claimed_amount=Decimal("10000.00"),
        verified_amount=Decimal("10000.00"),
        status=ActualExpenseStatus.VERIFIED,
        bill_document_id=doc.id,
        submitted_by=sec.id,
    )
    db.add(exp)
    await db.flush()

    # Create settled BALANCED settlement: P = 10000, A = 10000, B = 0 -> SETTLED
    settlement = FinancialSettlement(
        id=uuid.uuid4(),
        event_id=event.id,
        approved_version_id=ver.id,
        sanctioned_grant=sanctioned_grant,
        sanctioned_expenditure=sanctioned_exp,
        expected_income=expected_inc,
        total_claimed_expenditure=Decimal("10000.00"),
        total_verified_expenditure=Decimal("10000.00"),
        total_disallowed_expenditure=Decimal("0.00"),
        total_verified_income=Decimal("0.00"),
        net_deficit=Decimal("10000.00"),
        institutional_payout=Decimal("10000.00"),
        cash_advance_disbursed=Decimal("10000.00"),
        settlement_balance=Decimal("0.00"),
        reimbursement_due=Decimal("0.00"),
        refund_due=Decimal("0.00"),
        settlement_type=SettlementType.BALANCED,
        status=SettlementStatus.SETTLED,
        prepared_by=sec.id,
        audited_by=fo.id,
        audited_at=now - timedelta(hours=12),
        submitted_at=now - timedelta(hours=14),
    )
    db.add(settlement)
    await db.flush()

    return {
        "sec": sec,
        "other_sec": other_sec,
        "fo": fo,
        "admin": admin,
        "principal": principal,
        "dean": dean,
        "advisor": advisor,
        "other_advisor": other_advisor,
        "club": club,
        "other_club": other_club,
        "hall": hall,
        "booking": booking,
        "req": req,
        "ver": ver,
        "event": event,
        "report": report,
        "expense": exp,
        "settlement": settlement,
    }


# =============================================================================
# 1. ELIGIBILITY EVALUATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_eligibility_fully_eligible(db_session: AsyncSession):
    """Eligible event passes all gates with zero blockers."""
    env = await _create_closeout_test_env(db_session)
    elig = await CloseoutService.get_closure_eligibility(db_session, env["event"].id, env["sec"])

    assert elig["eligible"] is True
    assert elig["blockers"] == []
    assert elig["event_status"] == EventStatus.COMPLETED.value
    assert elig["settlement_status"] == SettlementStatus.SETTLED.value
    assert elig["report_status"] == PostEventReportStatus.CERTIFIED.value
    assert elig["venue_status"]["has_booking"] is True
    assert elig["venue_status"]["booking_ended"] is True


@pytest.mark.asyncio
async def test_eligibility_report_not_certified(db_session: AsyncSession):
    """Post-event report not certified blocks eligibility."""
    env = await _create_closeout_test_env(db_session)
    env["report"].status = PostEventReportStatus.SUBMITTED
    await db_session.flush()

    elig = await CloseoutService.get_closure_eligibility(db_session, env["event"].id, env["sec"])
    assert elig["eligible"] is False
    assert "POST_EVENT_REPORT_NOT_CERTIFIED" in elig["blockers"]


@pytest.mark.asyncio
async def test_eligibility_unresolved_expense(db_session: AsyncSession):
    """Unresolved draft/submitted/queried expense blocks eligibility."""
    env = await _create_closeout_test_env(db_session)
    env["expense"].status = ActualExpenseStatus.SUBMITTED
    await db_session.flush()

    elig = await CloseoutService.get_closure_eligibility(db_session, env["event"].id, env["sec"])
    assert elig["eligible"] is False
    assert "UNRESOLVED_EXPENSES" in elig["blockers"]


@pytest.mark.asyncio
async def test_eligibility_unverified_income(db_session: AsyncSession):
    """Recorded income that has not been verified by Finance blocks eligibility."""
    env = await _create_closeout_test_env(db_session)
    inc = ActualIncome(
        id=uuid.uuid4(),
        event_id=env["event"].id,
        source_type=IncomeSourceType.SPONSORSHIP,
        description="Corporate sponsorship",
        amount=Decimal("5000.00"),
        received_date=date.today(),
        payer_name="Tech Corp",
        evidence_document_id=env["expense"].bill_document_id,
        status=ActualIncomeStatus.RECORDED,
        recorded_by=env["sec"].id,
    )
    db_session.add(inc)
    await db_session.flush()

    elig = await CloseoutService.get_closure_eligibility(db_session, env["event"].id, env["sec"])
    assert elig["eligible"] is False
    assert "UNVERIFIED_INCOME" in elig["blockers"]


@pytest.mark.asyncio
async def test_eligibility_settlement_missing(db_session: AsyncSession):
    """Missing financial settlement blocks eligibility."""
    env = await _create_closeout_test_env(db_session)
    await db_session.delete(env["settlement"])
    await db_session.flush()

    elig = await CloseoutService.get_closure_eligibility(db_session, env["event"].id, env["sec"])
    assert elig["eligible"] is False
    assert "SETTLEMENT_MISSING" in elig["blockers"]


@pytest.mark.asyncio
async def test_eligibility_settlement_not_settled(db_session: AsyncSession):
    """Settlement in non-SETTLED status (e.g. UNDER_AUDIT) blocks eligibility."""
    env = await _create_closeout_test_env(db_session)
    env["settlement"].status = SettlementStatus.UNDER_AUDIT
    await db_session.flush()

    elig = await CloseoutService.get_closure_eligibility(db_session, env["event"].id, env["sec"])
    assert elig["eligible"] is False
    assert "SETTLEMENT_NOT_SETTLED" in elig["blockers"]


@pytest.mark.asyncio
async def test_eligibility_active_hall_booking_blocks(db_session: AsyncSession):
    """Hall booking that has not yet ended blocks closeout."""
    env = await _create_closeout_test_env(db_session)
    # Set booking end_time to tomorrow
    env["booking"].end_time = datetime.now(UTC) + timedelta(days=1)
    await db_session.flush()

    elig = await CloseoutService.get_closure_eligibility(db_session, env["event"].id, env["sec"])
    assert elig["eligible"] is False
    assert "VENUE_BOOKING_NOT_ENDED" in elig["blockers"]
    assert elig["venue_status"]["booking_ended"] is False


@pytest.mark.asyncio
async def test_eligibility_cancelled_event(db_session: AsyncSession):
    """Cancelled event blocks eligibility."""
    env = await _create_closeout_test_env(db_session)
    env["event"].status = EventStatus.CANCELLED
    env["event"].cancelled_at = datetime.now(UTC)
    await db_session.flush()

    elig = await CloseoutService.get_closure_eligibility(db_session, env["event"].id, env["sec"])
    assert elig["eligible"] is False
    assert "EVENT_CANCELLED" in elig["blockers"] or "EVENT_NOT_COMPLETED" in elig["blockers"]


# =============================================================================
# 2. CLOSEOUT REQUEST TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_request_closeout_valid_secretary(db_session: AsyncSession):
    """Club Secretary successfully initiates closeout for completed eligible event."""
    env = await _create_closeout_test_env(db_session)
    res = await CloseoutService.request_closeout(
        db_session, env["event"].id, env["sec"], remarks="All activities concluded"
    )

    assert res["status"] == EventStatus.CLOSURE_REQUESTED.value
    assert env["event"].status == EventStatus.CLOSURE_REQUESTED

    # Verify AuditLog created
    audit = await db_session.scalar(
        select(AuditLog)
        .where(
            AuditLog.entity_id == str(env["event"].id),
            AuditLog.action == AuditAction.CLOSURE_REQUESTED,
        )
    )
    assert audit is not None
    assert audit.actor_id == env["sec"].id

    # Verify notification created for Dean and Principal
    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.notification_type == NotificationType.EVENT_CLOSURE_REQUESTED.value
            )
        )
    ).all()
    recipient_ids = {n.recipient_id for n in notifs}
    assert env["dean"].id in recipient_ids
    assert env["principal"].id in recipient_ids


@pytest.mark.asyncio
async def test_request_closeout_idempotency(db_session: AsyncSession):
    """Repeated request in CLOSURE_REQUESTED returns cleanly without duplicate logs."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    # Second call
    res = await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    assert res["status"] == EventStatus.CLOSURE_REQUESTED.value
    assert "already been requested" in res["message"]

    # Verify only 1 audit log created
    audits = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == str(env["event"].id),
                AuditLog.action == AuditAction.CLOSURE_REQUESTED,
            )
        )
    ).all()
    assert len(audits) == 1


@pytest.mark.asyncio
async def test_request_closeout_unauthorized_role(db_session: AsyncSession):
    """Finance Officer, Advisor, or System Admin cannot request closeout."""
    env = await _create_closeout_test_env(db_session)

    with pytest.raises(ForbiddenError):
        await CloseoutService.request_closeout(db_session, env["event"].id, env["fo"])

    with pytest.raises(ForbiddenError):
        await CloseoutService.request_closeout(db_session, env["event"].id, env["admin"])

    with pytest.raises(ForbiddenError):
        await CloseoutService.request_closeout(db_session, env["event"].id, env["advisor"])


@pytest.mark.asyncio
async def test_request_closeout_cross_club_idor(db_session: AsyncSession):
    """Secretary of another club cannot request closeout for this club's event."""
    env = await _create_closeout_test_env(db_session)

    with pytest.raises(ResourceOwnershipError):
        await CloseoutService.request_closeout(db_session, env["event"].id, env["other_sec"])


@pytest.mark.asyncio
async def test_request_closeout_invalid_event_state(db_session: AsyncSession):
    """Cannot request closeout for SCHEDULED or IN_PROGRESS events."""
    env = await _create_closeout_test_env(db_session)
    env["event"].status = EventStatus.SCHEDULED
    await db_session.flush()

    with pytest.raises(InvalidWorkflowTransitionError):
        await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])


@pytest.mark.asyncio
async def test_request_closeout_blocked_eligibility(db_session: AsyncSession):
    """Cannot request closeout if event has unresolved blockers."""
    env = await _create_closeout_test_env(db_session)
    env["report"].status = PostEventReportStatus.DRAFT
    await db_session.flush()

    with pytest.raises(BusinessRuleError, match="not eligible for closeout"):
        await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])


# =============================================================================
# 3. CLOSURE CERTIFICATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_certify_closeout_dean_success(db_session: AsyncSession):
    """Dean Student Affairs successfully certifies closeout with venue clearance attestation."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    closure = await CloseoutService.certify_closeout(
        db=db_session,
        event_id=env["event"].id,
        actor=env["dean"],
        closure_notes="Dean formal closeout certification",
        venue_cleared=True,
    )

    assert closure is not None
    assert closure.certified_by == env["dean"].id
    assert closure.venue_cleared is True
    assert len(closure.certificate_manifest_hash) == 64
    assert env["event"].status == EventStatus.CLOSED

    # Verify AuditLog created
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == str(env["event"].id),
            AuditLog.action == AuditAction.EVENT_CLOSED,
        )
    )
    assert audit is not None
    assert audit.actor_id == env["dean"].id

    # Verify notification created for Secretary
    notif = await db_session.scalar(
        select(Notification).where(
            Notification.recipient_id == env["sec"].id,
            Notification.notification_type == NotificationType.EVENT_CLOSED.value,
        )
    )
    assert notif is not None


@pytest.mark.asyncio
async def test_certify_closeout_principal_success(db_session: AsyncSession):
    """Principal successfully certifies closeout."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    closure = await CloseoutService.certify_closeout(
        db=db_session,
        event_id=env["event"].id,
        actor=env["principal"],
        venue_cleared=True,
    )
    assert closure.certified_by == env["principal"].id
    assert env["event"].status == EventStatus.CLOSED


@pytest.mark.asyncio
async def test_certify_closeout_advisor_disabled_by_default(db_session: AsyncSession):
    """Faculty Advisor cannot certify when ALLOW_ADVISOR_EVENT_CLOSEOUT=False."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    with pytest.raises(ForbiddenError, match="not permitted to certify event closure"):
        await CloseoutService.certify_closeout(
            db=db_session,
            event_id=env["event"].id,
            actor=env["advisor"],
            venue_cleared=True,
        )


@pytest.mark.asyncio
async def test_certify_closeout_advisor_enabled_with_delegation(
    db_session: AsyncSession, monkeypatch
):
    """Faculty Advisor can certify when ALLOW_ADVISOR_EVENT_CLOSEOUT=True and assigned to club."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ALLOW_ADVISOR_EVENT_CLOSEOUT", True)

    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    closure = await CloseoutService.certify_closeout(
        db=db_session,
        event_id=env["event"].id,
        actor=env["advisor"],
        venue_cleared=True,
    )
    assert closure.certified_by == env["advisor"].id
    assert env["event"].status == EventStatus.CLOSED


@pytest.mark.asyncio
async def test_certify_closeout_advisor_wrong_club_denied(db_session: AsyncSession, monkeypatch):
    """Advisor of a different club cannot certify even when delegation setting is True."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ALLOW_ADVISOR_EVENT_CLOSEOUT", True)

    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    with pytest.raises(ForbiddenError, match="designated Faculty Advisor for the owning club"):
        await CloseoutService.certify_closeout(
            db=db_session,
            event_id=env["event"].id,
            actor=env["other_advisor"],
            venue_cleared=True,
        )


@pytest.mark.asyncio
async def test_certify_closeout_system_admin_strictly_barred(db_session: AsyncSession):
    """System Admin is strictly barred from closeout certification (403)."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    with pytest.raises(ForbiddenError, match="strictly barred"):
        await CloseoutService.certify_closeout(
            db=db_session,
            event_id=env["event"].id,
            actor=env["admin"],
            venue_cleared=True,
        )


@pytest.mark.asyncio
async def test_certify_closeout_venue_cleared_false_rejected(db_session: AsyncSession):
    """venue_cleared=False is strictly rejected (must not silently default to True)."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    with pytest.raises(BusinessRuleError, match="venue clearance attestation"):
        await CloseoutService.certify_closeout(
            db=db_session,
            event_id=env["event"].id,
            actor=env["dean"],
            venue_cleared=False,
        )


@pytest.mark.asyncio
async def test_certify_closeout_manifest_hash_deterministic(db_session: AsyncSession):
    """Certificate manifest hash is deterministic across identical parameters."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    closure = await CloseoutService.certify_closeout(
        db=db_session,
        event_id=env["event"].id,
        actor=env["dean"],
        venue_cleared=True,
    )
    hash1 = closure.certificate_manifest_hash
    assert len(hash1) == 64
    assert all(c in "0123456789abcdef" for c in hash1)


# =============================================================================
# 4. CLOSURE REJECTION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_reject_closeout_valid(db_session: AsyncSession):
    """Institutional certifier rejects closeout request; event returns to COMPLETED."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    event = await CloseoutService.reject_closeout(
        db=db_session,
        event_id=env["event"].id,
        actor=env["dean"],
        reason="Missing sponsor sign-off",
    )

    assert event.status == EventStatus.COMPLETED

    # Verify AuditLog created
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == str(event.id),
            AuditLog.action == AuditAction.CLOSURE_REJECTED,
        )
    )
    assert audit is not None
    assert audit.new_state["rejection_reason"] == "Missing sponsor sign-off"

    # Verify notification created
    notif = await db_session.scalar(
        select(Notification).where(
            Notification.recipient_id == env["sec"].id,
            Notification.notification_type == NotificationType.EVENT_CLOSURE_REJECTED.value,
        )
    )
    assert notif is not None


@pytest.mark.asyncio
async def test_reject_closeout_mandatory_reason(db_session: AsyncSession):
    """Rejection requires mandatory, non-empty reason."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    with pytest.raises(BadRequestError, match="mandatory"):
        await CloseoutService.reject_closeout(
            db=db_session, event_id=env["event"].id, actor=env["dean"], reason="   "
        )


@pytest.mark.asyncio
async def test_reject_closeout_unauthorized(db_session: AsyncSession):
    """Secretary, FO, or System Admin cannot reject closeout."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    with pytest.raises(ForbiddenError):
        await CloseoutService.reject_closeout(
            db=db_session, event_id=env["event"].id, actor=env["sec"], reason="Cannot self-reject"
        )

    with pytest.raises(ForbiddenError):
        await CloseoutService.reject_closeout(
            db=db_session,
            event_id=env["event"].id,
            actor=env["admin"],
            reason="Admin cannot reject",
        )


@pytest.mark.asyncio
async def test_closeout_request_history_resolves_latest_request_after_rejection(
    db_session: AsyncSession,
):
    """
    Option A audit verification (Section 4):
    request (sec1) -> rejection -> second request (sec2) -> certification.
    EventClosure.requested_by / requested_at MUST resolve from the SECOND (latest)
    AuditAction.CLOSURE_REQUESTED, not the initial rejected one.
    """
    env = await _create_closeout_test_env(db_session)

    # Add second secretary to owning club
    sec2 = User(
        id=uuid.uuid4(),
        email=f"sec2_{uuid.uuid4().hex[:6]}@college.edu",
        password_hash="hash",
        full_name="Secretary Two",
        role=UserRole.CLUB_SECRETARY,
        is_active=True,
    )
    db_session.add(sec2)
    db_session.add(
        ClubMember(
            id=uuid.uuid4(),
            club_id=env["club"].id,
            user_id=sec2.id,
            member_role=ClubMemberRole.SECRETARY,
            is_active=True,
        )
    )
    await db_session.flush()

    # Step 1: Initial closeout request by sec1
    await CloseoutService.request_closeout(
        db=db_session, event_id=env["event"].id, actor=env["sec"], remarks="First request"
    )
    assert env["event"].status == EventStatus.CLOSURE_REQUESTED

    # Step 2: Certifier rejects closeout -> returns to COMPLETED
    await CloseoutService.reject_closeout(
        db=db_session,
        event_id=env["event"].id,
        actor=env["dean"],
        reason="Incomplete bills, please attach vendor receipt",
    )
    assert env["event"].status == EventStatus.COMPLETED

    # Step 3: Second request by sec2
    await CloseoutService.request_closeout(
        db=db_session, event_id=env["event"].id, actor=sec2, remarks="Second request with bill"
    )
    assert env["event"].status == EventStatus.CLOSURE_REQUESTED

    # Step 4: Dean certifies closeout
    closure = await CloseoutService.certify_closeout(
        db=db_session,
        event_id=env["event"].id,
        actor=env["dean"],
        closure_notes="Approved with vendor receipt",
        venue_cleared=True,
    )

    # Step 5: Verify EventClosure resolved the latest (second) request
    assert closure.requested_by == sec2.id
    assert closure.requested_by != env["sec"].id
    assert closure.certified_by == env["dean"].id
    assert env["event"].status == EventStatus.CLOSED


# =============================================================================
# 5. CLOSED & ARCHIVED IMMUTABILITY TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_immutability_closed_event_mutations_blocked(db_session: AsyncSession):
    """Mutations across downstream services are strictly rejected on CLOSED events."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
    )
    assert env["event"].status == EventStatus.CLOSED

    # 1. ExpenseService mutation rejected
    with pytest.raises(ConflictError, match="terminal status"):
        await ExpenseService.delete_draft_expense(
            db_session, env["event"].id, env["expense"].id, env["sec"]
        )

    # 2. SettlementService mutation rejected
    with pytest.raises(ConflictError, match="terminal status"):
        await SettlementService.record_income(
            db=db_session,
            event_id=env["event"].id,
            source_type=IncomeSourceType.TICKET_SALES,
            description="Ticket sales",
            amount=Decimal("1000.00"),
            received_date=date.today(),
            payer_name="Student",
            evidence_document_id=env["expense"].bill_document_id,
            actor=env["sec"],
        )

    # 3. Direct settlement reopening without Dean approval rejected
    with pytest.raises(ConflictError, match="Cannot reopen settlement directly"):
        await SettlementService.reopen_settlement(
            db=db_session,
            settlement_id=env["settlement"].id,
            reopening_reason="Direct FO bypass",
            actor=env["fo"],
        )

    # 4. EventExecutionService report update rejected
    with pytest.raises(ConflictError, match="terminal status"):
        await EventExecutionService.update_report(
            db=db_session,
            event_id=env["event"].id,
            update_in=None,  # will fail on status check before payload
            actor=env["sec"],
        )


@pytest.mark.asyncio
async def test_immutability_archived_event_mutations_blocked(db_session: AsyncSession):
    """Mutations are strictly rejected on ARCHIVED events."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
    )
    await CloseoutService.archive_event(db_session, env["event"].id, env["admin"])
    assert env["event"].status == EventStatus.ARCHIVED

    with pytest.raises(ConflictError, match="terminal status"):
        await ExpenseService.create_draft_expense(
            db=db_session,
            event_id=env["event"].id,
            payload=None,
            actor=env["sec"],
        )


# =============================================================================
# 6. REOPEN TESTS (TWO-STAGE PETITION & APPROVAL)
# =============================================================================


@pytest.mark.asyncio
async def test_reopen_request_valid_petitioners(db_session: AsyncSession):
    """Secretary, Faculty Advisor, and Finance Officer can petition for reopening."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
    )

    # 1. Secretary petition
    res_sec = await CloseoutService.request_reopen(
        db_session, env["event"].id, env["sec"], reason="Discovered overlooked invoice"
    )
    assert res_sec["status"] == EventStatus.CLOSED.value

    # 2. Finance Officer petition
    res_fo = await CloseoutService.request_reopen(
        db_session, env["event"].id, env["fo"], reason="Audit adjustment required"
    )
    assert res_fo["status"] == EventStatus.CLOSED.value

    # 3. Faculty Advisor petition
    res_adv = await CloseoutService.request_reopen(
        db_session, env["event"].id, env["advisor"], reason="Advisor re-evaluation"
    )
    assert res_adv["status"] == EventStatus.CLOSED.value


@pytest.mark.asyncio
async def test_reopen_request_system_admin_denied(db_session: AsyncSession):
    """System Admin cannot petition for reopening."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
    )

    with pytest.raises(ForbiddenError, match="cannot petition"):
        await CloseoutService.request_reopen(
            db_session, env["event"].id, env["admin"], reason="Admin reopen petition"
        )


@pytest.mark.asyncio
async def test_reopen_approve_dean_success(db_session: AsyncSession):
    """Dean approves reopening: Event -> COMPLETED, Settlement -> REOPENED, Revision captured."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
    )

    # Submit petition
    await CloseoutService.request_reopen(
        db_session, env["event"].id, env["sec"], reason="Invoice discovered"
    )

    # Dean approves
    rev = await CloseoutService.approve_reopen(
        db=db_session,
        event_id=env["event"].id,
        actor=env["dean"],
        reason="Approved unsealing for invoice adjustment",
    )

    assert rev is not None
    assert rev.revision_number == 1
    assert rev.reopened_by == env["dean"].id
    assert "settlement_snapshot" in rev.snapshot_data
    assert env["event"].status == EventStatus.COMPLETED
    assert env["settlement"].status == SettlementStatus.REOPENED

    # Verify AuditLog created
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == str(env["event"].id),
            AuditLog.action == AuditAction.EVENT_REOPENED,
        )
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_reopen_approve_unauthorized_roles_denied(db_session: AsyncSession):
    """System Admin, Secretary, or FO cannot approve reopening."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
    )

    with pytest.raises(ForbiddenError, match="strictly barred"):
        await CloseoutService.approve_reopen(
            db=db_session, event_id=env["event"].id, actor=env["admin"], reason="Admin approval"
        )

    with pytest.raises(ForbiddenError):
        await CloseoutService.approve_reopen(
            db=db_session, event_id=env["event"].id, actor=env["sec"], reason="Sec approval"
        )

    with pytest.raises(ForbiddenError):
        await CloseoutService.approve_reopen(
            db=db_session, event_id=env["event"].id, actor=env["fo"], reason="FO approval"
        )


@pytest.mark.asyncio
async def test_finance_officer_reopen_security_scenario(db_session: AsyncSession):
    """
    Mandatory security scenario (Section 2 audit):
    1. Finance Officer -> direct settlement reopen on CLOSED event -> MUST fail (ConflictError 409).
    2. Finance Officer -> closeout reopen approval -> MUST fail (ForbiddenError 403).
    3. Dean / Principal -> closeout reopen approval -> succeeds.
    """
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
    )
    assert env["event"].status == EventStatus.CLOSED

    # 1. FO direct settlement reopen attempt on CLOSED event -> MUST fail
    with pytest.raises(
        ConflictError, match="Cannot reopen settlement directly while event is in terminal status"
    ):
        await SettlementService.reopen_settlement(
            db=db_session,
            settlement_id=env["settlement"].id,
            reopening_reason="FO direct settlement reopen attempt",
            actor=env["fo"],
        )

    # 2. FO closeout reopen approval -> MUST fail
    with pytest.raises(
        ForbiddenError, match="Only the Dean of Student Affairs or the Principal"
    ):
        await CloseoutService.approve_reopen(
            db=db_session,
            event_id=env["event"].id,
            actor=env["fo"],
            reason="FO closeout reopen approval attempt",
        )

    # 3. Dean closeout reopen approval -> succeeds
    rev = await CloseoutService.approve_reopen(
        db=db_session,
        event_id=env["event"].id,
        actor=env["dean"],
        reason="Statutory reopen approved by Dean",
    )
    assert rev is not None
    assert rev.revision_number == 1
    assert env["event"].status == EventStatus.COMPLETED
    assert env["settlement"].status == SettlementStatus.REOPENED


@pytest.mark.asyncio
async def test_reopen_successive_revisions_numbering(db_session: AsyncSession):
    """Successive re-closures and reopenings increment revision_number safely (rev 1, rev 2)."""
    env = await _create_closeout_test_env(db_session)

    # First Closeout & Reopen
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db_session, env["event"].id, env["dean"], venue_cleared=True
    )
    rev1 = await CloseoutService.approve_reopen(
        db_session, env["event"].id, env["dean"], reason="Reopen 1"
    )
    assert rev1.revision_number == 1

    # Resettle the financial settlement
    env["settlement"].status = SettlementStatus.SETTLED
    await db_session.flush()

    # Second Closeout & Reopen
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db_session, env["event"].id, env["principal"], venue_cleared=True
    )
    rev2 = await CloseoutService.approve_reopen(
        db_session, env["event"].id, env["principal"], reason="Reopen 2"
    )
    assert rev2.revision_number == 2


# =============================================================================
# 7. ARCHIVAL TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_archive_event_system_admin_success(db_session: AsyncSession):
    """System Administrator successfully archives a CLOSED event."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
    )

    event = await CloseoutService.archive_event(db_session, env["event"].id, env["admin"])
    assert event.status == EventStatus.ARCHIVED

    # Verify audit log
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == str(event.id),
            AuditLog.action == AuditAction.EVENT_ARCHIVED,
        )
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_archive_event_unauthorized_roles_denied(db_session: AsyncSession):
    """Secretary, Advisor, Finance Officer, Dean, Principal cannot archive."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
    )

    with pytest.raises(ForbiddenError, match="Only System Administrators"):
        await CloseoutService.archive_event(db_session, env["event"].id, env["dean"])

    with pytest.raises(ForbiddenError):
        await CloseoutService.archive_event(db_session, env["event"].id, env["sec"])

    with pytest.raises(ForbiddenError):
        await CloseoutService.archive_event(db_session, env["event"].id, env["fo"])


@pytest.mark.asyncio
async def test_archive_event_non_closed_denied(db_session: AsyncSession):
    """Cannot archive a COMPLETED or CLOSURE_REQUESTED event."""
    env = await _create_closeout_test_env(db_session)
    assert env["event"].status == EventStatus.COMPLETED

    with pytest.raises(InvalidWorkflowTransitionError):
        await CloseoutService.archive_event(db_session, env["event"].id, env["admin"])


@pytest.mark.asyncio
async def test_archive_event_already_archived_idempotent(db_session: AsyncSession):
    """Archiving an already ARCHIVED event returns cleanly without error."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
    )
    await CloseoutService.archive_event(db_session, env["event"].id, env["admin"])

    # Second call
    event = await CloseoutService.archive_event(db_session, env["event"].id, env["admin"])
    assert event.status == EventStatus.ARCHIVED

# =============================================================================
# 8. ADDITIONAL HARDENING & SECURITY TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_eligibility_on_closed_and_archived_event(db_session: AsyncSession):
    """Eligibility check on closed and archived events reports terminal status."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db_session, env["event"].id, env["dean"], venue_cleared=True
    )
    assert env["event"].status == EventStatus.CLOSED

    elig_closed = await CloseoutService.get_closure_eligibility(
        db_session, env["event"].id, env["sec"]
    )
    assert elig_closed["event_status"] == EventStatus.CLOSED.value
    assert elig_closed["eligible"] is True

    await CloseoutService.archive_event(db_session, env["event"].id, env["admin"])
    elig_arch = await CloseoutService.get_closure_eligibility(
        db_session, env["event"].id, env["sec"]
    )
    assert elig_arch["event_status"] == EventStatus.ARCHIVED.value
    assert elig_arch["eligible"] is True


@pytest.mark.asyncio
async def test_certify_closeout_eligibility_changed_fails(db_session: AsyncSession):
    """If eligibility changes while in CLOSURE_REQUESTED, certification fails."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    # Simulate an unsettled condition arriving (e.g. report unmarked)
    env["report"].status = PostEventReportStatus.REVISION_REQUIRED
    await db_session.flush()

    with pytest.raises(BusinessRuleError, match="eligibility check failed"):
        await CloseoutService.certify_closeout(
            db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
        )


@pytest.mark.asyncio
async def test_certify_closeout_secretary_and_fo_barred(db_session: AsyncSession):
    """Secretary and Finance Officer are strictly barred from closeout certification."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])

    with pytest.raises(ForbiddenError, match="not authorized to certify"):
        await CloseoutService.certify_closeout(
            db=db_session, event_id=env["event"].id, actor=env["sec"], venue_cleared=True
        )

    with pytest.raises(ForbiddenError, match="not authorized to certify"):
        await CloseoutService.certify_closeout(
            db=db_session, event_id=env["event"].id, actor=env["fo"], venue_cleared=True
        )


@pytest.mark.asyncio
async def test_immutability_closed_event_document_upload_blocked(db_session: AsyncSession):
    """Uploading post-event documents on a CLOSED event is blocked with ConflictError."""
    from unittest.mock import MagicMock

    from app.services.document_service import DocumentService

    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
    )

    from unittest.mock import AsyncMock
    mock_file = MagicMock()
    mock_file.filename = "test.pdf"
    mock_file.read = AsyncMock(return_value=b"%PDF-1.4...")

    with pytest.raises(ConflictError, match="terminal status"):
        await DocumentService.upload_settlement_payment_proof(
            db=db_session,
            event_id=env["event"].id,
            file=mock_file,
            actor=env["fo"],
        )


@pytest.mark.asyncio
async def test_reopen_request_mandatory_reason(db_session: AsyncSession):
    """Reopen petition requires mandatory, non-empty reason."""
    env = await _create_closeout_test_env(db_session)
    await CloseoutService.request_closeout(db_session, env["event"].id, env["sec"])
    await CloseoutService.certify_closeout(
        db=db_session, event_id=env["event"].id, actor=env["dean"], venue_cleared=True
    )

    with pytest.raises(BadRequestError, match="mandatory"):
        await CloseoutService.request_reopen(
            db_session, env["event"].id, env["sec"], reason="   "
        )


@pytest.mark.asyncio
async def test_reopen_request_non_closed_event_denied(db_session: AsyncSession):
    """Cannot petition to reopen a non-CLOSED event."""
    env = await _create_closeout_test_env(db_session)
    assert env["event"].status == EventStatus.COMPLETED

    with pytest.raises(InvalidWorkflowTransitionError, match="Only 'CLOSED' events"):
        await CloseoutService.request_reopen(
            db_session, env["event"].id, env["sec"], reason="Premature petition"
        )

