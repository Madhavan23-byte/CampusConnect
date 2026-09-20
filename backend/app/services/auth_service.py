"""
CampusConnect Backend — Authentication Service

Encapsulates all authentication and session domain logic:
1. User registration:
   - Validates normalized email
   - Prevents duplicate registrations (with DB-level race condition handling)
   - Argon2id password hashing
   - Safe transaction handling
2. User authentication (Login):
   - Case-insensitive email lookup
   - Timing-attack safe credential verification
   - Account status checking (is_active)
   - Brute-force protection: failed-login counter & temporary lockout
   - Resets failed attempts and records last_login_at on success
   - Transparent password rehashing on upgrade
   - JWT access token generation
   - Opaque refresh token generation with SHA-256 hash stored in database
3. Refresh token rotation & session management:
   - Validates refresh token via SHA-256 hash lookup
   - Checks expiration and revocation status
   - Enforces single-use token rotation: revokes old token, issues new token
   - Token reuse detection: invalidates all active sessions if a revoked token is used
4. Logout & session revocation:
   - Revokes specific refresh token
   - Revokes all active refresh tokens for a user
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    AccountInactiveError,
    AccountLockedError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidTokenError,
    TokenExpiredError,
)
from app.core.security import (
    create_access_token,
    generate_secure_random_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from app.models.domain import RefreshToken, User
from app.schemas.auth import UserLoginRequest, UserRegisterRequest

# Dummy Argon2id hash used to equalize execution timing when a user does not exist
DUMMY_ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$F53IMsfK6I6ChyDeFoCO8A$yoKhongjpic2FC/RvgqQNvdSJA+Nk5AAzNrMBhybIIQ"


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure datetime has UTC timezone (handles SQLite offset-naive timestamps)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class AuthService:
    """Service handling user registration, authentication, and token rotation."""

    @staticmethod
    async def register_user(
        db: AsyncSession,
        register_data: UserRegisterRequest,
    ) -> User:
        """
        Register a new user account.

        - Normalizes email to lowercase.
        - Checks for existing active user with the same email.
        - Hashes password with Argon2id.
        - Creates User in database with is_active=True and email_verified=False.
        - Safely catches concurrent duplicate registration via IntegrityError.

        Raises:
            EmailAlreadyExistsError: If email is already registered.
        """
        normalized_email = register_data.email.strip().lower()

        # Check existing user
        stmt = select(User).where(
            func.lower(User.email) == normalized_email,
            User.deleted_at.is_(None),
        )
        existing_user = (await db.execute(stmt)).scalar_one_or_none()
        if existing_user is not None:
            raise EmailAlreadyExistsError("An account with this email address already exists")

        # Hash password using Argon2id
        hashed_password = hash_password(register_data.password)

        user = User(
            email=normalized_email,
            password_hash=hashed_password,
            full_name=register_data.full_name,
            role=register_data.role,
            department=register_data.department,
            designation=register_data.designation,
            phone=register_data.phone,
            email_verified=False,
            is_active=True,
            failed_login_attempts=0,
            locked_until=None,
        )

        db.add(user)
        try:
            await db.commit()
            await db.refresh(user)
        except IntegrityError as exc:
            await db.rollback()
            raise EmailAlreadyExistsError(
                "An account with this email address already exists"
            ) from exc

        return user

    @staticmethod
    async def authenticate_user(
        db: AsyncSession,
        login_data: UserLoginRequest,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[User, str, str, int]:
        """
        Authenticate a user by email and password.

        Returns:
            tuple of (user, access_token, raw_refresh_token, expires_in_seconds)

        Raises:
            InvalidCredentialsError: If email not found or password incorrect (timing-safe).
            AccountInactiveError: If user account has been deactivated.
            AccountLockedError: If account is locked due to consecutive failed attempts.
        """
        settings = get_settings()
        now = datetime.now(UTC)
        normalized_email = login_data.email.strip().lower()

        # Find user by email
        stmt = select(User).where(
            func.lower(User.email) == normalized_email,
            User.deleted_at.is_(None),
        )
        user = (await db.execute(stmt)).scalar_one_or_none()

        # Timing attack prevention: perform dummy hash verification if user not found
        if user is None:
            verify_password("dummy_password_timing_check", DUMMY_ARGON2_HASH)
            raise InvalidCredentialsError("Invalid email or password")

        # Check account status
        if not user.is_active:
            raise AccountInactiveError("Account is deactivated. Please contact an administrator.")

        # Check lockout
        locked_until_utc = _ensure_utc(user.locked_until)
        if locked_until_utc is not None and locked_until_utc > now:
            remaining_seconds = int((locked_until_utc - now).total_seconds())
            remaining_minutes = max(1, (remaining_seconds + 59) // 60)
            raise AccountLockedError(
                f"Account is temporarily locked due to repeated failed login attempts. "
                f"Please try again in {remaining_minutes} minute(s)."
            )

        # Verify password
        if not verify_password(login_data.password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=settings.ACCOUNT_LOCKOUT_MINUTES)
                await db.commit()
                raise AccountLockedError(
                    f"Account has been locked for {settings.ACCOUNT_LOCKOUT_MINUTES} minutes "
                    f"due to {settings.MAX_LOGIN_ATTEMPTS} consecutive failed login attempts."
                )
            await db.commit()
            raise InvalidCredentialsError("Invalid email or password")

        # Successful authentication: reset failed login attempts & lockout
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now

        # Transparent password rehashing if algorithm parameters have upgraded
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(login_data.password)

        # Generate JWT access token
        role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        access_token = create_access_token(
            subject=user.id,
            role=role_str,
            email=user.email,
        )

        # Generate opaque refresh token and store only its SHA-256 hash
        raw_refresh_token = generate_secure_random_token(48)
        refresh_token_hash = hash_token(raw_refresh_token)
        refresh_expires = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        refresh_record = RefreshToken(
            user_id=user.id,
            token_hash=refresh_token_hash,
            expires_at=refresh_expires,
            revoked_at=None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(refresh_record)
        await db.commit()
        await db.refresh(user)

        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        return user, access_token, raw_refresh_token, expires_in

    @staticmethod
    async def rotate_refresh_token(
        db: AsyncSession,
        raw_refresh_token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[User, str, str, int]:
        """
        Validate and rotate a refresh token.

        - Look up record by SHA-256 hash.
        - Check revocation and expiration.
        - Detect token reuse: if an already-revoked token is used, invalidate ALL
          active refresh tokens for that user to prevent compromise.
        - Revoke old token and issue a fresh pair (access token + new refresh token).

        Returns:
            tuple of (user, new_access_token, new_raw_refresh_token, expires_in_seconds)

        Raises:
            InvalidTokenError: If token is unknown, malformed, or already revoked.
            TokenExpiredError: If token has expired.
            AccountInactiveError: If user account is deactivated.
        """
        if not raw_refresh_token or not isinstance(raw_refresh_token, str):
            raise InvalidTokenError("Refresh token must be a non-empty string")

        token_hash = hash_token(raw_refresh_token)
        now = datetime.now(UTC)
        settings = get_settings()

        # Find refresh token record
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        record = (await db.execute(stmt)).scalar_one_or_none()

        if record is None:
            raise InvalidTokenError("Invalid or unknown refresh token")

        # REUSE DETECTION: If token was already revoked, someone may have stolen it
        if record.revoked_at is not None:
            # Invalidate all active tokens for this user as a defense measure
            await db.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.user_id == record.user_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await db.commit()
            raise InvalidTokenError(
                "Refresh token has already been revoked. Potential token reuse detected. "
                "All sessions have been invalidated for security."
            )

        # Check expiration
        expires_at_utc = _ensure_utc(record.expires_at)
        if expires_at_utc <= now:
            record.revoked_at = now
            await db.commit()
            raise TokenExpiredError("Refresh token has expired. Please log in again.")

        # Find user
        user = await db.get(User, record.user_id)
        if user is None or not user.is_active or user.deleted_at is not None:
            record.revoked_at = now
            await db.commit()
            raise AccountInactiveError("User account is inactive or not found")

        # Perform rotation:
        # 1. Revoke the old token
        record.revoked_at = now

        # 2. Issue new access token
        role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        new_access_token = create_access_token(
            subject=user.id,
            role=role_str,
            email=user.email,
        )

        # 3. Issue new refresh token
        new_raw_refresh = generate_secure_random_token(48)
        new_token_hash = hash_token(new_raw_refresh)
        new_expires = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        new_record = RefreshToken(
            user_id=user.id,
            token_hash=new_token_hash,
            expires_at=new_expires,
            revoked_at=None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(new_record)
        await db.commit()

        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        return user, new_access_token, new_raw_refresh, expires_in

    @staticmethod
    async def revoke_refresh_token(
        db: AsyncSession,
        raw_refresh_token: str,
    ) -> bool:
        """
        Revoke a single refresh token (e.g. on logout).
        Returns True if revoked, False if not found or already revoked.
        """
        if not raw_refresh_token:
            return False

        token_hash = hash_token(raw_refresh_token)
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        record = (await db.execute(stmt)).scalar_one_or_none()

        if record is None or record.revoked_at is not None:
            return False

        record.revoked_at = datetime.now(UTC)
        await db.commit()
        return True

    @staticmethod
    async def revoke_all_user_tokens(
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> int:
        """
        Revoke all active refresh tokens for a user (e.g. password reset or global logout).
        Returns the number of revoked tokens.
        """
        now = datetime.now(UTC)
        result = await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await db.commit()
        return result.rowcount
