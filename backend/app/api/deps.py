"""
CampusConnect Backend — Shared API Dependencies and RBAC Guards

Provides:
- Database session dependency (`get_db`)
- Current authenticated user dependency (`get_current_user`)
- Role-based authorization dependencies (`require_role`, `require_any_role`)
- Permission-based authorization dependency (`require_permission`)
"""

import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import (
    AccountInactiveError,
    InsufficientRoleError,
    InvalidTokenError,
    UnauthorizedError,
)
from app.core.permissions import ROLE_PERMISSIONS, Permission
from app.core.security import decode_access_token
from app.models.domain import User
from app.models.enums import UserRole

# HTTPBearer scheme with auto_error=False to allow clean custom exception handling
http_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
) -> User:
    """
    Authenticate request via Bearer access token.

    Steps:
    1. Extract Authorization: Bearer <access_token> header.
    2. Decode and validate JWT (signature, expiry, token_type='access').
    3. Extract user ID (sub claim).
    4. Fetch active user from database.
    5. Verify user is active and not soft-deleted.
    6. Return User model instance.

    Raises:
        UnauthorizedError: If header is missing, token expired, or user not found.
        InvalidTokenError: If token is malformed, invalid signature, or wrong type.
        AccountInactiveError: If user is deactivated.
    """
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Authentication credentials were not provided")

    token = credentials.credentials
    payload = decode_access_token(token)

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise InvalidTokenError("Token missing subject claim")

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError as exc:
        raise InvalidTokenError("Invalid user ID in token") from exc

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise UnauthorizedError("User associated with this token was not found")

    if not user.is_active:
        raise AccountInactiveError("User account is deactivated")

    return user


def _normalize_role(role: UserRole | str) -> str:
    """Validate and normalize a role input to its canonical string representation."""
    if isinstance(role, UserRole):
        return role.value
    if isinstance(role, str):
        try:
            return UserRole(role).value
        except ValueError:
            valid_roles = ", ".join(sorted(r.value for r in UserRole))
            raise ValueError(f"Invalid user role: '{role}'. Must be one of: {valid_roles}")
    raise TypeError(f"Role must be a UserRole enum or str, got {type(role).__name__}")


class RoleChecker:
    """
    Reusable FastAPI dependency that enforces role-based access control (RBAC).

    Guarantees:
    1. Builds on `get_current_user` so authentication, token decoding, and active-user
       verification are strictly not duplicated.
    2. Enforces authorization using the database-verified user state (User.role),
       preventing any privilege escalation through forged or tampered JWT claims.
    3. Institutional roles represent distinct institutional responsibilities;
       no implicit hierarchical inheritance is assumed (e.g. PRINCIPAL does not
       automatically inherit CLUB_SECRETARY or FINANCE_OFFICER actions).
    4. SYSTEM_ADMIN access is explicit: administrators do not silently bypass
       endpoint guards unless SYSTEM_ADMIN is explicitly included in allowed roles.
    5. Returns 401 for unauthenticated/inactive/deleted users via get_current_user.
    6. Returns 403 (InsufficientRoleError) when authenticated with an insufficient role.
    """

    def __init__(self, allowed_roles: Sequence[UserRole | str]) -> None:
        if not allowed_roles:
            raise ValueError("RoleChecker requires at least one allowed role")
        self.allowed_roles = frozenset(_normalize_role(r) for r in allowed_roles)

    async def __call__(
        self,
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        user_role = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        )
        if user_role not in self.allowed_roles:
            raise InsufficientRoleError(
                f"Role '{user_role}' is not authorized to access this resource. "
                f"Required: {', '.join(sorted(self.allowed_roles))}"
            )
        return current_user


def require_role(role: UserRole | str) -> RoleChecker:
    """
    FastAPI dependency factory that requires the authenticated user to have a specific role.

    Usage:
        @router.get("/proposals")
        async def get_proposals(user: Annotated[User, Depends(require_role(UserRole.CLUB_SECRETARY))]):
            ...
    """
    return RoleChecker([role])


def require_any_role(*roles: UserRole | str) -> RoleChecker:
    """
    FastAPI dependency factory that requires the authenticated user to have at least one
    of the specified roles.

    Usage:
        @router.get("/review-queue")
        async def get_queue(
            user: Annotated[User, Depends(require_any_role(
                UserRole.FACULTY_ADVISOR,
                UserRole.DEAN_STUDENT_AFFAIRS,
                UserRole.PRINCIPAL
            ))]
        ):
            ...
    """
    if not roles:
        raise ValueError("require_any_role requires at least one role argument")
    return RoleChecker(roles)


def require_permission(permission: Permission) -> RoleChecker:
    """
    FastAPI dependency factory that requires the authenticated user to possess
    a specific domain permission, resolving to the institutional roles configured
    for that permission.

    Usage:
        @router.post("/events")
        async def create_event(user: Annotated[User, Depends(require_permission(Permission.EVENT_PROPOSE))]):
            ...
    """
    allowed_roles = ROLE_PERMISSIONS.get(permission)
    if not allowed_roles:
        raise ValueError(f"No roles configured for permission: {permission}")
    return RoleChecker(list(allowed_roles))
