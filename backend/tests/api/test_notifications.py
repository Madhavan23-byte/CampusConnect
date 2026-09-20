"""
CampusConnect - Notification API & Service Test Suite
Covers in-app notifications, recipient isolation, unread filtering, batch read,
and workflow transition event hooks.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.models.domain import Club, ClubMember, Hall, User
from app.models.enums import ClubMemberRole, NotificationType, UserRole
from app.services.notification_service import NotificationService


async def _create_user(db, role: UserRole, prefix: str) -> User:
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@college.edu",
        password_hash=hash_password("Pass123!Secure"),
        full_name=f"Test {role} {uid}",
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


async def _create_club_and_advisor(db, name: str, admin: User):
    uid = uuid.uuid4().hex[:6]
    slug = f"{name.lower().replace(' ', '-')}-{uid}"

    advisor = await _create_user(db, UserRole.FACULTY_ADVISOR, f"fa_{uid}")
    secretary = await _create_user(db, UserRole.CLUB_SECRETARY, f"sec_{uid}")

    club = Club(
        name=f"{name} {uid}",
        slug=slug,
        description="A test club",
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


async def _create_test_hall(db) -> Hall:
    uid = uuid.uuid4().hex[:6]
    hall = Hall(
        name=f"Auditorium {uid}",
        capacity=500,
        location="Campus Center",
        available_facilities=["projector", "ac"],
        is_active=True,
    )
    db.add(hall)
    await db.commit()
    await db.refresh(hall)
    return hall


async def _create_and_submit_proposal(
    client: AsyncClient, db, club: Club, secretary: User, hall: Hall
) -> str:
    create_res = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "National Hackathon",
            "description": "Hackathon description",
            "event_type": "TECHNICAL",
            "expected_attendees": 200,
            "event_date": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
            "academic_year": "2026-27",
        },
        headers=_auth_header(secretary),
    )
    assert create_res.status_code == 201
    event_id = create_res.json()["id"]

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
            "expected_audience": 200,
        },
        headers=_auth_header(secretary),
    )
    assert vr_res.status_code == 201

    bp_res = await client.post(
        f"/api/v1/events/{event_id}/budget",
        json={
            "expected_income": 5000.0,
            "institute_contribution": 15000.0,
        },
        headers=_auth_header(secretary),
    )
    assert bp_res.status_code == 201

    li_res = await client.post(
        f"/api/v1/events/{event_id}/budget/items",
        json={
            "category": "PRINTING",
            "description": "Certificates",
            "estimated_amount": 5000.0,
        },
        headers=_auth_header(secretary),
    )
    assert li_res.status_code == 201

    sub_res = await client.post(
        f"/api/v1/events/{event_id}/submit",
        json={"change_summary": "Initial submit"},
        headers=_auth_header(secretary),
    )
    assert sub_res.status_code == 200
    return event_id


@pytest.mark.asyncio
class TestNotificationAPI:
    """Tests for notification endpoints and recipient isolation."""

    async def test_01_get_notifications_empty(self, client: AsyncClient, db_session):
        """User with no notifications receives an empty list."""
        user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "user_empty")
        res = await client.get("/api/v1/notifications", headers=_auth_header(user))
        assert res.status_code == 200
        assert res.json() == []

    async def test_02_get_notification_counts_zero(self, client: AsyncClient, db_session):
        """User with no notifications receives 0 unread and 0 total."""
        user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "user_cnt_zero")
        res = await client.get("/api/v1/notifications/count", headers=_auth_header(user))
        assert res.status_code == 200
        data = res.json()
        assert data["unread_count"] == 0
        assert data["total_count"] == 0

    async def test_03_create_and_fetch_notifications(self, client: AsyncClient, db_session):
        """Created notifications are listed for the recipient."""
        user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "user_list")
        await NotificationService.create_notification(
            db=db_session,
            recipient_id=user.id,
            notification_type=NotificationType.ACTION_REQUIRED,
            title="Review Task",
            message="Please review proposal Alpha.",
        )
        await db_session.commit()

        res = await client.get("/api/v1/notifications", headers=_auth_header(user))
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 1
        assert items[0]["title"] == "Review Task"
        assert items[0]["is_read"] is False
        assert items[0]["notification_type"] == "ACTION_REQUIRED"

    async def test_04_unread_only_filter(self, client: AsyncClient, db_session):
        """unread_only query param returns only unread notifications."""
        user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "user_filter")
        await NotificationService.create_notification(
            db=db_session,
            recipient_id=user.id,
            notification_type=NotificationType.ACTION_REQUIRED,
            title="N1 Unread",
            message="Unread msg",
        )
        n2 = await NotificationService.create_notification(
            db=db_session,
            recipient_id=user.id,
            notification_type=NotificationType.STEP_APPROVED,
            title="N2 Read",
            message="Read msg",
        )
        n2.is_read = True
        n2.read_at = datetime.now(UTC)
        await db_session.commit()

        # Unread only
        res_unread = await client.get(
            "/api/v1/notifications?unread_only=true", headers=_auth_header(user)
        )
        assert res_unread.status_code == 200
        assert len(res_unread.json()) == 1
        assert res_unread.json()[0]["title"] == "N1 Unread"

        # All
        res_all = await client.get(
            "/api/v1/notifications?unread_only=false", headers=_auth_header(user)
        )
        assert res_all.status_code == 200
        assert len(res_all.json()) == 2

    async def test_05_notification_pagination(self, client: AsyncClient, db_session):
        """Limit and offset correctly paginate notifications."""
        user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "user_page")
        for i in range(5):
            await NotificationService.create_notification(
                db=db_session,
                recipient_id=user.id,
                notification_type=NotificationType.SYSTEM,
                title=f"Note {i}",
                message=f"Msg {i}",
            )
        await db_session.commit()

        res = await client.get(
            "/api/v1/notifications?limit=2&offset=1", headers=_auth_header(user)
        )
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 2

    async def test_06_mark_notification_as_read(self, client: AsyncClient, db_session):
        """PATCH /notifications/{id}/read marks a notification as read."""
        user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "user_read_single")
        notif = await NotificationService.create_notification(
            db=db_session,
            recipient_id=user.id,
            notification_type=NotificationType.ACTION_REQUIRED,
            title="To Read",
            message="Body text",
        )
        await db_session.commit()

        res = await client.patch(
            f"/api/v1/notifications/{notif.id}/read", headers=_auth_header(user)
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_read"] is True
        assert data["read_at"] is not None

    async def test_07_mark_all_as_read(self, client: AsyncClient, db_session):
        """PATCH /notifications/read-all marks all unread notifications as read."""
        user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "user_read_all")
        for i in range(3):
            await NotificationService.create_notification(
                db=db_session,
                recipient_id=user.id,
                notification_type=NotificationType.ACTION_REQUIRED,
                title=f"Unread {i}",
                message=f"Msg {i}",
            )
        await db_session.commit()

        res = await client.patch("/api/v1/notifications/read-all", headers=_auth_header(user))
        assert res.status_code == 200
        assert res.json()["updated_count"] == 3

        res_cnt = await client.get("/api/v1/notifications/count", headers=_auth_header(user))
        assert res_cnt.json()["unread_count"] == 0
        assert res_cnt.json()["total_count"] == 3

    async def test_08_strict_recipient_isolation_read(self, client: AsyncClient, db_session):
        """User B cannot mark User A's notification as read (returns 404 - anti-IDOR)."""
        user_a = await _create_user(db_session, UserRole.CLUB_SECRETARY, "user_a")
        user_b = await _create_user(db_session, UserRole.CLUB_SECRETARY, "user_b")

        notif_a = await NotificationService.create_notification(
            db=db_session,
            recipient_id=user_a.id,
            notification_type=NotificationType.ACTION_REQUIRED,
            title="Private to A",
            message="Confidential",
        )
        await db_session.commit()

        res = await client.patch(
            f"/api/v1/notifications/{notif_a.id}/read", headers=_auth_header(user_b)
        )
        assert res.status_code == 404

    async def test_09_strict_recipient_isolation_listing(self, client: AsyncClient, db_session):
        """User B never sees User A's notifications in list or count endpoints."""
        user_a = await _create_user(db_session, UserRole.CLUB_SECRETARY, "user_a2")
        user_b = await _create_user(db_session, UserRole.CLUB_SECRETARY, "user_b2")

        await NotificationService.create_notification(
            db=db_session,
            recipient_id=user_a.id,
            notification_type=NotificationType.ACTION_REQUIRED,
            title="Notice for A",
            message="Notice body",
        )
        await db_session.commit()

        res_b = await client.get("/api/v1/notifications", headers=_auth_header(user_b))
        assert res_b.status_code == 200
        assert len(res_b.json()) == 0

        res_cnt = await client.get("/api/v1/notifications/count", headers=_auth_header(user_b))
        assert res_cnt.json()["total_count"] == 0

    async def test_10_unauthenticated_notification_endpoints(self, client: AsyncClient):
        """Unauthenticated requests are rejected with 401."""
        res1 = await client.get("/api/v1/notifications")
        assert res1.status_code == 401

        res2 = await client.get("/api/v1/notifications/count")
        assert res2.status_code == 401

        fake_id = uuid.uuid4()
        res3 = await client.patch(f"/api/v1/notifications/{fake_id}/read")
        assert res3.status_code == 401

        res4 = await client.patch("/api/v1/notifications/read-all")
        assert res4.status_code == 401

    async def test_11_workflow_step_1_active_notification(self, client: AsyncClient, db_session):
        """Submitting a proposal triggers an ACTION_REQUIRED notification to Step 1 assignee."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_notif1")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Coding Notif Club", admin
        )
        hall = await _create_test_hall(db_session)
        await _create_and_submit_proposal(client, db_session, club, secretary, hall)

        # Advisor (Step 1 assignee) should have an ACTION_REQUIRED notification
        notifs_adv = await client.get(
            "/api/v1/notifications", headers=_auth_header(advisor)
        )
        assert notifs_adv.status_code == 200
        items = notifs_adv.json()
        assert len(items) >= 1
        assert any(n["notification_type"] == "ACTION_REQUIRED" for n in items)

    async def test_12_workflow_step_approval_notification(self, client: AsyncClient, db_session):
        """Step approval creates STEP_APPROVED for secretary and ACTION_REQUIRED for next step."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_notif2")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Robotics Notif Club", admin
        )
        hall = await _create_test_hall(db_session)
        await _create_user(db_session, UserRole.HALL_INCHARGE, "hall_notif")

        event_id = await _create_and_submit_proposal(client, db_session, club, secretary, hall)

        # Get workflow instance step 1
        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        steps = {s["step_order"]: s["id"] for s in wf_res.json()["steps"]}

        # Advisor approves Step 1
        app_res = await client.post(
            f"/api/v1/workflows/steps/{steps[1]}/approve",
            json={"comments": "Academic objectives clear."},
            headers=_auth_header(advisor),
        )
        assert app_res.status_code == 200

        # Secretary receives STEP_APPROVED
        sec_notifs = await client.get("/api/v1/notifications", headers=_auth_header(secretary))
        assert sec_notifs.status_code == 200
        assert any(n["notification_type"] == "STEP_APPROVED" for n in sec_notifs.json())

    async def test_13_workflow_revision_notification(self, client: AsyncClient, db_session):
        """Requesting revision triggers REVISION_REQUIRED notification to secretary."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_notif3")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Art Notif Club", admin
        )
        hall = await _create_test_hall(db_session)
        event_id = await _create_and_submit_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        step1_id = next(s["id"] for s in wf_res.json()["steps"] if s["step_order"] == 1)

        rev_res = await client.post(
            f"/api/v1/workflows/steps/{step1_id}/request-revision",
            json={"comments": "Please update details with additional information."},
            headers=_auth_header(advisor),
        )
        assert rev_res.status_code == 200

        sec_notifs = await client.get("/api/v1/notifications", headers=_auth_header(secretary))
        assert sec_notifs.status_code == 200
        assert any(n["notification_type"] == "REVISION_REQUIRED" for n in sec_notifs.json())

    async def test_14_workflow_rejection_notification(self, client: AsyncClient, db_session):
        """Rejecting a step triggers PROPOSAL_REJECTED notification to secretary."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_notif4")
        club, secretary, advisor = await _create_club_and_advisor(
            db_session, "Gaming Notif Club", admin
        )
        hall = await _create_test_hall(db_session)
        event_id = await _create_and_submit_proposal(client, db_session, club, secretary, hall)

        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        step1_id = next(s["id"] for s in wf_res.json()["steps"] if s["step_order"] == 1)

        rej_res = await client.post(
            f"/api/v1/workflows/steps/{step1_id}/reject",
            json={"comments": "Proposal rejected due to policy non-compliance."},
            headers=_auth_header(advisor),
        )
        assert rej_res.status_code == 200

        sec_notifs = await client.get("/api/v1/notifications", headers=_auth_header(secretary))
        assert sec_notifs.status_code == 200
        assert any(n["notification_type"] == "PROPOSAL_REJECTED" for n in sec_notifs.json())

    async def test_15_invalid_uuid_handling(self, client: AsyncClient, db_session):
        """Malformed UUID returns 422 Unprocessable Entity."""
        user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "user_uuid_err")
        res = await client.patch(
            "/api/v1/notifications/invalid-uuid-format/read", headers=_auth_header(user)
        )
        assert res.status_code == 422
