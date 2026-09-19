"""
CampusConnect Backend — Shared API Dependencies

Provides:
- Database session dependency (`get_db`)
- Current authenticated user dependency (`get_current_user`)
"""
import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import (
    AccountInactiveError,
    InvalidTokenError,
    UnauthorizedError,
)
from app.core.security import decode_access_token
from app.models.domain import User

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
    5. Verify user is active.
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
