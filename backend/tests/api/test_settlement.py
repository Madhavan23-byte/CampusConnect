"""
CampusConnect - Phase 2.3 Financial Settlement API Integration Test Suite

HTTP Integration Tests covering all required scenarios:
- Authentication & Segregation of Duties (SOD) / RBAC (401, 403)
- Cross-club isolation (403 IDOR)
- Cash Advance lifecycle (Request, Approve, Reject, Disburse, Caps, Invariants)
- Actual Income ledger (Evidence upload, Record, Verify, Reject, Invariants)
- Financial Settlement lifecycle (Prepare, Submit, Stale-Data 409, FO Audit Approve/Query, Reopen)
- Settlement Payments (Reimbursement, Refund, Proof upload,
  Directional enforcement, Overpayment block)
- History & Auditing (Payment history, Immutable revision snapshots)
- Event Closure Eligibility (Read-only check, blocker codes, no CLOSED status)
- Security & Input Validation (Malformed UUID, Invalid Decimal, Negative amounts, Forged event IDs)
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.domain import (
    ActualExpense,
    Club,
    ClubMember,
    Document,
    Event,
    EventRequest,
    EventRequestVersion,
    PostEventReport,
    User,
)
from app.models.enums import (
    ActualExpenseStatus,
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
    UserRole,
)


def _auth_header(user: User) -> dict[str, str]:
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token(
        subject=user.id,
        role=role_str,
        email=user.email,
    )
    return {"Authorization": f"Bearer {token}"}


def _dummy_pdf_content(marker: str = "TestDoc") -> bytes:
    """Generate minimal valid PDF bytes with custom marker to vary SHA-256."""
    pdf_str = (
        f"%PDF-1.4\n1 0 obj\n<< /Title ({marker}) >>\nendobj\n"
        "xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
    )
    return pdf_str.encode()


async def _create_test_env(
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
        password_hash=hash_password("Pass123!"),
        full_name=f"Secretary {uid}",
        role=UserRole.CLUB_SECRETARY,
        is_active=True,
    )
    other_sec = User(
        id=uuid.uuid4(),
        email=f"other_sec_{uid}@college.edu",
        password_hash=hash_password("Pass123!"),
        full_name=f"Other Sec {uid}",
        role=UserRole.CLUB_SECRETARY,
        is_active=True,
    )
    fo = User(
        id=uuid.uuid4(),
        email=f"fo_{uid}@college.edu",
        password_hash=hash_password("Pass123!"),
        full_name=f"Finance Officer {uid}",
        role=UserRole.FINANCE_OFFICER,
        is_active=True,
    )
    admin = User(
        id=uuid.uuid4(),
        email=f"admin_{uid}@college.edu",
        password_hash=hash_password("Pass123!"),
        full_name=f"Admin {uid}",
        role=UserRole.SYSTEM_ADMIN,
        is_active=True,
    )
    principal = User(
        id=uuid.uuid4(),
        email=f"principal_{uid}@college.edu",
        password_hash=hash_password("Pass123!"),
        full_name=f"Principal {uid}",
        role=UserRole.PRINCIPAL,
        is_active=True,
    )
    advisor = User(
        id=uuid.uuid4(),
        email=f"adv_{uid}@college.edu",
        password_hash=hash_password("Pass123!"),
        full_name=f"Advisor {uid}",
        role=UserRole.FACULTY_ADVISOR,
        is_active=True,
    )
    db.add_all([sec, other_sec, fo, admin, principal, advisor])
    await db.flush()

    club = Club(
        id=uuid.uuid4(),
        name=f"Robotics Club {uid}",
        slug=f"robotics-{uid}",
        academic_year="2026-27",
        created_by=admin.id,
        is_active=True,
    )
    other_club = Club(
        id=uuid.uuid4(),
        name=f"Literary Society {uid}",
        slug=f"lit-{uid}",
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
    await db.commit()

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


async def _add_verified_expense(
    db: AsyncSession,
    event: Event,
    user: User,
    fo: User,
    claimed: Decimal = Decimal("20000.00"),
    verified: Decimal = Decimal("20000.00"),
) -> ActualExpense:
    """Helper to inject a verified actual expense."""
    doc = await _create_test_document(db, event, user, DocumentType.EXPENSE_INVOICE)
    exp = ActualExpense(
        id=uuid.uuid4(),
        event_id=event.id,
        category=BudgetLineItemCategory.MATERIALS,
        description="Event supplies",
        vendor_name="Acme Hardware",
        invoice_date=date.today(),
        claimed_amount=claimed,
        verified_amount=verified,
        status=ActualExpenseStatus.VERIFIED,
        bill_document_id=doc.id,
        submitted_by=user.id,
        verified_by=fo.id,
        verified_at=datetime.now(UTC),
    )
    db.add(exp)
    await db.commit()
    return exp


@pytest.mark.asyncio
class TestAuthenticationAndAuthorization:
    """Tests 1-8: Unauthenticated, Role Authorization, SOD, and Admin Exclusion."""

    async def test_01_unauthenticated_request_returns_401(self, client: AsyncClient, db_session):
        """1. Unauthenticated request to settlement endpoints must return 401."""
        random_event_id = uuid.uuid4()
        res = await client.get(f"/api/v1/events/{random_event_id}/settlement")
        assert res.status_code == 401

    async def test_02_secretary_allowed_advance_request(self, client: AsyncClient, db_session):
        """2. Secretary is authorized to request a cash advance."""
        env = await _create_test_env(db_session)
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "10000.00", "reason": "Initial setup materials"},
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == CashAdvanceStatus.REQUESTED.value
        assert Decimal(str(data["amount_requested"])) == Decimal("10000.00")

    async def test_03_finance_allowed_advance_approval(self, client: AsyncClient, db_session):
        """3. Finance Officer is authorized to approve cash advance."""
        env = await _create_test_env(db_session)
        req_res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "10000.00", "reason": "Supplies needed"},
            headers=_auth_header(env["sec"]),
        )
        adv_id = req_res.json()["id"]

        app_res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances/{adv_id}/approve",
            json={"amount_approved": "10000.00", "remarks": "Approved for purchase"},
            headers=_auth_header(env["fo"]),
        )
        assert app_res.status_code == 200
        assert app_res.json()["status"] == CashAdvanceStatus.APPROVED.value

    async def test_04_secretary_cannot_approve_advance_returns_403(
        self, client: AsyncClient, db_session
    ):
        """4. Secretary cannot approve advance (SOD violation -> 403)."""
        env = await _create_test_env(db_session)
        req_res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "10000.00", "reason": "Supplies needed"},
            headers=_auth_header(env["sec"]),
        )
        adv_id = req_res.json()["id"]

        app_res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances/{adv_id}/approve",
            json={"amount_approved": "10000.00", "remarks": "Self approve attempt"},
            headers=_auth_header(env["sec"]),
        )
        assert app_res.status_code == 403

    async def test_05_finance_cannot_perform_secretary_action_returns_403(
        self, client: AsyncClient, db_session
    ):
        """5. Finance Officer cannot perform Secretary-only actions (request advance -> 403)."""
        env = await _create_test_env(db_session)
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "5000.00", "reason": "FO requesting advance"},
            headers=_auth_header(env["fo"]),
        )
        assert res.status_code == 403

    async def test_06_principal_can_reopen(self, client: AsyncClient, db_session):
        """6. Principal is authorized to reopen settlement."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("15000.00"),
            Decimal("15000.00"),
        )

        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )

        # Upload proof and pay to transition to SETTLED
        pdf = _dummy_pdf_content("ReopenProof")
        proof = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/upload-proof",
            files={"file": ("proof.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["fo"]),
        )
        proof_id = proof.json()["document_id"]
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/payments",
            json={
                "payment_type": SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value,
                "amount": "15000.00",
                "payment_method": PaymentMethod.BANK_TRANSFER_NEFT.value,
                "transaction_reference": "TXN-REOPEN-1",
                "transaction_date": datetime.now(UTC).isoformat(),
                "proof_document_id": proof_id,
            },
            headers=_auth_header(env["fo"]),
        )

        reopen_res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/reopen",
            json={"reopening_reason": "Auditing discrepancy discovered by Principal office"},
            headers=_auth_header(env["principal"]),
        )
        assert reopen_res.status_code == 200
        assert reopen_res.json()["revision_number"] == 1

        sett_res = await client.get(
            f"/api/v1/events/{env['event'].id}/settlement", headers=_auth_header(env["sec"])
        )
        assert sett_res.json()["status"] == "REOPENED"

    async def test_07_system_admin_financial_operation_returns_403(
        self, client: AsyncClient, db_session
    ):
        """7. System Admin is barred from all financial operations -> 403."""
        env = await _create_test_env(db_session)
        res1 = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "5000.00", "reason": "Admin request"},
            headers=_auth_header(env["admin"]),
        )
        assert res1.status_code == 403

        res2 = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare",
            headers=_auth_header(env["admin"]),
        )
        assert res2.status_code == 403

    async def test_08_cross_club_access_returns_403(self, client: AsyncClient, db_session):
        """8. Cross-club access returns 403 (IDOR prevention)."""
        env = await _create_test_env(db_session)
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "5000.00", "reason": "Cross club request"},
            headers=_auth_header(env["other_sec"]),
        )
        assert res.status_code == 403


@pytest.mark.asyncio
class TestCashAdvanceEndpoints:
    """Tests 9-14b: Cash Advance Full Lifecycle and Bounds."""

    async def test_09_request_advance(self, client: AsyncClient, db_session):
        """9. Secretary successfully requests cash advance."""
        env = await _create_test_env(db_session)
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "12000.00", "reason": "Advance for hardware parts"},
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "REQUESTED"
        assert Decimal(str(data["amount_requested"])) == Decimal("12000.00")

    async def test_10_approve_advance(self, client: AsyncClient, db_session):
        """10. Finance Officer approves cash advance."""
        env = await _create_test_env(db_session)
        req = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "8000.00", "reason": "Advance request"},
            headers=_auth_header(env["sec"]),
        )
        adv_id = req.json()["id"]

        res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances/{adv_id}/approve",
            json={"amount_approved": "8000.00", "remarks": "Verified against budget ceiling"},
            headers=_auth_header(env["fo"]),
        )
        assert res.status_code == 200
        assert res.json()["status"] == "APPROVED"
        assert res.json()["approved_by"] == str(env["fo"].id)

    async def test_11_reject_advance(self, client: AsyncClient, db_session):
        """11. Finance Officer rejects cash advance with mandatory reason."""
        env = await _create_test_env(db_session)
        req = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "8000.00", "reason": "Advance request"},
            headers=_auth_header(env["sec"]),
        )
        adv_id = req.json()["id"]

        res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances/{adv_id}/reject",
            json={"rejection_reason": "Advance not justified for this category"},
            headers=_auth_header(env["fo"]),
        )
        assert res.status_code == 200
        assert res.json()["status"] == "REJECTED"
        assert res.json()["rejection_reason"] == "Advance not justified for this category"

    async def test_12_disburse_advance(self, client: AsyncClient, db_session):
        """12. Finance Officer disburses approved cash advance."""
        env = await _create_test_env(db_session)
        req = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "8000.00", "reason": "Advance request"},
            headers=_auth_header(env["sec"]),
        )
        adv_id = req.json()["id"]
        await client.post(
            f"/api/v1/events/{env['event'].id}/advances/{adv_id}/approve",
            json={"amount_approved": "8000.00"},
            headers=_auth_header(env["fo"]),
        )

        res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances/{adv_id}/disburse",
            json={
                "amount_disbursed": "8000.00",
                "payment_reference": "TXN-BANK-9988",
                "notes": "Direct transfer to club secretary",
            },
            headers=_auth_header(env["fo"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "DISBURSED"
        assert data["payment_reference"] == "TXN-BANK-9988"

    async def test_13_invalid_advance_state(self, client: AsyncClient, db_session):
        """13. Cannot disburse before approval."""
        env = await _create_test_env(db_session)
        req = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "5000.00", "reason": "Early disburse test"},
            headers=_auth_header(env["sec"]),
        )
        adv_id = req.json()["id"]

        disb_res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances/{adv_id}/disburse",
            json={"amount_disbursed": "5000.00", "payment_reference": "TXN-EARLY"},
            headers=_auth_header(env["fo"]),
        )
        assert disb_res.status_code in (400, 409, 422)

    async def test_14_excessive_advance(self, client: AsyncClient, db_session):
        """14. Advance approval exceeding sanctioned grant is rejected by finance rules."""
        env = await _create_test_env(db_session, sanctioned_grant=Decimal("20000.00"))
        req_res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "25000.00", "reason": "Advance request"},
            headers=_auth_header(env["sec"]),
        )
        assert req_res.status_code == 201
        adv_id = req_res.json()["id"]

        # FO attempts to approve 25000 which exceeds sanctioned grant 20000 -> 422
        app_res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances/{adv_id}/approve",
            json={"amount_approved": "25000.00", "remarks": "Excessive approval attempt"},
            headers=_auth_header(env["fo"]),
        )
        assert app_res.status_code in (400, 422)

    async def test_14b_duplicate_advance_blocked(self, client: AsyncClient, db_session):
        """14b. Second advance request blocked while one is already active."""
        env = await _create_test_env(db_session)
        res1 = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "5000.00", "reason": "First advance"},
            headers=_auth_header(env["sec"]),
        )
        assert res1.status_code == 201

        res2 = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "5000.00", "reason": "Second advance attempt"},
            headers=_auth_header(env["sec"]),
        )
        assert res2.status_code == 409


@pytest.mark.asyncio
class TestActualIncomeEndpoints:
    """Tests 15-19: Actual Income Evidence, Recording, Verification, Rejection."""

    async def test_15_record_income(self, client: AsyncClient, db_session):
        """15. Secretary uploads evidence and records actual income."""
        env = await _create_test_env(db_session)
        pdf = _dummy_pdf_content("TicketReceipt")
        up_res = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes/upload-evidence",
            files={"file": ("tickets.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["sec"]),
        )
        assert up_res.status_code == 201
        doc_id = up_res.json()["document_id"]

        inc_res = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes",
            json={
                "source_type": IncomeSourceType.TICKET_SALES.value,
                "amount": "4500.00",
                "description": "Ticket registration income",
                "payer_name": "Attendees",
                "received_date": date.today().isoformat(),
                "evidence_document_id": doc_id,
            },
            headers=_auth_header(env["sec"]),
        )
        assert inc_res.status_code == 201
        data = inc_res.json()
        assert data["status"] == "RECORDED"
        assert Decimal(str(data["amount"])) == Decimal("4500.00")
        assert data["evidence_document_id"] == doc_id

    async def test_16_verify_income(self, client: AsyncClient, db_session):
        """16. Finance Officer verifies recorded actual income."""
        env = await _create_test_env(db_session)
        pdf = _dummy_pdf_content("Sponsorship")
        up = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes/upload-evidence",
            files={"file": ("sponsor.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["sec"]),
        )
        doc_id = up.json()["document_id"]

        inc = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes",
            json={
                "source_type": IncomeSourceType.SPONSORSHIP.value,
                "amount": "10000.00",
                "description": "Title sponsor grant",
                "payer_name": "Tech Corp",
                "received_date": date.today().isoformat(),
                "evidence_document_id": doc_id,
            },
            headers=_auth_header(env["sec"]),
        )
        inc_id = inc.json()["id"]

        ver_res = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes/{inc_id}/verify",
            json={"finance_remarks": "Bank credit matched"},
            headers=_auth_header(env["fo"]),
        )
        assert ver_res.status_code == 200
        data = ver_res.json()
        assert data["status"] == "VERIFIED"
        assert Decimal(str(data["amount"])) == Decimal("10000.00")
        assert data["verified_by"] == str(env["fo"].id)

    async def test_17_reject_income(self, client: AsyncClient, db_session):
        """17. Finance Officer rejects recorded income with mandatory reason."""
        env = await _create_test_env(db_session)
        pdf = _dummy_pdf_content("StallFee")
        up = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes/upload-evidence",
            files={"file": ("stall.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["sec"]),
        )
        doc_id = up.json()["document_id"]

        inc = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes",
            json={
                "source_type": IncomeSourceType.STALL_RENTAL.value,
                "amount": "3000.00",
                "description": "Food stall vendor fee",
                "payer_name": "Food Vendor",
                "received_date": date.today().isoformat(),
                "evidence_document_id": doc_id,
            },
            headers=_auth_header(env["sec"]),
        )
        inc_id = inc.json()["id"]

        rej_res = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes/{inc_id}/reject",
            json={"rejection_reason": "No corresponding bank entry found"},
            headers=_auth_header(env["fo"]),
        )
        assert rej_res.status_code == 200
        assert rej_res.json()["status"] == "REJECTED"
        assert "No corresponding bank entry found" in rej_res.json()["finance_remarks"]

    async def test_18_missing_evidence(self, client: AsyncClient, db_session):
        """18. Recording income without evidence_document_id fails validation -> 422."""
        env = await _create_test_env(db_session)
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes",
            json={
                "source_type": IncomeSourceType.REGISTRATION_FEE.value,
                "amount": "2000.00",
                "description": "Registration fees",
                "payer_name": "Delegates",
                "received_date": date.today().isoformat(),
            },
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code == 422

    async def test_19_invalid_income_state(self, client: AsyncClient, db_session):
        """19. Cannot verify an already verified income -> 400/409/422."""
        env = await _create_test_env(db_session)
        pdf = _dummy_pdf_content("IncomeDoc")
        up = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes/upload-evidence",
            files={"file": ("inc.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["sec"]),
        )
        doc_id = up.json()["document_id"]

        inc = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes",
            json={
                "source_type": IncomeSourceType.OTHER.value,
                "amount": "1000.00",
                "description": "Donation",
                "payer_name": "Alumni",
                "received_date": date.today().isoformat(),
                "evidence_document_id": doc_id,
            },
            headers=_auth_header(env["sec"]),
        )
        inc_id = inc.json()["id"]

        await client.post(
            f"/api/v1/events/{env['event'].id}/incomes/{inc_id}/verify",
            json={"finance_remarks": "First verify"},
            headers=_auth_header(env["fo"]),
        )

        res2 = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes/{inc_id}/verify",
            json={"finance_remarks": "Duplicate verify attempt"},
            headers=_auth_header(env["fo"]),
        )
        assert res2.status_code in (400, 409, 422)


@pytest.mark.asyncio
class TestSettlementLifecycle:
    """Tests 20-25: Prepare, Submit, Stale-Data 409, FO Audit Approve/Query, Reopen."""

    async def test_20_prepare_settlement(self, client: AsyncClient, db_session):
        """20. Secretary prepares financial settlement draft."""
        env = await _create_test_env(db_session, sanctioned_grant=Decimal("30000.00"))
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("22000.00"),
            Decimal("22000.00"),
        )

        res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare",
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "DRAFT"
        assert Decimal(str(data["total_verified_expenditure"])) == Decimal("22000.00")
        assert Decimal(str(data["settlement_balance"])) == Decimal("22000.00")
        assert Decimal(str(data["reimbursement_due"])) == Decimal("22000.00")

    async def test_21_submit_settlement(self, client: AsyncClient, db_session):
        """21. Secretary submits prepared settlement to finance."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("15000.00"),
            Decimal("15000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )

        sub_res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit",
            headers=_auth_header(env["sec"]),
        )
        assert sub_res.status_code == 200
        assert sub_res.json()["status"] == "UNDER_AUDIT"

    async def test_22_stale_settlement_returns_409(self, client: AsyncClient, db_session):
        """22. Modifying underlying expense ledger invalidates source fingerprint -> 409."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("10000.00"),
            Decimal("10000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )

        await _add_verified_expense(
            db_session, env["event"], env["sec"], env["fo"], Decimal("5000.00"), Decimal("5000.00")
        )

        audit_res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )
        assert audit_res.status_code == 409

    async def test_23_finance_approve(self, client: AsyncClient, db_session):
        """23. Finance audits and approves settlement."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("18000.00"),
            Decimal("18000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )

        res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "PENDING_REIMBURSEMENT"
        assert Decimal(str(data["reimbursement_due"])) == Decimal("18000.00")

    async def test_24_finance_query(self, client: AsyncClient, db_session):
        """24. Finance audits settlement with QUERY action and mandatory reason."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("18000.00"),
            Decimal("18000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )

        res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "QUERY", "query_reason": "Missing itemized bill details"},
            headers=_auth_header(env["fo"]),
        )
        assert res.status_code == 200
        assert res.json()["status"] == "QUERIED"

    async def test_25_reopen(self, client: AsyncClient, db_session):
        """25. Finance Officer reopens settlement; creates revision snapshot."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("15000.00"),
            Decimal("15000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )

        pdf = _dummy_pdf_content("ReopenProofFO")
        proof = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/upload-proof",
            files={"file": ("proof.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["fo"]),
        )
        proof_id = proof.json()["document_id"]
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/payments",
            json={
                "payment_type": SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value,
                "amount": "15000.00",
                "payment_method": PaymentMethod.BANK_TRANSFER_NEFT.value,
                "transaction_reference": "TXN-REOPEN-FO",
                "transaction_date": datetime.now(UTC).isoformat(),
                "proof_document_id": proof_id,
            },
            headers=_auth_header(env["fo"]),
        )

        reopen_res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/reopen",
            json={"reopening_reason": "Additional invoice found by club"},
            headers=_auth_header(env["fo"]),
        )
        assert reopen_res.status_code == 200
        assert reopen_res.json()["revision_number"] == 1

        sett_res = await client.get(
            f"/api/v1/events/{env['event'].id}/settlement", headers=_auth_header(env["sec"])
        )
        assert sett_res.json()["status"] == "REOPENED"


@pytest.mark.asyncio
class TestSettlementPayments:
    """Tests 26-31: Settlement Payment Clearance, Direction, Overpayment, and Proof."""

    async def test_26_reimbursement_payment(self, client: AsyncClient, db_session):
        """26. Record reimbursement payment against PENDING_REIMBURSEMENT."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("15000.00"),
            Decimal("15000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )

        pdf = _dummy_pdf_content("ReimbProof")
        proof_res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/upload-proof",
            files={"file": ("reimb_proof.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["fo"]),
        )
        assert proof_res.status_code == 201
        proof_id = proof_res.json()["document_id"]

        pay_res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/payments",
            json={
                "payment_type": SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value,
                "amount": "15000.00",
                "payment_method": PaymentMethod.BANK_TRANSFER_NEFT.value,
                "transaction_reference": "TXN-REIMB-1001",
                "transaction_date": datetime.now(UTC).isoformat(),
                "proof_document_id": proof_id,
            },
            headers=_auth_header(env["fo"]),
        )
        assert pay_res.status_code == 201
        data = pay_res.json()
        assert data["payment_type"] == SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value
        assert Decimal(str(data["amount"])) == Decimal("15000.00")

        sett_res = await client.get(
            f"/api/v1/events/{env['event'].id}/settlement", headers=_auth_header(env["sec"])
        )
        assert sett_res.status_code == 200
        assert sett_res.json()["status"] == "SETTLED"
        assert len(sett_res.json()["payments"]) == 1

    async def test_27_refund_payment(self, client: AsyncClient, db_session):
        """27. Record refund payment against PENDING_REFUND."""
        env = await _create_test_env(db_session)
        req = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "20000.00", "reason": "Advance for event"},
            headers=_auth_header(env["sec"]),
        )
        adv_id = req.json()["id"]
        await client.post(
            f"/api/v1/events/{env['event'].id}/advances/{adv_id}/approve",
            json={"amount_approved": "20000.00"},
            headers=_auth_header(env["fo"]),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/advances/{adv_id}/disburse",
            json={"amount_disbursed": "20000.00", "payment_reference": "TXN-ADV"},
            headers=_auth_header(env["fo"]),
        )

        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("15000.00"),
            Decimal("15000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )
        app_res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )
        assert app_res.json()["status"] == "PENDING_REFUND"

        pdf = _dummy_pdf_content("RefundProof")
        proof = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/upload-proof",
            files={"file": ("refund_proof.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["fo"]),
        )
        proof_id = proof.json()["document_id"]

        pay_res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/payments",
            json={
                "payment_type": SettlementPaymentType.ADVANCE_REFUND_RECEIPT.value,
                "amount": "5000.00",
                "payment_method": PaymentMethod.CHEQUE.value,
                "transaction_reference": "CHQ-REF-001",
                "transaction_date": datetime.now(UTC).isoformat(),
                "proof_document_id": proof_id,
            },
            headers=_auth_header(env["fo"]),
        )
        assert pay_res.status_code == 201
        assert pay_res.json()["payment_type"] == SettlementPaymentType.ADVANCE_REFUND_RECEIPT.value

    async def test_28_wrong_payment_direction(self, client: AsyncClient, db_session):
        """28. Attempting wrong payment direction returns 400/409/422."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("15000.00"),
            Decimal("15000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )

        pdf = _dummy_pdf_content("Proof")
        proof = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/upload-proof",
            files={"file": ("p.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["fo"]),
        )
        proof_id = proof.json()["document_id"]

        pay_res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/payments",
            json={
                "payment_type": SettlementPaymentType.ADVANCE_REFUND_RECEIPT.value,
                "amount": "5000.00",
                "payment_method": PaymentMethod.CASH_VOUCHER.value,
                "transaction_reference": "TXN-WRONG",
                "transaction_date": datetime.now(UTC).isoformat(),
                "proof_document_id": proof_id,
            },
            headers=_auth_header(env["fo"]),
        )
        assert pay_res.status_code in (400, 409, 422)

    async def test_29_payment_exceeds_balance(self, client: AsyncClient, db_session):
        """29. Payment exceeding remaining balance is blocked."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("10000.00"),
            Decimal("10000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )

        pdf = _dummy_pdf_content("Proof")
        proof = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/upload-proof",
            files={"file": ("p.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["fo"]),
        )
        proof_id = proof.json()["document_id"]

        pay_res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/payments",
            json={
                "payment_type": SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value,
                "amount": "15000.00",
                "payment_method": PaymentMethod.BANK_TRANSFER_NEFT.value,
                "transaction_reference": "TXN-OVER",
                "transaction_date": datetime.now(UTC).isoformat(),
                "proof_document_id": proof_id,
            },
            headers=_auth_header(env["fo"]),
        )
        assert pay_res.status_code in (400, 409, 422)

    async def test_30_duplicate_excess_payment_when_settled(self, client: AsyncClient, db_session):
        """30. Cannot record payment when settlement is already SETTLED."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("10000.00"),
            Decimal("10000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )

        pdf = _dummy_pdf_content("Proof")
        proof = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/upload-proof",
            files={"file": ("p.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["fo"]),
        )
        proof_id = proof.json()["document_id"]

        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/payments",
            json={
                "payment_type": SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value,
                "amount": "10000.00",
                "payment_method": PaymentMethod.BANK_TRANSFER_NEFT.value,
                "transaction_reference": "TXN-1",
                "transaction_date": datetime.now(UTC).isoformat(),
                "proof_document_id": proof_id,
            },
            headers=_auth_header(env["fo"]),
        )

        pay2 = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/payments",
            json={
                "payment_type": SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value,
                "amount": "1000.00",
                "payment_method": PaymentMethod.BANK_TRANSFER_NEFT.value,
                "transaction_reference": "TXN-2",
                "transaction_date": datetime.now(UTC).isoformat(),
                "proof_document_id": proof_id,
            },
            headers=_auth_header(env["fo"]),
        )
        assert pay2.status_code in (400, 409, 422)

    async def test_31_payment_proof_authorization(self, client: AsyncClient, db_session):
        """31. Secretary cannot upload settlement payment proof (FO only -> 403)."""
        env = await _create_test_env(db_session)
        pdf = _dummy_pdf_content("Proof")
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/upload-proof",
            files={"file": ("p.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code == 403


@pytest.mark.asyncio
class TestRevisionAndHistory:
    """Tests 32-33c: Payment History, Revision Snapshot History, List Advances/Incomes/Detail."""

    async def test_32_payment_history(self, client: AsyncClient, db_session):
        """32. List settlement payments for an event."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("10000.00"),
            Decimal("10000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )

        pdf = _dummy_pdf_content("Proof")
        proof = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/upload-proof",
            files={"file": ("p.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["fo"]),
        )
        proof_id = proof.json()["document_id"]

        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/payments",
            json={
                "payment_type": SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value,
                "amount": "6000.00",
                "payment_method": PaymentMethod.BANK_TRANSFER_NEFT.value,
                "transaction_reference": "TXN-P1",
                "transaction_date": datetime.now(UTC).isoformat(),
                "proof_document_id": proof_id,
            },
            headers=_auth_header(env["fo"]),
        )

        res = await client.get(
            f"/api/v1/events/{env['event'].id}/settlement/payments",
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert Decimal(str(data[0]["amount"])) == Decimal("6000.00")

    async def test_33_revision_history(self, client: AsyncClient, db_session):
        """33. List settlement revision history after reopening."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("10000.00"),
            Decimal("10000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )

        pdf = _dummy_pdf_content("RevHistProof")
        proof = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/upload-proof",
            files={"file": ("proof.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["fo"]),
        )
        proof_id = proof.json()["document_id"]
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/payments",
            json={
                "payment_type": SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value,
                "amount": "10000.00",
                "payment_method": PaymentMethod.BANK_TRANSFER_NEFT.value,
                "transaction_reference": "TXN-REV-HIST",
                "transaction_date": datetime.now(UTC).isoformat(),
                "proof_document_id": proof_id,
            },
            headers=_auth_header(env["fo"]),
        )

        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/reopen",
            json={"reopening_reason": "Audit review required"},
            headers=_auth_header(env["fo"]),
        )

        res = await client.get(
            f"/api/v1/events/{env['event'].id}/settlement/revisions",
            headers=_auth_header(env["fo"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 1
        assert data[0]["revision_number"] == 1
        assert "snapshot_data" in data[0]

    async def test_33b_list_advances_and_incomes(self, client: AsyncClient, db_session):
        """33b. GET advances and GET incomes lists."""
        env = await _create_test_env(db_session)
        await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "5000.00", "reason": "Advance req"},
            headers=_auth_header(env["sec"]),
        )
        adv_res = await client.get(
            f"/api/v1/events/{env['event'].id}/advances", headers=_auth_header(env["sec"])
        )
        assert adv_res.status_code == 200
        assert Decimal(str(adv_res.json()["amount_requested"])) == Decimal("5000.00")

        pdf = _dummy_pdf_content("IncomeList")
        up = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes/upload-evidence",
            files={"file": ("inc.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["sec"]),
        )
        doc_id = up.json()["document_id"]
        await client.post(
            f"/api/v1/events/{env['event'].id}/incomes",
            json={
                "source_type": IncomeSourceType.REGISTRATION_FEE.value,
                "amount": "2500.00",
                "description": "Registration entry fees",
                "payer_name": "Attendees",
                "received_date": date.today().isoformat(),
                "evidence_document_id": doc_id,
            },
            headers=_auth_header(env["sec"]),
        )
        inc_res = await client.get(
            f"/api/v1/events/{env['event'].id}/incomes", headers=_auth_header(env["sec"])
        )
        assert inc_res.status_code == 200
        assert len(inc_res.json()) == 1

    async def test_33c_get_settlement_detail(self, client: AsyncClient, db_session):
        """33c. GET settlement returns complete comprehensive payload."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("12000.00"),
            Decimal("12000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )

        res = await client.get(
            f"/api/v1/events/{env['event'].id}/settlement", headers=_auth_header(env["sec"])
        )
        assert res.status_code == 200
        data = res.json()
        assert data["event_id"] == str(env["event"].id)
        assert "sanctioned_grant" in data
        assert "total_verified_expenditure" in data
        assert "payments" in data
        assert "revisions" in data


@pytest.mark.asyncio
class TestClosureEligibility:
    """Tests 34-35, 45: Closure Eligibility Verification and Blocker Codes."""

    async def test_34_closure_eligible(self, client: AsyncClient, db_session):
        """34. Event closure eligible when SETTLED with zero balance."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("10000.00"),
            Decimal("10000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )

        pdf = _dummy_pdf_content("Proof")
        proof = await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/upload-proof",
            files={"file": ("p.pdf", pdf, "application/pdf")},
            headers=_auth_header(env["fo"]),
        )
        proof_id = proof.json()["document_id"]
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/payments",
            json={
                "payment_type": SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value,
                "amount": "10000.00",
                "payment_method": PaymentMethod.BANK_TRANSFER_NEFT.value,
                "transaction_reference": "TXN-CLR",
                "transaction_date": datetime.now(UTC).isoformat(),
                "proof_document_id": proof_id,
            },
            headers=_auth_header(env["fo"]),
        )

        res = await client.get(
            f"/api/v1/events/{env['event'].id}/settlement/closure-eligibility",
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["eligible"] is True
        assert len(data["blockers"]) == 0

    async def test_35_closure_blocked(self, client: AsyncClient, db_session):
        """35. Event closure blocked when settlement is pending payment."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("10000.00"),
            Decimal("10000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/submit", headers=_auth_header(env["sec"])
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/audit",
            json={"action": "APPROVE"},
            headers=_auth_header(env["fo"]),
        )

        res = await client.get(
            f"/api/v1/events/{env['event'].id}/settlement/closure-eligibility",
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["eligible"] is False
        assert len(data["blockers"]) > 0


@pytest.mark.asyncio
class TestSecurityAndInputValidation:
    """Tests 36-45: Security boundaries, IDOR, malformed UUID, negative values."""

    async def test_36_forged_event_id(self, client: AsyncClient, db_session):
        """36. Forged event ID returns 404 Not Found."""
        env = await _create_test_env(db_session)
        random_id = uuid.uuid4()
        res = await client.get(
            f"/api/v1/events/{random_id}/settlement",
            headers=_auth_header(env["fo"]),
        )
        assert res.status_code == 404

    async def test_37_cross_club_idor(self, client: AsyncClient, db_session):
        """37. Cross-club IDOR attempt on settlement details returns 403."""
        env = await _create_test_env(db_session)
        await _add_verified_expense(
            db_session,
            env["event"],
            env["sec"],
            env["fo"],
            Decimal("10000.00"),
            Decimal("10000.00"),
        )
        await client.post(
            f"/api/v1/events/{env['event'].id}/settlement/prepare", headers=_auth_header(env["sec"])
        )

        res = await client.get(
            f"/api/v1/events/{env['event'].id}/settlement",
            headers=_auth_header(env["other_sec"]),
        )
        assert res.status_code == 403

    async def test_38_forged_role(self, client: AsyncClient, db_session):
        """38. Role cannot be forged in request body."""
        env = await _create_test_env(db_session)
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={
                "amount_requested": "5000.00",
                "reason": "Attempting forge",
                "role": "FINANCE_OFFICER",
                "user_id": str(env["fo"].id),
            },
            headers=_auth_header(env["fo"]),
        )
        assert res.status_code == 403

    async def test_39_system_admin_bypass(self, client: AsyncClient, db_session):
        """39. System Admin cannot bypass financial segregation of duties."""
        env = await _create_test_env(db_session)
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "5000.00", "reason": "Admin advance attempt"},
            headers=_auth_header(env["admin"]),
        )
        assert res.status_code == 403

    async def test_40_malformed_uuid(self, client: AsyncClient, db_session):
        """40. Malformed UUID parameter returns 422."""
        env = await _create_test_env(db_session)
        res = await client.get(
            "/api/v1/events/not-a-valid-uuid/settlement",
            headers=_auth_header(env["fo"]),
        )
        assert res.status_code == 422

    async def test_41_invalid_decimal(self, client: AsyncClient, db_session):
        """41. Invalid Decimal format returns 422."""
        env = await _create_test_env(db_session)
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "abc_not_a_number", "reason": "Invalid decimal test"},
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code == 422

    async def test_42_negative_monetary_value(self, client: AsyncClient, db_session):
        """42. Negative monetary amount returns 422."""
        env = await _create_test_env(db_session)
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/advances",
            json={"amount_requested": "-5000.00", "reason": "Negative amount test"},
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code == 422

    async def test_43_get_settlement_not_prepared_returns_404(
        self, client: AsyncClient, db_session
    ):
        """43. GET settlement before prepare returns 404."""
        env = await _create_test_env(db_session)
        res = await client.get(
            f"/api/v1/events/{env['event'].id}/settlement",
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code == 404

    async def test_44_income_upload_evidence_magic_bytes(self, client: AsyncClient, db_session):
        """44. Uploading invalid file format without PDF magic bytes is rejected."""
        env = await _create_test_env(db_session)
        fake_pdf = b"Plain text disguised as pdf"
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/incomes/upload-evidence",
            files={"file": ("fake.pdf", fake_pdf, "application/pdf")},
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code in (400, 422)

    async def test_45_closure_eligibility_no_settlement_blocked(
        self, client: AsyncClient, db_session
    ):
        """45. Closure eligibility when no settlement exists returns is_eligible: false."""
        env = await _create_test_env(db_session)
        res = await client.get(
            f"/api/v1/events/{env['event'].id}/settlement/closure-eligibility",
            headers=_auth_header(env["sec"]),
        )
        assert res.status_code == 200
        assert res.json()["eligible"] is False
        assert "SETTLEMENT_MISSING" in res.json()["blockers"]
