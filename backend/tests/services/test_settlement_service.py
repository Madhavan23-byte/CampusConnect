"""
CampusConnect - Phase 2.3 Financial Settlement Service Test Suite

Comprehensive tests for:
A. Authoritative Accounting Engine (Decimal formulas, caps, locked cases 1-4)
B. Expense Integration (Status handling, verification amounts, unresolved gates)
C. Actual Income Ledger (Evidence check, SOD, self-verification prevention)
D. Cash Advance Lifecycle (Req/App/Disb/Rej, single advance invariant, caps)
E. Settlement Lifecycle (Prep, submit, query, resubmit, stale data protection)
F. Payment Clearance (Directional enforcement, overpayment block, full clearing)
G. Reopening & Revisions (Snapshot preservation, revision increment, role guards)
H. Closure Eligibility (Read-only check, blocker codes, no CLOSED status)
I. Segregation of Duties & Security (Cross-club, Admin bar, SOD matrix)
J. Concurrency & Integrity (Duplicate creation safety, payment locking)
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestError,
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    InvalidWorkflowTransitionError,
)
from app.models.domain import (
    ActualExpense,
    AuditLog,
    Club,
    ClubMember,
    Document,
    Event,
    EventRequest,
    EventRequestVersion,
    PostEventReport,
    SettlementPayment,
    User,
)
from app.models.enums import (
    ActualExpenseStatus,
    ActualIncomeStatus,
    AuditAction,
    BudgetLineItemCategory,
    CashAdvanceStatus,
    ClubMemberRole,
    DocumentType,
    EventStatus,
    EventType,
    IncomeSourceType,
    PaymentMethod,
    PostEventReportStatus,
    SettlementPaymentType,
    SettlementStatus,
    SettlementType,
    UserRole,
)
from app.services.settlement_service import SettlementService, SettlementStaleDataError

# =============================================================================
# FIXTURES & HELPERS
# =============================================================================


async def _create_test_environment(
    db: AsyncSession,
    sanctioned_grant: Decimal = Decimal("30000.00"),
    sanctioned_exp: Decimal = Decimal("35000.00"),
    expected_inc: Decimal = Decimal("5000.00"),
) -> dict[str, Any]:
    """Helper to assemble a valid, confirmed, completed, and certified event."""
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
    advisor = User(
        id=uuid.uuid4(),
        email=f"adv_{uid}@college.edu",
        password_hash="hash",
        full_name=f"Advisor {uid}",
        role=UserRole.FACULTY_ADVISOR,
        is_active=True,
    )
    db.add_all([sec, other_sec, fo, admin, principal, advisor])
    await db.flush()

    club = Club(
        id=uuid.uuid4(),
        name=f"Tech Club {uid}",
        slug=f"tech-{uid}",
        academic_year="2026-27",
        created_by=admin.id,
        is_active=True,
    )
    other_club = Club(
        id=uuid.uuid4(),
        name=f"Arts Club {uid}",
        slug=f"arts-{uid}",
        academic_year="2026-27",
        created_by=admin.id,
        is_active=True,
    )
    db.add_all([club, other_club])
    await db.flush()

    db.add(
        ClubMember(
            club_id=club.id, user_id=sec.id, member_role=ClubMemberRole.SECRETARY, is_active=True
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

    now = datetime.now(UTC)
    req = EventRequest(
        id=uuid.uuid4(),
        club_id=club.id,
        title=f"Workshop {uid}",
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
        snapshot={
            "title": f"Workshop {uid}",
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
        title=f"Workshop {uid}",
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
        actual_attendance=150,
        summary="Event delivered successfully",
        objectives_achieved="All objectives achieved",
        status=PostEventReportStatus.CERTIFIED,
        submitted_by=sec.id,
        submitted_at=now,
        certified_by=advisor.id,
        certified_at=now,
        certification_remarks="Certified by advisor",
    )
    db.add(report)
    await db.flush()

    return {
        "sec": sec,
        "other_sec": other_sec,
        "fo": fo,
        "admin": admin,
        "principal": principal,
        "advisor": advisor,
        "club": club,
        "other_club": other_club,
        "req": req,
        "ver": ver,
        "event": event,
        "report": report,
        "sanctioned_grant": sanctioned_grant,
    }


async def _create_test_document(
    db: AsyncSession,
    event: Event,
    uploaded_by: User,
    doc_type: DocumentType = DocumentType.INCOME_EVIDENCE,
) -> Document:
    """Helper to create a test document record."""
    doc = Document(
        id=uuid.uuid4(),
        event_request_id=event.event_request_id,
        event_id=event.id,
        uploaded_by=uploaded_by.id,
        document_type=doc_type.value,
        original_filename="test_proof.pdf",
        stored_filename=f"doc_{uuid.uuid4().hex}.pdf",
        file_size_bytes=1024,
        mime_type="application/pdf",
        storage_path="/storage/test_proof.pdf",
        is_active=True,
    )
    db.add(doc)
    await db.flush()
    return doc


async def _add_test_expense(
    db: AsyncSession,
    event: Event,
    submitted_by: User,
    claimed: Decimal,
    verified: Decimal | None,
    status: ActualExpenseStatus,
) -> ActualExpense:
    """Helper to attach an ActualExpense to the event."""
    doc = await _create_test_document(db, event, submitted_by, DocumentType.EXPENSE_INVOICE)
    exp = ActualExpense(
        id=uuid.uuid4(),
        event_id=event.id,
        category=BudgetLineItemCategory.MATERIALS,
        description="Event supplies",
        vendor_name="Acme Hardware",
        invoice_date=date.today(),
        claimed_amount=claimed,
        verified_amount=verified,
        status=status,
        bill_document_id=doc.id,
        submitted_by=submitted_by.id,
    )
    db.add(exp)
    await db.flush()
    return exp


# =============================================================================
# A. ACCOUNTING ENGINE TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_accounting_case_1(db_session: AsyncSession):
    """
    Case 1 from Locked Institutional Spec:
    G = 30000, V = 40000, I = 0, A = 20000
    NetDeficit = max(0, 40000 - 0) = 40000
    P = min(30000, 40000) = 30000
    B = 30000 - 20000 = 10000
    Expected: REIMBURSEMENT_DUE = 10000.
    """
    env = await _create_test_environment(db_session, sanctioned_grant=Decimal("30000.00"))
    event = env["event"]

    # Add verified expense: V = 40000
    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("40000.00"),
        Decimal("40000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    # Disburse advance: A = 20000
    adv = await SettlementService.request_advance(
        db_session, event.id, Decimal("20000.00"), "Setup", env["sec"]
    )
    await SettlementService.approve_advance(db_session, adv.id, Decimal("20000.00"), env["fo"])
    await SettlementService.disburse_advance(
        db_session, adv.id, Decimal("20000.00"), "NEFT-001", datetime.now(UTC), env["fo"]
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])

    assert settlement.sanctioned_grant == Decimal("30000.00")
    assert settlement.total_verified_expenditure == Decimal("40000.00")
    assert settlement.total_verified_income == Decimal("0.00")
    assert settlement.cash_advance_disbursed == Decimal("20000.00")
    assert settlement.net_deficit == Decimal("40000.00")
    assert settlement.institutional_payout == Decimal("30000.00")
    assert settlement.settlement_balance == Decimal("10000.00")
    assert settlement.reimbursement_due == Decimal("10000.00")
    assert settlement.refund_due == Decimal("0.00")
    assert settlement.settlement_type == SettlementType.REIMBURSEMENT_DUE


@pytest.mark.asyncio
async def test_accounting_case_2(db_session: AsyncSession):
    """
    Case 2 from Locked Institutional Spec:
    G = 30000, V = 20000, I = 0, A = 25000
    NetDeficit = 20000
    P = min(30000, 20000) = 20000
    B = 20000 - 25000 = -5000
    Expected: REFUND_DUE = 5000.
    """
    env = await _create_test_environment(db_session, sanctioned_grant=Decimal("30000.00"))
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("20000.00"),
        Decimal("20000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    adv = await SettlementService.request_advance(
        db_session, event.id, Decimal("25000.00"), "Setup", env["sec"]
    )
    await SettlementService.approve_advance(db_session, adv.id, Decimal("25000.00"), env["fo"])
    await SettlementService.disburse_advance(
        db_session, adv.id, Decimal("25000.00"), "NEFT-002", datetime.now(UTC), env["fo"]
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])

    assert settlement.institutional_payout == Decimal("20000.00")
    assert settlement.settlement_balance == Decimal("-5000.00")
    assert settlement.reimbursement_due == Decimal("0.00")
    assert settlement.refund_due == Decimal("5000.00")
    assert settlement.settlement_type == SettlementType.REFUND_DUE


@pytest.mark.asyncio
async def test_accounting_case_3(db_session: AsyncSession):
    """
    Case 3 from Locked Institutional Spec:
    G = 30000, V = 20000, I = 5000, A = 15000
    NetDeficit = max(0, 20000 - 5000) = 15000
    P = min(30000, 15000) = 15000
    B = 15000 - 15000 = 0
    Expected: BALANCED (No zero-value payment required).
    """
    env = await _create_test_environment(db_session, sanctioned_grant=Decimal("30000.00"))
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("20000.00"),
        Decimal("20000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    # Record and verify income: I = 5000
    inc_doc = await _create_test_document(
        db_session, event, env["sec"], DocumentType.INCOME_EVIDENCE
    )
    inc = await SettlementService.record_income(
        db_session,
        event.id,
        IncomeSourceType.REGISTRATION_FEE,
        Decimal("5000.00"),
        "Registration",
        "Students",
        date.today(),
        inc_doc.id,
        env["sec"],
    )
    await SettlementService.verify_income(db_session, inc.id, env["fo"])

    # Disburse advance: A = 15000
    adv = await SettlementService.request_advance(
        db_session, event.id, Decimal("15000.00"), "Materials", env["sec"]
    )
    await SettlementService.approve_advance(db_session, adv.id, Decimal("15000.00"), env["fo"])
    await SettlementService.disburse_advance(
        db_session, adv.id, Decimal("15000.00"), "NEFT-003", datetime.now(UTC), env["fo"]
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])

    assert settlement.net_deficit == Decimal("15000.00")
    assert settlement.institutional_payout == Decimal("15000.00")
    assert settlement.settlement_balance == Decimal("0.00")
    assert settlement.reimbursement_due == Decimal("0.00")
    assert settlement.refund_due == Decimal("0.00")
    assert settlement.settlement_type == SettlementType.BALANCED


@pytest.mark.asyncio
async def test_accounting_case_4_partial_expense(db_session: AsyncSession):
    """
    Case 4: Claimed = 10000, Verified = 6000.
    V contribution MUST be 6000, NOT 10000.
    Disallowed contribution = 4000.
    """
    env = await _create_test_environment(db_session, sanctioned_grant=Decimal("30000.00"))
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("6000.00"),
        ActualExpenseStatus.PARTIALLY_VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])

    assert settlement.total_claimed_expenditure == Decimal("10000.00")
    assert settlement.total_verified_expenditure == Decimal("6000.00")
    assert settlement.total_disallowed_expenditure == Decimal("4000.00")
    assert settlement.institutional_payout == Decimal("6000.00")


@pytest.mark.asyncio
async def test_accounting_surplus_income_exceeds_expenditure(db_session: AsyncSession):
    """
    Income exceeds expenditure: V = 10000, I = 15000, G = 20000, A = 2000.
    NetDeficit = max(0, 10000 - 15000) = 0.
    P = min(20000, 0) = 0.
    B = 0 - 2000 = -2000 -> REFUND_DUE = 2000.
    """
    env = await _create_test_environment(db_session, sanctioned_grant=Decimal("20000.00"))
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    inc_doc = await _create_test_document(
        db_session, event, env["sec"], DocumentType.INCOME_EVIDENCE
    )
    inc = await SettlementService.record_income(
        db_session,
        event.id,
        IncomeSourceType.SPONSORSHIP,
        Decimal("15000.00"),
        "Sponsorship",
        "Sponsor Corp",
        date.today(),
        inc_doc.id,
        env["sec"],
    )
    await SettlementService.verify_income(db_session, inc.id, env["fo"])

    adv = await SettlementService.request_advance(
        db_session, event.id, Decimal("2000.00"), "Advance", env["sec"]
    )
    await SettlementService.approve_advance(db_session, adv.id, Decimal("2000.00"), env["fo"])
    await SettlementService.disburse_advance(
        db_session, adv.id, Decimal("2000.00"), "NEFT-SURPLUS", datetime.now(UTC), env["fo"]
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])

    assert settlement.net_deficit == Decimal("0.00")
    assert settlement.institutional_payout == Decimal("0.00")
    assert settlement.settlement_balance == Decimal("-2000.00")
    assert settlement.refund_due == Decimal("2000.00")
    assert settlement.settlement_type == SettlementType.REFUND_DUE


@pytest.mark.asyncio
async def test_accounting_decimal_precision(db_session: AsyncSession):
    """Monetary calculations must retain exact 2-decimal precision without rounding drift."""
    env = await _create_test_environment(db_session, sanctioned_grant=Decimal("10000.00"))
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("1234.56"),
        Decimal("1234.56"),
        ActualExpenseStatus.VERIFIED,
    )
    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("765.43"),
        Decimal("765.43"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    # 1234.56 + 765.43 = 1999.99
    assert settlement.total_verified_expenditure == Decimal("1999.99")
    assert settlement.institutional_payout == Decimal("1999.99")
    assert settlement.reimbursement_due == Decimal("1999.99")


# =============================================================================
# B. EXPENSE INTEGRATION & UNRESOLVED EXPENSE GATE
# =============================================================================


@pytest.mark.asyncio
async def test_unresolved_draft_expense_blocks_settlement(db_session: AsyncSession):
    """Settlement preparation must fail if any expense claim is in DRAFT status."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session, event, env["sec"], Decimal("500.00"), None, ActualExpenseStatus.DRAFT
    )

    with pytest.raises(BusinessRuleError) as exc:
        await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert "DRAFT" in str(exc.value)


@pytest.mark.asyncio
async def test_unresolved_submitted_expense_blocks_settlement(db_session: AsyncSession):
    """Settlement preparation must fail if any expense claim is in SUBMITTED status."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session, event, env["sec"], Decimal("500.00"), None, ActualExpenseStatus.SUBMITTED
    )

    with pytest.raises(BusinessRuleError) as exc:
        await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert "SUBMITTED" in str(exc.value)


@pytest.mark.asyncio
async def test_unresolved_queried_expense_blocks_settlement(db_session: AsyncSession):
    """Settlement preparation must fail if any expense claim is in QUERIED status."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session, event, env["sec"], Decimal("500.00"), None, ActualExpenseStatus.QUERIED
    )

    with pytest.raises(BusinessRuleError) as exc:
        await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert "QUERIED" in str(exc.value)


@pytest.mark.asyncio
async def test_disallowed_expense_excluded_from_verified_total(db_session: AsyncSession):
    """Disallowed expenses contribute 0 to verified and count to total_disallowed."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("5000.00"),
        Decimal("0.00"),
        ActualExpenseStatus.DISALLOWED,
    )
    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("3000.00"),
        Decimal("3000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert settlement.total_claimed_expenditure == Decimal("8000.00")
    assert settlement.total_verified_expenditure == Decimal("3000.00")
    assert settlement.total_disallowed_expenditure == Decimal("5000.00")


# =============================================================================
# C. ACTUAL INCOME LEDGER TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_unverified_recorded_income_blocks_settlement(db_session: AsyncSession):
    """Settlement preparation must fail if any income entry is still in RECORDED status."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    doc = await _create_test_document(db_session, event, env["sec"], DocumentType.INCOME_EVIDENCE)
    await SettlementService.record_income(
        db_session,
        event.id,
        IncomeSourceType.TICKET_SALES,
        Decimal("1000.00"),
        "Tickets",
        "Public",
        date.today(),
        doc.id,
        env["sec"],
    )

    with pytest.raises(BusinessRuleError) as exc:
        await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert "RECORDED" in str(exc.value)


@pytest.mark.asyncio
async def test_income_secretary_cannot_self_verify(db_session: AsyncSession):
    """Secretary who recorded income cannot self-verify it (Segregation of Duties)."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    doc = await _create_test_document(db_session, event, env["sec"], DocumentType.INCOME_EVIDENCE)
    inc = await SettlementService.record_income(
        db_session,
        event.id,
        IncomeSourceType.DONATION,
        Decimal("2000.00"),
        "Donation",
        "Alumni",
        date.today(),
        doc.id,
        env["sec"],
    )

    with pytest.raises(ForbiddenError):
        await SettlementService.verify_income(db_session, inc.id, env["sec"])


@pytest.mark.asyncio
async def test_income_system_admin_cannot_verify(db_session: AsyncSession):
    """System Administrator cannot verify income."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    doc = await _create_test_document(db_session, event, env["sec"], DocumentType.INCOME_EVIDENCE)
    inc = await SettlementService.record_income(
        db_session,
        event.id,
        IncomeSourceType.DONATION,
        Decimal("2000.00"),
        "Donation",
        "Alumni",
        date.today(),
        doc.id,
        env["sec"],
    )

    with pytest.raises(ForbiddenError) as exc:
        await SettlementService.verify_income(db_session, inc.id, env["admin"])
    assert "System administrators" in str(exc.value)


@pytest.mark.asyncio
async def test_income_cross_event_evidence_rejected(db_session: AsyncSession):
    """Evidence document from another event must be strictly rejected."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    # Create another event
    env2 = await _create_test_environment(db_session)
    event2 = env2["event"]

    # Document belongs to event2
    doc_other = await _create_test_document(
        db_session, event2, env2["sec"], DocumentType.INCOME_EVIDENCE
    )

    with pytest.raises(BadRequestError) as exc:
        await SettlementService.record_income(
            db_session,
            event.id,
            IncomeSourceType.STALL_RENTAL,
            Decimal("1500.00"),
            "Stall",
            "Vendor",
            date.today(),
            doc_other.id,
            env["sec"],
        )
    assert "does not belong to this event" in str(exc.value)


@pytest.mark.asyncio
async def test_income_invalid_document_type_rejected(db_session: AsyncSession):
    """Document must be of type INCOME_EVIDENCE."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    # Create document with wrong type (EXPENSE_INVOICE)
    doc_wrong = await _create_test_document(
        db_session, event, env["sec"], DocumentType.EXPENSE_INVOICE
    )

    with pytest.raises(BadRequestError) as exc:
        await SettlementService.record_income(
            db_session,
            event.id,
            IncomeSourceType.STALL_RENTAL,
            Decimal("1500.00"),
            "Stall",
            "Vendor",
            date.today(),
            doc_wrong.id,
            env["sec"],
        )
    assert "INCOME_EVIDENCE" in str(exc.value)


@pytest.mark.asyncio
async def test_income_reject_flow(db_session: AsyncSession):
    """Finance Officer can reject income with mandatory reason."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    doc = await _create_test_document(db_session, event, env["sec"], DocumentType.INCOME_EVIDENCE)
    inc = await SettlementService.record_income(
        db_session,
        event.id,
        IncomeSourceType.OTHER,
        Decimal("500.00"),
        "Cash pool",
        "Unknown",
        date.today(),
        doc.id,
        env["sec"],
    )

    # Empty reason fails
    with pytest.raises(BadRequestError):
        await SettlementService.reject_income(db_session, inc.id, "", env["fo"])

    rejected_inc = await SettlementService.reject_income(
        db_session, inc.id, "Missing bank deposit voucher", env["fo"]
    )
    assert rejected_inc.status == ActualIncomeStatus.REJECTED


# =============================================================================
# D. CASH ADVANCE LIFECYCLE TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_advance_full_lifecycle(db_session: AsyncSession):
    """Full lifecycle: REQUESTED -> APPROVED -> DISBURSED with audit logs."""
    env = await _create_test_environment(db_session, sanctioned_grant=Decimal("20000.00"))
    event = env["event"]

    # 1. Request
    adv = await SettlementService.request_advance(
        db_session, event.id, Decimal("10000.00"), "Stage advance", env["sec"]
    )
    assert adv.status == CashAdvanceStatus.REQUESTED

    # 2. Approve
    approved_adv = await SettlementService.approve_advance(
        db_session, adv.id, Decimal("10000.00"), env["fo"], "Approved by FO"
    )
    assert approved_adv.status == CashAdvanceStatus.APPROVED
    assert approved_adv.amount_approved == Decimal("10000.00")

    # 3. Disburse
    disbursed_adv = await SettlementService.disburse_advance(
        db_session, adv.id, Decimal("10000.00"), "NEFT-789", datetime.now(UTC), env["fo"]
    )
    assert disbursed_adv.status == CashAdvanceStatus.DISBURSED
    assert disbursed_adv.amount_disbursed == Decimal("10000.00")


@pytest.mark.asyncio
async def test_advance_approval_exceeding_grant_rejected(db_session: AsyncSession):
    """Approved advance cannot exceed the sanctioned institutional grant."""
    env = await _create_test_environment(db_session, sanctioned_grant=Decimal("15000.00"))
    event = env["event"]

    adv = await SettlementService.request_advance(
        db_session, event.id, Decimal("20000.00"), "Big advance", env["sec"]
    )
    with pytest.raises(BusinessRuleError) as exc:
        await SettlementService.approve_advance(db_session, adv.id, Decimal("20000.00"), env["fo"])
    assert "cannot exceed sanctioned" in str(exc.value)


@pytest.mark.asyncio
async def test_advance_partial_disbursement_rejected(db_session: AsyncSession):
    """
    Current CashAdvance state machine does not support partial disbursement.
    Disbursed amount must strictly equal approved amount.
    """
    env = await _create_test_environment(db_session, sanctioned_grant=Decimal("20000.00"))
    event = env["event"]

    adv = await SettlementService.request_advance(
        db_session, event.id, Decimal("10000.00"), "Advance", env["sec"]
    )
    await SettlementService.approve_advance(db_session, adv.id, Decimal("10000.00"), env["fo"])

    # Disbursing 5000 when 10000 was approved must fail
    with pytest.raises(BusinessRuleError) as exc:
        await SettlementService.disburse_advance(
            db_session, adv.id, Decimal("5000.00"), "NEFT-PARTIAL", datetime.now(UTC), env["fo"]
        )
    assert "Partial or excess disbursement not permitted" in str(exc.value)


@pytest.mark.asyncio
async def test_advance_duplicate_request_rejected(db_session: AsyncSession):
    """Only one CashAdvance record allowed per event (1:0..1)."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    await SettlementService.request_advance(
        db_session, event.id, Decimal("5000.00"), "First", env["sec"]
    )
    with pytest.raises(ConflictError):
        await SettlementService.request_advance(
            db_session, event.id, Decimal("5000.00"), "Second", env["sec"]
        )


@pytest.mark.asyncio
async def test_advance_system_admin_blocked(db_session: AsyncSession):
    """System Administrator cannot approve or disburse cash advances."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    adv = await SettlementService.request_advance(
        db_session, event.id, Decimal("5000.00"), "Advance", env["sec"]
    )
    with pytest.raises(ForbiddenError):
        await SettlementService.approve_advance(
            db_session, adv.id, Decimal("5000.00"), env["admin"]
        )


# =============================================================================
# E. SETTLEMENT LIFECYCLE & STALE DATA PROTECTION
# =============================================================================


@pytest.mark.asyncio
async def test_settlement_submission_and_query_flow(db_session: AsyncSession):
    """Secretary submits, FO queries with reason, Secretary amends and resubmits."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert settlement.status == SettlementStatus.DRAFT

    # 1. Submit
    submitted = await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    assert submitted.status == SettlementStatus.UNDER_AUDIT

    # 2. Finance Query
    queried = await SettlementService.audit_settlement(
        db_session,
        settlement.id,
        "QUERY",
        env["fo"],
        remarks="Missing details",
        query_reason="Need clarification on invoice #3",
    )
    assert queried.status == SettlementStatus.QUERIED
    assert queried.query_reason == "Need clarification on invoice #3"

    # 3. Resubmit
    resubmitted = await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    assert resubmitted.status == SettlementStatus.UNDER_AUDIT


@pytest.mark.asyncio
async def test_stale_data_detection_on_audit_approval(db_session: AsyncSession):
    """
    If verified expenses are added or altered after settlement preparation,
    Finance Officer approval must detect the stale data and reject.
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])

    # Simulate retroactive addition/alteration of expense
    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("5000.00"),
        Decimal("5000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    # FO attempts approval -> Stale data detected
    with pytest.raises(SettlementStaleDataError) as exc:
        await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])
    assert "Settlement source data has changed" in str(exc.value)


@pytest.mark.asyncio
async def test_duplicate_settlement_creation_prevented(db_session: AsyncSession):
    """Attempting to prepare a second settlement on the same event must fail."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    await SettlementService.prepare_settlement(db_session, event.id, env["sec"])

    with pytest.raises(ConflictError) as exc:
        await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert "already exists" in str(exc.value)


# =============================================================================
# F. PAYMENT RECORDING & CLEARANCE
# =============================================================================


@pytest.mark.asyncio
async def test_payment_recording_and_clearing_reimbursement(db_session: AsyncSession):
    """
    Reimbursement payment:
    reimbursement_due = 10000.
    1. Partial payment: 6000 -> status remains PENDING_REIMBURSEMENT.
    2. Overpayment attempt: 5000 -> REJECTED (remaining due is 4000).
    3. Exact clearing payment: 4000 -> status transitions to SETTLED.
    """
    env = await _create_test_environment(db_session, sanctioned_grant=Decimal("20000.00"))
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    approved = await SettlementService.audit_settlement(
        db_session, settlement.id, "APPROVE", env["fo"]
    )
    assert approved.status == SettlementStatus.PENDING_REIMBURSEMENT
    assert approved.reimbursement_due == Decimal("10000.00")

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )

    # 1. Partial payment of 6000
    p1 = await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("6000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-PARTIAL",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )
    assert p1.amount == Decimal("6000.00")
    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.PENDING_REIMBURSEMENT

    # 2. Overpayment attempt (5000 > 4000 remaining)
    with pytest.raises(BusinessRuleError) as exc:
        await SettlementService.record_payment(
            db_session,
            settlement.id,
            SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
            Decimal("5000.00"),
            PaymentMethod.BANK_TRANSFER_NEFT,
            "UTR-OVER",
            datetime.now(UTC),
            proof_doc.id,
            env["fo"],
        )
    assert "exceeds remaining balance due" in str(exc.value)

    # 3. Exact final clearing payment of 4000
    p2 = await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("4000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-FINAL",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )
    assert p2.amount == Decimal("4000.00")
    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.SETTLED


@pytest.mark.asyncio
async def test_payment_wrong_direction_rejected(db_session: AsyncSession):
    """Cannot record ADVANCE_REFUND_RECEIPT on a REIMBURSEMENT_DUE settlement."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )
    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )

    with pytest.raises(BusinessRuleError) as exc:
        await SettlementService.record_payment(
            db_session,
            settlement.id,
            SettlementPaymentType.ADVANCE_REFUND_RECEIPT,
            Decimal("1000.00"),
            PaymentMethod.BANK_TRANSFER_NEFT,
            "UTR-WRONG",
            datetime.now(UTC),
            proof_doc.id,
            env["fo"],
        )
    assert "Invalid payment type" in str(exc.value)


@pytest.mark.asyncio
async def test_payment_balanced_settlement_rejects_payments(db_session: AsyncSession):
    """Balanced settlements auto-settle upon approval and permit no payments."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    approved = await SettlementService.audit_settlement(
        db_session, settlement.id, "APPROVE", env["fo"]
    )

    assert approved.status == SettlementStatus.SETTLED
    assert approved.settlement_type == SettlementType.BALANCED

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )

    with pytest.raises(InvalidWorkflowTransitionError):
        await SettlementService.record_payment(
            db_session,
            settlement.id,
            SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
            Decimal("100.00"),
            PaymentMethod.BANK_TRANSFER_NEFT,
            "UTR-NO",
            datetime.now(UTC),
            proof_doc.id,
            env["fo"],
        )


# =============================================================================
# G. SETTLEMENT REOPENING & REVISIONS
# =============================================================================


@pytest.mark.asyncio
async def test_reopen_settled_settlement_creates_revision(db_session: AsyncSession):
    """
    Finance Officer reopens a SETTLED settlement:
    1. Revisions count increments.
    2. Snapshot preserves complete prior financial numbers.
    3. Status transitions to REOPENED.
    4. Event status remains COMPLETED (never reverted).
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.SETTLED

    # Reopen
    rev = await SettlementService.reopen_settlement(
        db_session, settlement.id, "Auditor found missing sponsor challan", env["fo"]
    )

    assert rev.revision_number == 1
    assert rev.reopening_reason == "Auditor found missing sponsor challan"
    assert rev.snapshot_data["status"] == SettlementStatus.SETTLED.value

    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.REOPENED

    await db_session.refresh(event)
    assert event.status == EventStatus.COMPLETED  # Event status remains COMPLETED!


@pytest.mark.asyncio
async def test_reopen_non_settled_rejected(db_session: AsyncSession):
    """Only SETTLED settlements can be reopened."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    with pytest.raises(BusinessRuleError) as exc:
        await SettlementService.reopen_settlement(
            db_session, settlement.id, "Try reopen draft", env["fo"]
        )
    assert "Only 'SETTLED' settlements can be reopened" in str(exc.value)


@pytest.mark.asyncio
async def test_reopen_role_guards(db_session: AsyncSession):
    """Only Finance Officer and Principal can reopen. Secretary and Admin are blocked."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    # Secretary blocked
    with pytest.raises(ForbiddenError):
        await SettlementService.reopen_settlement(
            db_session, settlement.id, "Sec reopen", env["sec"]
        )

    # System Admin blocked
    with pytest.raises(ForbiddenError) as exc:
        await SettlementService.reopen_settlement(
            db_session, settlement.id, "Admin reopen", env["admin"]
        )
    assert "System administrators" in str(exc.value)

    # Principal allowed
    rev = await SettlementService.reopen_settlement(
        db_session, settlement.id, "Executive audit query by Principal", env["principal"]
    )
    assert rev.revision_number == 1


# =============================================================================
# H. CLOSURE ELIGIBILITY (READ-ONLY)
# =============================================================================


@pytest.mark.asyncio
async def test_closure_eligibility_all_conditions_met(db_session: AsyncSession):
    """When event is completed, certified, all expenses settled, event is closure eligible."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    res = await SettlementService.get_closure_eligibility(db_session, event.id, env["fo"])
    assert res["eligible"] is True
    assert len(res["blockers"]) == 0
    assert res["event_id"] == str(event.id)
    assert res["settlement_id"] == str(settlement.id)


@pytest.mark.asyncio
async def test_closure_eligibility_blockers(db_session: AsyncSession):
    """Reports specific machine-readable blockers when preconditions are missing."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    # 1. Missing settlement blocker
    res1 = await SettlementService.get_closure_eligibility(db_session, event.id, env["fo"])
    assert res1["eligible"] is False
    assert "SETTLEMENT_MISSING" in res1["blockers"]

    # 2. Unsettled reimbursement blocker
    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )
    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    res2 = await SettlementService.get_closure_eligibility(db_session, event.id, env["fo"])
    assert res2["eligible"] is False
    assert "SETTLEMENT_NOT_SETTLED" in res2["blockers"]


# =============================================================================
# I. SEGREGATION OF DUTIES & SECURITY
# =============================================================================


@pytest.mark.asyncio
async def test_cross_club_isolation(db_session: AsyncSession):
    """Secretary of Club B cannot request advances or prepare settlements for Club A."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    # other_sec belongs to other_club
    with pytest.raises(ForbiddenError):
        await SettlementService.request_advance(
            db_session, event.id, Decimal("5000.00"), "Cross club", env["other_sec"]
        )

    with pytest.raises(ForbiddenError):
        await SettlementService.prepare_settlement(db_session, event.id, env["other_sec"])


@pytest.mark.asyncio
async def test_system_admin_strictly_barred_from_financial_actions(db_session: AsyncSession):
    """System Administrator is strictly forbidden across all financial action APIs."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])

    # Admin audit barred
    with pytest.raises(ForbiddenError):
        await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["admin"])

    # Admin payment barred
    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )
    with pytest.raises(ForbiddenError):
        await SettlementService.record_payment(
            db_session,
            settlement.id,
            SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
            Decimal("100.00"),
            PaymentMethod.BANK_TRANSFER_NEFT,
            "UTR-ADM",
            datetime.now(UTC),
            proof_doc.id,
            env["admin"],
        )


# =============================================================================
# J. AUDIT LOGGING VERIFICATION
# =============================================================================


@pytest.mark.asyncio
async def test_audit_logs_recorded_for_all_transitions(db_session: AsyncSession):
    """Verify that every major financial state transition generates an AuditLog entry."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    adv = await SettlementService.request_advance(
        db_session, event.id, Decimal("5000.00"), "Advance", env["sec"]
    )
    await SettlementService.approve_advance(db_session, adv.id, Decimal("5000.00"), env["fo"])
    await SettlementService.disburse_advance(
        db_session, adv.id, Decimal("5000.00"), "NEFT-AUDIT", datetime.now(UTC), env["fo"]
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    # Query audit logs
    audit_actions = (
        await db_session.scalars(
            select(AuditLog.action).where(
                AuditLog.action.in_(
                    [
                        AuditAction.ADVANCE_REQUESTED.value,
                        AuditAction.ADVANCE_APPROVED.value,
                        AuditAction.ADVANCE_DISBURSED.value,
                        AuditAction.SETTLEMENT_PREPARED.value,
                        AuditAction.SETTLEMENT_SUBMITTED.value,
                        AuditAction.SETTLEMENT_APPROVED.value,
                    ]
                )
            )
        )
    ).all()

    assert AuditAction.ADVANCE_REQUESTED.value in audit_actions
    assert AuditAction.ADVANCE_APPROVED.value in audit_actions
    assert AuditAction.ADVANCE_DISBURSED.value in audit_actions
    assert AuditAction.SETTLEMENT_PREPARED.value in audit_actions
    assert AuditAction.SETTLEMENT_SUBMITTED.value in audit_actions
    assert AuditAction.SETTLEMENT_APPROVED.value in audit_actions


# =============================================================================
# J. CONCURRENCY & INTEGRITY TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_concurrency_duplicate_settlement_creation(db_session: AsyncSession):
    """
    Simulated race condition: duplicate settlement creation attempt.
    The service must ensure only ONE active settlement is prepared,
    and concurrent/repeat attempts raise ConflictError without database corruption.
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    # First preparation succeeds
    s1 = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert s1 is not None

    # Immediate second preparation fails with domain ConflictError
    with pytest.raises(ConflictError) as exc:
        await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert "already exists" in str(exc.value)


@pytest.mark.asyncio
async def test_concurrency_payment_overpayment_prevention(db_session: AsyncSession):
    """
    Simulated race condition: two payments attempted on a remaining balance.
    Remaining balance = 10000.
    Payment 1: 6000 -> succeeds, remaining balance = 4000.
    Payment 2: 6000 -> must fail with BusinessRuleError, preventing overpayment.
    Total cleared never exceeds 10000.
    """
    env = await _create_test_environment(db_session, sanctioned_grant=Decimal("20000.00"))
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    approved = await SettlementService.audit_settlement(
        db_session, settlement.id, "APPROVE", env["fo"]
    )
    assert approved.reimbursement_due == Decimal("10000.00")

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )

    # First payment: 6000 succeeds
    p1 = await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("6000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-CONC-1",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )
    assert p1.amount == Decimal("6000.00")

    # Second payment: 6000 fails (remaining is 4000)
    with pytest.raises(BusinessRuleError) as exc:
        await SettlementService.record_payment(
            db_session,
            settlement.id,
            SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
            Decimal("6000.00"),
            PaymentMethod.BANK_TRANSFER_NEFT,
            "UTR-CONC-2",
            datetime.now(UTC),
            proof_doc.id,
            env["fo"],
        )
    assert "exceeds remaining balance due" in str(exc.value)

    # Remaining 4000 succeeds and settles
    p2 = await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("4000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-CONC-3",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )
    assert p2.amount == Decimal("4000.00")

    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.SETTLED


# =============================================================================
# K. PHASE 2.3 FINANCIAL INTEGRITY HARDENING TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_stale_data_fails_on_expense_replacement_with_identical_total(
    db_session: AsyncSession,
):
    """
    Replacing an expense record with another record having the IDENTICAL total
    must fail stale data protection (detected via deterministic SHA-256 fingerprint).
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    exp1 = await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])

    # Disallow exp1 (V=0) and add exp2 (V=10000) -> Total V is STILL 10000.00!
    exp1.status = ActualExpenseStatus.DISALLOWED
    exp1.verified_amount = Decimal("0.00")
    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )
    await db_session.flush()

    # FO attempts approval -> Stale data detected via fingerprint!
    with pytest.raises(SettlementStaleDataError) as exc:
        await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])
    assert "fingerprint mismatch" in str(exc.value) or "source data has changed" in str(exc.value)


@pytest.mark.asyncio
async def test_stale_data_fails_on_expense_status_substitution(db_session: AsyncSession):
    """
    Swapping expense statuses while keeping total verified expenditure constant
    must fail stale data protection.
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    exp1 = await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("5000.00"),
        Decimal("5000.00"),
        ActualExpenseStatus.VERIFIED,
    )
    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("5000.00"),
        Decimal("5000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])

    # Disallow exp1 and add exp3 for 5000 -> Total V remains 10000.00!
    exp1.status = ActualExpenseStatus.DISALLOWED
    exp1.verified_amount = Decimal("0.00")
    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("5000.00"),
        Decimal("5000.00"),
        ActualExpenseStatus.VERIFIED,
    )
    await db_session.flush()

    with pytest.raises(SettlementStaleDataError) as exc:
        await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])
    assert "fingerprint mismatch" in str(exc.value) or "source data has changed" in str(exc.value)


@pytest.mark.asyncio
async def test_stale_data_fails_on_income_replacement_with_identical_total(
    db_session: AsyncSession,
):
    """
    Replacing an income record with another having the identical amount
    must fail stale data protection.
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    doc1 = await _create_test_document(db_session, event, env["sec"], DocumentType.INCOME_EVIDENCE)
    inc1 = await SettlementService.record_income(
        db_session,
        event.id,
        IncomeSourceType.SPONSORSHIP,
        Decimal("2000.00"),
        "Sponsor Alpha",
        "Alpha Corp",
        date.today(),
        doc1.id,
        env["sec"],
        reference_number="REF-1",
    )
    await SettlementService.verify_income(db_session, inc1.id, env["fo"])

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])

    # Reject inc1 and record inc2 with same amount 2000.00
    inc1.status = ActualIncomeStatus.REJECTED
    doc2 = await _create_test_document(db_session, event, env["sec"], DocumentType.INCOME_EVIDENCE)
    inc2 = await SettlementService.record_income(
        db_session,
        event.id,
        IncomeSourceType.TICKET_SALES,
        Decimal("2000.00"),
        "Tickets",
        "Attendees",
        date.today(),
        doc2.id,
        env["sec"],
        reference_number="REF-2",
    )
    await SettlementService.verify_income(db_session, inc2.id, env["fo"])
    await db_session.flush()

    with pytest.raises(SettlementStaleDataError) as exc:
        await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])
    assert "fingerprint mismatch" in str(exc.value) or "source data has changed" in str(exc.value)


@pytest.mark.asyncio
async def test_stale_data_fails_on_approved_version_swap(db_session: AsyncSession):
    """
    Switching the event's approved_version_id to an amended version
    (even with identical sanctioned grant) must fail stale data protection.
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])

    # Create amended version 2 with identical grant 30000.00
    v2 = EventRequestVersion(
        id=uuid.uuid4(),
        event_request_id=event.event_request_id,
        version_number=2,
        snapshot={
            "title": "Amended Event Request",
            "budget": {
                "institute_contribution": "30000.00",
                "total_expected_expenditure": "35000.00",
                "expected_income": "5000.00",
            },
        },
        submitted_by=env["sec"].id,
    )
    db_session.add(v2)
    await db_session.flush()

    event.approved_version_id = v2.id
    await db_session.flush()

    with pytest.raises(SettlementStaleDataError) as exc:
        await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    assert "proposal version changed" in str(exc.value) or "fingerprint mismatch" in str(exc.value)


@pytest.mark.asyncio
async def test_reopen_downward_revision_transitions_to_pending_refund(
    db_session: AsyncSession,
):
    """
    Downward revision after full reimbursement payment must transition to PENDING_REFUND
    (overpayment recovery obligation), NOT PENDING_REIMBURSEMENT.
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    exp = await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )
    await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("10000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-REV1-10000",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )

    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.SETTLED

    # Reopen
    await SettlementService.reopen_settlement(
        db_session, settlement.id, "Post-settlement audit disallowance of ₹4,000", env["fo"]
    )
    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.REOPENED

    # Disallow 4000.00: verified drops to 6000.00
    exp.verified_amount = Decimal("6000.00")
    exp.status = ActualExpenseStatus.PARTIALLY_VERIFIED
    await db_session.flush()

    # Re-prepare settlement
    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert settlement.status == SettlementStatus.DRAFT
    assert settlement.institutional_payout == Decimal("6000.00")
    assert settlement.settlement_balance == Decimal("-4000.00")
    assert settlement.refund_due == Decimal("4000.00")
    assert settlement.reimbursement_due == Decimal("0.00")
    assert settlement.settlement_type == SettlementType.REFUND_DUE

    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    approved = await SettlementService.audit_settlement(
        db_session, settlement.id, "APPROVE", env["fo"]
    )

    # Must be PENDING_REFUND (recovery due)
    assert approved.status == SettlementStatus.PENDING_REFUND


@pytest.mark.asyncio
async def test_reopen_downward_revision_clears_via_refund(db_session: AsyncSession):
    """
    Downward revision in PENDING_REFUND clears and marks SETTLED when club refunds the excess.
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    exp = await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )
    await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("10000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-REV1-10000",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )

    await SettlementService.reopen_settlement(
        db_session, settlement.id, "Post-settlement audit disallowance of ₹4,000", env["fo"]
    )
    exp.verified_amount = Decimal("6000.00")
    exp.status = ActualExpenseStatus.PARTIALLY_VERIFIED
    await db_session.flush()

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    # Club deposits refund of 4000.00
    refund_proof = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )
    refund_pmt = await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.ADVANCE_REFUND_RECEIPT,
        Decimal("4000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-REFUND-4000",
        datetime.now(UTC),
        refund_proof.id,
        env["fo"],
    )
    assert refund_pmt.amount == Decimal("4000.00")

    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.SETTLED

    # Historical payments preserved: 2 records total
    payments = await SettlementService.get_settlement_payments(db_session, settlement.id, env["fo"])
    assert len(payments) == 2


@pytest.mark.asyncio
async def test_reopen_upward_revision_creates_supplementary_reimbursement(
    db_session: AsyncSession,
):
    """
    Upward revision after full reimbursement payment creates a supplementary
    reimbursement obligation for only the incremental delta (e.g. ₹4,000).
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("6000.00"),
        Decimal("6000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )
    await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("6000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-REV1-6000",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )

    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.SETTLED

    # Reopen
    await SettlementService.reopen_settlement(
        db_session, settlement.id, "Club discovered omitted valid bill of ₹4,000", env["fo"]
    )

    # Add omitted bill of 4000.00
    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("4000.00"),
        Decimal("4000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert settlement.institutional_payout == Decimal("10000.00")
    assert settlement.settlement_balance == Decimal("4000.00")
    assert settlement.reimbursement_due == Decimal("4000.00")
    assert settlement.refund_due == Decimal("0.00")
    assert settlement.settlement_type == SettlementType.REIMBURSEMENT_DUE

    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    # Disburse incremental 4000.00
    pmt2 = await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("4000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-REV2-4000",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )
    assert pmt2.amount == Decimal("4000.00")

    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.SETTLED


@pytest.mark.asyncio
async def test_reopen_downward_revision_with_partial_prior_payment(db_session: AsyncSession):
    """
    Downward revision where initial payout was 7000 and revised entitlement is 6000:
    Club refunds only 1000 (not 4000).
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    exp = await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("7000.00"),
        Decimal("7000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )
    await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("7000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-7000",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )

    await SettlementService.reopen_settlement(
        db_session, settlement.id, "Audit disallowance of ₹1,000 from initial 7000", env["fo"]
    )
    exp.verified_amount = Decimal("6000.00")
    exp.status = ActualExpenseStatus.PARTIALLY_VERIFIED
    await db_session.flush()

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert settlement.institutional_payout == Decimal("6000.00")
    assert settlement.settlement_balance == Decimal("-1000.00")
    assert settlement.refund_due == Decimal("1000.00")

    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    # Club refunds only 1000.00
    await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.ADVANCE_REFUND_RECEIPT,
        Decimal("1000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-REFUND-1000",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )

    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.SETTLED


@pytest.mark.asyncio
async def test_reopen_direction_flip_credits_prior_refund(db_session: AsyncSession):
    """
    When a club refunds advance in Rev 1 (e.g. ₹5,000 on ₹25,000 advance with ₹20,000 expense)
    and Rev 2 expense increases to ₹30,000:
    Net institutional transfer is 20,000. Revision balance must be +10,000 reimbursement due.
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    # Disburse advance of 25000.00
    adv = await SettlementService.request_advance(
        db_session, event.id, Decimal("25000.00"), "Festival logistics advance", env["sec"]
    )
    await SettlementService.approve_advance(db_session, adv.id, Decimal("25000.00"), env["fo"])
    await SettlementService.disburse_advance(
        db_session,
        adv.id,
        Decimal("25000.00"),
        "UTR-ADV-25K",
        datetime.now(UTC),
        env["fo"],
    )

    # Initial expense of 20000.00
    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("20000.00"),
        Decimal("20000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert settlement.refund_due == Decimal("5000.00")
    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )
    await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.ADVANCE_REFUND_RECEIPT,
        Decimal("5000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-REFUND-5K",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )

    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.SETTLED

    # Reopen to Revision 2
    await SettlementService.reopen_settlement(
        db_session, settlement.id, "Additional verified bills discovered post-refund", env["fo"]
    )

    # Add 10000.00 expense -> Total V becomes 30000.00
    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )

    settlement = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert settlement.institutional_payout == Decimal("30000.00")
    assert settlement.settlement_balance == Decimal("10000.00")
    assert settlement.reimbursement_due == Decimal("10000.00")
    assert settlement.refund_due == Decimal("0.00")
    assert settlement.settlement_type == SettlementType.REIMBURSEMENT_DUE

    await SettlementService.submit_settlement(db_session, settlement.id, env["sec"])
    await SettlementService.audit_settlement(db_session, settlement.id, "APPROVE", env["fo"])

    # Disburse supplementary reimbursement of 10000.00
    await SettlementService.record_payment(
        db_session,
        settlement.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("10000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-SUPP-10K",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )

    await db_session.refresh(settlement)
    assert settlement.status == SettlementStatus.SETTLED


@pytest.mark.asyncio
async def test_multiple_successive_reopenings_preserve_cumulative_balance(
    db_session: AsyncSession,
):
    """
    Demonstrates Case 5 from research:
    Rev 1: Entitlement 10,000, Paid 10,000 -> SETTLED
    Rev 2: Entitlement 6,000, Refund 4,000 -> SETTLED
    Rev 3: Entitlement 8,000, Supplementary Reimbursement 2,000 -> SETTLED
    """
    env = await _create_test_environment(db_session)
    event = env["event"]
    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )

    # Step 1: Rev 1
    exp = await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )
    s = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, s.id, env["sec"])
    await SettlementService.audit_settlement(db_session, s.id, "APPROVE", env["fo"])
    await SettlementService.record_payment(
        db_session,
        s.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("10000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-1",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )
    await db_session.refresh(s)
    assert s.status == SettlementStatus.SETTLED

    # Step 2: Rev 2 (Downward to 6000)
    await SettlementService.reopen_settlement(db_session, s.id, "Audit query rev 2", env["fo"])
    exp.verified_amount = Decimal("6000.00")
    exp.status = ActualExpenseStatus.PARTIALLY_VERIFIED
    await db_session.flush()

    s = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert s.refund_due == Decimal("4000.00")
    await SettlementService.submit_settlement(db_session, s.id, env["sec"])
    await SettlementService.audit_settlement(db_session, s.id, "APPROVE", env["fo"])
    await SettlementService.record_payment(
        db_session,
        s.id,
        SettlementPaymentType.ADVANCE_REFUND_RECEIPT,
        Decimal("4000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-2",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )
    await db_session.refresh(s)
    assert s.status == SettlementStatus.SETTLED

    # Step 3: Rev 3 (Upward to 8000)
    await SettlementService.reopen_settlement(
        db_session, s.id, "Executive appeal rev 3", env["fo"]
    )
    exp.verified_amount = Decimal("8000.00")
    await db_session.flush()

    s = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    assert s.institutional_payout == Decimal("8000.00")
    assert s.settlement_balance == Decimal("2000.00")
    assert s.reimbursement_due == Decimal("2000.00")
    assert s.refund_due == Decimal("0.00")
    await SettlementService.submit_settlement(db_session, s.id, env["sec"])
    await SettlementService.audit_settlement(db_session, s.id, "APPROVE", env["fo"])
    await SettlementService.record_payment(
        db_session,
        s.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("2000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-3",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )
    await db_session.refresh(s)
    assert s.status == SettlementStatus.SETTLED

    # Cumulative audit: 3 payments, Net = 8000.00
    pmts = await SettlementService.get_settlement_payments(db_session, s.id, env["fo"])
    assert len(pmts) == 3


@pytest.mark.asyncio
async def test_historical_payments_are_immutable_across_reopen(db_session: AsyncSession):
    """
    Historical SettlementPayment records cannot be deleted or mutated across reopening.
    """
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )
    s = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, s.id, env["sec"])
    await SettlementService.audit_settlement(db_session, s.id, "APPROVE", env["fo"])

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )
    p1 = await SettlementService.record_payment(
        db_session,
        s.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("10000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-HIST-1",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )
    p1_id = p1.id

    rev = await SettlementService.reopen_settlement(
        db_session, s.id, "Reopen for audit check", env["fo"]
    )

    # Verify payment snapshot captured in revision
    assert len(rev.snapshot_data["payments"]) == 1
    assert rev.snapshot_data["payments"][0]["id"] == str(p1_id)
    assert rev.snapshot_data["payments"][0]["amount"] == "10000.00"

    # Verify payment still exists in DB
    pmt_db = await db_session.scalar(
        select(SettlementPayment).where(SettlementPayment.id == p1_id)
    )
    assert pmt_db is not None
    assert pmt_db.amount == Decimal("10000.00")


@pytest.mark.asyncio
async def test_no_duplicate_reimbursement_after_reopen(db_session: AsyncSession):
    """Overpayment guard prevents paying more than remaining due in an upward revision."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("6000.00"),
        Decimal("6000.00"),
        ActualExpenseStatus.VERIFIED,
    )
    s = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, s.id, env["sec"])
    await SettlementService.audit_settlement(db_session, s.id, "APPROVE", env["fo"])

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )
    await SettlementService.record_payment(
        db_session,
        s.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("6000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-1",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )

    await SettlementService.reopen_settlement(db_session, s.id, "Add 4000 bill", env["fo"])
    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("4000.00"),
        Decimal("4000.00"),
        ActualExpenseStatus.VERIFIED,
    )
    s = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, s.id, env["sec"])
    await SettlementService.audit_settlement(db_session, s.id, "APPROVE", env["fo"])

    # Attempting to pay 5000 when remaining due is 4000 must fail
    with pytest.raises(BusinessRuleError) as exc:
        await SettlementService.record_payment(
            db_session,
            s.id,
            SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
            Decimal("5000.00"),
            PaymentMethod.BANK_TRANSFER_NEFT,
            "UTR-OVER",
            datetime.now(UTC),
            proof_doc.id,
            env["fo"],
        )
    assert "exceeds remaining balance due" in str(exc.value)


@pytest.mark.asyncio
async def test_no_duplicate_refund_after_reopen(db_session: AsyncSession):
    """Overpayment guard prevents excess refund in a downward revision."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    exp = await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )
    s = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, s.id, env["sec"])
    await SettlementService.audit_settlement(db_session, s.id, "APPROVE", env["fo"])

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )
    await SettlementService.record_payment(
        db_session,
        s.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("10000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-1",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )

    await SettlementService.reopen_settlement(db_session, s.id, "Disallow 1000", env["fo"])
    exp.verified_amount = Decimal("9000.00")
    exp.status = ActualExpenseStatus.PARTIALLY_VERIFIED
    await db_session.flush()

    s = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, s.id, env["sec"])
    await SettlementService.audit_settlement(db_session, s.id, "APPROVE", env["fo"])

    # Attempting to refund 2000 when refund due is 1000 must fail
    with pytest.raises(BusinessRuleError) as exc:
        await SettlementService.record_payment(
            db_session,
            s.id,
            SettlementPaymentType.ADVANCE_REFUND_RECEIPT,
            Decimal("2000.00"),
            PaymentMethod.BANK_TRANSFER_NEFT,
            "UTR-OVER-REF",
            datetime.now(UTC),
            proof_doc.id,
            env["fo"],
        )
    assert "exceeds remaining balance due" in str(exc.value)


@pytest.mark.asyncio
async def test_closure_blocked_while_reopened_revision_has_outstanding_balance(
    db_session: AsyncSession,
):
    """Event closure is blocked while a reopened revision has an outstanding balance."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    exp = await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("10000.00"),
        Decimal("10000.00"),
        ActualExpenseStatus.VERIFIED,
    )
    s = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, s.id, env["sec"])
    await SettlementService.audit_settlement(db_session, s.id, "APPROVE", env["fo"])

    proof_doc = await _create_test_document(
        db_session, event, env["fo"], DocumentType.SETTLEMENT_PAYMENT_PROOF
    )
    await SettlementService.record_payment(
        db_session,
        s.id,
        SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT,
        Decimal("10000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-1",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )

    # Eligible when settled
    elig = await SettlementService.get_closure_eligibility(db_session, event.id, env["sec"])
    assert elig["eligible"] is True

    # Reopen -> Blocked with SETTLEMENT_NOT_SETTLED
    await SettlementService.reopen_settlement(
        db_session, s.id, "Reopened for review", env["fo"]
    )
    elig = await SettlementService.get_closure_eligibility(db_session, event.id, env["sec"])
    assert elig["eligible"] is False
    assert "SETTLEMENT_NOT_SETTLED" in elig["blockers"]

    # Disallow 4000 and approve -> PENDING_REFUND -> Still blocked
    exp.verified_amount = Decimal("6000.00")
    exp.status = ActualExpenseStatus.PARTIALLY_VERIFIED
    await db_session.flush()

    s = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, s.id, env["sec"])
    await SettlementService.audit_settlement(db_session, s.id, "APPROVE", env["fo"])

    elig = await SettlementService.get_closure_eligibility(db_session, event.id, env["sec"])
    assert elig["eligible"] is False
    assert "SETTLEMENT_NOT_SETTLED" in elig["blockers"]

    # Clear refund -> Eligible again
    await SettlementService.record_payment(
        db_session,
        s.id,
        SettlementPaymentType.ADVANCE_REFUND_RECEIPT,
        Decimal("4000.00"),
        PaymentMethod.BANK_TRANSFER_NEFT,
        "UTR-REF-4K",
        datetime.now(UTC),
        proof_doc.id,
        env["fo"],
    )

    elig = await SettlementService.get_closure_eligibility(db_session, event.id, env["sec"])
    assert elig["eligible"] is True
    assert elig["blockers"] == []


@pytest.mark.asyncio
async def test_fingerprint_detects_approved_version_change_with_same_grant(
    db_session: AsyncSession,
):
    """Fingerprint detects amended EventRequestVersion even when grant ceiling is identical."""
    env = await _create_test_environment(db_session)
    event = env["event"]

    await _add_test_expense(
        db_session,
        event,
        env["sec"],
        Decimal("8000.00"),
        Decimal("8000.00"),
        ActualExpenseStatus.VERIFIED,
    )
    s = await SettlementService.prepare_settlement(db_session, event.id, env["sec"])
    await SettlementService.submit_settlement(db_session, s.id, env["sec"])

    # Create amended version 2 with identical grant
    v2 = EventRequestVersion(
        id=uuid.uuid4(),
        event_request_id=event.event_request_id,
        version_number=2,
        snapshot={
            "title": "Amended Event Proposal",
            "budget": {
                "institute_contribution": "30000.00",
                "total_expected_expenditure": "30000.00",
                "expected_income": "0.00",
            },
        },
        submitted_by=env["sec"].id,
    )
    db_session.add(v2)
    await db_session.flush()
    event.approved_version_id = v2.id
    await db_session.flush()

    with pytest.raises(SettlementStaleDataError) as exc:
        await SettlementService.audit_settlement(db_session, s.id, "APPROVE", env["fo"])
    assert "proposal version changed" in str(exc.value) or "fingerprint mismatch" in str(exc.value)
