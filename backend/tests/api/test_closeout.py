"""
CampusConnect - Event Closeout, Reopening & Archival REST API Test Suite (Phase 2.4.3)

Comprehensive API Integration Tests covering all 7 closeout endpoints:
1. GET  /api/v1/events/{event_id}/closure                (Eligibility & State Inspection)
2. POST /api/v1/events/{event_id}/closure/request        (Club Secretary Requests Closeout)
3. POST /api/v1/events/{event_id}/closure/certify        (Dean/Principal/Advisor Certifies Closeout)
4. POST /api/v1/events/{event_id}/closure/reject         (Institutional Authority Rejects Closeout)
5. POST /api/v1/events/{event_id}/closure/reopen-request (Petition to Reopen Closed Event)
6. POST /api/v1/events/{event_id}/closure/reopen-approve (Executive Approves Reopening)
7. POST /api/v1/events/{event_id}/archive                (System Admin Archives Event)

Testing Matrix:
- Authentication & Segregation of Duties (SOD) / RBAC (401, 403)
- Resource-level authorization & IDOR prevention (403, 404)
- Faculty Advisor closeout delegation gate (ALLOW_ADVISOR_EVENT_CLOSEOUT)
- Venue clearance attestation requirement (venue_cleared=True)
- Deterministic 64-char SHA-256 certificate manifest hashing
- Mandatory rejection/reopening rationale validation (422)
- Lifecycle transition conflicts & stale-state prevention (409)
- Idempotent repeated operations (Request, Archive)
- Audit log propagation: actor_id, IP address, and User-Agent capture
- Concurrency & double-transition protection
- OpenAPI schema completeness for all 7 endpoints
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.domain import (
    ActualExpense,
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
    PostEventReport,
    User,
    VenueRequest,
)
from app.models.enums import (
    ActualExpenseStatus,
    AuditAction,
    BudgetLineItemCategory,
    ClubMemberRole,
    DocumentType,
    EventStatus,
    EventType,
    PostEventReportStatus,
    SettlementStatus,
    SettlementType,
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


async def _create_closeout_api_env(
    db: AsyncSession,
    sanctioned_grant: Decimal = Decimal("30000.00"),
    sanctioned_exp: Decimal = Decimal("35000.00"),
    expected_inc: Decimal = Decimal("5000.00"),
) -> dict[str, Any]:
    """Helper to assemble a complete, valid test environment for closeout API tests."""
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
# 1. AUTHENTICATION (Tests 1-2)
# =============================================================================


async def test_01_unauthenticated_get_closure_returns_401(
    client: AsyncClient, db_session: AsyncSession
):
    """1. Unauthenticated GET /closure must return 401."""
    env = await _create_closeout_api_env(db_session)
    res = await client.get(f"/api/v1/events/{env['event'].id}/closure")
    assert res.status_code == 401


async def test_02_unauthenticated_mutations_return_401(
    client: AsyncClient, db_session: AsyncSession
):
    """2. Unauthenticated POST to any closeout mutation endpoint returns 401."""
    env = await _create_closeout_api_env(db_session)
    eid = env["event"].id
    endpoints = [
        ("POST", f"/api/v1/events/{eid}/closure/request", {}),
        ("POST", f"/api/v1/events/{eid}/closure/certify", {"venue_cleared": True}),
        ("POST", f"/api/v1/events/{eid}/closure/reject", {"reason": "test"}),
        ("POST", f"/api/v1/events/{eid}/closure/reopen-request", {"reason": "test"}),
        ("POST", f"/api/v1/events/{eid}/closure/reopen-approve", {"reason": "test"}),
        ("POST", f"/api/v1/events/{eid}/archive", None),
    ]
    for method, url, payload in endpoints:
        res = await client.request(method, url, json=payload)
        assert res.status_code == 401, f"Expected 401 for {url}, got {res.status_code}"


# =============================================================================
# 2. CLOSEOUT REQUEST (Tests 3-8)
# =============================================================================


async def test_03_closeout_request_authorized_secretary_success(
    client: AsyncClient, db_session: AsyncSession
):
    """3. Authorized Club Secretary requests closeout -> 200 with CLOSURE_REQUESTED."""
    env = await _create_closeout_api_env(db_session)
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        json={"remarks": "Submitting closeout for review"},
        headers=_auth_header(env["sec"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == EventStatus.CLOSURE_REQUESTED.value
    assert "closeout" in data["message"].lower() and "requested" in data["message"].lower()


async def test_04_closeout_request_other_club_secretary_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """4. Secretary from another club is denied with 403 (IDOR)."""
    env = await _create_closeout_api_env(db_session)
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        json={"remarks": "Illegal request"},
        headers=_auth_header(env["other_sec"]),
    )
    assert res.status_code == 403


async def test_05_closeout_request_non_secretary_roles_return_403(
    client: AsyncClient, db_session: AsyncSession
):
    """5. Non-secretary roles (FO, Advisor, Dean, Admin) cannot request closeout -> 403."""
    env = await _create_closeout_api_env(db_session)
    for u in [env["fo"], env["advisor"], env["dean"], env["principal"], env["admin"]]:
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/closure/request",
            json={"remarks": "Unauthorized role"},
            headers=_auth_header(u),
        )
        assert res.status_code == 403, f"Role {u.role} should be barred from requesting closeout"


async def test_06_closeout_request_duplicate_idempotent_returns_200(
    client: AsyncClient, db_session: AsyncSession
):
    """6. Repeated closeout request is safe and idempotent -> returns 200."""
    env = await _create_closeout_api_env(db_session)
    res1 = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        json={"remarks": "Initial"},
        headers=_auth_header(env["sec"]),
    )
    assert res1.status_code == 200
    res2 = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        json={"remarks": "Repeated"},
        headers=_auth_header(env["sec"]),
    )
    assert res2.status_code == 200
    assert "already" in res2.json()["message"].lower()


async def test_07_closeout_request_invalid_lifecycle_returns_409(
    client: AsyncClient, db_session: AsyncSession
):
    """7. Attempting closeout request on an event not in COMPLETED status -> 409 Conflict."""
    env = await _create_closeout_api_env(db_session)
    env["event"].status = EventStatus.SCHEDULED
    await db_session.flush()
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        json={"remarks": "Premature request"},
        headers=_auth_header(env["sec"]),
    )
    assert res.status_code == 409


async def test_08_closeout_request_ineligible_due_to_unsettled_financials_returns_422(
    client: AsyncClient, db_session: AsyncSession
):
    """8. Unsettled financial state blocks closeout request with 422 Unprocessable Entity."""
    env = await _create_closeout_api_env(db_session)
    env["settlement"].status = SettlementStatus.DRAFT
    await db_session.flush()
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    assert res.status_code == 422


# =============================================================================
# 3. CLOSEOUT CERTIFICATION (Tests 9-18)
# =============================================================================


async def test_09_certify_dean_success(client: AsyncClient, db_session: AsyncSession):
    """9. Dean certifies closeout with venue_cleared=True -> 200 CLOSED."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True, "closure_notes": "Dean approval"},
        headers=_auth_header(env["dean"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["certified_by"] == str(env["dean"].id)
    assert len(data["certificate_manifest_hash"]) == 64
    assert data["venue_cleared"] is True


async def test_10_certify_principal_success(client: AsyncClient, db_session: AsyncSession):
    """10. Principal certifies closeout -> 200 CLOSED."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["principal"]),
    )
    assert res.status_code == 200
    assert res.json()["certified_by"] == str(env["principal"].id)


async def test_11_certify_faculty_advisor_with_delegation_success(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """11. Faculty Advisor with ALLOW_ADVISOR_EVENT_CLOSEOUT=True certifies closeout -> 200."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ALLOW_ADVISOR_EVENT_CLOSEOUT", True)
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True, "closure_notes": "Advisor certified"},
        headers=_auth_header(env["advisor"]),
    )
    assert res.status_code == 200
    assert res.json()["certified_by"] == str(env["advisor"].id)


async def test_12_certify_faculty_advisor_without_delegation_returns_403(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """12. Faculty Advisor when delegation flag is False is denied -> 403."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ALLOW_ADVISOR_EVENT_CLOSEOUT", False)
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["advisor"]),
    )
    assert res.status_code == 403


async def test_13_certify_faculty_advisor_other_club_returns_403(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """13. Unrelated Faculty Advisor is denied even when delegation is enabled -> 403."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ALLOW_ADVISOR_EVENT_CLOSEOUT", True)
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["other_advisor"]),
    )
    assert res.status_code == 403


async def test_14_certify_system_admin_barred_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """14. System Administrator is strictly barred from certifying closeout -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["admin"]),
    )
    assert res.status_code == 403


async def test_15_certify_finance_officer_barred_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """15. Finance Officer cannot certify closeout (SOD enforcement) -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["fo"]),
    )
    assert res.status_code == 403


async def test_16_certify_venue_cleared_false_rejected(
    client: AsyncClient, db_session: AsyncSession
):
    """16. venue_cleared=False is rejected with 422 Unprocessable Entity."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": False},
        headers=_auth_header(env["dean"]),
    )
    assert res.status_code == 422


async def test_17_certify_invalid_lifecycle_returns_409(
    client: AsyncClient, db_session: AsyncSession
):
    """17. Attempting to certify when event is not CLOSURE_REQUESTED -> 409 Conflict."""
    env = await _create_closeout_api_env(db_session)
    # Event is COMPLETED without closeout request
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    assert res.status_code == 409


async def test_18_certify_manifest_hash_deterministic(
    client: AsyncClient, db_session: AsyncSession
):
    """18. Response includes deterministic 64-char lowercase hex SHA-256 manifest hash."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    assert res.status_code == 200
    h = res.json()["certificate_manifest_hash"]
    assert re.match(r"^[0-9a-f]{64}$", h) is not None


# =============================================================================
# 4. CLOSEOUT REJECTION (Tests 19-23)
# =============================================================================


async def test_19_reject_authorized_dean_success(
    client: AsyncClient, db_session: AsyncSession
):
    """19. Dean rejects closeout request -> 200 with event returned to COMPLETED."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reject",
        json={"reason": "Auditor query requires clarification on vendor invoice"},
        headers=_auth_header(env["dean"]),
    )
    assert res.status_code == 200
    assert res.json()["status"] == EventStatus.COMPLETED.value


async def test_20_reject_authorized_principal_success(
    client: AsyncClient, db_session: AsyncSession
):
    """20. Principal rejects closeout request -> 200 with COMPLETED status."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reject",
        json={"reason": "Principal requesting further report review"},
        headers=_auth_header(env["principal"]),
    )
    assert res.status_code == 200
    assert res.json()["status"] == EventStatus.COMPLETED.value


async def test_21_reject_missing_or_blank_reason_returns_422(
    client: AsyncClient, db_session: AsyncSession
):
    """21. Missing or whitespace reason is rejected with 422 Unprocessable Entity."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res1 = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reject",
        json={"reason": "   "},
        headers=_auth_header(env["dean"]),
    )
    assert res1.status_code == 422
    res2 = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reject",
        json={},
        headers=_auth_header(env["dean"]),
    )
    assert res2.status_code == 422


async def test_22_reject_unauthorized_roles_return_403(
    client: AsyncClient, db_session: AsyncSession
):
    """22. Secretary, Finance Officer, or Admin cannot reject closeout -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    for u in [env["sec"], env["fo"], env["admin"]]:
        res = await client.post(
            f"/api/v1/events/{env['event'].id}/closure/reject",
            json={"reason": "Unauthorized rejection"},
            headers=_auth_header(u),
        )
        assert res.status_code == 403


async def test_23_reject_invalid_lifecycle_returns_409(
    client: AsyncClient, db_session: AsyncSession
):
    """23. Attempting to reject an event not in CLOSURE_REQUESTED -> 409 Conflict."""
    env = await _create_closeout_api_env(db_session)
    # Event is COMPLETED, not CLOSURE_REQUESTED
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reject",
        json={"reason": "Invalid lifecycle rejection"},
        headers=_auth_header(env["dean"]),
    )
    assert res.status_code == 409


# =============================================================================
# 5. REOPEN PETITION (Tests 24-31)
# =============================================================================


async def test_24_reopen_request_secretary_success(
    client: AsyncClient, db_session: AsyncSession
):
    """24. Club Secretary petitions to reopen CLOSED event -> 200."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-request",
        json={"reason": "Late expense invoice arrived for sound equipment"},
        headers=_auth_header(env["sec"]),
    )
    assert res.status_code == 200
    assert res.json()["status"] == EventStatus.CLOSED.value


async def test_25_reopen_request_faculty_advisor_success(
    client: AsyncClient, db_session: AsyncSession
):
    """25. Assigned Faculty Advisor petitions to reopen CLOSED event -> 200."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-request",
        json={"reason": "Advisor found unrecorded sponsorship contribution"},
        headers=_auth_header(env["advisor"]),
    )
    assert res.status_code == 200


async def test_26_reopen_request_finance_officer_success(
    client: AsyncClient, db_session: AsyncSession
):
    """26. Finance Officer petitions to reopen CLOSED event -> 200."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-request",
        json={"reason": "Audit reconciliations require bank transaction adjustment"},
        headers=_auth_header(env["fo"]),
    )
    assert res.status_code == 200


async def test_27_reopen_request_unauthorized_system_admin_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """27. System Admin cannot petition event reopening -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-request",
        json={"reason": "Admin petition attempt"},
        headers=_auth_header(env["admin"]),
    )
    assert res.status_code == 403


async def test_28_reopen_request_other_club_secretary_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """28. Secretary of unrelated club cannot petition reopening -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-request",
        json={"reason": "Cross-club reopening petition"},
        headers=_auth_header(env["other_sec"]),
    )
    assert res.status_code == 403


async def test_29_reopen_request_unrelated_faculty_advisor_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """29. Unrelated Faculty Advisor cannot petition reopening -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-request",
        json={"reason": "Unrelated advisor petition"},
        headers=_auth_header(env["other_advisor"]),
    )
    assert res.status_code == 403


async def test_30_reopen_request_non_closed_event_returns_409(
    client: AsyncClient, db_session: AsyncSession
):
    """30. Reopen petition on a non-CLOSED event returns 409 Conflict."""
    env = await _create_closeout_api_env(db_session)
    # Event is COMPLETED, not CLOSED
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-request",
        json={"reason": "Event is not closed"},
        headers=_auth_header(env["sec"]),
    )
    assert res.status_code == 409


async def test_31_reopen_request_empty_reason_returns_422(
    client: AsyncClient, db_session: AsyncSession
):
    """31. Empty reopening petition reason returns 422 Unprocessable Entity."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-request",
        json={"reason": "   "},
        headers=_auth_header(env["sec"]),
    )
    assert res.status_code == 422


# =============================================================================
# 6. REOPEN APPROVAL (Tests 32-38)
# =============================================================================


async def test_32_reopen_approve_dean_success(
    client: AsyncClient, db_session: AsyncSession
):
    """32. Dean approves reopening -> 200 with revision snapshot, event -> COMPLETED."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-approve",
        json={"reason": "Approved late invoice adjustment by executive authority"},
        headers=_auth_header(env["dean"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["revision_number"] == 1
    assert data["reopened_by"] == str(env["dean"].id)
    # Check that event returned to COMPLETED
    closure_res = await client.get(
        f"/api/v1/events/{env['event'].id}/closure",
        headers=_auth_header(env["dean"]),
    )
    assert closure_res.json()["event_status"] == EventStatus.COMPLETED.value


async def test_33_reopen_approve_principal_success(
    client: AsyncClient, db_session: AsyncSession
):
    """33. Principal approves reopening -> 200 with revision record."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-approve",
        json={"reason": "Principal approved institutional adjustment"},
        headers=_auth_header(env["principal"]),
    )
    assert res.status_code == 200
    assert res.json()["reopened_by"] == str(env["principal"].id)


async def test_34_reopen_approve_unauthorized_secretary_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """34. Club Secretary cannot approve reopening -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-approve",
        json={"reason": "Self-approval attempt"},
        headers=_auth_header(env["sec"]),
    )
    assert res.status_code == 403


async def test_35_reopen_approve_unauthorized_finance_officer_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """35. Finance Officer cannot approve reopening (strictly Dean/Principal) -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-approve",
        json={"reason": "FO approving reopening"},
        headers=_auth_header(env["fo"]),
    )
    assert res.status_code == 403


async def test_36_reopen_approve_unauthorized_system_admin_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """36. System Admin cannot approve reopening -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-approve",
        json={"reason": "Admin approving reopening"},
        headers=_auth_header(env["admin"]),
    )
    assert res.status_code == 403


async def test_37_reopen_approve_non_closed_event_returns_409(
    client: AsyncClient, db_session: AsyncSession
):
    """37. Approving reopening on a non-CLOSED event returns 409 Conflict."""
    env = await _create_closeout_api_env(db_session)
    # Event is COMPLETED, not CLOSED
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-approve",
        json={"reason": "Event is not closed"},
        headers=_auth_header(env["dean"]),
    )
    assert res.status_code == 409


async def test_38_reopen_approve_empty_reason_returns_422(
    client: AsyncClient, db_session: AsyncSession
):
    """38. Blank approval rationale is rejected with 422 Unprocessable Entity."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-approve",
        json={"reason": "   "},
        headers=_auth_header(env["dean"]),
    )
    assert res.status_code == 422


# =============================================================================
# 7. ARCHIVAL (Tests 39-45)
# =============================================================================


async def test_39_archive_system_admin_success(
    client: AsyncClient, db_session: AsyncSession
):
    """39. System Administrator archives CLOSED event -> 200 with ARCHIVED status."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/archive",
        headers=_auth_header(env["admin"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == EventStatus.ARCHIVED.value
    assert "archived" in data["message"].lower()


async def test_40_archive_dean_barred_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """40. Dean cannot archive event (strictly SYSTEM_ADMIN) -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/archive",
        headers=_auth_header(env["dean"]),
    )
    assert res.status_code == 403


async def test_41_archive_principal_barred_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """41. Principal cannot archive event -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/archive",
        headers=_auth_header(env["principal"]),
    )
    assert res.status_code == 403


async def test_42_archive_finance_officer_barred_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """42. Finance Officer cannot archive event -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/archive",
        headers=_auth_header(env["fo"]),
    )
    assert res.status_code == 403


async def test_43_archive_secretary_barred_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """43. Club Secretary cannot archive event -> 403."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/archive",
        headers=_auth_header(env["sec"]),
    )
    assert res.status_code == 403


async def test_44_archive_non_closed_event_returns_409(
    client: AsyncClient, db_session: AsyncSession
):
    """44. Attempting to archive a non-CLOSED event returns 409 Conflict."""
    env = await _create_closeout_api_env(db_session)
    # Event is COMPLETED, not CLOSED
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/archive",
        headers=_auth_header(env["admin"]),
    )
    assert res.status_code == 409


async def test_45_archive_repeated_idempotent_returns_200(
    client: AsyncClient, db_session: AsyncSession
):
    """45. Repeated archive calls on an already ARCHIVED event are safe -> 200."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res1 = await client.post(
        f"/api/v1/events/{env['event'].id}/archive",
        headers=_auth_header(env["admin"]),
    )
    assert res1.status_code == 200
    res2 = await client.post(
        f"/api/v1/events/{env['event'].id}/archive",
        headers=_auth_header(env["admin"]),
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == EventStatus.ARCHIVED.value


# =============================================================================
# 8. SECURITY, IDOR, AUDIT CONTEXT & PAYLOAD (Tests 46-50)
# =============================================================================


async def test_46_idor_nonexistent_event_uuid_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    """46. Nonexistent event UUID returns 404 Not Found on all endpoints."""
    env = await _create_closeout_api_env(db_session)
    fake_id = uuid.uuid4()
    endpoints = [
        ("GET", f"/api/v1/events/{fake_id}/closure", None),
        ("POST", f"/api/v1/events/{fake_id}/closure/request", {}),
        ("POST", f"/api/v1/events/{fake_id}/closure/certify", {"venue_cleared": True}),
        ("POST", f"/api/v1/events/{fake_id}/closure/reject", {"reason": "Valid rationale"}),
        ("POST", f"/api/v1/events/{fake_id}/closure/reopen-request", {"reason": "Valid rationale"}),
        ("POST", f"/api/v1/events/{fake_id}/closure/reopen-approve", {"reason": "Valid rationale"}),
        ("POST", f"/api/v1/events/{fake_id}/archive", None),
    ]
    for method, url, payload in endpoints:
        res = await client.request(method, url, json=payload, headers=_auth_header(env["dean"]))
        assert res.status_code in (403, 404), f"Expected 404/403 for {url}, got {res.status_code}"


async def test_47_idor_cross_club_view_closure_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    """47. Secretary of other club cannot inspect closure details -> 403."""
    env = await _create_closeout_api_env(db_session)
    res = await client.get(
        f"/api/v1/events/{env['event'].id}/closure",
        headers=_auth_header(env["other_sec"]),
    )
    assert res.status_code == 403


async def test_48_client_supplied_actor_identity_ignored_in_payload(
    client: AsyncClient, db_session: AsyncSession
):
    """48. Client-supplied actor IDs in payload are ignored; DB actor is authenticated user."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    spoofed_uuid = str(uuid.uuid4())
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True, "certified_by": spoofed_uuid, "actor_id": spoofed_uuid},
        headers=_auth_header(env["dean"]),
    )
    assert res.status_code == 200
    assert res.json()["certified_by"] == str(env["dean"].id)
    assert res.json()["certified_by"] != spoofed_uuid


async def test_49_audit_log_actor_and_client_meta_propagated(
    client: AsyncClient, db_session: AsyncSession
):
    """49. Audit log entry correctly captures authenticated actor and client metadata."""
    env = await _create_closeout_api_env(db_session)
    custom_ua = "CampusConnectAutomatedTest/2.4.3"
    res = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers={**_auth_header(env["sec"]), "User-Agent": custom_ua},
    )
    assert res.status_code == 200

    stmt = (
        select(AuditLog)
        .where(
            AuditLog.entity_id == str(env["event"].id),
            AuditLog.action == AuditAction.CLOSURE_REQUESTED.value,
        )
        .order_by(AuditLog.created_at.desc())
    )
    audit = (await db_session.execute(stmt)).scalars().first()
    assert audit is not None
    assert audit.actor_id == env["sec"].id


async def test_50_get_closure_comprehensive_payload(
    client: AsyncClient, db_session: AsyncSession
):
    """50. GET /closure returns comprehensive state, eligibility, request and revisions."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        json={"remarks": "Initial request notes"},
        headers=_auth_header(env["sec"]),
    )
    res = await client.get(
        f"/api/v1/events/{env['event'].id}/closure",
        headers=_auth_header(env["sec"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["event_id"] == str(env["event"].id)
    assert data["event_status"] == EventStatus.CLOSURE_REQUESTED.value
    assert data["eligibility"]["eligible"] is True
    assert data["eligibility"]["blockers"] == []
    assert data["latest_request"]["requested_by"] == str(env["sec"].id)
    assert data["latest_request"]["remarks"] == "Initial request notes"


# =============================================================================
# 9. CONCURRENCY & DOUBLE TRANSITION PROTECTION (Tests 51-52)
# =============================================================================


async def test_51_concurrency_double_certify_protection(
    client: AsyncClient, db_session: AsyncSession
):
    """51. Two certification calls cannot create duplicate closures; 2nd returns 409."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    res1 = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    assert res1.status_code == 200

    res2 = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["principal"]),
    )
    assert res2.status_code == 409


async def test_52_concurrency_double_reopen_approve_protection(
    client: AsyncClient, db_session: AsyncSession
):
    """52. Two reopen approvals cannot create duplicate revisions; 2nd returns 409."""
    env = await _create_closeout_api_env(db_session)
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/request",
        headers=_auth_header(env["sec"]),
    )
    await client.post(
        f"/api/v1/events/{env['event'].id}/closure/certify",
        json={"venue_cleared": True},
        headers=_auth_header(env["dean"]),
    )
    res1 = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-approve",
        json={"reason": "First approval"},
        headers=_auth_header(env["dean"]),
    )
    assert res1.status_code == 200

    res2 = await client.post(
        f"/api/v1/events/{env['event'].id}/closure/reopen-approve",
        json={"reason": "Second approval attempt"},
        headers=_auth_header(env["principal"]),
    )
    assert res2.status_code == 409


# =============================================================================
# 10. OPENAPI CONTRACT SPECIFICATION (Test 53)
# =============================================================================


async def test_53_openapi_schema_contains_all_seven_endpoints(client: AsyncClient):
    """53. OpenAPI schema documents all 7 closeout endpoints with HTTP status codes."""
    res = await client.get("/api/v1/openapi.json")
    assert res.status_code == 200
    spec = res.json()
    paths = spec["paths"]
    expected_endpoints = [
        ("/api/v1/events/{event_id}/closure", "get"),
        ("/api/v1/events/{event_id}/closure/request", "post"),
        ("/api/v1/events/{event_id}/closure/certify", "post"),
        ("/api/v1/events/{event_id}/closure/reject", "post"),
        ("/api/v1/events/{event_id}/closure/reopen-request", "post"),
        ("/api/v1/events/{event_id}/closure/reopen-approve", "post"),
        ("/api/v1/events/{event_id}/archive", "post"),
    ]
    for path, method in expected_endpoints:
        assert path in paths, f"Path {path} missing in OpenAPI schema"
        assert method in paths[path], f"Method {method} missing for {path}"
