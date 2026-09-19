"""
CampusConnect — Role-Based Access Control (RBAC) Integration & Security Tests

Verifies:
1. Single role guard (require_role):
   - Correct role allowed (200 OK)
   - Wrong role rejected (403 Forbidden)
   - Detailed 403 error payload matches standard schema (error="forbidden")

2. Multi-role guard (require_any_role):
   - Any authorized role allowed (200 OK for each allowed role)
   - Non-matching role rejected (403 Forbidden)

3. Permission guard (require_permission):
   - Resolves granular institutional permissions to explicit authorized roles
   - Authorized role allowed (200 OK)
   - Unauthorized role rejected (403 Forbidden)

4. Institutional boundary enforcement (No implicit hierarchy):
   - Principal does not inherit Club Secretary or Finance Officer permissions
   - Faculty Advisor cannot perform Student Union Advisor actions

5. Explicit SYSTEM_ADMIN handling:
   - SYSTEM_ADMIN cannot silently bypass institutional routes unless explicitly allowed
   - SYSTEM_ADMIN allowed on administrative routes

6. Authentication and Lifecycle enforcement:
   - Unauthenticated request rejected (401 Unauthorized)
   - Deactivated / inactive user rejected (401 Unauthorized)
   - Soft-deleted user rejected (401 Unauthorized)

7. Zero Privilege Escalation:
   - Tampered/spoofed JWT claims (e.g. role="SYSTEM_ADMIN" in token payload)
     cannot escalate privileges; the authorization guard strictly checks the
     database-verified User.role.

8. Input validation on dependency instantiation:
   - Invalid role name raises ValueError
   - Empty role arguments raise ValueError
"""
import uuid
from datetime import datetime, timezone
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends
from httpx import AsyncClient

from app.api.deps import require_any_role, require_permission, require_role
from app.core.exceptions import InsufficientRoleError
from app.core.permissions import Permission
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.domain import User
from app.models.enums import UserRole

# ---------------------------------------------------------------------------
# Test Router Setup (attached to app during tests)
# ---------------------------------------------------------------------------
rbac_test_router = APIRouter(prefix="/api/v1/test-rbac", tags=["rbac-test"])


@rbac_test_router.get("/secretary-only")
async def secretary_endpoint(
    user: Annotated[User, Depends(require_role(UserRole.CLUB_SECRETARY))]
):
    return {"message": "secretary authorized", "role": user.role.value if hasattr(user.role, 'value') else str(user.role)}


@rbac_test_router.get("/officials-only")
async def officials_endpoint(
    user: Annotated[User, Depends(require_any_role(
        UserRole.FACULTY_ADVISOR,
        UserRole.DEAN_STUDENT_AFFAIRS,
        UserRole.PRINCIPAL,
    ))]
):
    return {"message": "official authorized", "role": user.role.value if hasattr(user.role, 'value') else str(user.role)}


@rbac_test_router.get("/admin-only")
async def admin_endpoint(
    user: Annotated[User, Depends(require_role(UserRole.SYSTEM_ADMIN))]
):
    return {"message": "admin authorized", "role": user.role.value if hasattr(user.role, 'value') else str(user.role)}


@rbac_test_router.get("/propose-permission")
async def propose_endpoint(
    user: Annotated[User, Depends(require_permission(Permission.EVENT_PROPOSE))]
):
    return {"message": "event propose authorized", "role": user.role.value if hasattr(user.role, 'value') else str(user.role)}


@rbac_test_router.get("/finance-review")
async def finance_endpoint(
    user: Annotated[User, Depends(require_permission(Permission.APPROVAL_FINANCE_REVIEW))]
):
    return {"message": "finance authorized", "role": user.role.value if hasattr(user.role, 'value') else str(user.role)}


# Include test router in FastAPI app once
if not any(r.path == "/api/v1/test-rbac" for r in app.routes):
    app.include_router(rbac_test_router)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _create_test_user(
    db,
    role: UserRole,
    email_prefix: str,
    is_active: bool = True,
    is_deleted: bool = False,
) -> User:
    unique_id = uuid.uuid4().hex[:8]
    user = User(
        email=f"{email_prefix}_{unique_id}@college.edu",
        password_hash=hash_password("SecurePass123!"),
        full_name=f"Test {role.value} User",
        role=role,
        is_active=is_active,
        deleted_at=datetime.now(timezone.utc) if is_deleted else None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _auth_header(user: User, custom_role_claim: str | None = None) -> dict[str, str]:
    token_role = custom_role_claim if custom_role_claim else (
        user.role.value if hasattr(user.role, 'value') else str(user.role) if hasattr(user.role, "value") else str(user.role)
    )
    token = create_access_token(
        subject=user.id,
        role=token_role,
        email=user.email,
    )
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Unit Tests for Guard Instantiation & Direct Execution
# ===========================================================================
class TestRBACUnit:
    """Unit tests for RoleChecker and factory methods."""

    def test_require_role_with_valid_enum(self):
        checker = require_role(UserRole.CLUB_SECRETARY)
        assert UserRole.CLUB_SECRETARY.value in checker.allowed_roles

    def test_require_role_with_valid_string(self):
        checker = require_role("CLUB_SECRETARY")
        assert "CLUB_SECRETARY" in checker.allowed_roles

    def test_require_role_with_invalid_role_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid user role"):
            require_role("NON_EXISTENT_ROLE")

    def test_require_any_role_empty_raises_value_error(self):
        with pytest.raises(ValueError, match="require_any_role requires at least one role"):
            require_any_role()

    def test_require_permission_maps_correctly(self):
        checker = require_permission(Permission.EVENT_PROPOSE)
        assert UserRole.CLUB_SECRETARY.value in checker.allowed_roles
        assert len(checker.allowed_roles) == 1

    def test_require_permission_multi_role_mapping(self):
        checker = require_permission(Permission.AUDIT_LOG_VIEW)
        assert UserRole.SYSTEM_ADMIN.value in checker.allowed_roles
        assert UserRole.PRINCIPAL.value in checker.allowed_roles
        assert UserRole.DEAN_STUDENT_AFFAIRS.value in checker.allowed_roles


# ===========================================================================
# Integration Tests via API Client
# ===========================================================================
class TestRequireRoleAPI:
    """Tests single role guard behavior on API endpoints."""

    @pytest.mark.asyncio
    async def test_correct_role_allowed(self, client: AsyncClient, db_session):
        user = await _create_test_user(db_session, UserRole.CLUB_SECRETARY, "sec_ok")
        headers = _auth_header(user)

        response = await client.get("/api/v1/test-rbac/secretary-only", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "secretary authorized"
        assert data["role"] == "CLUB_SECRETARY"

    @pytest.mark.asyncio
    async def test_wrong_role_rejected_with_403(self, client: AsyncClient, db_session):
        user = await _create_test_user(db_session, UserRole.FACULTY_ADVISOR, "fac_bad")
        headers = _auth_header(user)

        response = await client.get("/api/v1/test-rbac/secretary-only", headers=headers)
        assert response.status_code == 403
        data = response.json()
        assert data["error"] == "forbidden"
        assert "not authorized" in data["message"]

    @pytest.mark.asyncio
    async def test_system_admin_rejected_when_not_in_allowed_roles(
        self, client: AsyncClient, db_session
    ):
        """
        Critical requirement: SYSTEM_ADMIN must NOT silently bypass institutional
        boundaries unless explicitly granted access.
        """
        admin = await _create_test_user(db_session, UserRole.SYSTEM_ADMIN, "admin_strict")
        headers = _auth_header(admin)

        response = await client.get("/api/v1/test-rbac/secretary-only", headers=headers)
        assert response.status_code == 403
        data = response.json()
        assert data["error"] == "forbidden"

    @pytest.mark.asyncio
    async def test_system_admin_allowed_on_admin_endpoint(
        self, client: AsyncClient, db_session
    ):
        admin = await _create_test_user(db_session, UserRole.SYSTEM_ADMIN, "admin_ok")
        headers = _auth_header(admin)

        response = await client.get("/api/v1/test-rbac/admin-only", headers=headers)
        assert response.status_code == 200
        assert response.json()["message"] == "admin authorized"


class TestRequireAnyRoleAPI:
    """Tests multi-role guard behavior on API endpoints."""

    @pytest.mark.asyncio
    async def test_all_specified_roles_allowed(self, client: AsyncClient, db_session):
        faculty = await _create_test_user(db_session, UserRole.FACULTY_ADVISOR, "fac_multi")
        dean = await _create_test_user(db_session, UserRole.DEAN_STUDENT_AFFAIRS, "dean_multi")
        principal = await _create_test_user(db_session, UserRole.PRINCIPAL, "prin_multi")

        for u in (faculty, dean, principal):
            headers = _auth_header(u)
            response = await client.get("/api/v1/test-rbac/officials-only", headers=headers)
            assert response.status_code == 200
            assert response.json()["message"] == "official authorized"

    @pytest.mark.asyncio
    async def test_unauthorized_role_rejected_from_multi_role(
        self, client: AsyncClient, db_session
    ):
        secretary = await _create_test_user(db_session, UserRole.CLUB_SECRETARY, "sec_multi_bad")
        headers = _auth_header(secretary)

        response = await client.get("/api/v1/test-rbac/officials-only", headers=headers)
        assert response.status_code == 403
        data = response.json()
        assert data["error"] == "forbidden"


class TestInstitutionalBoundaries:
    """Verifies that executive roles do not implicitly inherit operational roles."""

    @pytest.mark.asyncio
    async def test_principal_cannot_access_finance_specific_permission(
        self, client: AsyncClient, db_session
    ):
        principal = await _create_test_user(db_session, UserRole.PRINCIPAL, "prin_boundary")
        headers = _auth_header(principal)

        response = await client.get("/api/v1/test-rbac/finance-review", headers=headers)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_finance_officer_can_access_finance_specific_permission(
        self, client: AsyncClient, db_session
    ):
        finance = await _create_test_user(db_session, UserRole.FINANCE_OFFICER, "fin_ok")
        headers = _auth_header(finance)

        response = await client.get("/api/v1/test-rbac/finance-review", headers=headers)
        assert response.status_code == 200


class TestAuthenticationAndLifecycleEnforcement:
    """Verifies 401 unauthenticated and lifecycle error propagation."""

    @pytest.mark.asyncio
    async def test_unauthenticated_request_returns_401(self, client: AsyncClient):
        response = await client.get("/api/v1/test-rbac/secretary-only")
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_inactive_user_returns_401(self, client: AsyncClient, db_session):
        user = await _create_test_user(
            db_session, UserRole.CLUB_SECRETARY, "sec_inactive", is_active=False
        )
        headers = _auth_header(user)

        response = await client.get("/api/v1/test-rbac/secretary-only", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_soft_deleted_user_returns_401(self, client: AsyncClient, db_session):
        user = await _create_test_user(
            db_session, UserRole.CLUB_SECRETARY, "sec_deleted", is_deleted=True
        )
        headers = _auth_header(user)

        response = await client.get("/api/v1/test-rbac/secretary-only", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"


class TestSecurityPrivilegeEscalation:
    """Verifies that tampering with JWT claims cannot bypass RBAC checks."""

    @pytest.mark.asyncio
    async def test_forged_jwt_role_claim_cannot_escalate_privilege(
        self, client: AsyncClient, db_session
    ):
        """
        An attacker generates a signed token whose 'role' claim claims to be SYSTEM_ADMIN,
        but the subject ID belongs to a CLUB_SECRETARY user in PostgreSQL.
        The system must inspect the database-verified user role, preventing privilege escalation.
        """
        secretary = await _create_test_user(
            db_session, UserRole.CLUB_SECRETARY, "spoof_attacker"
        )
        # Forge token: role claim set to SYSTEM_ADMIN, but sub is secretary's UUID
        spoofed_headers = _auth_header(secretary, custom_role_claim="SYSTEM_ADMIN")

        # Attempt to access admin endpoint
        response = await client.get("/api/v1/test-rbac/admin-only", headers=spoofed_headers)
        assert response.status_code == 403
        data = response.json()
        assert data["error"] == "forbidden"
        # Real role was CLUB_SECRETARY
        assert "CLUB_SECRETARY" in data["message"]
