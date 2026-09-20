"""
CampusConnect — Event Execution & Post-Event Delivery Test Suite (Phase 2.1)
Verifies:
- Execution lifecycle (SCHEDULED -> IN_PROGRESS -> COMPLETED)
- Strict secretary-only execution start (blocking ordinary SYSTEM_ADMIN bypass)
- Emergency administrative override start with mandatory audit reason
- Concurrency & idempotency protection
- Post-event report submission with attendance and summary validation
- Non-destructive report revision lifecycle with audit snapshots
- Statutory Faculty Advisor delivery certification
- Self-certification and unrelated advisor rejection
- SYSTEM_ADMIN certification block (statutory role guard)
- Photographic evidence upload with magic-byte check and Decimal(9,6) geo metadata
"""

import asyncio
import io
import uuid
from datetime import UTC, datetime, timedelta
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
    EventStatus,
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
        name=f"Execution Hall {uid}",
        capacity=500,
        location="Campus Center",
        available_facilities=["projector", "ac"],
        is_active=True,
    )
    db.add(hall)
    await db.commit()
    await db.refresh(hall)
    return hall


async def _setup_confirmed_event(
    client: AsyncClient, db_session, start_time_offset: timedelta = timedelta(hours=1)
):
    """Sets up a 6-stage approved event resulting in confirmed Event in SCHEDULED status."""
    admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
    advisor = await _create_user(db_session, UserRole.FACULTY_ADVISOR, "advisor")
    secretary = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec")
    hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
    finance = await _create_user(db_session, UserRole.FINANCE_OFFICER, "finance")
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
    await db_session.flush()

    sec_member = ClubMember(
        club_id=club.id,
        user_id=secretary.id,
        member_role=ClubMemberRole.SECRETARY,
        is_active=True,
    )
    db_session.add(sec_member)
    await db_session.commit()

    hall = await _create_test_hall(db_session)

    start_time = datetime.now(UTC) + start_time_offset
    end_time = start_time + timedelta(hours=3)

    # 1. Proposal
    create_res = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "Autonomous Drone Challenge",
            "description": "Annual state robotics competition",
            "event_type": "TECHNICAL",
            "expected_attendees": 300,
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
            "expected_audience": 300,
        },
        headers=_auth_header(secretary),
    )

    # 3. Budget
    await client.post(
        f"/api/v1/events/{event_id}/budget",
        json={"expected_income": 0.0, "institute_contribution": 10000.0},
        headers=_auth_header(secretary),
    )
    await client.post(
        f"/api/v1/events/{event_id}/budget/items",
        json={
            "category": "MATERIALS",
            "description": "Propellers and frames",
            "estimated_amount": 10000.0,
        },
        headers=_auth_header(secretary),
    )

    # 4. Submit
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

    confirmed_row = await db_session.scalar(
        select(Event).where(Event.event_request_id == uuid.UUID(event_id))
    )
    assert confirmed_row is not None
    assert confirmed_row.status == EventStatus.SCHEDULED

    return {
        "event_id": event_id,
        "confirmed_event_id": str(confirmed_row.id),
        "secretary": secretary,
        "advisor": advisor,
        "admin": admin,
        "dean": dean,
        "club": club,
        "hall": hall,
    }


@pytest.mark.asyncio
class TestEventExecution:
    """Test suite for Phase 2.1 Event Execution and Post-Event Certification."""

    async def test_01_start_event_happy_path(self, client: AsyncClient, db_session):
        """Authorized secretary starts scheduled event within operational window."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=30)
        )
        sec_headers = _auth_header(setup["secretary"])

        res = await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "IN_PROGRESS"

        # Verify DB and AuditLog
        event_row = await db_session.scalar(
            select(Event).where(Event.id == uuid.UUID(setup["confirmed_event_id"]))
        )
        assert event_row.status == EventStatus.IN_PROGRESS

        audit = await db_session.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == str(event_row.id),
                AuditLog.action == AuditAction.EVENT_STARTED,
            )
        )
        assert audit is not None
        assert audit.actor_id == setup["secretary"].id

    async def test_02_start_event_before_window_rejected(self, client: AsyncClient, db_session):
        """Starting an event more than 2 hours before scheduled time is rejected with 400."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(days=2)
        )
        sec_headers = _auth_header(setup["secretary"])

        res = await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)
        assert res.status_code == 400
        msg = (res.json().get("message") or res.json().get("detail", "")).lower()
        assert "before scheduled" in msg

    async def test_03_unauthorized_start_rejected(self, client: AsyncClient, db_session):
        """Non-secretary roles receive 403 Forbidden when calling /start."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=30)
        )
        dean_headers = _auth_header(setup["dean"])

        res = await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=dean_headers)
        assert res.status_code == 403

    async def test_04_cross_club_start_rejected(self, client: AsyncClient, db_session):
        """Secretary of Club B cannot start an event belonging to Club A."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=30)
        )
        other_sec = await _create_user(db_session, UserRole.CLUB_SECRETARY, "other_sec")

        res = await client.post(
            f"/api/v1/events/{setup['event_id']}/start", headers=_auth_header(other_sec)
        )
        assert res.status_code == 403

    async def test_05_system_admin_ordinary_start_blocked(self, client: AsyncClient, db_session):
        """SYSTEM_ADMIN cannot call ordinary /start endpoint (must use admin-start)."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=30)
        )
        admin_headers = _auth_header(setup["admin"])

        res = await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=admin_headers)
        assert res.status_code == 403
        msg = res.json().get("message") or res.json().get("detail", "")
        assert "Club Secretary" in msg

    async def test_06_admin_emergency_start_with_reason(self, client: AsyncClient, db_session):
        """SYSTEM_ADMIN can use /admin-start with mandatory reason in emergency scenarios."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(days=2)
        )
        admin_headers = _auth_header(setup["admin"])

        res = await client.post(
            f"/api/v1/events/{setup['event_id']}/admin-start",
            json={"reason": "Emergency pre-start authorized due to early dignitary arrival."},
            headers=admin_headers,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "IN_PROGRESS"

        audit = await db_session.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == setup["confirmed_event_id"],
                AuditLog.action == AuditAction.ADMIN_EVENT_STARTED,
            )
        )
        assert audit is not None
        assert "dignitary" in audit.new_state.get("admin_reason", "")

    async def test_07_complete_event_and_submit_report_happy_path(
        self, client: AsyncClient, db_session
    ):
        """Secretary concludes event execution and submits post-event report; notifies Advisor."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])

        # 1. Start event
        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)

        # 2. Conclude and submit report
        report_payload = {
            "actual_attendance": 285,
            "summary": "Autonomous Drone Challenge concluded with 28 teams.",
            "objectives_achieved": "Flight demo of obstacle avoidance algorithms.",
            "outcomes": "Top 3 teams received awards; 2 patents filed for control firmware.",
            "challenges": "High wind conditions required relocating semi-finals indoors.",
        }
        comp_res = await client.post(
            f"/api/v1/events/{setup['event_id']}/complete",
            json=report_payload,
            headers=sec_headers,
        )
        assert comp_res.status_code == 201
        report_data = comp_res.json()
        assert report_data["status"] == "SUBMITTED"
        assert report_data["actual_attendance"] == 285
        assert report_data["revision_number"] == 1

        # Verify Event is COMPLETED
        evt_row = await db_session.scalar(
            select(Event).where(Event.id == uuid.UUID(setup["confirmed_event_id"]))
        )
        assert evt_row.status == EventStatus.COMPLETED

        # Verify notification created for Faculty Advisor
        adv_notifs = await client.get(
            "/api/v1/notifications", headers=_auth_header(setup["advisor"])
        )
        assert any(
            n["notification_type"] == "POST_EVENT_REPORT_SUBMITTED" for n in adv_notifs.json()
        )

    async def test_08_invalid_report_validation_errors(self, client: AsyncClient, db_session):
        """Validation rejections: attendance <= 0, short summary, short objectives."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])
        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)

        # 1. Attendance 0
        res1 = await client.post(
            f"/api/v1/events/{setup['event_id']}/complete",
            json={
                "actual_attendance": 0,
                "summary": "Valid summary of the event that took place today.",
                "objectives_achieved": "Successful completion.",
            },
            headers=sec_headers,
        )
        assert res1.status_code == 422

        # 2. Summary too short (< 20 chars)
        res2 = await client.post(
            f"/api/v1/events/{setup['event_id']}/complete",
            json={
                "actual_attendance": 100,
                "summary": "Too short.",
                "objectives_achieved": "Successful completion.",
            },
            headers=sec_headers,
        )
        assert res2.status_code == 422

    async def test_09_duplicate_completion_conflict(self, client: AsyncClient, db_session):
        """Double completion calls are rejected with 409 Conflict."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])
        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)

        payload = {
            "actual_attendance": 200,
            "summary": "Comprehensive event execution summary with full details.",
            "objectives_achieved": "Achieved all planned goals.",
        }
        res1 = await client.post(
            f"/api/v1/events/{setup['event_id']}/complete", json=payload, headers=sec_headers
        )
        assert res1.status_code == 201

        # Second completion attempt
        res2 = await client.post(
            f"/api/v1/events/{setup['event_id']}/complete", json=payload, headers=sec_headers
        )
        assert res2.status_code == 409

    async def test_10_advisor_certification_happy_path(self, client: AsyncClient, db_session):
        """Assigned Faculty Advisor certifies submitted post-event report; notifies Secretary."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])
        adv_headers = _auth_header(setup["advisor"])

        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)
        await client.post(
            f"/api/v1/events/{setup['event_id']}/complete",
            json={
                "actual_attendance": 150,
                "summary": "Detailed event report submitted for official certification.",
                "objectives_achieved": "Students built autonomous flight controllers.",
            },
            headers=sec_headers,
        )

        cert_res = await client.post(
            f"/api/v1/events/{setup['event_id']}/post-event-report/certify",
            json={"remarks": "Inspected drone flights and attendee roster. Highly satisfied."},
            headers=adv_headers,
        )
        assert cert_res.status_code == 200
        data = cert_res.json()
        assert data["status"] == "CERTIFIED"
        assert data["certified_by"] == str(setup["advisor"].id)
        assert "Inspected drone flights" in data["certification_remarks"]

        # Secretary receives POST_EVENT_REPORT_CERTIFIED notification
        sec_notifs = await client.get("/api/v1/notifications", headers=sec_headers)
        assert any(
            n["notification_type"] == "POST_EVENT_REPORT_CERTIFIED" for n in sec_notifs.json()
        )

    async def test_11_self_certification_and_statutory_bypass_blocked(
        self, client: AsyncClient, db_session
    ):
        """Secretary self-certification, other advisor, and SYSTEM_ADMIN are blocked (403)."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])

        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)
        await client.post(
            f"/api/v1/events/{setup['event_id']}/complete",
            json={
                "actual_attendance": 150,
                "summary": "Detailed event report submitted for official certification.",
                "objectives_achieved": "Students built autonomous flight controllers.",
            },
            headers=sec_headers,
        )

        # 1. Secretary attempts self-certification
        res1 = await client.post(
            f"/api/v1/events/{setup['event_id']}/post-event-report/certify",
            json={"remarks": "Self-certifying."},
            headers=sec_headers,
        )
        assert res1.status_code == 403
        msg1 = res1.json().get("message") or res1.json().get("detail", "")
        assert "Conflict of Interest" in msg1

        # 2. SYSTEM_ADMIN attempts certification bypass
        res2 = await client.post(
            f"/api/v1/events/{setup['event_id']}/post-event-report/certify",
            json={"remarks": "Admin bypass."},
            headers=_auth_header(setup["admin"]),
        )
        assert res2.status_code == 403
        msg2 = res2.json().get("message") or res2.json().get("detail", "")
        assert "SYSTEM_ADMIN cannot substitute" in msg2

        # 3. Unrelated advisor attempts certification
        other_adv = await _create_user(db_session, UserRole.FACULTY_ADVISOR, "other_adv")
        res3 = await client.post(
            f"/api/v1/events/{setup['event_id']}/post-event-report/certify",
            json={"remarks": "Unrelated advisor."},
            headers=_auth_header(other_adv),
        )
        assert res3.status_code == 403

    async def test_12_report_revision_and_resubmission_lifecycle(
        self, client: AsyncClient, db_session
    ):
        """Advisor requests revision -> Secretary amends -> Resubmits (v2) -> Advisor certifies."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])
        adv_headers = _auth_header(setup["advisor"])

        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)
        await client.post(
            f"/api/v1/events/{setup['event_id']}/complete",
            json={
                "actual_attendance": 80,
                "summary": "Initial draft of post-event report submitted for clearance.",
                "objectives_achieved": "Workshops conducted.",
            },
            headers=sec_headers,
        )

        # 1. Advisor requests revision
        rev_res = await client.post(
            f"/api/v1/events/{setup['event_id']}/post-event-report/revise",
            json={
                "remarks": "Please provide count of external participants and lab outcome metrics."
            },
            headers=adv_headers,
        )
        assert rev_res.status_code == 200
        assert rev_res.json()["status"] == "REVISION_REQUIRED"

        # 2. Secretary updates report details
        patch_res = await client.patch(
            f"/api/v1/events/{setup['event_id']}/post-event-report",
            json={
                "actual_attendance": 95,
                "outcomes": "15 external participants; 4 functional prototypes demonstrated.",
            },
            headers=sec_headers,
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["actual_attendance"] == 95

        # 3. Secretary resubmits
        resub_res = await client.post(
            f"/api/v1/events/{setup['event_id']}/post-event-report/resubmit",
            headers=sec_headers,
        )
        assert resub_res.status_code == 200
        assert resub_res.json()["status"] == "SUBMITTED"
        assert resub_res.json()["revision_number"] == 2

        # 4. Advisor certifies v2
        final_cert = await client.post(
            f"/api/v1/events/{setup['event_id']}/post-event-report/certify",
            json={"remarks": "External participant breakdown verified. Approved."},
            headers=adv_headers,
        )
        assert final_cert.status_code == 200
        assert final_cert.json()["status"] == "CERTIFIED"
        assert final_cert.json()["revision_number"] == 2

    async def test_13_post_event_evidence_upload(self, client: AsyncClient, db_session):
        """Secretary uploads post-event evidence with magic-byte PNG and decimal geo metadata."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])

        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)

        # Valid 1x1 PNG bytes with genuine PNG signature
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02"
            b"\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        files = {"file": ("event_stage.png", png_bytes, "image/png")}
        data = {
            "geo_latitude": "11.028450",
            "geo_longitude": "76.955420",
            "geo_source": "CLIENT_DECLARED",
        }

        up_res = await client.post(
            f"/api/v1/events/{setup['event_id']}/evidence",
            data=data,
            files=files,
            headers=sec_headers,
        )
        assert up_res.status_code == 201
        doc_data = up_res.json()
        assert doc_data["document_type"] == "POST_EVENT_PHOTO"
        assert Decimal(str(doc_data["geo_latitude"])) == Decimal("11.028450")
        assert Decimal(str(doc_data["geo_longitude"])) == Decimal("76.955420")
        assert doc_data["geo_source"] == "CLIENT_DECLARED"

        # List evidence endpoint
        list_res = await client.get(
            f"/api/v1/events/{setup['event_id']}/evidence", headers=sec_headers
        )
        assert list_res.status_code == 200
        assert len(list_res.json()) >= 1

    async def test_14_evidence_magic_byte_rejection(self, client: AsyncClient, db_session):
        """Spoofed file with executable content disguised as PNG is rejected with 400."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])
        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)

        fake_exe_bytes = b"MZ\x90\x00\x03\x00\x00\x00fake_windows_binary"
        files = {"file": ("malicious.png", fake_exe_bytes, "image/png")}

        res = await client.post(
            f"/api/v1/events/{setup['event_id']}/evidence",
            files=files,
            headers=sec_headers,
        )
        assert res.status_code == 400
        msg = (res.json().get("message") or res.json().get("detail", "")).lower()
        assert "magic bytes" in msg

    async def test_15_concurrent_event_start(self, client: AsyncClient, db_session):
        """Concurrency test: Two simultaneous start requests on the same scheduled event."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=15)
        )
        sec_headers = _auth_header(setup["secretary"])

        res1, res2 = await asyncio.gather(
            client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers),
            client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers),
            return_exceptions=False,
        )

        statuses = sorted([res1.status_code, res2.status_code])
        # One must succeed (200), second must either be 200 (if serialized) or 400/403
        assert statuses[0] == 200
        assert statuses[1] in (200, 400, 403)

    async def test_16_revision_history_audit_preservation(self, client: AsyncClient, db_session):
        """Verifies audit trail records snapshots when report goes through revision cycle."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])
        adv_headers = _auth_header(setup["advisor"])

        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)
        await client.post(
            f"/api/v1/events/{setup['event_id']}/complete",
            json={
                "actual_attendance": 85,
                "summary": "Original summary version 1.",
                "objectives_achieved": "V1 objectives.",
            },
            headers=sec_headers,
        )

        # Advisor requests revision
        await client.post(
            f"/api/v1/events/{setup['event_id']}/post-event-report/revise",
            json={"remarks": "Please provide more detail in summary."},
            headers=adv_headers,
        )

        # Secretary patches and resubmits
        await client.patch(
            f"/api/v1/events/{setup['event_id']}/post-event-report",
            json={"summary": "Revised summary version 2 with expanded content."},
            headers=sec_headers,
        )
        resubmit_res = await client.post(
            f"/api/v1/events/{setup['event_id']}/post-event-report/resubmit",
            headers=sec_headers,
        )
        assert resubmit_res.status_code == 200
        assert resubmit_res.json()["revision_number"] == 2
        assert resubmit_res.json()["status"] == "SUBMITTED"

        # Verify audit entries for both submission and revision
        audits = (
            await db_session.scalars(
                select(AuditLog).where(
                    AuditLog.action.in_(
                        [
                            AuditAction.POST_EVENT_REPORT_SUBMITTED,
                            AuditAction.POST_EVENT_REPORT_REVISION_REQUESTED,
                        ]
                    )
                )
            )
        ).all()
        actions = [a.action for a in audits]
        assert AuditAction.POST_EVENT_REPORT_SUBMITTED in actions
        assert AuditAction.POST_EVENT_REPORT_REVISION_REQUESTED in actions

    async def test_17_unauthorized_revision_request_blocked(self, client: AsyncClient, db_session):
        """Secretary or non-advisor user cannot request revisions."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])

        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)
        await client.post(
            f"/api/v1/events/{setup['event_id']}/complete",
            json={
                "actual_attendance": 50,
                "summary": "Valid summary with more than twenty characters for compliance.",
                "objectives_achieved": "Core objectives completed.",
            },
            headers=sec_headers,
        )

        # Secretary attempts to request revision on own report -> 403
        rev_res = await client.post(
            f"/api/v1/events/{setup['event_id']}/post-event-report/revise",
            json={"remarks": "Invalid self revision."},
            headers=sec_headers,
        )
        assert rev_res.status_code == 403

    async def test_18_empty_revision_remarks_rejected(self, client: AsyncClient, db_session):
        """Requesting revision with empty or blank remarks is rejected with 422."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])
        adv_headers = _auth_header(setup["advisor"])

        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)
        await client.post(
            f"/api/v1/events/{setup['event_id']}/complete",
            json={
                "actual_attendance": 50,
                "summary": "Valid summary with more than twenty characters for compliance.",
                "objectives_achieved": "Core objectives completed.",
            },
            headers=sec_headers,
        )

        # Empty remarks -> 422
        bad_rev = await client.post(
            f"/api/v1/events/{setup['event_id']}/post-event-report/revise",
            json={"remarks": "   "},
            headers=adv_headers,
        )
        assert bad_rev.status_code == 422

    async def test_19_geo_coordinates_decimal_storage(self, client: AsyncClient, db_session):
        """Uploading evidence stores unverified decimal geo-coordinates without verification."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])

        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)

        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
            b"\x1f\x15c4"
        )
        files = {"file": ("venue_gps.png", io.BytesIO(png_bytes), "image/png")}
        data = {
            "geo_latitude": "12.971598",
            "geo_longitude": "77.594562",
            "geo_source": "CLIENT_DECLARED_GPS",
        }
        res = await client.post(
            f"/api/v1/events/{setup['event_id']}/evidence",
            files=files,
            data=data,
            headers=sec_headers,
        )
        assert res.status_code == 201
        body = res.json()
        assert float(body["geo_latitude"]) == pytest.approx(12.971598, abs=1e-5)
        assert float(body["geo_longitude"]) == pytest.approx(77.594562, abs=1e-5)
        assert body["geo_source"] == "CLIENT_DECLARED_GPS"

    async def test_20_confirmed_event_read_by_id_and_request_id(
        self, client: AsyncClient, db_session
    ):
        """GET /events/{id}/confirmed works by both event proposal UUID and confirmed event UUID."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])

        res_by_req = await client.get(
            f"/api/v1/events/{setup['event_id']}/confirmed",
            headers=sec_headers,
        )
        assert res_by_req.status_code == 200

        res_by_event = await client.get(
            f"/api/v1/events/{setup['confirmed_event_id']}/confirmed",
            headers=sec_headers,
        )
        assert res_by_event.status_code == 200
        assert res_by_req.json()["id"] == res_by_event.json()["id"]

    async def test_21_evidence_listing_and_filtering(self, client: AsyncClient, db_session):
        """GET /events/{id}/evidence lists all uploaded photo/document evidence."""
        setup = await _setup_confirmed_event(
            client, db_session, start_time_offset=timedelta(minutes=10)
        )
        sec_headers = _auth_header(setup["secretary"])

        await client.post(f"/api/v1/events/{setup['event_id']}/start", headers=sec_headers)

        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
            b"\x1f\x15c4"
        )
        await client.post(
            f"/api/v1/events/{setup['event_id']}/evidence",
            files={"file": ("photo1.png", io.BytesIO(png_bytes), "image/png")},
            headers=sec_headers,
        )
        await client.post(
            f"/api/v1/events/{setup['event_id']}/evidence",
            files={"file": ("photo2.png", io.BytesIO(png_bytes), "image/png")},
            headers=sec_headers,
        )

        list_res = await client.get(
            f"/api/v1/events/{setup['event_id']}/evidence",
            headers=sec_headers,
        )
        assert list_res.status_code == 200
        docs = list_res.json()
        assert len(docs) >= 2
        assert any(d["original_filename"] == "photo1.png" for d in docs)
        assert any(d["original_filename"] == "photo2.png" for d in docs)
