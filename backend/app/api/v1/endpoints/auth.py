"""
CampusConnect Backend — Authentication API Endpoints

Routes:
- POST /api/v1/auth/register: Register a new user account
- POST /api/v1/auth/login: Authenticate user, issue access token & HttpOnly refresh cookie
- POST /api/v1/auth/refresh: Rotate refresh token from cookie & return new access token
- POST /api/v1/auth/logout: Revoke refresh token & clear cookie
- GET  /api/v1/auth/me: Retrieve current authenticated user profile
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.models.domain import User
from app.schemas.auth import (
    TokenResponse,
    UserAuthResponse,
    UserLoginRequest,
    UserRegisterRequest,
)
from app.services.auth_service import AuthService

router = APIRouter()


@router.post(
    "/register",
    response_model=UserAuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Register a new college club member or coordinator account. Passwords must satisfy complexity requirements.",
)
async def register(
    register_data: UserRegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserAuthResponse:
    """Register user and return safe public profile without sensitive tokens or hashes."""
    user = await AuthService.register_user(db=db, register_data=register_data)
    return UserAuthResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate user",
    description="Authenticate with email and password. Returns JWT access token; sets opaque refresh token in HttpOnly cookie.",
)
async def login(
    login_data: UserLoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Authenticate user, set HttpOnly refresh token cookie, and return access token."""
    settings = get_settings()
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    user, access_token, raw_refresh_token, expires_in = await AuthService.authenticate_user(
        db=db,
        login_data=login_data,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    # Set refresh token strictly as an HttpOnly, secure cookie
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        httponly=True,
        secure=settings.is_cookie_secure,
        samesite=settings.COOKIE_SAMESITE,
        path=settings.COOKIE_PATH,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )

    # Never include refresh token in JSON response
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        refresh_token=None,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate refresh token",
    description="Rotates refresh token supplied via HttpOnly cookie. Returns fresh access token and replaces refresh cookie.",
)
async def refresh_token(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Read HttpOnly refresh cookie, perform single-use rotation, and update cookie."""
    settings = get_settings()
    raw_refresh = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not raw_refresh:
        raise UnauthorizedError("Refresh token cookie is missing")

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    user, new_access_token, new_raw_refresh, expires_in = await AuthService.rotate_refresh_token(
        db=db,
        raw_refresh_token=raw_refresh,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    # Replace cookie with newly minted refresh token
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=new_raw_refresh,
        httponly=True,
        secure=settings.is_cookie_secure,
        samesite=settings.COOKIE_SAMESITE,
        path=settings.COOKIE_PATH,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )

    return TokenResponse(
        access_token=new_access_token,
        token_type="bearer",
        expires_in=expires_in,
        refresh_token=None,
    )


@router.post(
    "/logout",
    summary="Log out user",
    description="Revokes the active refresh token and clears the HttpOnly refresh cookie.",
)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Revoke refresh token and clear authentication cookie idempotently."""
    settings = get_settings()
    raw_refresh = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if raw_refresh:
        await AuthService.revoke_refresh_token(db=db, raw_refresh_token=raw_refresh)

    # Always clear the cookie regardless of whether token was found
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=settings.COOKIE_PATH,
        secure=settings.is_cookie_secure,
        samesite=settings.COOKIE_SAMESITE,
    )
    return {"message": "Successfully logged out"}


@router.get(
    "/me",
    response_model=UserAuthResponse,
    summary="Get current user profile",
    description="Returns the authenticated user's profile details.",
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserAuthResponse:
    """Return authenticated user profile validated against the database."""
    return UserAuthResponse.model_validate(current_user)
