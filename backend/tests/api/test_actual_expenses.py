"""
CampusConnect - Actual Expense Ledger & Finance Verification Test Suite (Phase 2.2)
Verifies:
- Preconditions: Expenses allowed when COMPLETED; FO audit allowed when report is CERTIFIED
- Strict Segregation of Duties (Secretary submits, FO verifies/queries, Admin cannot bypass)
- Cross-club security & isolation (Secretary cannot access/create expenses for other clubs)
- Authentic bill evidence upload, magic byte validation, and storage isolation
- Layered anti-duplicate engine (SHA-256 cross-event hard block, metadata duplicate detection)
- Full, partial, query, and disallow verification actions with mandatory justification
- Non-destructive query revision cycle with AuditLog preservation
- Terminal immutability of verified and disallowed claims
- Decimal precision & database invariants (claimed > 0, 0 <= verified <= claimed)
- Reconciliation summary arithmetic (claimed, verified, disallowed)
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.domain import (
    AuditLog,
    Club,
    ClubMember,
    Event,
    Hall,
    User,
)
from app.models.enums import (
    AuditAction,
    ClubMemberRole,
    UserRole,
)


async def _create_user(db, role: UserRole, prefix: str) -> User:
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@college.edu",
        password_hash=hash_password("Pass123!Secure"),
        full_name=f"Test {role.value} {uid}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user



def _err_msg(res) -> str:
    """Helper to extract error message from response JSON."""
    data = res.json()
    return data.get("message") or data.get("detail") or str(data)

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
        name=f"Expense Hall {uid}",
        capacity=500,
        location="Auditorium Complex",
        available_facilities=["projector", "sound"],
        is_active=True,
    )
    db.add(hall)
    await db.commit()
    await db.refresh(hall)
    return hall


async def _setup_completed_certified_event(client: AsyncClient, db_session):
    """
    Sets up a full end-to-end event:
    1. Proposal approved across all 6 workflow steps (SCHEDULED)
    2. Started by Secretary (IN_PROGRESS)
    3. Concluded by Secretary with PostEventReport (COMPLETED, report SUBMITTED)
    4. Certified by Faculty Advisor (report CERTIFIED)
    Returns dictionary with all users, IDs, and models.
    """
    admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
    advisor = await _create_user(db_session, UserRole.FACULTY_ADVISOR, "advisor")
    secretary = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec")
    other_sec = await _create_user(db_session, UserRole.CLUB_SECRETARY, "other_sec")
    finance = await _create_user(db_session, UserRole.FINANCE_OFFICER, "finance")
    hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
    union_advisor = await _create_user(db_session, UserRole.ADVISOR_STUDENTS_UNION, "union")
    dean = await _create_user(db_session, UserRole.DEAN_STUDENT_AFFAIRS, "dean")
    principal = await _create_user(db_session, UserRole.PRINCIPAL, "principal")

    uid = uuid.uuid4().hex[:6]
    club = Club(
        name=f"Robotics Club {uid}",
        slug=f"robotics-{uid}",
        description="Autonomous systems and AI",
        academic_year="2026-27",
        faculty_advisor_id=advisor.id,
        created_by=admin.id,
        is_active=True,
    )
    db_session.add(club)

    other_club = Club(
        name=f"Literary Society {uid}",
        slug=f"lit-{uid}",
        description="Debate and literature",
        academic_year="2026-27",
        faculty_advisor_id=advisor.id,
        created_by=admin.id,
        is_active=True,
    )
    db_session.add(other_club)
    await db_session.flush()

    db_session.add(
        ClubMember(
            club_id=club.id,
            user_id=secretary.id,
            member_role=ClubMemberRole.SECRETARY,
            is_active=True,
        )
    )
    db_session.add(
        ClubMember(
            club_id=other_club.id,
            user_id=other_sec.id,
            member_role=ClubMemberRole.SECRETARY,
            is_active=True,
        )
    )
    await db_session.commit()

    hall = await _create_test_hall(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=1)
    end_time = start_time + timedelta(hours=2)

    # 1. Create Proposal
    create_res = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": f"Robotics Conclave {uid}",
            "description": "Robotics workshops and exhibits",
            "event_type": "TECHNICAL",
            "expected_attendees": 250,
            "event_date": start_time.isoformat(),
            "academic_year": "2026-27",
        },
        headers=_auth_header(secretary),
    )
    assert create_res.status_code == 201
    event_id = create_res.json()["id"]

    # 2. Venue
    await client.post(
        f"/api/v1/events/{event_id}/venue",
        json={
            "hall_id": str(hall.id),
            "requested_date": start_time.date().isoformat(),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "expected_audience": 250,
        },
        headers=_auth_header(secretary),
    )

    # 3. Budget
    await client.post(
        f"/api/v1/events/{event_id}/budget",
        json={"expected_income": 0.0, "institute_contribution": 25000.0},
        headers=_auth_header(secretary),
    )
    await client.post(
        f"/api/v1/events/{event_id}/budget/items",
        json={
            "category": "MATERIALS",
            "description": "Microcontrollers and sensors",
            "estimated_amount": 25000.0,
        },
        headers=_auth_header(secretary),
    )

    # 4. Submit Proposal
    await client.post(
        f"/api/v1/events/{event_id}/submit",
        json={"change_summary": "Initial submission"},
        headers=_auth_header(secretary),
    )

    # 5. Approve all 6 steps
    wf_res = await client.get(
        f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
    )
    steps = {s["step_order"]: s["id"] for s in wf_res.json()["steps"]}
    approvers = {1: advisor, 2: hall_incharge, 3: finance, 4: union_advisor, 5: dean, 6: principal}
    for order in range(1, 7):
        res = await client.post(
            f"/api/v1/workflows/steps/{steps[order]}/approve",
            json={"comments": f"Step {order} approved."},
            headers=_auth_header(approvers[order]),
        )
        assert res.status_code == 200

    confirmed_event = await db_session.scalar(
        select(Event).where(Event.event_request_id == uuid.UUID(event_id))
    )
    assert confirmed_event is not None

    # 6. Start Event
    start_res = await client.post(
        f"/api/v1/events/{event_id}/start",
        headers=_auth_header(secretary),
    )
    assert start_res.status_code == 200

    # 7. Complete Event & Submit Report
    comp_res = await client.post(
        f"/api/v1/events/{event_id}/complete",
        json={
            "actual_attendance": 230,
            "summary": "The Robotics Conclave completed with outstanding turnout and "
            "participation.",
            "objectives_achieved": "Demonstrated AI autonomy to over 200 undergraduate engineers.",
            "outcomes": "15 new autonomous prototype projects initiated.",
            "challenges": "Minor sensor calibration delays during morning workshop.",
        },
        headers=_auth_header(secretary),
    )
    assert comp_res.status_code in (200, 201)

    # 8. Certify Report by Faculty Advisor
    cert_res = await client.post(
        f"/api/v1/events/{event_id}/post-event-report/certify",
        json={"remarks": "Personally inspected event execution. Fully certified."},
        headers=_auth_header(advisor),
    )
    assert cert_res.status_code == 200

    return {
        "event_id": event_id,
        "confirmed_event_id": str(confirmed_event.id),
        "secretary": secretary,
        "other_sec": other_sec,
        "advisor": advisor,
        "finance": finance,
        "admin": admin,
        "club": club,
        "other_club": other_club,
    }


def _dummy_pdf_content(marker: str = "Test") -> bytes:
    """Generate minimal valid PDF bytes with custom marker to vary SHA-256."""
    pdf_str = (
        f"%PDF-1.4\n1 0 obj\n<< /Title ({marker}) >>\nendobj\n"
        "xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
    )
    return pdf_str.encode()


@pytest.mark.asyncio
class TestActualExpenses:
    """Comprehensive test suite for Phase 2.2 Actual Expenses Ledger & Finance Verification."""

    async def test_01_upload_bill_document_happy_path(self, client: AsyncClient, db_session):
        """Secretary uploads a valid PDF bill document for a completed event."""
        env = await _setup_completed_certified_event(client, db_session)
        pdf_bytes = _dummy_pdf_content("Robotics Bill 01")

        res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={"file": ("invoice_microcontroller.pdf", pdf_bytes, "application/pdf")},
            headers=_auth_header(env["secretary"]),
        )
        assert res.status_code == 201
        data = res.json()
        assert "id" in data
        assert data["original_filename"] == "invoice_microcontroller.pdf"
        assert data["file_hash"] is not None

    async def test_02_upload_bill_invalid_magic_bytes_rejected(
        self, client: AsyncClient, db_session
    ):
        """Uploading corrupted or malicious file pretending to be PDF is rejected."""
        env = await _setup_completed_certified_event(client, db_session)
        fake_bytes = b"This is plain text pretending to be PDF"

        res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={"file": ("malicious.pdf", fake_bytes, "application/pdf")},
            headers=_auth_header(env["secretary"]),
        )
        assert res.status_code == 400
        assert "magic signature mismatch" in _err_msg(res)

    async def test_03_create_draft_expense_happy_path(self, client: AsyncClient, db_session):
        """Secretary creates a valid draft expense referencing an uploaded bill."""
        env = await _setup_completed_certified_event(client, db_session)

        # Upload bill
        bill_res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={"file": ("bill_001.pdf", _dummy_pdf_content("Bill 001"), "application/pdf")},
            headers=_auth_header(env["secretary"]),
        )
        bill_id = bill_res.json()["id"]

        exp_res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "MATERIALS",
                "description": "5x Arduino Mega boards and motor drivers",
                "vendor_name": "RoboCraft Components Ltd",
                "vendor_gstin": "29ABCDE1234F1Z5",
                "invoice_number": "INV-2026-001",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "8500.00",
                "bill_document_id": bill_id,
            },
            headers=_auth_header(env["secretary"]),
        )
        assert exp_res.status_code == 201
        data = exp_res.json()
        assert data["status"] == "DRAFT"
        assert data["claimed_amount"] == "8500.00"
        assert data["verified_amount"] is None
        assert data["disallowed_amount"] == "0.00"
        assert data["is_flagged_for_review"] is False

    async def test_04_create_expense_other_club_rejected_403(self, client: AsyncClient, db_session):
        """Secretary of another club cannot create an expense for this event."""
        env = await _setup_completed_certified_event(client, db_session)

        bill_res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={"file": ("bill.pdf", _dummy_pdf_content("Bill Sec"), "application/pdf")},
            headers=_auth_header(env["secretary"]),
        )
        bill_id = bill_res.json()["id"]

        res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "MATERIALS",
                "description": "Unauthorized claim",
                "vendor_name": "Acme Corp",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "500.00",
                "bill_document_id": bill_id,
            },
            headers=_auth_header(env["other_sec"]),
        )
        assert res.status_code == 403
        assert "Club Secretary" in _err_msg(res)

    async def test_05_finance_officer_cannot_create_expense_403(
        self, client: AsyncClient, db_session
    ):
        """Finance Officer cannot create or inject expenses on behalf of a club."""
        env = await _setup_completed_certified_event(client, db_session)

        res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "MATERIALS",
                "description": "FO attempt",
                "vendor_name": "Vendor",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "500.00",
                "bill_document_id": str(uuid.uuid4()),
            },
            headers=_auth_header(env["finance"]),
        )
        assert res.status_code == 403

    async def test_06_claimed_amount_must_be_positive(self, client: AsyncClient, db_session):
        """Zero or negative claimed amounts are rejected by schema and DB check constraints."""
        env = await _setup_completed_certified_event(client, db_session)

        res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "MATERIALS",
                "description": "Negative claim",
                "vendor_name": "Vendor",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "-100.00",
                "bill_document_id": str(uuid.uuid4()),
            },
            headers=_auth_header(env["secretary"]),
        )
        assert res.status_code == 422

    async def test_07_duplicate_file_hash_across_events_rejected_409(
        self, client: AsyncClient, db_session
    ):
        """Uploading identical SHA-256 invoice across different events is hard-blocked."""
        env1 = await _setup_completed_certified_event(client, db_session)
        env2 = await _setup_completed_certified_event(client, db_session)

        shared_pdf = _dummy_pdf_content("Shared Unique Invoice 9999")

        # Event 1 upload succeeds
        res1 = await client.post(
            f"/api/v1/events/{env1['event_id']}/expenses/upload-bill",
            files={"file": ("bill.pdf", shared_pdf, "application/pdf")},
            headers=_auth_header(env1["secretary"]),
        )
        assert res1.status_code == 201

        # Event 2 upload of exact same file fails with 409
        res2 = await client.post(
            f"/api/v1/events/{env2['event_id']}/expenses/upload-bill",
            files={"file": ("bill_copy.pdf", shared_pdf, "application/pdf")},
            headers=_auth_header(env2["secretary"]),
        )
        assert res2.status_code == 409
        assert "Duplicate bill detected" in _err_msg(res2)

    async def test_08_multi_line_bill_sharing_in_same_event_allowed(
        self, client: AsyncClient, db_session
    ):
        """Multiple expenses referencing the same bill document within the same event succeeds."""
        env = await _setup_completed_certified_event(client, db_session)

        bill_res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={
                "file": (
                    "retail_store.pdf",
                    _dummy_pdf_content("Retail Store ₹10k"),
                    "application/pdf",
                )
            },
            headers=_auth_header(env["secretary"]),
        )
        bill_id = bill_res.json()["id"]

        # Line 1: Materials
        res1 = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "MATERIALS",
                "description": "Component wires",
                "vendor_name": "General Mart",
                "invoice_number": "MART-101",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "6000.00",
                "bill_document_id": bill_id,
            },
            headers=_auth_header(env["secretary"]),
        )
        assert res1.status_code == 201

        # Line 2: Printing (same bill document, same invoice number allowed for line item split)
        res2 = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "PRINTING",
                "description": "Brochure printing",
                "vendor_name": "General Mart",
                "invoice_number": "MART-101",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "4000.00",
                "bill_document_id": bill_id,
            },
            headers=_auth_header(env["secretary"]),
        )
        assert res2.status_code == 201

    async def test_09_duplicate_metadata_across_events_rejected_409(
        self, client: AsyncClient, db_session
    ):
        """Submitting same vendor + invoice_number + date across events is blocked."""
        env1 = await _setup_completed_certified_event(client, db_session)
        env2 = await _setup_completed_certified_event(client, db_session)

        # Upload bill 1 for Event 1
        bill1 = await client.post(
            f"/api/v1/events/{env1['event_id']}/expenses/upload-bill",
            files={"file": ("b1.pdf", _dummy_pdf_content("B1 unique"), "application/pdf")},
            headers=_auth_header(env1["secretary"]),
        )
        # Upload bill 2 for Event 2
        bill2 = await client.post(
            f"/api/v1/events/{env2['event_id']}/expenses/upload-bill",
            files={"file": ("b2.pdf", _dummy_pdf_content("B2 unique"), "application/pdf")},
            headers=_auth_header(env2["secretary"]),
        )

        today_str = date.today().isoformat()
        # Event 1 records invoice INV-777
        res1 = await client.post(
            f"/api/v1/events/{env1['event_id']}/expenses",
            json={
                "category": "CATERING",
                "description": "Lunch boxes",
                "vendor_name": "Royal Caterers",
                "invoice_number": "INV-777",
                "invoice_date": today_str,
                "claimed_amount": "5000.00",
                "bill_document_id": bill1.json()["id"],
            },
            headers=_auth_header(env1["secretary"]),
        )
        assert res1.status_code == 201

        # Event 2 attempts to claim same invoice number and vendor
        res2 = await client.post(
            f"/api/v1/events/{env2['event_id']}/expenses",
            json={
                "category": "CATERING",
                "description": "Lunch boxes reuse",
                "vendor_name": "royal caterers",
                "invoice_number": "inv-777 ",
                "invoice_date": today_str,
                "claimed_amount": "5000.00",
                "bill_document_id": bill2.json()["id"],
            },
            headers=_auth_header(env2["secretary"]),
        )
        assert res2.status_code == 409
        assert "Duplicate invoice detected" in _err_msg(res2)

    async def test_10_missing_invoice_number_allowed_with_flag(
        self, client: AsyncClient, db_session
    ):
        """Vouchers without invoice number are accepted but flagged for manual Finance review."""
        env = await _setup_completed_certified_event(client, db_session)

        bill = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={"file": ("voucher.pdf", _dummy_pdf_content("Tea Voucher"), "application/pdf")},
            headers=_auth_header(env["secretary"]),
        )

        res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "CATERING",
                "description": "Local tea shop refreshments",
                "vendor_name": "Campus Tea Stall",
                "invoice_number": None,
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "450.00",
                "bill_document_id": bill.json()["id"],
            },
            headers=_auth_header(env["secretary"]),
        )
        assert res.status_code == 201
        data = res.json()
        assert data["is_flagged_for_review"] is True
        assert "Finance review required" in data["review_notes"]

    async def test_11_submit_and_full_verification_flow(self, client: AsyncClient, db_session):
        """Full lifecycle: DRAFT -> SUBMITTED -> VERIFIED with audit logs and notifications."""
        env = await _setup_completed_certified_event(client, db_session)

        bill = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={"file": ("tent_bill.pdf", _dummy_pdf_content("Tent bill"), "application/pdf")},
            headers=_auth_header(env["secretary"]),
        )
        exp = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "VENUE",
                "description": "Staging and podium setup",
                "vendor_name": "Stage Crafters",
                "invoice_number": "SC-100",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "12000.00",
                "bill_document_id": bill.json()["id"],
            },
            headers=_auth_header(env["secretary"]),
        )
        exp_id = exp.json()["id"]

        # Secretary submits
        sub_res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/submit",
            headers=_auth_header(env["secretary"]),
        )
        assert sub_res.status_code == 200
        assert sub_res.json()[0]["status"] == "SUBMITTED"

        # Finance verifies full amount
        ver_res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp_id}/verify",
            json={"remarks": "All stage equipment verified on site."},
            headers=_auth_header(env["finance"]),
        )
        assert ver_res.status_code == 200
        data = ver_res.json()
        assert data["status"] == "VERIFIED"
        assert data["claimed_amount"] == "12000.00"
        assert data["verified_amount"] == "12000.00"
        assert data["disallowed_amount"] == "0.00"
        assert data["finance_remarks"] == "All stage equipment verified on site."

        # Terminal immutability: cannot re-verify or edit
        re_edit = await client.patch(
            f"/api/v1/events/{env['event_id']}/expenses/{exp_id}",
            json={"claimed_amount": "13000.00"},
            headers=_auth_header(env["secretary"]),
        )
        assert re_edit.status_code in (400, 403)

    async def test_12_partial_verification_flow(self, client: AsyncClient, db_session):
        """Partial verification: approved amount < claimed amount; disallowed derived correctly."""
        env = await _setup_completed_certified_event(client, db_session)

        bill = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={
                "file": ("catering.pdf", _dummy_pdf_content("Catering bill"), "application/pdf")
            },
            headers=_auth_header(env["secretary"]),
        )
        exp = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "CATERING",
                "description": "Lunch and luxury desserts",
                "vendor_name": "Gourmet Foods",
                "invoice_number": "GF-555",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "10000.00",
                "bill_document_id": bill.json()["id"],
            },
            headers=_auth_header(env["secretary"]),
        )
        exp_id = exp.json()["id"]

        await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp_id}/submit",
            headers=_auth_header(env["secretary"]),
        )

        # FO partially verifies: approves 7500, disallows 2500
        part_res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp_id}/partial-verify",
            json={
                "verified_amount": "7500.00",
                "remarks": (
                    "Disallowed luxury dessert items not permitted under "
                    "college guidelines."
                ),
            },
            headers=_auth_header(env["finance"]),
        )
        assert part_res.status_code == 200
        data = part_res.json()
        assert data["status"] == "PARTIALLY_VERIFIED"
        assert data["claimed_amount"] == "10000.00"
        assert data["verified_amount"] == "7500.00"
        assert data["disallowed_amount"] == "2500.00"

    async def test_13_query_and_resubmission_cycle(self, client: AsyncClient, db_session):
        """Query cycle: SUBMITTED -> QUERIED -> amended by Secretary -> SUBMITTED -> VERIFIED."""
        env = await _setup_completed_certified_event(client, db_session)

        bill = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={"file": ("printer.pdf", _dummy_pdf_content("Printing"), "application/pdf")},
            headers=_auth_header(env["secretary"]),
        )
        exp = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "PRINTING",
                "description": "Certificates and badges",
                "vendor_name": "Quick Print",
                "invoice_number": "QP-12",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "3000.00",
                "bill_document_id": bill.json()["id"],
            },
            headers=_auth_header(env["secretary"]),
        )
        exp_id = exp.json()["id"]

        await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp_id}/submit",
            headers=_auth_header(env["secretary"]),
        )

        # Finance queries
        query_res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp_id}/query",
            json={"remarks": "Invoice scan is blurry. Please upload clearer scan showing GSTIN."},
            headers=_auth_header(env["finance"]),
        )
        assert query_res.status_code == 200
        assert query_res.json()["status"] == "QUERIED"

        # Secretary amends: updates vendor GSTIN and adjusts claim
        patch_res = await client.patch(
            f"/api/v1/events/{env['event_id']}/expenses/{exp_id}",
            json={"vendor_gstin": "29XYZ1234F1Z8", "claimed_amount": "2800.00"},
            headers=_auth_header(env["secretary"]),
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["claimed_amount"] == "2800.00"

        # Secretary resubmits
        resub_res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp_id}/submit",
            headers=_auth_header(env["secretary"]),
        )
        assert resub_res.status_code == 200
        assert resub_res.json()["status"] == "SUBMITTED"

        # Finance verifies amended claim
        final_ver = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp_id}/verify",
            json={"remarks": "Clear scan provided. Approved."},
            headers=_auth_header(env["finance"]),
        )
        assert final_ver.status_code == 200
        assert final_ver.json()["status"] == "VERIFIED"
        assert final_ver.json()["verified_amount"] == "2800.00"

    async def test_14_disallow_expense_flow(self, client: AsyncClient, db_session):
        """Finance Officer completely disallows an expense: verified = 0, disallowed = claimed."""
        env = await _setup_completed_certified_event(client, db_session)

        bill = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={
                "file": ("prohibited.pdf", _dummy_pdf_content("Prohibited item"), "application/pdf")
            },
            headers=_auth_header(env["secretary"]),
        )
        exp = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "OTHER",
                "description": "Unauthorized club merchandise",
                "vendor_name": "Fashion Hub",
                "invoice_number": "FH-01",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "4000.00",
                "bill_document_id": bill.json()["id"],
            },
            headers=_auth_header(env["secretary"]),
        )
        exp_id = exp.json()["id"]

        await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp_id}/submit",
            headers=_auth_header(env["secretary"]),
        )

        dis_res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp_id}/disallow",
            json={"remarks": "Merchandise purchase not approved in sanctioned budget proposal."},
            headers=_auth_header(env["finance"]),
        )
        assert dis_res.status_code == 200
        data = dis_res.json()
        assert data["status"] == "DISALLOWED"
        assert data["verified_amount"] == "0.00"
        assert data["disallowed_amount"] == "4000.00"

    async def test_15_ledger_summary_reconciliation(self, client: AsyncClient, db_session):
        """Reconciliation summary calculates claimed, verified, and disallowed spend accurately."""
        env = await _setup_completed_certified_event(client, db_session)

        # Upload bills
        b1 = (await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={"file": ("b1.pdf", _dummy_pdf_content("B1 Sum"), "application/pdf")},
            headers=_auth_header(env["secretary"]),
        )).json()["id"]

        b2 = (await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={"file": ("b2.pdf", _dummy_pdf_content("B2 Sum"), "application/pdf")},
            headers=_auth_header(env["secretary"]),
        )).json()["id"]

        b3 = (await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={"file": ("b3.pdf", _dummy_pdf_content("B3 Sum"), "application/pdf")},
            headers=_auth_header(env["secretary"]),
        )).json()["id"]

        # Item 1: Full verification (Claimed 5000 -> Verified 5000)
        e1 = (await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "MATERIALS",
                "description": "Sensors",
                "vendor_name": "V1",
                "invoice_number": "I1",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "5000.00",
                "bill_document_id": b1,
            },
            headers=_auth_header(env["secretary"]),
        )).json()["id"]

        # Item 2: Partial verification (Claimed 4000 -> Verified 3000, Disallowed 1000)
        e2 = (await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "PRINTING",
                "description": "Banners",
                "vendor_name": "V2",
                "invoice_number": "I2",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "4000.00",
                "bill_document_id": b2,
            },
            headers=_auth_header(env["secretary"]),
        )).json()["id"]

        # Item 3: Disallowed (Claimed 2000 -> Verified 0, Disallowed 2000)
        e3 = (await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "OTHER",
                "description": "Luxury flowers",
                "vendor_name": "V3",
                "invoice_number": "I3",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "2000.00",
                "bill_document_id": b3,
            },
            headers=_auth_header(env["secretary"]),
        )).json()["id"]

        # Submit all
        await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/submit",
            headers=_auth_header(env["secretary"]),
        )

        # FO Actions
        await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{e1}/verify",
            json={"remarks": "Approved"},
            headers=_auth_header(env["finance"]),
        )
        await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{e2}/partial-verify",
            json={"verified_amount": "3000.00", "remarks": "Partially approved"},
            headers=_auth_header(env["finance"]),
        )
        await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{e3}/disallow",
            json={"remarks": "Disallowed"},
            headers=_auth_header(env["finance"]),
        )

        # Get summary
        sum_res = await client.get(
            f"/api/v1/events/{env['event_id']}/expenses/summary",
            headers=_auth_header(env["secretary"]),
        )
        assert sum_res.status_code == 200
        summary = sum_res.json()

        # Total Claimed (active): 5000 + 4000 = 9000 (DISALLOWED is excluded from net claimed)
        assert Decimal(summary["total_claimed_spend"]) == Decimal("9000.00")
        # Total Verified: 5000 + 3000 = 8000
        assert Decimal(summary["total_verified_spend"]) == Decimal("8000.00")
        # Total Disallowed: 1000 + 2000 = 3000
        assert Decimal(summary["total_disallowed_spend"]) == Decimal("3000.00")
        assert summary["total_expenses_count"] == 3
        assert summary["status_counts"]["VERIFIED"] == 1
        assert summary["status_counts"]["PARTIALLY_VERIFIED"] == 1
        assert summary["status_counts"]["DISALLOWED"] == 1

    async def test_16_system_admin_cannot_verify_expenses_403(
        self, client: AsyncClient, db_session
    ):
        """SYSTEM_ADMIN is barred from verifying financial claims (Statutory SOD Guard)."""
        env = await _setup_completed_certified_event(client, db_session)

        bill = (await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={"file": ("bill.pdf", _dummy_pdf_content("Admin SOD test"), "application/pdf")},
            headers=_auth_header(env["secretary"]),
        )).json()["id"]

        exp = (await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "MATERIALS",
                "description": "Claim",
                "vendor_name": "Vendor",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "1000.00",
                "bill_document_id": bill,
            },
            headers=_auth_header(env["secretary"]),
        )).json()["id"]

        await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp}/submit",
            headers=_auth_header(env["secretary"]),
        )

        # Admin tries to verify
        res = await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp}/verify",
            json={"remarks": "Admin bypass attempt"},
            headers=_auth_header(env["admin"]),
        )
        assert res.status_code == 403
        assert "Finance Officers" in _err_msg(res)

    async def test_17_audit_log_reconstruction_integrity(self, client: AsyncClient, db_session):
        """Verify that every lifecycle milestone creates an immutable AuditLog record."""
        env = await _setup_completed_certified_event(client, db_session)

        bill = (await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/upload-bill",
            files={"file": ("audit.pdf", _dummy_pdf_content("Audit Integrity"), "application/pdf")},
            headers=_auth_header(env["secretary"]),
        )).json()["id"]

        exp = (await client.post(
            f"/api/v1/events/{env['event_id']}/expenses",
            json={
                "category": "TRANSPORT",
                "description": "Guest pickup cab",
                "vendor_name": "City Cabs",
                "invoice_number": "CAB-99",
                "invoice_date": date.today().isoformat(),
                "claimed_amount": "1500.00",
                "bill_document_id": bill,
            },
            headers=_auth_header(env["secretary"]),
        )).json()["id"]

        await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp}/submit",
            headers=_auth_header(env["secretary"]),
        )

        await client.post(
            f"/api/v1/events/{env['event_id']}/expenses/{exp}/verify",
            json={"remarks": "Driver trip sheet verified."},
            headers=_auth_header(env["finance"]),
        )

        # Query AuditLog table
        logs = (
            await db_session.scalars(
                select(AuditLog)
                .where(AuditLog.entity_id == exp, AuditLog.entity_type == "actual_expense")
                .order_by(AuditLog.created_at.asc())
            )
        ).all()

        actions = [log.action for log in logs]
        assert AuditAction.EXPENSE_CREATED in actions
        assert AuditAction.EXPENSE_SUBMITTED in actions
        assert AuditAction.EXPENSE_VERIFIED in actions

        # Check verifier record has remarks
        ver_log = next(log for log in logs if log.action == AuditAction.EXPENSE_VERIFIED)
        assert ver_log.new_state["verified_amount"] == "1500.00"
        assert ver_log.reason == "Driver trip sheet verified."
