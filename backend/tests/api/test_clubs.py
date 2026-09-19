"""
CampusConnect — Core Club Governance API & Security Test Suite

Comprehensive test coverage for Day 3.2:
- Club Creation (auth, validation, advisor assignment, slug, collision, audit)
- Club Retrieval (get by ID, list, soft-delete exclusion)
- Club Updates (ownership enforcement, cross-club 403, system admin rules, audit)
- Membership Management (add, update, remove/soft-deactivate, cross-club 403, validation)
- Security & Ownership (path ID tampering, untrusted client claims, zero credential leak, soft-deleted user)
- Transaction & Integrity (database uniqueness, rollback on failure, clean audit snapshots)
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.domain import AuditLog, Club, ClubMember, User
from app.models.enums import AuditAction, ClubMemberRole, UserRole


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
    """Create a verified test user with explicit role and status."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@college.edu",
        password_hash=hash_password("StrongPass123!"),
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
    """Generate valid Bearer authorization header for a test user."""
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token(
        subject=user.id,
        role=role_str,
        email=user.email,
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_club_in_db(
    db,
    name: str,
    creator: User,
    advisor: User | None = None,
    slug: str | None = None,
    is_active: bool = True,
    is_deleted: bool = False,
) -> Club:
    """Directly insert a club into DB for test setup."""
    from app.services.club_service import slugify
    club_slug = slug or slugify(name)
    club = Club(
        name=name,
        slug=club_slug,
        description=f"Description for {name}",
        faculty_advisor_id=advisor.id if advisor else None,
        academic_year="2026-27",
        is_active=is_active,
        created_by=creator.id,
        deleted_at=datetime.now(timezone.utc) if is_deleted else None,
    )
    db.add(club)
    await db.commit()
    await db.refresh(club)
    return club


async def _assign_club_secretary(db, club: Club, user: User) -> ClubMember:
    """Assign a user as active secretary of a club in the club_members table."""
    member = ClubMember(
        club_id=club.id,
        user_id=user.id,
        member_role=ClubMemberRole.SECRETARY,
        is_active=True,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


# ===========================================================================
# 1. CLUB CREATION TESTS
# ===========================================================================
@pytest.mark.asyncio
class TestClubCreation:
    """Tests 1-10: Club creation, permissions, advisor validation, slug, collisions, audits."""

    async def test_01_authorized_club_creation_succeeds(self, client: AsyncClient, db_session):
        """1. Authorized SYSTEM_ADMIN club creation succeeds with 201."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        advisor = await _create_user(db_session, UserRole.FACULTY_ADVISOR, "advisor")

        payload = {
            "name": "Robotics & AI Club",
            "description": "Building autonomous campus bots",
            "faculty_advisor_id": str(advisor.id),
            "academic_year": "2026-27",
            "logo_url": "https://college.edu/logos/robotics.png",
        }
        res = await client.post("/api/v1/clubs", json=payload, headers=_auth_header(admin))
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "Robotics & AI Club"
        assert data["slug"] == "robotics-ai-club"
        assert data["faculty_advisor_id"] == str(advisor.id)
        assert data["faculty_advisor_name"] == advisor.full_name
        assert data["academic_year"] == "2026-27"
        assert data["is_active"] is True
        assert data["created_by"] == str(admin.id)
        assert "password_hash" not in str(data)

    async def test_02_unauthorized_role_receives_403(self, client: AsyncClient, db_session):
        """2. Unauthorized role (e.g. CLUB_SECRETARY) cannot create a club."""
        secretary = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec")
        payload = {
            "name": "Unauthorized Club",
            "academic_year": "2026-27",
        }
        res = await client.post("/api/v1/clubs", json=payload, headers=_auth_header(secretary))
        assert res.status_code == 403
        assert res.json()["error"] == "forbidden"

    async def test_03_missing_authentication_receives_401(self, client: AsyncClient):
        """3. Missing authentication header receives 401."""
        payload = {"name": "No Auth Club", "academic_year": "2026-27"}
        res = await client.post("/api/v1/clubs", json=payload)
        assert res.status_code == 401
        assert res.json()["error"] == "unauthorized"

    async def test_04_invalid_faculty_advisor_is_rejected(self, client: AsyncClient, db_session):
        """4. Invalid faculty advisor (nonexistent UUID) is rejected with 400."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        fake_uuid = str(uuid.uuid4())
        payload = {
            "name": "Invalid Advisor Club",
            "faculty_advisor_id": fake_uuid,
            "academic_year": "2026-27",
        }
        res = await client.post("/api/v1/clubs", json=payload, headers=_auth_header(admin))
        assert res.status_code == 400
        assert res.json()["error"] == "bad_request"

    async def test_05_inactive_faculty_advisor_is_rejected(self, client: AsyncClient, db_session):
        """5. Inactive faculty advisor is rejected with 400."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        inactive_advisor = await _create_user(
            db_session, UserRole.FACULTY_ADVISOR, "inact_adv", is_active=False
        )
        payload = {
            "name": "Inactive Advisor Club",
            "faculty_advisor_id": str(inactive_advisor.id),
            "academic_year": "2026-27",
        }
        res = await client.post("/api/v1/clubs", json=payload, headers=_auth_header(admin))
        assert res.status_code == 400
        assert res.json()["error"] == "bad_request"

    async def test_06_non_faculty_user_cannot_be_assigned_as_advisor(self, client: AsyncClient, db_session):
        """6. Non-faculty user (e.g. CLUB_SECRETARY) cannot be assigned as advisor."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        secretary = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_adv")
        payload = {
            "name": "Wrong Role Advisor Club",
            "faculty_advisor_id": str(secretary.id),
            "academic_year": "2026-27",
        }
        res = await client.post("/api/v1/clubs", json=payload, headers=_auth_header(admin))
        assert res.status_code == 400
        assert res.json()["error"] == "bad_request"

    async def test_07_duplicate_club_name_handled_correctly(self, client: AsyncClient, db_session):
        """7. Duplicate club name returns 409 Conflict."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        payload = {"name": "Astronomy Society", "academic_year": "2026-27"}
        res1 = await client.post("/api/v1/clubs", json=payload, headers=_auth_header(admin))
        assert res1.status_code == 201

        # Attempt to create exact same name
        res2 = await client.post("/api/v1/clubs", json=payload, headers=_auth_header(admin))
        assert res2.status_code == 409
        assert res2.json()["error"] == "conflict"

    async def test_08_slug_generated_correctly(self, client: AsyncClient, db_session):
        """8. Slug is generated in lowercase, URL-safe, hyphen-separated format."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        payload = {"name": "Coding & Algorithms 101!", "academic_year": "2026-27"}
        res = await client.post("/api/v1/clubs", json=payload, headers=_auth_header(admin))
        assert res.status_code == 201
        assert res.json()["slug"] == "coding-algorithms-101"

    async def test_09_slug_collision_handled_correctly(self, client: AsyncClient, db_session):
        """9. Slug collision handled safely by incrementing numerical suffix."""
        from app.services.club_service import ClubService
        slug1 = await ClubService.generate_unique_slug(db_session, "Music Society")
        assert slug1 == "music-society"

        # Create a club with this slug
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        await _create_club_in_db(db_session, "Music Society", admin, slug="music-society")

        # Now generating unique slug for another club that maps to same base slug
        slug2 = await ClubService.generate_unique_slug(db_session, "Music-Society!")
        assert slug2 == "music-society-2"

    async def test_10_audit_log_created_on_club_creation(self, client: AsyncClient, db_session):
        """10. Audit log entries (CLUB_CREATED, ADVISOR_ASSIGNED) are created upon club creation."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        advisor = await _create_user(db_session, UserRole.FACULTY_ADVISOR, "adv")

        payload = {
            "name": "Biotech Society",
            "faculty_advisor_id": str(advisor.id),
            "academic_year": "2026-27",
        }
        res = await client.post("/api/v1/clubs", json=payload, headers=_auth_header(admin))
        assert res.status_code == 201
        club_id = res.json()["id"]

        # Verify audit logs in database
        stmt = select(AuditLog).where(
            AuditLog.entity_id == club_id, AuditLog.action == AuditAction.CLUB_CREATED
        )
        log = await db_session.scalar(stmt)
        assert log is not None
        assert log.actor_id == admin.id
        assert log.actor_role == UserRole.SYSTEM_ADMIN.value
        assert log.new_state["name"] == "Biotech Society"


# ===========================================================================
# 2. CLUB RETRIEVAL TESTS
# ===========================================================================
@pytest.mark.asyncio
class TestClubRetrieval:
    """Tests 11-13: Retrieve by ID, list clubs, exclude soft-deleted."""

    async def test_11_active_club_can_be_retrieved(self, client: AsyncClient, db_session):
        """11. Active club can be retrieved by any authenticated user."""
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "student")
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        advisor = await _create_user(db_session, UserRole.FACULTY_ADVISOR, "adv")
        club = await _create_club_in_db(db_session, "Debating Society", admin, advisor=advisor)

        res = await client.get(f"/api/v1/clubs/{club.id}", headers=_auth_header(student))
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == str(club.id)
        assert data["name"] == "Debating Society"
        assert data["faculty_advisor_name"] == advisor.full_name

    async def test_12_club_listing_works(self, client: AsyncClient, db_session):
        """12. Club listing works with pagination."""
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "student")
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        await _create_club_in_db(db_session, "Club Alpha", admin)
        await _create_club_in_db(db_session, "Club Beta", admin)

        res = await client.get("/api/v1/clubs?skip=0&limit=10", headers=_auth_header(student))
        assert res.status_code == 200
        clubs = res.json()
        assert isinstance(clubs, list)
        names = [c["name"] for c in clubs]
        assert "Club Alpha" in names
        assert "Club Beta" in names

    async def test_13_soft_deleted_club_is_not_returned(self, client: AsyncClient, db_session):
        """13. Soft-deleted club is not returned through normal active queries."""
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "student")
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        deleted_club = await _create_club_in_db(
            db_session, "Old Inactive Club", admin, is_deleted=True
        )

        # GET by ID returns 404
        res_get = await client.get(
            f"/api/v1/clubs/{deleted_club.id}", headers=_auth_header(student)
        )
        assert res_get.status_code == 404

        # Listing excludes soft-deleted club
        res_list = await client.get("/api/v1/clubs", headers=_auth_header(student))
        assert res_list.status_code == 200
        names = [c["name"] for c in res_list.json()]
        assert "Old Inactive Club" not in names


# ===========================================================================
# 3. CLUB UPDATE TESTS
# ===========================================================================
@pytest.mark.asyncio
class TestClubUpdate:
    """Tests 14-18: Ownership verification, cross-club 403, admin permission, audit record."""

    async def test_14_authorized_secretary_can_update_own_club(self, client: AsyncClient, db_session):
        """14. Authorized club secretary can update their own club profile."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec1")
        club = await _create_club_in_db(db_session, "Math Club", admin)
        await _assign_club_secretary(db_session, club, sec_user)

        payload = {"description": "Advanced problem solving and topology"}
        res = await client.patch(
            f"/api/v1/clubs/{club.id}", json=payload, headers=_auth_header(sec_user)
        )
        assert res.status_code == 200
        assert res.json()["description"] == "Advanced problem solving and topology"

    async def test_15_club_secretary_cannot_update_another_club(self, client: AsyncClient, db_session):
        """15. Club secretary cannot update another club (403 Forbidden)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_user_a = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_a")
        club_a = await _create_club_in_db(db_session, "Club One", admin)
        club_b = await _create_club_in_db(db_session, "Club Two", admin)
        await _assign_club_secretary(db_session, club_a, sec_user_a)

        # Secretary A tries to update Club B
        payload = {"description": "Malicious takeover attempt"}
        res = await client.patch(
            f"/api/v1/clubs/{club_b.id}", json=payload, headers=_auth_header(sec_user_a)
        )
        assert res.status_code == 403
        assert res.json()["error"] == "forbidden"

    async def test_16_unauthorized_role_receives_403(self, client: AsyncClient, db_session):
        """16. Unauthorized role (e.g. FINANCE_OFFICER) receives 403."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        finance = await _create_user(db_session, UserRole.FINANCE_OFFICER, "fin")
        club = await _create_club_in_db(db_session, "Finance Target Club", admin)

        res = await client.patch(
            f"/api/v1/clubs/{club.id}", json={"description": "Test"}, headers=_auth_header(finance)
        )
        assert res.status_code == 403
        assert res.json()["error"] == "forbidden"

    async def test_17_system_admin_can_update_any_club(self, client: AsyncClient, db_session):
        """17. SYSTEM_ADMIN behavior follows explicit permission rules and can update any club."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club = await _create_club_in_db(db_session, "Admin Target Club", admin)

        payload = {"description": "Institutional governance update"}
        res = await client.patch(
            f"/api/v1/clubs/{club.id}", json=payload, headers=_auth_header(admin)
        )
        assert res.status_code == 200
        assert res.json()["description"] == "Institutional governance update"

    async def test_18_update_creates_appropriate_audit_record(self, client: AsyncClient, db_session):
        """18. Update creates appropriate audit record with state diff."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        club = await _create_club_in_db(db_session, "Audited Club", admin)

        payload = {"description": "Fresh description for audit"}
        res = await client.patch(
            f"/api/v1/clubs/{club.id}", json=payload, headers=_auth_header(admin)
        )
        assert res.status_code == 200

        stmt = select(AuditLog).where(
            AuditLog.entity_id == str(club.id), AuditLog.action == AuditAction.CLUB_UPDATED
        )
        log = await db_session.scalar(stmt)
        assert log is not None
        assert log.new_state["description"] == "Fresh description for audit"


# ===========================================================================
# 4. MEMBERSHIP MANAGEMENT TESTS
# ===========================================================================
@pytest.mark.asyncio
class TestClubMembership:
    """Tests 19-28: Add member, nonexistent, inactive, duplicate, roles, update, remove, 403, audit."""

    async def test_19_authorized_secretary_can_add_member(self, client: AsyncClient, db_session):
        """19. Authorized secretary can add member to their club."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_mem")
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "student_mem")
        club = await _create_club_in_db(db_session, "Chess Club", admin)
        await _assign_club_secretary(db_session, club, sec_user)

        payload = {"user_id": str(student.id), "member_role": "MEMBER"}
        res = await client.post(
            f"/api/v1/clubs/{club.id}/members", json=payload, headers=_auth_header(sec_user)
        )
        assert res.status_code == 201
        data = res.json()
        assert data["club_id"] == str(club.id)
        assert data["user_id"] == str(student.id)
        assert data["member_role"] == "MEMBER"
        assert data["is_active"] is True

    async def test_20_cannot_add_nonexistent_user(self, client: AsyncClient, db_session):
        """20. Cannot add nonexistent user ID to club roster."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_ghost")
        club = await _create_club_in_db(db_session, "Ghost Target Club", admin)
        await _assign_club_secretary(db_session, club, sec_user)

        payload = {"user_id": str(uuid.uuid4()), "member_role": "MEMBER"}
        res = await client.post(
            f"/api/v1/clubs/{club.id}/members", json=payload, headers=_auth_header(sec_user)
        )
        assert res.status_code == 404

    async def test_21_cannot_add_inactive_user(self, client: AsyncClient, db_session):
        """21. Cannot add inactive user to club roster."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_inact")
        inactive_user = await _create_user(
            db_session, UserRole.CLUB_SECRETARY, "inact_stu", is_active=False
        )
        club = await _create_club_in_db(db_session, "Inactive Member Club", admin)
        await _assign_club_secretary(db_session, club, sec_user)

        payload = {"user_id": str(inactive_user.id), "member_role": "MEMBER"}
        res = await client.post(
            f"/api/v1/clubs/{club.id}/members", json=payload, headers=_auth_header(sec_user)
        )
        assert res.status_code == 400

    async def test_22_duplicate_membership_is_rejected(self, client: AsyncClient, db_session):
        """22. Duplicate active membership returns 409 Conflict."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_dup")
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "student_dup")
        club = await _create_club_in_db(db_session, "Duplicate Target Club", admin)
        await _assign_club_secretary(db_session, club, sec_user)

        payload = {"user_id": str(student.id), "member_role": "MEMBER"}
        res1 = await client.post(
            f"/api/v1/clubs/{club.id}/members", json=payload, headers=_auth_header(sec_user)
        )
        assert res1.status_code == 201

        # Attempt to add same user again
        res2 = await client.post(
            f"/api/v1/clubs/{club.id}/members", json=payload, headers=_auth_header(sec_user)
        )
        assert res2.status_code == 409
        assert res2.json()["error"] == "conflict"

    async def test_23_member_role_validation_works(self, client: AsyncClient, db_session):
        """23. Invalid member role is rejected by schema validation (422)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_val")
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "stu_val")
        club = await _create_club_in_db(db_session, "Validation Club", admin)
        await _assign_club_secretary(db_session, club, sec_user)

        payload = {"user_id": str(student.id), "member_role": "SUPREME_OVERLORD"}
        res = await client.post(
            f"/api/v1/clubs/{club.id}/members", json=payload, headers=_auth_header(sec_user)
        )
        assert res.status_code == 422

    async def test_24_authorized_secretary_can_update_member_role(self, client: AsyncClient, db_session):
        """24. Authorized secretary can promote/update a member role to TREASURER."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_upd")
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "stu_upd")
        club = await _create_club_in_db(db_session, "Promotion Club", admin)
        await _assign_club_secretary(db_session, club, sec_user)

        # First add member
        await client.post(
            f"/api/v1/clubs/{club.id}/members",
            json={"user_id": str(student.id), "member_role": "MEMBER"},
            headers=_auth_header(sec_user),
        )

        # Update member role to TREASURER
        res = await client.patch(
            f"/api/v1/clubs/{club.id}/members/{student.id}",
            json={"member_role": "TREASURER"},
            headers=_auth_header(sec_user),
        )
        assert res.status_code == 200
        assert res.json()["member_role"] == "TREASURER"

    async def test_25_authorized_secretary_can_remove_member(self, client: AsyncClient, db_session):
        """25. Authorized secretary can remove (soft-deactivate) a member with 204."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_rem")
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "stu_rem")
        club = await _create_club_in_db(db_session, "Removal Club", admin)
        await _assign_club_secretary(db_session, club, sec_user)

        # Add member
        await client.post(
            f"/api/v1/clubs/{club.id}/members",
            json={"user_id": str(student.id), "member_role": "MEMBER"},
            headers=_auth_header(sec_user),
        )

        # Delete / Deactivate member
        res = await client.delete(
            f"/api/v1/clubs/{club.id}/members/{student.id}",
            headers=_auth_header(sec_user),
        )
        assert res.status_code == 204

        # Member should now be is_active=False in DB
        member = await db_session.scalar(
            select(ClubMember).where(ClubMember.club_id == club.id, ClubMember.user_id == student.id)
        )
        assert member is not None
        assert member.is_active is False

    async def test_26_cross_club_membership_manipulation_returns_403(self, client: AsyncClient, db_session):
        """26. Cross-club membership manipulation returns 403 Forbidden."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_a = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_a_cross")
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "stu_cross")
        club_a = await _create_club_in_db(db_session, "Club Alpha Cross", admin)
        club_b = await _create_club_in_db(db_session, "Club Beta Cross", admin)
        await _assign_club_secretary(db_session, club_a, sec_a)

        # Secretary A tries to add member to Club B
        payload = {"user_id": str(student.id), "member_role": "MEMBER"}
        res = await client.post(
            f"/api/v1/clubs/{club_b.id}/members", json=payload, headers=_auth_header(sec_a)
        )
        assert res.status_code == 403
        assert res.json()["error"] == "forbidden"

    async def test_27_unauthorized_role_receives_403_on_members(self, client: AsyncClient, db_session):
        """27. Unauthorized role (e.g. DEAN_STUDENT_AFFAIRS) receives 403 managing members."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        dean = await _create_user(db_session, UserRole.DEAN_STUDENT_AFFAIRS, "dean")
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "stu_dean")
        club = await _create_club_in_db(db_session, "Dean Target Club", admin)

        payload = {"user_id": str(student.id), "member_role": "MEMBER"}
        res = await client.post(
            f"/api/v1/clubs/{club.id}/members", json=payload, headers=_auth_header(dean)
        )
        assert res.status_code == 403

    async def test_28_membership_audit_events_created(self, client: AsyncClient, db_session):
        """28. Audit events (MEMBER_ADDED, MEMBER_REMOVED) are recorded with snapshots."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_user = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_aud")
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "stu_aud")
        club = await _create_club_in_db(db_session, "Audit Membership Club", admin)
        await _assign_club_secretary(db_session, club, sec_user)

        # Add member
        await client.post(
            f"/api/v1/clubs/{club.id}/members",
            json={"user_id": str(student.id), "member_role": "MEMBER"},
            headers=_auth_header(sec_user),
        )
        # Remove member
        await client.delete(
            f"/api/v1/clubs/{club.id}/members/{student.id}",
            headers=_auth_header(sec_user),
        )

        added_log = await db_session.scalar(
            select(AuditLog).where(
                AuditLog.action == AuditAction.MEMBER_ADDED,
                AuditLog.actor_id == sec_user.id,
            )
        )
        assert added_log is not None
        assert added_log.new_state["user_id"] == str(student.id)

        removed_log = await db_session.scalar(
            select(AuditLog).where(
                AuditLog.action == AuditAction.MEMBER_REMOVED,
                AuditLog.actor_id == sec_user.id,
            )
        )
        assert removed_log is not None
        assert removed_log.new_state["is_active"] is False


# ===========================================================================
# 5. SECURITY & OWNERSHIP HARDENING
# ===========================================================================
@pytest.mark.asyncio
class TestSecurityAndOwnership:
    """Tests 29-33: Path tampering, untrusted client claims, zero credential leak, soft-deleted user."""

    async def test_29_user_cannot_modify_club_b_by_path_tampering(self, client: AsyncClient, db_session):
        """29. User cannot modify Club B by simply changing the path UUID parameter."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_a = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_tamper")
        club_a = await _create_club_in_db(db_session, "Tamper Club A", admin)
        club_b = await _create_club_in_db(db_session, "Tamper Club B", admin)
        await _assign_club_secretary(db_session, club_a, sec_a)

        # Tampering path to club_b
        res = await client.patch(
            f"/api/v1/clubs/{club_b.id}",
            json={"description": "Hacked description"},
            headers=_auth_header(sec_a),
        )
        assert res.status_code == 403
        assert res.json()["error"] == "forbidden"

    async def test_30_user_cannot_manage_club_b_members(self, client: AsyncClient, db_session):
        """30. User cannot manage Club B members via URL tampering."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        sec_a = await _create_user(db_session, UserRole.CLUB_SECRETARY, "sec_tamper2")
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "stu_tamper")
        club_a = await _create_club_in_db(db_session, "Tamper Member A", admin)
        club_b = await _create_club_in_db(db_session, "Tamper Member B", admin)
        await _assign_club_secretary(db_session, club_a, sec_a)

        res = await client.delete(
            f"/api/v1/clubs/{club_b.id}/members/{student.id}",
            headers=_auth_header(sec_a),
        )
        assert res.status_code == 403

    async def test_31_client_supplied_ownership_information_is_never_trusted(self, client: AsyncClient, db_session):
        """31. Server validates against database-backed ClubMember table, never client claims."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        unassigned_sec = await _create_user(db_session, UserRole.CLUB_SECRETARY, "unassigned_sec")
        club = await _create_club_in_db(db_session, "No Secretary Club", admin)

        # User has system role CLUB_SECRETARY but is NOT registered as secretary for this club
        res = await client.patch(
            f"/api/v1/clubs/{club.id}",
            json={"description": "Unauthorized"},
            headers=_auth_header(unassigned_sec),
        )
        assert res.status_code == 403

    async def test_32_sensitive_authentication_data_never_appears_in_responses(self, client: AsyncClient, db_session):
        """32. Sensitive authentication data (hashes, tokens, secrets) never appears in responses."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        advisor = await _create_user(db_session, UserRole.FACULTY_ADVISOR, "leak_adv")
        club = await _create_club_in_db(db_session, "Leak Audit Club", admin, advisor=advisor)

        res = await client.get(f"/api/v1/clubs/{club.id}", headers=_auth_header(admin))
        assert res.status_code == 200
        raw_text = res.text.lower()
        assert "password" not in raw_text
        assert "hash" not in raw_text
        assert "secret" not in raw_text
        assert "token" not in raw_text

    async def test_33_soft_deleted_users_cannot_perform_club_operations(self, client: AsyncClient, db_session):
        """33. Soft-deleted users cannot perform club operations (401 Unauthorized)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        deleted_admin = await _create_user(
            db_session, UserRole.SYSTEM_ADMIN, "del_adm", is_deleted=True
        )

        payload = {"name": "Deleted Admin Club", "academic_year": "2026-27"}
        res = await client.post("/api/v1/clubs", json=payload, headers=_auth_header(deleted_admin))
        assert res.status_code == 401


# ===========================================================================
# 6. TRANSACTION & INTEGRITY
# ===========================================================================
@pytest.mark.asyncio
class TestTransactionAndIntegrity:
    """Tests 34-36: Database uniqueness, no orphan audit logs, clean snapshots."""

    async def test_34_database_uniqueness_remains_enforced(self, client: AsyncClient, db_session):
        """34. Database uniqueness constraint prevents duplicate member insertion."""
        from sqlalchemy.exc import IntegrityError

        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        student = await _create_user(db_session, UserRole.CLUB_SECRETARY, "uniq_stu")
        club = await _create_club_in_db(db_session, "DB Uniq Club", admin)

        member1 = ClubMember(club_id=club.id, user_id=student.id, member_role=ClubMemberRole.MEMBER)
        db_session.add(member1)
        await db_session.commit()

        # Direct second insert must trigger IntegrityError
        member2 = ClubMember(club_id=club.id, user_id=student.id, member_role=ClubMemberRole.MEMBER)
        db_session.add(member2)
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_35_failed_operations_do_not_create_orphan_audits(self, client: AsyncClient, db_session):
        """35. Failed operations rollback cleanly and create no orphan audit logs."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")

        # Record count of audit logs before failure
        count_before = len((await db_session.scalars(select(AuditLog))).all())

        # Submit request designed to fail (invalid advisor)
        payload = {
            "name": "Orphan Test Club",
            "faculty_advisor_id": str(uuid.uuid4()),
            "academic_year": "2026-27",
        }
        res = await client.post("/api/v1/clubs", json=payload, headers=_auth_header(admin))
        assert res.status_code == 400

        count_after = len((await db_session.scalars(select(AuditLog))).all())
        assert count_after == count_before

    async def test_36_audit_state_snapshots_contain_only_intended_fields(self, client: AsyncClient, db_session):
        """36. Audit state snapshots contain only intended fields and zero credentials."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin")
        res = await client.post(
            "/api/v1/clubs",
            json={"name": "Snapshot Audit Club", "academic_year": "2026-27"},
            headers=_auth_header(admin),
        )
        assert res.status_code == 201
        club_id = res.json()["id"]

        log = await db_session.scalar(
            select(AuditLog).where(AuditLog.entity_id == club_id, AuditLog.action == AuditAction.CLUB_CREATED)
        )
        assert log is not None
        assert isinstance(log.new_state, dict)
        keys = set(log.new_state.keys())
        assert keys == {
            "name",
            "slug",
            "academic_year",
            "faculty_advisor_id",
            "description",
            "logo_url",
            "is_active",
        }
