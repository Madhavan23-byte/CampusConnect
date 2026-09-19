"""
CampusConnect — Budget Proposal & Financial Line Item API Test Suite

Comprehensive tests for Day 4.3:
- Budget proposal creation & line item categorization
- Club secretary ownership & cross-club isolation
- Server-calculated financial arithmetic & Decimal integrity
- Non-negative and decimal scale validation
- ₹30,000 institutional contribution cap policy enforcement
- Automatic server-side total recalculation on line item add/update/delete
- Proposal submission immutability & version snapshot verification
- Revision workflow editing support
- Finance Officer independent pre-audit verification (VERIFIED / QUERIED)
- Transactional audit trail with zero credential leakage
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.domain import (
    AuditLog,
    BudgetLineItem,
    BudgetProposal,
    Club,
    ClubMember,
    EventRequest,
    EventRequestVersion,
    User,
)
from app.models.enums import (
    AuditAction,
    BudgetLineItemCategory,
    ClubMemberRole,
    EventRequestStatus,
    EventType,
    FinanceVerificationStatus,
    UserRole,
)


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------
async def _create_user(
    db,
    role: UserRole | str,
    prefix: str,
    is_active: bool = True,
    is_deleted: bool = False,
) -> User:
    """Create a verified test user."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@college.edu",
        password_hash=hash_password("Pass123!Secure"),
        full_name=f"Test {role} {uid}",
        role=role,
        is_active=is_active,
        deleted_at=datetime.now(timezone.utc) if is_deleted else None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _auth_header(user: User) -> dict[str, str]:
    """Generate authorization header for a test user."""
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token(
        subject=user.id,
        role=role_str,
        email=user.email,
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_club_and_secretary(
    db,
    club_name: str,
    admin: User,
    is_active: bool = True,
    is_deleted: bool = False,
) -> tuple[Club, User]:
    """Create a club and assign an active secretary."""
    uid = uuid.uuid4().hex[:6]
    slug = f"{club_name.lower().replace(' ', '-')}-{uid}"
    club = Club(
        name=f"{club_name} {uid}",
        slug=slug,
        description="A prominent student organization",
        academic_year="2026-27",
        is_active=is_active,
        created_by=admin.id,
        deleted_at=datetime.now(timezone.utc) if is_deleted else None,
    )
    db.add(club)
    await db.commit()
    await db.refresh(club)

    secretary = await _create_user(db, UserRole.CLUB_SECRETARY, f"sec_{uid}")
    member = ClubMember(
        club_id=club.id,
        user_id=secretary.id,
        member_role=ClubMemberRole.SECRETARY,
        is_active=True,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return club, secretary


async def _create_event_draft(
    db,
    club: Club,
    secretary: User,
    attendees: int = 100,
) -> EventRequest:
    """Create an event draft directly in database."""
    event = EventRequest(
        id=uuid.uuid4(),
        club_id=club.id,
        submitted_by=secretary.id,
        title="National Robotics Conclave",
        description="Annual multi-track robotics competition and symposium",
        event_type=EventType.TECHNICAL,
        expected_attendees=attendees,
        academic_year="2026-27",
        status=EventRequestStatus.DRAFT,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


# ===========================================================================
# 1. BUDGET PROPOSAL CREATION & AUTHORIZATION
# ===========================================================================
@pytest.mark.asyncio
class TestBudgetProposalCreation:
    """Tests for creating budget proposals with itemized costs."""

    async def test_01_authorized_secretary_can_create_budget_with_line_items(
        self, client: AsyncClient, db_session
    ):
        """1. Authorized club secretary can attach a budget proposal with line items."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Aero Club", admin)
        event = await _create_event_draft(db_session, club, secretary)

        payload = {
            "expected_income": "5000.00",
            "institute_contribution": "15000.00",
            "notes": "Expected revenue from delegate registration fees.",
            "line_items": [
                {
                    "description": "Guest Speaker Memento & Honorarium",
                    "category": "HONORARIUM",
                    "estimated_amount": "8000.00",
                    "notes": "2 speakers @ 4000",
                },
                {
                    "description": "Flyers & Delegate Badges",
                    "category": "PRINTING",
                    "estimated_amount": "4000.00",
                },
                {
                    "description": "Refreshments & High Tea",
                    "category": "CATERING",
                    "estimated_amount": "8000.00",
                },
            ],
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/budget", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 201
        data = res.json()
        assert data["event_request_id"] == str(event.id)
        assert data["expected_income"] == "5000.00"
        assert data["institute_contribution"] == "15000.00"
        assert data["total_expected_expenditure"] == "20000.00"
        assert data["finance_status"] == "PENDING"
        assert len(data["line_items"]) == 3

        # Verify audit log
        audit = await db_session.scalar(
            select(AuditLog).where(
                AuditLog.action == AuditAction.PROPOSAL_UPDATED,
                AuditLog.entity_id == data["id"],
            )
        )
        assert audit is not None
        assert audit.actor_id == secretary.id

    async def test_02_secretary_cannot_create_budget_for_other_clubs_event(
        self, client: AsyncClient, db_session
    ):
        """2. Secretary from Club B cannot attach budget to Club A's event proposal."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club_a, sec_a = await _create_club_and_secretary(db_session, "Club Alpha", admin)
        club_b, sec_b = await _create_club_and_secretary(db_session, "Club Beta", admin)
        event_a = await _create_event_draft(db_session, club_a, sec_a)

        payload = {
            "expected_income": "0.00",
            "institute_contribution": "5000.00",
            "line_items": [
                {
                    "description": "Materials",
                    "category": "MATERIALS",
                    "estimated_amount": "5000.00",
                }
            ],
        }
        res = await client.post(
            f"/api/v1/events/{event_a.id}/budget", json=payload, headers=_auth_header(sec_b)
        )
        assert res.status_code == 403

    async def test_03_unauthorized_roles_cannot_create_budget(
        self, client: AsyncClient, db_session
    ):
        """3. Faculty Advisor or General Member cannot create a budget proposal."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Music Society", admin)
        event = await _create_event_draft(db_session, club, secretary)

        faculty = await _create_user(db_session, UserRole.FACULTY_ADVISOR, "fac")
        payload = {
            "expected_income": "0.00",
            "institute_contribution": "1000.00",
            "line_items": [
                {
                    "description": "Sheet Music",
                    "category": "MATERIALS",
                    "estimated_amount": "1000.00",
                }
            ],
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/budget", json=payload, headers=_auth_header(faculty)
        )
        assert res.status_code == 403

    async def test_04_cannot_create_second_budget_for_same_proposal(
        self, client: AsyncClient, db_session
    ):
        """4. 1-to-1 constraint: Cannot attach a second budget proposal to the same event."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Film Club", admin)
        event = await _create_event_draft(db_session, club, secretary)

        payload = {
            "expected_income": "0.00",
            "institute_contribution": "3000.00",
            "line_items": [
                {
                    "description": "Screen Rental",
                    "category": "VENUE",
                    "estimated_amount": "3000.00",
                }
            ],
        }
        res1 = await client.post(
            f"/api/v1/events/{event.id}/budget", json=payload, headers=_auth_header(secretary)
        )
        assert res1.status_code == 201

        # Second attempt must return 409 Conflict
        res2 = await client.post(
            f"/api/v1/events/{event.id}/budget", json=payload, headers=_auth_header(secretary)
        )
        assert res2.status_code == 409


# ===========================================================================
# 2. MONEY INTEGRITY, CAP POLICY, & ARITHMETIC VALIDATION
# ===========================================================================
@pytest.mark.asyncio
class TestMoneyIntegrityAndValidation:
    """Tests for financial decimals, non-negative bounds, and policy ceilings."""

    async def test_01_negative_amounts_rejected(self, client: AsyncClient, db_session):
        """1. Negative income or contribution rejected with 422 Unprocessable Entity."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Math Club", admin)
        event = await _create_event_draft(db_session, club, secretary)

        payload = {
            "expected_income": "-500.00",
            "institute_contribution": "1000.00",
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/budget", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 422

    async def test_02_zero_estimated_amount_in_line_item_rejected(
        self, client: AsyncClient, db_session
    ):
        """2. Line item with zero amount rejected with 422 (must be strictly > 0)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Coding Club", admin)
        event = await _create_event_draft(db_session, club, secretary)

        payload = {
            "expected_income": "0.00",
            "institute_contribution": "0.00",
            "line_items": [
                {
                    "description": "Free Service",
                    "category": "OTHER",
                    "estimated_amount": "0.00",
                }
            ],
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/budget", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code in (400, 422)

    async def test_03_excessive_decimal_places_rejected(
        self, client: AsyncClient, db_session
    ):
        """3. Amounts with more than 2 decimal places (e.g. 10.555) rejected with 422."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Physics Club", admin)
        event = await _create_event_draft(db_session, club, secretary)

        payload = {
            "expected_income": "0.00",
            "institute_contribution": "1000.555",
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/budget", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 422

    async def test_04_institutional_cap_exceeded_rejected(
        self, client: AsyncClient, db_session
    ):
        """4. Institutional contribution exceeding ₹30,000 cap rejected with 422 BudgetCapExceededError."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Mega Club", admin)
        event = await _create_event_draft(db_session, club, secretary)

        # ₹35,000 exceeds ₹30,000 cap
        payload = {
            "expected_income": "0.00",
            "institute_contribution": "35000.00",
            "line_items": [
                {
                    "description": "Grand Stage",
                    "category": "VENUE",
                    "estimated_amount": "35000.00",
                }
            ],
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/budget", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 422
        body = res.json()
        msg = body.get("message") or body.get("detail", "")
        assert "exceeds" in str(msg).lower() or "ceiling" in str(msg).lower()

    async def test_05_income_plus_contribution_exceeding_expenditure_rejected(
        self, client: AsyncClient, db_session
    ):
        """5. Income + Contribution exceeding total line-item expenditure rejected with 400."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Finance Club", admin)
        event = await _create_event_draft(db_session, club, secretary)

        payload = {
            "expected_income": "5000.00",
            "institute_contribution": "10000.00",  # total funding = 15,000
            "line_items": [
                {
                    "description": "Minor Expenses",
                    "category": "MATERIALS",
                    "estimated_amount": "5000.00",  # expenditure = 5,000 (15,000 > 5,000)
                }
            ],
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/budget", json=payload, headers=_auth_header(secretary)
        )
        assert res.status_code == 400
        body = res.json()
        msg = body.get("message") or body.get("detail", "")
        assert "cannot exceed total expenditure" in str(msg).lower()


# ===========================================================================
# 3. LINE ITEM MANAGEMENT & SERVER-SIDE RECALCULATION
# ===========================================================================
@pytest.mark.asyncio
class TestLineItemManagement:
    """Tests for adding, modifying, and removing line items with automatic total recalculation."""

    async def test_01_line_item_crud_and_recalculation(
        self, client: AsyncClient, db_session
    ):
        """1. Add, update, and delete line items; server accurately recalculates total_expected_expenditure."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Drama Society", admin)
        event = await _create_event_draft(db_session, club, secretary)

        # Create budget with one item of 2000
        bp_res = await client.post(
            f"/api/v1/events/{event.id}/budget",
            json={
                "expected_income": "0.00",
                "institute_contribution": "2000.00",
                "line_items": [
                    {
                        "description": "Costumes",
                        "category": "MATERIALS",
                        "estimated_amount": "2000.00",
                    }
                ],
            },
            headers=_auth_header(secretary),
        )
        assert bp_res.status_code == 201
        assert bp_res.json()["total_expected_expenditure"] == "2000.00"

        # 1. Add second line item of 3000 -> Total should become 5000
        item_payload = {
            "description": "Stage Makeup & Props",
            "category": "DECORATION",
            "estimated_amount": "3000.00",
        }
        item_res = await client.post(
            f"/api/v1/events/{event.id}/budget/items",
            json=item_payload,
            headers=_auth_header(secretary),
        )
        assert item_res.status_code == 201
        item_id = item_res.json()["id"]

        # Check budget total after addition
        get_bp = await client.get(
            f"/api/v1/events/{event.id}/budget", headers=_auth_header(secretary)
        )
        assert get_bp.json()["total_expected_expenditure"] == "5000.00"
        assert len(get_bp.json()["line_items"]) == 2

        # 2. Update line item from 3000 to 4500 -> Total should become 6500
        patch_res = await client.patch(
            f"/api/v1/events/{event.id}/budget/items/{item_id}",
            json={"estimated_amount": "4500.00", "description": "Professional Makeup"},
            headers=_auth_header(secretary),
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["estimated_amount"] == "4500.00"

        get_bp_updated = await client.get(
            f"/api/v1/events/{event.id}/budget", headers=_auth_header(secretary)
        )
        assert get_bp_updated.json()["total_expected_expenditure"] == "6500.00"

        # 3. Delete line item -> Total should revert to 2000
        del_res = await client.delete(
            f"/api/v1/events/{event.id}/budget/items/{item_id}",
            headers=_auth_header(secretary),
        )
        assert del_res.status_code == 204

        get_bp_final = await client.get(
            f"/api/v1/events/{event.id}/budget", headers=_auth_header(secretary)
        )
        assert get_bp_final.json()["total_expected_expenditure"] == "2000.00"
        assert len(get_bp_final.json()["line_items"]) == 1


# ===========================================================================
# 4. LIFECYCLE, IMMUTABILITY, & SUBMISSION SNAPSHOT
# ===========================================================================
@pytest.mark.asyncio
class TestBudgetLifecycleAndImmutability:
    """Tests for budget freezing on submission and version snapshotting."""

    async def test_01_submitted_proposal_freezes_budget(
        self, client: AsyncClient, db_session
    ):
        """1. Once proposal is SUBMITTED, budget and line items are frozen and cannot be modified."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Sports Union", admin)
        event = await _create_event_draft(db_session, club, secretary)

        # Attach budget
        await client.post(
            f"/api/v1/events/{event.id}/budget",
            json={
                "expected_income": "0.00",
                "institute_contribution": "4000.00",
                "line_items": [
                    {
                        "description": "Footballs & Cones",
                        "category": "MATERIALS",
                        "estimated_amount": "4000.00",
                    }
                ],
            },
            headers=_auth_header(secretary),
        )

        # Submit event proposal
        submit_res = await client.post(
            f"/api/v1/events/{event.id}/submit",
            json={"submission_notes": "Submitting sports event with budget"},
            headers=_auth_header(secretary),
        )
        assert submit_res.status_code == 200
        assert submit_res.json()["status"] == "SUBMITTED"

        # Attempt to PATCH budget must fail with 403 WorkflowStateError
        patch_res = await client.patch(
            f"/api/v1/events/{event.id}/budget",
            json={"notes": "Late addition"},
            headers=_auth_header(secretary),
        )
        assert patch_res.status_code == 403

        # Attempt to add line item must fail with 403 WorkflowStateError
        item_res = await client.post(
            f"/api/v1/events/{event.id}/budget/items",
            json={
                "description": "Extra Whistles",
                "category": "MATERIALS",
                "estimated_amount": "500.00",
            },
            headers=_auth_header(secretary),
        )
        assert item_res.status_code == 403

        # Attempt to DELETE budget must fail with 403 WorkflowStateError
        del_res = await client.delete(
            f"/api/v1/events/{event.id}/budget",
            headers=_auth_header(secretary),
        )
        assert del_res.status_code == 403

    async def test_02_submitted_proposal_contains_budget_in_version_snapshot(
        self, client: AsyncClient, db_session
    ):
        """2. Version snapshot created on submission contains complete budget and line items."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "History Club", admin)
        event = await _create_event_draft(db_session, club, secretary)

        # Attach budget
        await client.post(
            f"/api/v1/events/{event.id}/budget",
            json={
                "expected_income": "1000.00",
                "institute_contribution": "5000.00",
                "line_items": [
                    {
                        "description": "Museum Tickets",
                        "category": "TRANSPORT",
                        "estimated_amount": "6000.00",
                    }
                ],
            },
            headers=_auth_header(secretary),
        )

        # Submit
        await client.post(
            f"/api/v1/events/{event.id}/submit",
            json={"submission_notes": "Field trip budget finalized"},
            headers=_auth_header(secretary),
        )

        # Verify EventRequestVersion record directly in DB
        version = await db_session.scalar(
            select(EventRequestVersion).where(
                EventRequestVersion.event_request_id == event.id,
                EventRequestVersion.version_number == 1,
            )
        )
        assert version is not None
        assert "budget" in version.snapshot
        budget_snap = version.snapshot["budget"]
        assert budget_snap["expected_income"] == "1000.00"
        assert budget_snap["institute_contribution"] == "5000.00"
        assert budget_snap["total_expected_expenditure"] == "6000.00"
        assert len(budget_snap["line_items"]) == 1
        assert budget_snap["line_items"][0]["description"] == "Museum Tickets"


# ===========================================================================
# 5. FINANCE OFFICER INDEPENDENT PRE-AUDIT VERIFICATION
# ===========================================================================
@pytest.mark.asyncio
class TestFinanceOfficerVerification:
    """Tests for Finance Officer review marking budget as VERIFIED or QUERIED."""

    async def test_01_finance_officer_can_verify_budget(
        self, client: AsyncClient, db_session
    ):
        """1. Finance Officer can mark submitted budget as VERIFIED."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Tech Council", admin)
        event = await _create_event_draft(db_session, club, secretary)

        await client.post(
            f"/api/v1/events/{event.id}/budget",
            json={
                "expected_income": "0.00",
                "institute_contribution": "10000.00",
                "line_items": [
                    {
                        "description": "Cloud Servers",
                        "category": "TECHNOLOGY",
                        "estimated_amount": "10000.00",
                    }
                ],
            },
            headers=_auth_header(secretary),
        )

        finance_officer = await _create_user(db_session, UserRole.FINANCE_OFFICER, "fo")

        # Verify budget
        payload = {
            "status": "VERIFIED",
            "notes": "Cost estimate aligns with standard institutional IT rates.",
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/budget/verify",
            json=payload,
            headers=_auth_header(finance_officer),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["finance_status"] == "VERIFIED"
        assert data["finance_verified_by"] == str(finance_officer.id)
        assert data["finance_notes"] == payload["notes"]

        # Check audit log
        audit = await db_session.scalar(
            select(AuditLog).where(
                AuditLog.action == AuditAction.BUDGET_VERIFIED,
                AuditLog.entity_id == data["id"],
            )
        )
        assert audit is not None
        assert audit.actor_id == finance_officer.id

    async def test_02_finance_officer_can_query_budget(
        self, client: AsyncClient, db_session
    ):
        """2. Finance Officer can query budget with clarification request."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Art Collective", admin)
        event = await _create_event_draft(db_session, club, secretary)

        await client.post(
            f"/api/v1/events/{event.id}/budget",
            json={
                "expected_income": "0.00",
                "institute_contribution": "12000.00",
                "line_items": [
                    {
                        "description": "Imported Oil Paints",
                        "category": "MATERIALS",
                        "estimated_amount": "12000.00",
                    }
                ],
            },
            headers=_auth_header(secretary),
        )

        finance_officer = await _create_user(db_session, UserRole.FINANCE_OFFICER, "fo")

        # Query budget
        payload = {
            "status": "QUERIED",
            "notes": "Please provide three competing vendor quotations for imported supplies.",
        }
        res = await client.post(
            f"/api/v1/events/{event.id}/budget/verify",
            json=payload,
            headers=_auth_header(finance_officer),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["finance_status"] == "QUERIED"
        assert data["finance_notes"] == payload["notes"]

        # Check audit log
        audit = await db_session.scalar(
            select(AuditLog).where(
                AuditLog.action == AuditAction.BUDGET_QUERIED,
                AuditLog.entity_id == data["id"],
            )
        )
        assert audit is not None

    async def test_03_non_finance_officer_cannot_verify_budget(
        self, client: AsyncClient, db_session
    ):
        """3. Secretary or general user cannot perform finance verification."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary = await _create_club_and_secretary(db_session, "Lit Club", admin)
        event = await _create_event_draft(db_session, club, secretary)

        await client.post(
            f"/api/v1/events/{event.id}/budget",
            json={
                "expected_income": "0.00",
                "institute_contribution": "5000.00",
            },
            headers=_auth_header(secretary),
        )

        payload = {"status": "VERIFIED", "notes": "Self-verification attempt"}
        res = await client.post(
            f"/api/v1/events/{event.id}/budget/verify",
            json=payload,
            headers=_auth_header(secretary),
        )
        assert res.status_code == 403
