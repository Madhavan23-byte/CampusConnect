"""
CampusConnect — Role-Based Access Control (RBAC) Hardened Test Suite

Comprehensive coverage for:
1. Single role guard (require_role):
   - Every defined institutional role can be instantiated and authorized
   - Wrong role receives 403 Forbidden
   - SYSTEM_ADMIN is not implicitly accepted on non-admin routes
   - Invalid role input raises ValueError safely during construction

2. Multi-role guard (require_any_role):
   - One allowed role succeeds
   - Each allowed role succeeds individually
   - Unrelated role receives 403 Forbidden
   - Empty role list raises ValueError
   - Duplicate roles behave deterministically (deduplication in frozenset)

3. Permission guard (require_permission):
   - Complete matrix validation: every Permission has an explicit, non-empty role mapping
   - Every mapped role is a valid UserRole
   - Authorized role allowed (200 OK)
   - Unmapped role receives 403 Forbidden
   - Permission mapping cannot be bypassed by JWT claims

4. Institutional boundaries (No implicit hierarchy):
   - Principal does not inherit Club Secretary or Finance Officer permissions
   - Finance Officer cannot access Club Secretary operations

5. Explicit SYSTEM_ADMIN handling:
   - SYSTEM_ADMIN cannot silently bypass institutional routes
   - SYSTEM_ADMIN allowed only on administrative / explicitly permitted routes

6. Authentication and Lifecycle enforcement:
   - Missing token → 401 Unauthorized
   - Malformed token → 401 Unauthorized
   - Expired token → 401 Unauthorized
   - Invalid signature (tampered / wrong secret) → 401 Unauthorized
   - Wrong token type (e.g. refresh token used as Bearer) → 401 Unauthorized
   - Deactivated / inactive user → 401 Unauthorized
   - Soft-deleted user → 401 Unauthorized

7. Zero Privilege Escalation:
   - Database role remains authoritative
   - Spoofed JWT claims cannot bypass database role checks

8. Error handling & Information Leakage Audit:
   - Standard application exception format: {"error": "forbidden", "message": "..."}
   - Zero leakage of passwords, password hashes, secrets, tokens, or tracebacks
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from jose import jwt
import pytest
from fastapi import APIRouter, Depends
from httpx import AsyncClient

from app.api.deps import require_any_role, require_permission, require_role
from app.core.config import get_settings
from app.core.exceptions import InsufficientRoleError
from app.core.permissions import Permission, ROLE_PERMISSIONS
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.domain import User
from app.models.enums import UserRole

settings = get_settings()

# ---------------------------------------------------------------------------
# Test Router Setup (attached to app during tests)
# ---------------------------------------------------------------------------
rbac_test_router = APIRouter(prefix="/api/v1/test-rbac", tags=["rbac-test"])


@rbac_test_router.get("/secretary-only")
async def secretary_endpoint(
    user: Annotated[User, Depends(require_role(UserRole.CLUB_SECRETARY))]
):
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    return {"message": "secretary authorized", "role": role_str}


@rbac_test_router.get("/officials-only")
async def officials_endpoint(
    user: Annotated[User, Depends(require_any_role(
        UserRole.FACULTY_ADVISOR,
        UserRole.DEAN_STUDENT_AFFAIRS,
        UserRole.PRINCIPAL,
    ))]
):
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    return {"message": "official authorized", "role": role_str}


@rbac_test_router.get("/admin-only")
async def admin_endpoint(
    user: Annotated[User, Depends(require_role(UserRole.SYSTEM_ADMIN))]
):
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    return {"message": "admin authorized", "role": role_str}


@rbac_test_router.get("/propose-permission")
async def propose_endpoint(
    user: Annotated[User, Depends(require_permission(Permission.EVENT_PROPOSE))]
):
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    return {"message": "event propose authorized", "role": role_str}


@rbac_test_router.get("/finance-review")
async def finance_endpoint(
    user: Annotated[User, Depends(require_permission(Permission.APPROVAL_FINANCE_REVIEW))]
):
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    return {"message": "finance authorized", "role": role_str}


# Include test router in FastAPI app once
if not any(r.path == "/api/v1/test-rbac" for r in app.routes):
    app.include_router(rbac_test_router)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _create_test_user(
    db,
    role: UserRole | str,
    email_prefix: str,
    is_active: bool = True,
    is_deleted: bool = False,
) -> User:
    unique_id = uuid.uuid4().hex[:8]
    user = User(
        email=f"{email_prefix}_{unique_id}@college.edu",
        password_hash=hash_password("SecurePass123!"),
        full_name=f"Test {role} User",
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
        user.role.value if hasattr(user.role, "value") else str(user.role)
    )
    token = create_access_token(
        subject=user.id,
        role=token_role,
        email=user.email,
    )
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# A. Unit Tests for Guard Instantiation & Matrix Validation
# ===========================================================================
class TestRBACUnit:
    """Unit tests for RoleChecker, factory methods, and permission matrix."""

    @pytest.mark.parametrize("role", list(UserRole))
    def test_every_defined_role_can_be_explicitly_authorized(self, role: UserRole):
        """Every role in UserRole enum must be valid for require_role."""
        checker = require_role(role)
        assert role.value in checker.allowed_roles

    def test_require_role_with_valid_string(self):
        checker = require_role("CLUB_SECRETARY")
        assert "CLUB_SECRETARY" in checker.allowed_roles

    def test_require_role_with_invalid_role_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid user role"):
            require_role("NON_EXISTENT_ROLE")

    def test_require_any_role_empty_raises_value_error(self):
        with pytest.raises(ValueError, match="require_any_role requires at least one role"):
            require_any_role()

    def test_require_any_role_duplicate_roles_deduplicated(self):
        """Passing duplicate roles behaves deterministically and deduplicates into set."""
        checker = require_any_role(UserRole.CLUB_SECRETARY, UserRole.CLUB_SECRETARY)
        assert len(checker.allowed_roles) == 1
        assert UserRole.CLUB_SECRETARY.value in checker.allowed_roles

    def test_permission_matrix_complete_and_deterministic(self):
        """
        Verify that every defined Permission has an explicit, non-empty role mapping
        and that every role in the mapping is a valid UserRole.
        """
        for perm in Permission:
            assert perm in ROLE_PERMISSIONS, f"Missing mapping for permission: {perm}"
            allowed = ROLE_PERMISSIONS[perm]
            assert isinstance(allowed, frozenset), f"Mapping for {perm} must be frozenset"
            assert len(allowed) > 0, f"Mapping for {perm} cannot be empty"
            for role in allowed:
                assert isinstance(role, UserRole), f"Role {role} in {perm} must be UserRole"

    def test_system_admin_presence_in_permission_matrix_is_intentional(self):
        """
        SYSTEM_ADMIN should only appear in administrative or designated governance permissions.
        Verify SYSTEM_ADMIN is NOT present in student-only operations (e.g. proposing events).
        """
        assert UserRole.SYSTEM_ADMIN not in ROLE_PERMISSIONS[Permission.EVENT_PROPOSE]
        assert UserRole.SYSTEM_ADMIN not in ROLE_PERMISSIONS[Permission.EVENT_EDIT_DRAFT]
        assert UserRole.SYSTEM_ADMIN not in ROLE_PERMISSIONS[Permission.APPROVAL_FACULTY_REVIEW]
        assert UserRole.SYSTEM_ADMIN in ROLE_PERMISSIONS[Permission.SYSTEM_CONFIG]
        assert UserRole.SYSTEM_ADMIN in ROLE_PERMISSIONS[Permission.USER_MANAGE]


# ===========================================================================
# B. Integration Tests: Single Role Guard (require_role)
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


# ===========================================================================
# C. Integration Tests: Multi-Role Guard (require_any_role)
# ===========================================================================
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


# ===========================================================================
# D. Institutional Boundary Enforcement (No Implicit Hierarchy)
# ===========================================================================
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

    @pytest.mark.asyncio
    async def test_finance_officer_cannot_access_club_secretary_endpoint(
        self, client: AsyncClient, db_session
    ):
        finance = await _create_test_user(db_session, UserRole.FINANCE_OFFICER, "fin_boundary")
        headers = _auth_header(finance)

        response = await client.get("/api/v1/test-rbac/secretary-only", headers=headers)
        assert response.status_code == 403
        assert response.json()["error"] == "forbidden"


# ===========================================================================
# E. Authentication and Lifecycle Enforcement
# ===========================================================================
class TestAuthenticationAndLifecycleEnforcement:
    """Verifies 401 unauthenticated, invalid token, and account lifecycle enforcement."""

    @pytest.mark.asyncio
    async def test_unauthenticated_request_returns_401(self, client: AsyncClient):
        response = await client.get("/api/v1/test-rbac/secretary-only")
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_malformed_token_returns_401(self, client: AsyncClient):
        bad_headers = {"Authorization": "Bearer not.a.valid.jwt.token"}
        response = await client.get("/api/v1/test-rbac/secretary-only", headers=bad_headers)
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_expired_token_returns_401(self, client: AsyncClient, db_session):
        user = await _create_test_user(db_session, UserRole.CLUB_SECRETARY, "sec_expired")
        expired_token = create_access_token(
            subject=user.id,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            email=user.email,
            expires_delta=timedelta(seconds=-10),
        )
        headers = {"Authorization": f"Bearer {expired_token}"}
        response = await client.get("/api/v1/test-rbac/secretary-only", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_401(self, client: AsyncClient, db_session):
        """Token signed with a different key is rejected with 401."""
        user = await _create_test_user(db_session, UserRole.CLUB_SECRETARY, "sec_bad_sig")
        payload = {
            "sub": str(user.id),
            "email": user.email,
            "role": "CLUB_SECRETARY",
            "token_type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        }
        forged_token = jwt.encode(payload, "wrong-secret-key", algorithm="HS256")
        headers = {"Authorization": f"Bearer {forged_token}"}

        response = await client.get("/api/v1/test-rbac/secretary-only", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_wrong_token_type_returns_401(self, client: AsyncClient, db_session):
        """A token with token_type='refresh' presented as access token is rejected with 401."""
        user = await _create_test_user(db_session, UserRole.CLUB_SECRETARY, "sec_bad_type")
        payload = {
            "sub": str(user.id),
            "email": user.email,
            "role": "CLUB_SECRETARY",
            "token_type": "refresh",  # wrong type
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        }
        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/test-rbac/secretary-only", headers=headers)
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


# ===========================================================================
# F. Security: Privilege Escalation & Error Information Leakage Audit
# ===========================================================================
class TestSecurityAndInformationLeakage:
    """Verifies that JWT claims tampering cannot escalate privilege and errors don't leak."""

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
        spoofed_headers = _auth_header(secretary, custom_role_claim="SYSTEM_ADMIN")

        response = await client.get("/api/v1/test-rbac/admin-only", headers=spoofed_headers)
        assert response.status_code == 403
        data = response.json()
        assert data["error"] == "forbidden"
        assert "CLUB_SECRETARY" in data["message"]

    @pytest.mark.asyncio
    async def test_unknown_db_role_rejected_with_403(self, client: AsyncClient, db_session):
        """If a user record has an unknown role string, access is safely rejected with 403."""
        user = await _create_test_user(db_session, "NONEXISTENT_ROLE", "sec_unknown")
        headers = _auth_header(user)

        response = await client.get("/api/v1/test-rbac/secretary-only", headers=headers)
        assert response.status_code == 403
        data = response.json()
        assert data["error"] == "forbidden"
        assert "NONEXISTENT_ROLE" in data["message"]

    @pytest.mark.asyncio
    async def test_403_response_does_not_leak_sensitive_information(
        self, client: AsyncClient, db_session
    ):
        """Ensure 403 error payload contains standard keys and never exposes passwords, hashes or secrets."""
        user = await _create_test_user(db_session, UserRole.FACULTY_ADVISOR, "sec_leak_check")
        headers = _auth_header(user)

        response = await client.get("/api/v1/test-rbac/secretary-only", headers=headers)
        assert response.status_code == 403
        body_text = response.text.lower()

        # Sensitive keywords that must never be leaked
        assert "password" not in body_text
        assert "hash" not in body_text
        assert "token" not in body_text
        assert "secret_key" not in body_text
        assert "jwt_secret" not in body_text
        assert "traceback" not in body_text
        assert "exception" not in body_text
