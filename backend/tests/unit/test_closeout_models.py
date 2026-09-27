"""CampusConnect - Phase 2.4.1 Event Closeout & Archival Model & Schema Tests.

Validates:
1. EventStatus accepts CLOSURE_REQUESTED, CLOSED, and ARCHIVED.
2. NotificationType accepts closeout notification values.
3. AuditAction accepts closeout and archival enum values.
4. EventClosure persistence, defaults, and foreign keys.
5. EventClosure event_id uniqueness constraint.
6. EventClosure settlement_id uniqueness constraint.
7. EventClosure venue_cleared default is False (strictly not True).
8. EventClosureRevision persistence and JSONB snapshot storage.
9. EventClosureRevision (event_id, revision_number) uniqueness constraint.
10. Model relationships between Event, EventClosure, and EventClosureRevision.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    Club,
    ClubMember,
    Event,
    EventClosure,
    EventClosureRevision,
    EventRequest,
    EventRequestVersion,
    FinancialSettlement,
    PostEventReport,
    User,
)
from app.models.enums import (
    AuditAction,
    ClubMemberRole,
    EventStatus,
    EventType,
    NotificationType,
    PostEventReportStatus,
    SettlementStatus,
    SettlementType,
    UserRole,
)


def test_event_status_enum_values():
    """Verify EventStatus contains CLOSURE_REQUESTED, CLOSED, and ARCHIVED."""
    assert EventStatus.CLOSURE_REQUESTED.value == "CLOSURE_REQUESTED"
    assert EventStatus.CLOSED.value == "CLOSED"
    assert EventStatus.ARCHIVED.value == "ARCHIVED"
    assert EventStatus.SCHEDULED.value == "SCHEDULED"
    assert EventStatus.IN_PROGRESS.value == "IN_PROGRESS"
    assert EventStatus.COMPLETED.value == "COMPLETED"


def test_audit_action_and_notification_enums():
    """Verify Phase 2.4 AuditAction and NotificationType enums."""
    assert AuditAction.CLOSURE_REQUESTED.value == "CLOSURE_REQUESTED"
    assert AuditAction.CLOSURE_REJECTED.value == "CLOSURE_REJECTED"
    assert AuditAction.EVENT_CLOSED.value == "EVENT_CLOSED"
    assert AuditAction.EVENT_REOPEN_REQUESTED.value == "EVENT_REOPEN_REQUESTED"
    assert AuditAction.EVENT_REOPENED.value == "EVENT_REOPENED"
    assert AuditAction.EVENT_ARCHIVED.value == "EVENT_ARCHIVED"

    assert NotificationType.EVENT_CLOSURE_REQUESTED.value == "EVENT_CLOSURE_REQUESTED"
    assert NotificationType.EVENT_CLOSED.value == "EVENT_CLOSED"
    assert NotificationType.EVENT_CLOSURE_REJECTED.value == "EVENT_CLOSURE_REJECTED"
    assert NotificationType.EVENT_REOPENED.value == "EVENT_REOPENED"


def test_model_relationship_mappings():
    """Verify SQLAlchemy relationships for EventClosure and EventClosureRevision."""
    event_mapper = inspect(Event)
    assert "closure" in event_mapper.relationships
    assert not event_mapper.relationships["closure"].uselist

    closure_mapper = inspect(EventClosure)
    assert "event" in closure_mapper.relationships
    assert "settlement" in closure_mapper.relationships
    assert "post_event_report" in closure_mapper.relationships
    assert "revisions" in closure_mapper.relationships
    assert closure_mapper.relationships["revisions"].uselist

    rev_mapper = inspect(EventClosureRevision)
    assert "event" in rev_mapper.relationships
    assert "closure" in rev_mapper.relationships


async def _assemble_test_event_with_settlement(db: AsyncSession) -> dict[str, Any]:
    """Helper to assemble a valid completed event with certified report and settled settlement."""
    uid = uuid.uuid4().hex[:6]
    now = datetime.now(UTC)

    sec = User(
        id=uuid.uuid4(),
        email=f"sec_{uid}@college.edu",
        password_hash="hash",
        full_name=f"Secretary {uid}",
        role=UserRole.CLUB_SECRETARY,
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
    fo = User(
        id=uuid.uuid4(),
        email=f"fo_{uid}@college.edu",
        password_hash="hash",
        full_name=f"FO {uid}",
        role=UserRole.FINANCE_OFFICER,
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
    db.add_all([sec, dean, fo, advisor])
    await db.flush()

    club = Club(
        id=uuid.uuid4(),
        name=f"Club {uid}",
        slug=f"club-{uid}",
        academic_year="2026-27",
        created_by=dean.id,
        is_active=True,
    )
    db.add(club)
    await db.flush()

    db.add(
        ClubMember(
            club_id=club.id,
            user_id=sec.id,
            member_role=ClubMemberRole.SECRETARY,
            is_active=True,
        )
    )
    await db.flush()

    req = EventRequest(
        id=uuid.uuid4(),
        club_id=club.id,
        title=f"Closeout Test Event {uid}",
        event_type=EventType.WORKSHOP,
        event_date=now,
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
        snapshot={"title": req.title},
        submitted_by=sec.id,
    )
    db.add(ver)
    await db.flush()

    event = Event(
        id=uuid.uuid4(),
        event_request_id=req.id,
        approved_version_id=ver.id,
        club_id=club.id,
        title=f"Closeout Test Event {uid}",
        event_type=EventType.WORKSHOP,
        event_date=now,
        start_time=now,
        end_time=now + timedelta(hours=2),
        status=EventStatus.COMPLETED,
        academic_year="2026-27",
    )
    db.add(event)
    await db.flush()

    report = PostEventReport(
        id=uuid.uuid4(),
        event_id=event.id,
        revision_number=1,
        actual_attendance=100,
        summary="Completed successfully",
        objectives_achieved="Met all objectives",
        status=PostEventReportStatus.CERTIFIED,
        submitted_by=sec.id,
        submitted_at=now,
        certified_by=advisor.id,
        certified_at=now,
    )
    db.add(report)
    await db.flush()

    settlement = FinancialSettlement(
        id=uuid.uuid4(),
        event_id=event.id,
        approved_version_id=ver.id,
        sanctioned_grant=Decimal("20000.00"),
        sanctioned_expenditure=Decimal("20000.00"),
        expected_income=Decimal("0.00"),
        total_claimed_expenditure=Decimal("18000.00"),
        total_verified_expenditure=Decimal("18000.00"),
        total_disallowed_expenditure=Decimal("0.00"),
        total_verified_income=Decimal("0.00"),
        net_deficit=Decimal("18000.00"),
        institutional_payout=Decimal("18000.00"),
        cash_advance_disbursed=Decimal("18000.00"),
        settlement_balance=Decimal("0.00"),
        reimbursement_due=Decimal("0.00"),
        refund_due=Decimal("0.00"),
        settlement_type=SettlementType.BALANCED,
        status=SettlementStatus.SETTLED,
        prepared_by=sec.id,
        submitted_at=now,
        audited_by=fo.id,
        audited_at=now,
    )
    db.add(settlement)
    await db.flush()

    return {
        "sec": sec,
        "dean": dean,
        "fo": fo,
        "advisor": advisor,
        "event": event,
        "report": report,
        "settlement": settlement,
    }


@pytest.mark.asyncio
async def test_event_closure_persistence_and_defaults(db_session: AsyncSession):
    """Verify EventClosure persistence, foreign keys, and venue_cleared default False."""
    env = await _assemble_test_event_with_settlement(db_session)
    now = datetime.now(UTC)

    manifest_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    closure = EventClosure(
        id=uuid.uuid4(),
        event_id=env["event"].id,
        settlement_id=env["settlement"].id,
        post_event_report_id=env["report"].id,
        requested_by=env["sec"].id,
        requested_at=now,
        certified_by=env["dean"].id,
        certified_at=now,
        closure_notes="Event audited and certified closed by Dean.",
        certificate_manifest_hash=manifest_hash,
    )
    db_session.add(closure)
    await db_session.flush()

    # Verify default is False
    assert closure.venue_cleared is False
    assert closure.event_id == env["event"].id
    assert closure.settlement_id == env["settlement"].id
    assert closure.certified_by == env["dean"].id
    assert closure.certificate_manifest_hash == manifest_hash


@pytest.mark.asyncio
async def test_event_closure_event_id_uniqueness(db_session: AsyncSession):
    """Verify unique constraint on event_closures.event_id."""
    env = await _assemble_test_event_with_settlement(db_session)
    now = datetime.now(UTC)

    closure1 = EventClosure(
        id=uuid.uuid4(),
        event_id=env["event"].id,
        settlement_id=env["settlement"].id,
        post_event_report_id=env["report"].id,
        certified_by=env["dean"].id,
        certified_at=now,
        certificate_manifest_hash="a" * 64,
    )
    db_session.add(closure1)
    await db_session.flush()

    # Second closure for same event must fail unique constraint
    closure2 = EventClosure(
        id=uuid.uuid4(),
        event_id=env["event"].id,
        settlement_id=uuid.uuid4(),
        post_event_report_id=env["report"].id,
        certified_by=env["dean"].id,
        certified_at=now,
        certificate_manifest_hash="b" * 64,
    )
    db_session.add(closure2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_event_closure_settlement_id_uniqueness(db_session: AsyncSession):
    """Verify unique constraint on event_closures.settlement_id."""
    env1 = await _assemble_test_event_with_settlement(db_session)
    env2 = await _assemble_test_event_with_settlement(db_session)
    now = datetime.now(UTC)

    closure1 = EventClosure(
        id=uuid.uuid4(),
        event_id=env1["event"].id,
        settlement_id=env1["settlement"].id,
        post_event_report_id=env1["report"].id,
        certified_by=env1["dean"].id,
        certified_at=now,
        certificate_manifest_hash="a" * 64,
    )
    db_session.add(closure1)
    await db_session.flush()

    # Attempt to associate same settlement_id with another event
    closure2 = EventClosure(
        id=uuid.uuid4(),
        event_id=env2["event"].id,
        settlement_id=env1["settlement"].id,  # duplicate settlement_id
        post_event_report_id=env2["report"].id,
        certified_by=env2["dean"].id,
        certified_at=now,
        certificate_manifest_hash="b" * 64,
    )
    db_session.add(closure2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_event_closure_revision_persistence_and_snapshot(db_session: AsyncSession):
    """Verify EventClosureRevision persists JSONB snapshot_data and enforces uniqueness."""
    env = await _assemble_test_event_with_settlement(db_session)
    now = datetime.now(UTC)

    closure = EventClosure(
        id=uuid.uuid4(),
        event_id=env["event"].id,
        settlement_id=env["settlement"].id,
        post_event_report_id=env["report"].id,
        certified_by=env["dean"].id,
        certified_at=now,
        certificate_manifest_hash="c" * 64,
    )
    db_session.add(closure)
    await db_session.flush()

    snapshot = {
        "event_id": str(env["event"].id),
        "status": "CLOSED",
        "settlement_total": "18000.00",
        "metadata": {"closure_notes": "Sample note"},
    }

    rev1 = EventClosureRevision(
        id=uuid.uuid4(),
        event_id=env["event"].id,
        closure_id=closure.id,
        revision_number=1,
        reopened_by=env["dean"].id,
        reopened_at=now,
        reopening_reason="Statutory auditor requested recalculation of vendor bill",
        snapshot_data=snapshot,
    )
    db_session.add(rev1)
    await db_session.flush()

    assert rev1.revision_number == 1
    assert rev1.snapshot_data["status"] == "CLOSED"
    assert rev1.snapshot_data["settlement_total"] == "18000.00"

    # Attempt to insert duplicate revision_number for same event_id
    rev_duplicate = EventClosureRevision(
        id=uuid.uuid4(),
        event_id=env["event"].id,
        closure_id=closure.id,
        revision_number=1,  # Duplicate revision number
        reopened_by=env["dean"].id,
        reopened_at=now,
        reopening_reason="Another reason",
        snapshot_data=snapshot,
    )
    db_session.add(rev_duplicate)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
