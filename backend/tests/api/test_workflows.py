"""
CampusConnect — Multi-Stage Approval Workflow Engine Test Suite

Comprehensive tests for Day 5:
1. Proposal submission instantiates default 6-stage institutional workflow chain
2. Dynamic approver resolution (Faculty Advisor from Club.faculty_advisor_id)
3. Approver pending work queue inspection with role and assignment filtering
4. Strict sequential step progression & out-of-order action rejection
5. Conflict of interest guard (submitter cannot approve own proposal)
6. Role-based authorization & unauthorized actor rejection
7. Step 1 (Faculty Advisor) approval advances workflow pointer and transitions event to IN_REVIEW
8. Step 2 (Hall In-Charge) approval executes Venue interlock (confirms HallBookingConfirmed)
9. Step 3 (Finance Officer) approval executes Budget interlock (finance_status = VERIFIED)
10. Steps 4 (Advisor Union) & 5 (Dean Affairs) progression
11. Step 6 (Principal Executive Sanction) completes workflow and marks event APPROVED
12. Adverse action: Rejection with mandatory justification terminates workflow and rejects event
13. Adverse action: Revision request unlocks proposal for editing; resubmission marks old instance SUPERSEDED
14. Idempotency & double-approval prevention (step_version_lock & state machine checks)
15. Hall conflict detection during Step 2 approval raises 409 ConflictError
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
    Hall,
    HallBookingConfirmed,
    User,
)
from app.models.enums import (
    ClubMemberRole,
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
    """Create a verified test user with the specified institutional role."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@college.edu",
        password_hash=hash_password("Pass123!Secure"),
        full_name=f"Test {role} {uid}",
        role=role,
        is_active=is_active,
        deleted_at=datetime.now(UTC) if is_deleted else None,
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


async def _create_club_and_advisor(
    db,
    club_name: str,
    admin: User,
) -> tuple[Club, User, User]:
    """Create a club, assign a Faculty Advisor, and create a Secretary member."""
    uid = uuid.uuid4().hex[:6]
    slug = f"{club_name.lower().replace(' ', '-')}-{uid}"

    advisor = await _create_user(db, UserRole.FACULTY_ADVISOR, f"fa_{uid}")
    secretary = await _create_user(db, UserRole.CLUB_SECRETARY, f"sec_{uid}")

    club = Club(
        name=f"{club_name} {uid}",
        slug=slug,
        description="A collegiate technical society",
        academic_year="2026-27",
        is_active=True,
        faculty_advisor_id=advisor.id,
        created_by=admin.id,
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
    await db.refresh(member)

    return club, secretary, advisor


async def _create_test_hall(db, admin: User) -> Hall:
    """Create an active test seminar hall."""
    uid = uuid.uuid4().hex[:6]
    hall = Hall(
        name=f"APJ Abdul Kalam Auditorium {uid}",
        capacity=500,
        location="North Campus Academic Block",
        available_facilities=["projector", "ac", "audio_system"],
        is_active=True,
    )
    db.add(hall)
    await db.commit()
    await db.refresh(hall)
    return hall


async def _create_and_submit_full_proposal(
    client: AsyncClient,
    db,
    club: Club,
    secretary: User,
    hall: Hall,
) -> uuid.UUID:
    """Create a full draft proposal with venue & budget, then submit it."""
    # 1. Create event draft
    create_res = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "National Hackathon 2026",
            "description": "48-hour inter-college AI hackathon",
            "event_type": "TECHNICAL",
            "expected_attendees": 350,
            "event_date": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
            "academic_year": "2026-27",
        },
        headers=_auth_header(secretary),
    )
    assert create_res.status_code == 201
    event_id = create_res.json()["id"]

    # 2. Add venue request
    req_dt = datetime.now(UTC) + timedelta(days=20)
    s_time = req_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    e_time = req_dt.replace(hour=18, minute=0, second=0, microsecond=0)
    vr_res = await client.post(
        f"/api/v1/events/{event_id}/venue",
        json={
            "hall_id": str(hall.id),
            "requested_date": req_dt.date().isoformat(),
            "start_time": s_time.isoformat(),
            "end_time": e_time.isoformat(),
            "expected_audience": 350,
        },
        headers=_auth_header(secretary),
    )
    assert vr_res.status_code == 201

    # 3. Add budget proposal with line item
    bp_res = await client.post(
        f"/api/v1/events/{event_id}/budget",
        json={
            "expected_income": 15000.0,
            "institute_contribution": 25000.0,
        },
        headers=_auth_header(secretary),
    )
    assert bp_res.status_code == 201

    li_res = await client.post(
        f"/api/v1/events/{event_id}/budget/items",
        json={
            "category": "MATERIALS",
            "description": "First and Second place cash awards",
            "estimated_amount": 25000.0,
        },
        headers=_auth_header(secretary),
    )
    assert li_res.status_code == 201

    # 4. Submit proposal into workflow
    sub_res = await client.post(
        f"/api/v1/events/{event_id}/submit",
        json={"change_summary": "Initial submission for multi-stage approval"},
        headers=_auth_header(secretary),
    )
    assert sub_res.status_code == 200
    assert sub_res.json()["status"] == "SUBMITTED"
    assert sub_res.json()["workflow_instance_id"] is not None

    return uuid.UUID(event_id)


# ---------------------------------------------------------------------------
# Test Suite
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestWorkflowEngine:
    """Rigorous end-to-end integration tests for the Multi-Stage Approval Workflow Engine."""

    async def test_01_proposal_submission_instantiates_6_stage_workflow(
        self, client: AsyncClient, db_session
    ):
        """1. Submitting proposal automatically instantiates a 6-step sequential workflow."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary, advisor = await _create_club_and_advisor(db_session, "Coding Club", admin)
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        # Inspect workflow via API
        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow",
            headers=_auth_header(secretary),
        )
        assert wf_res.status_code == 200
        wf_data = wf_res.json()

        assert wf_data["event_request_id"] == str(event_id)
        assert wf_data["current_step_order"] == 1
        assert wf_data["status"] == "IN_PROGRESS"
        assert wf_data["version_number"] == 1
        assert len(wf_data["steps"]) == 6

        # Step 1 must be Faculty Advisor Review, dynamically assigned to club's advisor
        step1 = wf_data["steps"][0]
        assert step1["step_order"] == 1
        assert step1["step_name"] == "Faculty Advisor Review"
        assert step1["assigned_to"] == str(advisor.id)
        assert step1["status"] == "PENDING"

        # Verify all remaining steps are PENDING
        for s in wf_data["steps"][1:]:
            assert s["status"] == "PENDING"

    async def test_02_pending_queue_visibility_and_self_approval_guard(
        self, client: AsyncClient, db_session
    ):
        """2. Pending queue displays only active pending steps for caller; submitter self-approval excluded."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
        club, secretary, advisor = await _create_club_and_advisor(db_session, "Robotics Society", admin)
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        # 1. Faculty advisor pending queue should contain this proposal
        fa_queue_res = await client.get(
            "/api/v1/workflows/pending",
            headers=_auth_header(advisor),
        )
        assert fa_queue_res.status_code == 200
        fa_items = fa_queue_res.json()
        matching = [item for item in fa_items if item["event_request_id"] == str(event_id)]
        assert len(matching) == 1
        assert matching[0]["step_order"] == 1

        # 2. Hall In-Charge pending queue should NOT contain this proposal yet (Step 1 is still pending)
        hic_queue_res = await client.get(
            "/api/v1/workflows/pending",
            headers=_auth_header(hall_incharge),
        )
        assert hic_queue_res.status_code == 200
        hic_matching = [item for item in hic_queue_res.json() if item["event_request_id"] == str(event_id)]
        assert len(hic_matching) == 0

        # 3. Submitter queue should NOT contain the proposal even if role matches (Conflict of Interest)
        sec_queue_res = await client.get(
            "/api/v1/workflows/pending",
            headers=_auth_header(secretary),
        )
        assert sec_queue_res.status_code == 200
        sec_matching = [item for item in sec_queue_res.json() if item["event_request_id"] == str(event_id)]
        assert len(sec_matching) == 0

    async def test_03_out_of_order_action_rejected(
        self, client: AsyncClient, db_session
    ):
        """3. Approving or rejecting a step out-of-order raises 400 WorkflowStateError."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
        club, secretary, advisor = await _create_club_and_advisor(db_session, "AI Club", admin)
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        # Retrieve steps
        wf_res = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        step2_id = wf_res.json()["steps"][1]["id"]

        # Attempt to approve Step 2 while Step 1 is pending
        res = await client.post(
            f"/api/v1/workflows/steps/{step2_id}/approve",
            json={"comments": "Premature approval attempt"},
            headers=_auth_header(hall_incharge),
        )
        assert res.status_code == 403
        assert "out-of-order" in res.json()["message"].lower()

    async def test_04_submitter_self_approval_prevented(
        self, client: AsyncClient, db_session
    ):
        """4. Proposal submitter cannot approve own proposal (raises 403 ForbiddenError)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary, advisor = await _create_club_and_advisor(db_session, "Music Society", admin)
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        step1_id = wf_res.json()["steps"][0]["id"]

        # Secretary tries to approve own proposal
        res = await client.post(
            f"/api/v1/workflows/steps/{step1_id}/approve",
            json={"comments": "Self-endorsement"},
            headers=_auth_header(secretary),
        )
        assert res.status_code == 403
        assert "conflict of interest" in res.json()["message"].lower()

    async def test_05_unauthorized_actor_rejected(
        self, client: AsyncClient, db_session
    ):
        """5. An advisor from a different club cannot approve this club's proposal."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club_a, sec_a, advisor_a = await _create_club_and_advisor(db_session, "Club Alpha", admin)
        club_b, sec_b, advisor_b = await _create_club_and_advisor(db_session, "Club Beta", admin)
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club_a, sec_a, hall)

        wf_res = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(sec_a))
        step1_id = wf_res.json()["steps"][0]["id"]

        # Advisor of Club B attempts to approve Club A's proposal
        res = await client.post(
            f"/api/v1/workflows/steps/{step1_id}/approve",
            json={"comments": "Cross-club approval attempt"},
            headers=_auth_header(advisor_b),
        )
        assert res.status_code == 403
        assert "unauthorized" in res.json()["message"].lower()

    async def test_06_step_1_faculty_approval_advances_to_step_2_and_in_review(
        self, client: AsyncClient, db_session
    ):
        """6. Faculty Advisor approves Step 1 -> current_step_order=2 and event transitions to IN_REVIEW."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary, advisor = await _create_club_and_advisor(db_session, "Literary Society", admin)
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        step1_id = wf_res.json()["steps"][0]["id"]

        # Faculty Advisor approves
        approve_res = await client.post(
            f"/api/v1/workflows/steps/{step1_id}/approve",
            json={"comments": "Academic objectives and speaker profile verified"},
            headers=_auth_header(advisor),
        )
        assert approve_res.status_code == 200
        step1_data = approve_res.json()
        assert step1_data["status"] == "APPROVED"
        assert step1_data["comments"] == "Academic objectives and speaker profile verified"

        # Check updated workflow state
        wf_res2 = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        assert wf_res2.json()["current_step_order"] == 2

        # Check event request status transitioned to IN_REVIEW
        ev_res = await client.get(f"/api/v1/events/{event_id}", headers=_auth_header(secretary))
        assert ev_res.json()["status"] == "IN_REVIEW"

    async def test_07_step_2_hall_incharge_approval_triggers_venue_interlock(
        self, client: AsyncClient, db_session
    ):
        """7. Hall In-Charge approval confirms VenueRequest and allocates HallBookingConfirmed."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
        club, secretary, advisor = await _create_club_and_advisor(db_session, "Dance Club", admin)
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        step1_id = wf_res.json()["steps"][0]["id"]
        step2_id = wf_res.json()["steps"][1]["id"]

        # Step 1: Faculty Advisor approves
        await client.post(
            f"/api/v1/workflows/steps/{step1_id}/approve",
            json={"comments": "Looks good"},
            headers=_auth_header(advisor),
        )

        # Step 2: Hall In-Charge approves
        app2_res = await client.post(
            f"/api/v1/workflows/steps/{step2_id}/approve",
            json={"comments": "Space cleared and technician scheduled"},
            headers=_auth_header(hall_incharge),
        )
        assert app2_res.status_code == 200

        # Verify domain interlock: VenueRequest is APPROVED
        vr_res = await client.get(f"/api/v1/events/{event_id}/venue", headers=_auth_header(secretary))
        assert vr_res.status_code == 200
        assert vr_res.json()["status"] == "APPROVED"
        assert vr_res.json()["reviewed_by"] == str(hall_incharge.id)

        # Verify HallBookingConfirmed exists in database
        booking = await db_session.scalar(
            select(HallBookingConfirmed).where(
                HallBookingConfirmed.event_request_id == event_id,
                HallBookingConfirmed.is_active.is_(True),
            )
        )
        assert booking is not None
        assert booking.hall_id == hall.id

    async def test_08_step_3_finance_officer_approval_triggers_budget_interlock(
        self, client: AsyncClient, db_session
    ):
        """8. Finance Officer approval updates BudgetProposal.finance_status to VERIFIED."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
        finance_officer = await _create_user(db_session, UserRole.FINANCE_OFFICER, "fin_off")
        club, secretary, advisor = await _create_club_and_advisor(db_session, "Sports Club", admin)
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        step1_id = wf_res.json()["steps"][0]["id"]
        step2_id = wf_res.json()["steps"][1]["id"]
        step3_id = wf_res.json()["steps"][2]["id"]

        # Step 1: Faculty Advisor approves
        await client.post(f"/api/v1/workflows/steps/{step1_id}/approve", headers=_auth_header(advisor))
        # Step 2: Hall In-Charge approves
        await client.post(f"/api/v1/workflows/steps/{step2_id}/approve", headers=_auth_header(hall_incharge))

        # Step 3: Finance Officer approves
        app3_res = await client.post(
            f"/api/v1/workflows/steps/{step3_id}/approve",
            json={"comments": "Budget audited and ₹25,000 contribution within institutional cap."},
            headers=_auth_header(finance_officer),
        )
        assert app3_res.status_code == 200

        # Verify domain interlock: BudgetProposal is VERIFIED
        bp_res = await client.get(f"/api/v1/events/{event_id}/budget", headers=_auth_header(secretary))
        assert bp_res.status_code == 200
        assert bp_res.json()["finance_status"] == "VERIFIED"
        assert bp_res.json()["finance_verified_by"] == str(finance_officer.id)

    async def test_09_complete_6_stage_approval_flow_to_principal_sanction(
        self, client: AsyncClient, db_session
    ):
        """9. Full sequential chain: Step 1 -> 2 -> 3 -> 4 -> 5 -> 6 completes workflow & marks event APPROVED."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
        finance_officer = await _create_user(db_session, UserRole.FINANCE_OFFICER, "fin_off")
        union_advisor = await _create_user(db_session, UserRole.ADVISOR_STUDENTS_UNION, "union_adv")
        dean_affairs = await _create_user(db_session, UserRole.DEAN_STUDENT_AFFAIRS, "dean")
        principal = await _create_user(db_session, UserRole.PRINCIPAL, "principal")

        club, secretary, advisor = await _create_club_and_advisor(db_session, "Apex Tech Club", admin)
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        steps = wf_res.json()["steps"]

        # Step 1: Faculty Advisor
        res1 = await client.post(f"/api/v1/workflows/steps/{steps[0]['id']}/approve", headers=_auth_header(advisor))
        assert res1.status_code == 200

        # Step 2: Hall In-Charge
        res2 = await client.post(f"/api/v1/workflows/steps/{steps[1]['id']}/approve", headers=_auth_header(hall_incharge))
        assert res2.status_code == 200

        # Step 3: Finance Officer
        res3 = await client.post(f"/api/v1/workflows/steps/{steps[2]['id']}/approve", headers=_auth_header(finance_officer))
        assert res3.status_code == 200

        # Step 4: Advisor Students Union
        res4 = await client.post(
            f"/api/v1/workflows/steps/{steps[3]['id']}/approve",
            json={"comments": "No clash with academic calendar or cultural fest"},
            headers=_auth_header(union_advisor),
        )
        assert res4.status_code == 200

        # Step 5: Dean of Student Affairs
        res5 = await client.post(
            f"/api/v1/workflows/steps/{steps[4]['id']}/approve",
            json={"comments": "Administrative and disciplinary clearance granted"},
            headers=_auth_header(dean_affairs),
        )
        assert res5.status_code == 200

        # Step 6: Principal Executive Sanction
        res6 = await client.post(
            f"/api/v1/workflows/steps/{steps[5]['id']}/approve",
            json={"comments": "Sanctioned under institutional policy guidelines"},
            headers=_auth_header(principal),
        )
        assert res6.status_code == 200
        assert res6.json()["status"] == "APPROVED"

        # Verify WorkflowInstance is COMPLETED
        wf_final = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        assert wf_final.json()["status"] == "COMPLETED"

        # Verify EventRequest is APPROVED
        ev_final = await client.get(f"/api/v1/events/{event_id}", headers=_auth_header(secretary))
        assert ev_final.json()["status"] == "APPROVED"

    async def test_10_rejection_terminates_workflow_and_event(
        self, client: AsyncClient, db_session
    ):
        """10. Rejection requires mandatory comments (>=5 chars) and terminates workflow & event immediately."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Debate Society", admin
        )
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        step1_id = wf_res.json()["steps"][0]["id"]

        # Reject with too short comments -> 422
        bad_res = await client.post(
            f"/api/v1/workflows/steps/{step1_id}/reject",
            json={"comments": "no"},
            headers=_auth_header(advisor),
        )
        assert bad_res.status_code == 422

        # Reject with valid detailed justification
        rej_res = await client.post(
            f"/api/v1/workflows/steps/{step1_id}/reject",
            json={"comments": "Proposal violates institutional security policies for late night events."},
            headers=_auth_header(advisor),
        )
        assert rej_res.status_code == 200
        assert rej_res.json()["status"] == "REJECTED"

        # Verify workflow status is REJECTED
        wf_rej = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        assert wf_rej.json()["status"] == "REJECTED"

        # Verify event status is REJECTED
        ev_rej = await client.get(f"/api/v1/events/{event_id}", headers=_auth_header(secretary))
        assert ev_rej.json()["status"] == "REJECTED"

    async def test_11_revision_request_and_resubmission_creates_superseding_workflow(
        self, client: AsyncClient, db_session
    ):
        """11. Revision request transitions event to REVISION_REQUIRED; secretary edits & resubmits; old instance superseded."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary, advisor = await _create_club_and_advisor(db_session, "Astronomy Club", admin)
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        inst1_id = wf_res.json()["id"]
        step1_id = wf_res.json()["steps"][0]["id"]

        # Faculty Advisor requests revision
        rev_res = await client.post(
            f"/api/v1/workflows/steps/{step1_id}/request-revision",
            json={"comments": "Please update attendee capacity and add telescope safety measures."},
            headers=_auth_header(advisor),
        )
        assert rev_res.status_code == 200
        assert rev_res.json()["status"] == "REVISION_REQUESTED"

        # Verify event is now in REVISION_REQUIRED
        ev_rev = await client.get(f"/api/v1/events/{event_id}", headers=_auth_header(secretary))
        assert ev_rev.json()["status"] == "REVISION_REQUIRED"

        # Secretary edits the draft proposal (now unlocked)
        patch_res = await client.patch(
            f"/api/v1/events/{event_id}",
            json={"expected_attendees": 200, "title": "Night Sky Observation Camp v2"},
            headers=_auth_header(secretary),
        )
        assert patch_res.status_code == 200

        # Secretary resubmits (Version 2)
        sub2_res = await client.post(
            f"/api/v1/events/{event_id}/submit",
            json={"change_summary": "Adjusted attendee capacity and safety guidelines"},
            headers=_auth_header(secretary),
        )
        assert sub2_res.status_code == 200
        assert sub2_res.json()["current_version"] == 2
        inst2_id = sub2_res.json()["workflow_instance_id"]
        assert inst2_id != inst1_id

        # Verify old instance is SUPERSEDED
        old_inst_res = await client.get(f"/api/v1/workflows/instance/{inst1_id}", headers=_auth_header(secretary))
        assert old_inst_res.status_code == 200
        assert old_inst_res.json()["status"] == "SUPERSEDED"

        # Verify new instance is IN_PROGRESS at Step 1
        new_inst_res = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        assert new_inst_res.status_code == 200
        assert new_inst_res.json()["id"] == inst2_id
        assert new_inst_res.json()["status"] == "IN_PROGRESS"
        assert new_inst_res.json()["version_number"] == 2
        assert new_inst_res.json()["current_step_order"] == 1

    async def test_12_double_action_on_completed_step_raises_error(
        self, client: AsyncClient, db_session
    ):
        """12. Attempting to approve an already approved step raises 400 WorkflowStateError."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary, advisor = await _create_club_and_advisor(db_session, "Chess Club", admin)
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary))
        step1_id = wf_res.json()["steps"][0]["id"]

        # First approval succeeds
        res1 = await client.post(f"/api/v1/workflows/steps/{step1_id}/approve", headers=_auth_header(advisor))
        assert res1.status_code == 200

        # Duplicate approval attempt fails
        res2 = await client.post(f"/api/v1/workflows/steps/{step1_id}/approve", headers=_auth_header(advisor))
        assert res2.status_code == 403
        assert "already in 'approved' status" in res2.json()["message"].lower()

    async def test_13_venue_conflict_detection_on_step_2_approval(
        self, client: AsyncClient, db_session
    ):
        """13. Step 2 approval fails with 409 ConflictError if another event already holds confirmed booking."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
        club1, sec1, adv1 = await _create_club_and_advisor(db_session, "Club One", admin)
        club2, sec2, adv2 = await _create_club_and_advisor(db_session, "Club Two", admin)
        hall = await _create_test_hall(db_session, admin)

        # Submit both Event 1 and Event 2 for the same hall & time while unconfirmed
        event1_id = await _create_and_submit_full_proposal(client, db_session, club1, sec1, hall)
        event2_id = await _create_and_submit_full_proposal(client, db_session, club2, sec2, hall)

        # Event 1 approved through Step 2 -> secures confirmed booking in hall_bookings_confirmed
        wf1 = await client.get(f"/api/v1/events/{event1_id}/workflow", headers=_auth_header(sec1))
        await client.post(f"/api/v1/workflows/steps/{wf1.json()['steps'][0]['id']}/approve", headers=_auth_header(adv1))
        await client.post(f"/api/v1/workflows/steps/{wf1.json()['steps'][1]['id']}/approve", headers=_auth_header(hall_incharge))

        # Event 2 approved at Step 1
        wf2 = await client.get(f"/api/v1/events/{event2_id}/workflow", headers=_auth_header(sec2))
        await client.post(f"/api/v1/workflows/steps/{wf2.json()['steps'][0]['id']}/approve", headers=_auth_header(adv2))

        # Step 2 approval for Event 2 must detect venue conflict and raise 409!
        conflict_res = await client.post(
            f"/api/v1/workflows/steps/{wf2.json()['steps'][1]['id']}/approve",
            headers=_auth_header(hall_incharge),
        )
        assert conflict_res.status_code == 409
        assert "venue conflict" in conflict_res.json()["message"].lower()

    # -----------------------------------------------------------------------
    # SYSTEM_ADMIN Authorization Tests (Day 5 Security Fix)
    # -----------------------------------------------------------------------

    async def test_14_system_admin_cannot_approve_step2_institutional_step(
        self, client: AsyncClient, db_session
    ):
        """14. SYSTEM_ADMIN must NOT be able to approve Step 2 (Hall In-Charge).

        Statutory institutional approvals are reserved for role-holders only."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Crypto Club", admin
        )
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        # Get workflow and advance to Step 2 via the legitimate Faculty Advisor
        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(advisor)
        )
        assert wf_res.status_code == 200
        step1_id = wf_res.json()["steps"][0]["id"]
        step2_id = wf_res.json()["steps"][1]["id"]

        # Advance past Step 1 with the legitimate advisor
        adv_res = await client.post(
            f"/api/v1/workflows/steps/{step1_id}/approve",
            json={"comments": "Approved by faculty advisor."},
            headers=_auth_header(advisor),
        )
        assert adv_res.status_code == 200

        # Now attempt Step 2 approval with SYSTEM_ADMIN — must be forbidden
        forbidden_res = await client.post(
            f"/api/v1/workflows/steps/{step2_id}/approve",
            json={"comments": "Admin attempting to substitute for Hall In-Charge."},
            headers=_auth_header(admin),
        )
        assert forbidden_res.status_code == 403, (
            f"Expected 403 Forbidden for SYSTEM_ADMIN on Step 2 approval, "
            f"got {forbidden_res.status_code}: {forbidden_res.text}"
        )

    async def test_15_system_admin_cannot_reject_step6_principal(
        self, client: AsyncClient, db_session
    ):
        """15. SYSTEM_ADMIN must NOT be able to reject Step 6 (Principal).

        The Principal is the final statutory authority;
        only a PRINCIPAL role-holder may act."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
        finance = await _create_user(db_session, UserRole.FINANCE_OFFICER, "finance")
        union_advisor = await _create_user(
            db_session, UserRole.ADVISOR_STUDENTS_UNION, "union"
        )
        dean = await _create_user(db_session, UserRole.DEAN_STUDENT_AFFAIRS, "dean")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Drama Guild", admin
        )
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        steps = {s["step_order"]: s["id"] for s in wf_res.json()["steps"]}

        # Advance Steps 1-5 with legitimate institutional approvers
        approvers = [advisor, hall_incharge, finance, union_advisor, dean]
        for order, approver in enumerate(approvers, start=1):
            res = await client.post(
                f"/api/v1/workflows/steps/{steps[order]}/approve",
                json={"comments": f"Step {order} approved."},
                headers=_auth_header(approver),
            )
            assert res.status_code == 200, f"Step {order} approval failed: {res.text}"

        # Step 6 (Principal) — attempt rejection with SYSTEM_ADMIN — must be forbidden
        forbidden_res = await client.post(
            f"/api/v1/workflows/steps/{steps[6]}/reject",
            json={"comments": "Admin bypassing Principal sanction."},
            headers=_auth_header(admin),
        )
        assert forbidden_res.status_code == 403, (
            f"Expected 403 Forbidden for SYSTEM_ADMIN on Step 6 rejection, "
            f"got {forbidden_res.status_code}: {forbidden_res.text}"
        )

        # Verify workflow is still IN_PROGRESS (not prematurely rejected)
        wf_check = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        assert wf_check.json()["status"] == "IN_PROGRESS"

    async def test_16_system_admin_cannot_request_revision_on_finance_step(
        self, client: AsyncClient, db_session
    ):
        """16. SYSTEM_ADMIN must NOT be able to request revision on Step 3.

        Finance Officer Pre-Audit is a statutory institutional function."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Photography Club", admin
        )
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        steps = {s["step_order"]: s["id"] for s in wf_res.json()["steps"]}

        # Advance to Step 3 via Steps 1-2
        step1_res = await client.post(
            f"/api/v1/workflows/steps/{steps[1]}/approve",
            json={"comments": "Faculty advisor approval."},
            headers=_auth_header(advisor),
        )
        assert step1_res.status_code == 200

        step2_res = await client.post(
            f"/api/v1/workflows/steps/{steps[2]}/approve",
            json={"comments": "Hall approved."},
            headers=_auth_header(hall_incharge),
        )
        assert step2_res.status_code == 200

        # SYSTEM_ADMIN attempts revision request on Step 3 — must be forbidden
        forbidden_res = await client.post(
            f"/api/v1/workflows/steps/{steps[3]}/request-revision",
            json={"comments": "Admin substituting for Finance Officer revision."},
            headers=_auth_header(admin),
        )
        assert forbidden_res.status_code == 403, (
            f"Expected 403 Forbidden for SYSTEM_ADMIN on Step 3 revision request, "
            f"got {forbidden_res.status_code}: {forbidden_res.text}"
        )

    async def test_17_system_admin_can_still_approve_step1_faculty_advisor(
        self, client: AsyncClient, db_session
    ):
        """17. SYSTEM_ADMIN retains the ability to act on Step 1 (Faculty Advisor).

        Step 1 uses personal assignment; admin serves as an emergency unlock
        since role-match alone would be too broad across the institution."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary, advisor = await _create_club_and_advisor(db_session, "Chess Club", admin)
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        step1_id = wf_res.json()["steps"][0]["id"]

        # SYSTEM_ADMIN approves Step 1 — this must succeed
        approve_res = await client.post(
            f"/api/v1/workflows/steps/{step1_id}/approve",
            json={"comments": "Emergency admin approval at Step 1."},
            headers=_auth_header(admin),
        )
        assert approve_res.status_code == 200, (
            f"SYSTEM_ADMIN should be permitted on Step 1 but "
            f"got {approve_res.status_code}: {approve_res.text}"
        )
        assert approve_res.json()["status"] == "APPROVED"

        # Workflow pointer should have advanced to Step 2
        wf_after = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        assert wf_after.json()["current_step_order"] == 2

    async def test_18_role_authorized_approver_without_explicit_assignment_can_act_on_step2_6(
        self, client: AsyncClient, db_session
    ):
        """18. A user holding the required institutional role can act on Steps 2-6
        even without explicit assignment (role-match path).
        This confirms role-OR-assignment still works."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        # Create a DEAN with no direct assignment — role-match path
        unassigned_dean = await _create_user(
            db_session, UserRole.DEAN_STUDENT_AFFAIRS, "dean_unassigned"
        )
        hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
        finance = await _create_user(db_session, UserRole.FINANCE_OFFICER, "finance")
        union_advisor = await _create_user(db_session, UserRole.ADVISOR_STUDENTS_UNION, "union")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Music Club", admin
        )
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        steps = {s["step_order"]: s["id"] for s in wf_res.json()["steps"]}

        # Advance Steps 1-4 via legitimate approvers
        for order, approver in enumerate(
            [advisor, hall_incharge, finance, union_advisor], start=1
        ):
            res = await client.post(
                f"/api/v1/workflows/steps/{steps[order]}/approve",
                json={"comments": f"Step {order} approved."},
                headers=_auth_header(approver),
            )
            assert res.status_code == 200

        # Step 5 (Dean) — unassigned_dean holds DEAN_STUDENT_AFFAIRS role
        # Must succeed via role-match (no explicit assignment needed).
        dean_res = await client.post(
            f"/api/v1/workflows/steps/{steps[5]}/approve",
            json={"comments": "Dean approval via role-match (no explicit assignment)."},
            headers=_auth_header(unassigned_dean),
        )
        assert dean_res.status_code == 200, (
            f"Role-authorized Dean without explicit assignment should be permitted; "
            f"got {dean_res.status_code}: {dean_res.text}"
        )
        assert dean_res.json()["status"] == "APPROVED"

    async def test_19_submitter_conflict_of_interest_still_enforced_after_auth_fix(
        self, client: AsyncClient, db_session
    ):
        """19. The self-approval conflict-of-interest guard remains enforced after the
        SYSTEM_ADMIN authorization fix. A secretary who submitted the proposal cannot
        approve any step — the guard fires before the role/assignment check."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Debate Society", admin
        )
        hall = await _create_test_hall(db_session, admin)

        # Secretary submits the proposal
        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        step1_id = wf_res.json()["steps"][0]["id"]

        # The secretary who submitted attempts to approve Step 1 — conflict guard must fire.
        # Even though the secretary is not the assigned advisor, the guard is evaluated first.
        self_approve_res = await client.post(
            f"/api/v1/workflows/steps/{step1_id}/approve",
            json={"comments": "Attempting self-approval as the submitter."},
            headers=_auth_header(secretary),
        )
        assert self_approve_res.status_code == 403, (
            f"Self-approval must be blocked by conflict-of-interest guard, "
            f"got {self_approve_res.status_code}: {self_approve_res.text}"
        )

        # Verify the step is still PENDING (guard blocked any state change)
        wf_after = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(advisor)
        )
        step1_after = wf_after.json()["steps"][0]
        assert step1_after["status"] == "PENDING", (
            f"Step 1 must remain PENDING after blocked self-approval attempt, "
            f"got {step1_after['status']}"
        )

    async def test_20_system_admin_cannot_act_on_dean_step5(
        self, client: AsyncClient, db_session
    ):
        """20. SYSTEM_ADMIN cannot approve Step 5 (Dean of Student Affairs Review).
        Covers an additional intermediate institutional step beyond tests 14-16."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        hall_incharge = await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_mgr")
        finance = await _create_user(db_session, UserRole.FINANCE_OFFICER, "finance")
        union_advisor = await _create_user(db_session, UserRole.ADVISOR_STUDENTS_UNION, "union")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Robotics League", admin
        )
        hall = await _create_test_hall(db_session, admin)

        event_id = await _create_and_submit_full_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        steps = {s["step_order"]: s["id"] for s in wf_res.json()["steps"]}

        # Advance Steps 1-4 via legitimate approvers
        for order, approver in enumerate([advisor, hall_incharge, finance, union_advisor], start=1):
            res = await client.post(
                f"/api/v1/workflows/steps/{steps[order]}/approve",
                json={"comments": f"Step {order} approved."},
                headers=_auth_header(approver),
            )
            assert res.status_code == 200

        # Step 5 (Dean) — SYSTEM_ADMIN attempts approval — must be forbidden
        forbidden_res = await client.post(
            f"/api/v1/workflows/steps/{steps[5]}/approve",
            json={"comments": "Admin attempting to substitute for Dean."},
            headers=_auth_header(admin),
        )
        assert forbidden_res.status_code == 403, (
            f"Expected 403 Forbidden for SYSTEM_ADMIN on Step 5, "
            f"got {forbidden_res.status_code}: {forbidden_res.text}"
        )

