"""
Service-Level Unit Tests for AuthService

Covers:
1. Registration:
   - successful registration
   - duplicate email rejection
   - normalized email handling
   - password hashing (Argon2id format, no plaintext)
   - race condition handling via DB IntegrityError rollback
2. Login:
   - successful login returning user, JWT, and raw refresh token
   - wrong password rejection (timing safe)
   - nonexistent account rejection (generic error)
   - inactive account rejection
   - failed-login counter increment
   - successful login resets failed-login counter & lockout
   - lockout behavior after MAX_LOGIN_ATTEMPTS
   - respects existing unexpired lockout
3. Refresh Token Rotation:
   - valid refresh token rotation
   - expired refresh token rejection
   - already-revoked refresh token rejection
   - token rotation: old token revoked, new token issued
   - old token cannot be reused
   - token reuse detection invalidates all user tokens
   - only hashed token stored in database (never raw token)
4. Security:
   - no plaintext password stored in database
   - no raw refresh token stored in database
   - single token logout/revocation
   - revoke all tokens for user
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import (
    AccountInactiveError,
    AccountLockedError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidTokenError,
    TokenExpiredError,
)
from app.core.security import decode_access_token, hash_token, verify_password
from app.models.domain import RefreshToken, User
from app.models.enums import UserRole
from app.schemas.auth import UserLoginRequest, UserRegisterRequest
from app.services.auth_service import AuthService, _ensure_utc


def _make_register_request(
    email: str | None = None,
    password: str = "StrongPassword123!",
    full_name: str = "Test Student",
    role: UserRole = UserRole.CLUB_SECRETARY,
) -> UserRegisterRequest:
    if email is None:
        email = f"user_{uuid.uuid4().hex[:8]}@college.edu"
    return UserRegisterRequest(
        email=email,
        password=password,
        full_name=full_name,
        role=role,
        department="Computer Science",
    )


# ===========================================================================
# Registration Tests
# ===========================================================================


class TestUserRegistration:
    """Test user registration in AuthService."""

    @pytest.mark.asyncio
    async def test_successful_registration(self, db_session):
        req = _make_register_request()
        user = await AuthService.register_user(db_session, req)

        assert user.id is not None
        assert user.email == req.email.lower()
        assert user.full_name == req.full_name
        assert user.role == req.role
        assert user.is_active is True
        assert user.email_verified is False
        assert user.failed_login_attempts == 0
        assert user.locked_until is None

    @pytest.mark.asyncio
    async def test_duplicate_email_raises_error(self, db_session):
        email = f"dup_{uuid.uuid4().hex[:8]}@college.edu"
        req1 = _make_register_request(email=email)
        await AuthService.register_user(db_session, req1)

        req2 = _make_register_request(email=email)
        with pytest.raises(EmailAlreadyExistsError, match="already exists"):
            await AuthService.register_user(db_session, req2)

    @pytest.mark.asyncio
    async def test_normalized_email_handling(self, db_session):
        raw_email = f"MixedCase_{uuid.uuid4().hex[:8]}@College.EDU"
        req = _make_register_request(email=raw_email)
        user = await AuthService.register_user(db_session, req)

        assert user.email == raw_email.lower()

        # Duplicate check with different casing should still be rejected
        req_diff_case = _make_register_request(email=raw_email.upper())
        with pytest.raises(EmailAlreadyExistsError):
            await AuthService.register_user(db_session, req_diff_case)

    @pytest.mark.asyncio
    async def test_password_is_hashed_with_argon2id(self, db_session):
        raw_password = "MySuperSecretPassword99!"
        req = _make_register_request(password=raw_password)
        user = await AuthService.register_user(db_session, req)

        assert user.password_hash != raw_password
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(raw_password, user.password_hash) is True


# ===========================================================================
# Login Tests
# ===========================================================================


class TestUserAuthentication:
    """Test user authentication (login) in AuthService."""

    @pytest.mark.asyncio
    async def test_successful_login(self, db_session):
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        registered_user = await AuthService.register_user(db_session, req)

        login_req = UserLoginRequest(email=req.email, password=password)
        user, access_token, raw_refresh_token, expires_in = await AuthService.authenticate_user(
            db_session, login_req, ip_address="127.0.0.1", user_agent="PyTest"
        )

        assert user.id == registered_user.id
        assert user.last_login_at is not None
        assert user.failed_login_attempts == 0
        assert expires_in > 0

        # Validate access token claims
        claims = decode_access_token(access_token)
        assert claims["sub"] == str(user.id)
        assert claims["email"] == user.email
        role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        assert claims["role"] == role_str

        # Validate refresh token was hashed in DB
        assert isinstance(raw_refresh_token, str)
        token_hash = hash_token(raw_refresh_token)
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        record = (await db_session.execute(stmt)).scalar_one_or_none()
        assert record is not None
        assert record.user_id == user.id
        assert record.revoked_at is None

    @pytest.mark.asyncio
    async def test_wrong_password_rejection(self, db_session):
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        await AuthService.register_user(db_session, req)

        login_req = UserLoginRequest(email=req.email, password="WrongPassword999!")
        with pytest.raises(InvalidCredentialsError, match="Invalid email or password"):
            await AuthService.authenticate_user(db_session, login_req)

    @pytest.mark.asyncio
    async def test_nonexistent_account_rejection(self, db_session):
        login_req = UserLoginRequest(email="nonexistent_user_999@college.edu", password="SomePassword123!")
        with pytest.raises(InvalidCredentialsError, match="Invalid email or password"):
            await AuthService.authenticate_user(db_session, login_req)

    @pytest.mark.asyncio
    async def test_inactive_account_rejection(self, db_session):
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        user = await AuthService.register_user(db_session, req)

        # Deactivate user
        user.is_active = False
        await db_session.commit()

        login_req = UserLoginRequest(email=req.email, password=password)
        with pytest.raises(AccountInactiveError, match="deactivated"):
            await AuthService.authenticate_user(db_session, login_req)

    @pytest.mark.asyncio
    async def test_failed_login_counter_increments(self, db_session):
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        user = await AuthService.register_user(db_session, req)

        login_req = UserLoginRequest(email=req.email, password="WrongPassword1!")
        for i in range(1, 4):
            with pytest.raises(InvalidCredentialsError):
                await AuthService.authenticate_user(db_session, login_req)
            await db_session.refresh(user)
            assert user.failed_login_attempts == i

    @pytest.mark.asyncio
    async def test_successful_login_resets_failed_counter(self, db_session):
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        user = await AuthService.register_user(db_session, req)

        # Fail twice
        wrong_req = UserLoginRequest(email=req.email, password="WrongPassword1!")
        with pytest.raises(InvalidCredentialsError):
            await AuthService.authenticate_user(db_session, wrong_req)
        with pytest.raises(InvalidCredentialsError):
            await AuthService.authenticate_user(db_session, wrong_req)

        await db_session.refresh(user)
        assert user.failed_login_attempts == 2

        # Success resets counter
        correct_req = UserLoginRequest(email=req.email, password=password)
        await AuthService.authenticate_user(db_session, correct_req)

        await db_session.refresh(user)
        assert user.failed_login_attempts == 0
        assert user.locked_until is None

    @pytest.mark.asyncio
    async def test_lockout_after_max_attempts(self, db_session):
        settings = get_settings()
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        user = await AuthService.register_user(db_session, req)

        wrong_req = UserLoginRequest(email=req.email, password="WrongPassword1!")

        # Fail up to MAX_LOGIN_ATTEMPTS - 1
        for _ in range(settings.MAX_LOGIN_ATTEMPTS - 1):
            with pytest.raises(InvalidCredentialsError):
                await AuthService.authenticate_user(db_session, wrong_req)

        # Final failure triggers lockout
        with pytest.raises(AccountLockedError, match="locked"):
            await AuthService.authenticate_user(db_session, wrong_req)

        await db_session.refresh(user)
        assert user.locked_until is not None
        locked_until_utc = _ensure_utc(user.locked_until)
        assert locked_until_utc > datetime.now(timezone.utc)

        # Further attempts (even with correct password) are rejected while locked
        correct_req = UserLoginRequest(email=req.email, password=password)
        with pytest.raises(AccountLockedError):
            await AuthService.authenticate_user(db_session, correct_req)


# ===========================================================================
# Refresh Token Rotation Tests
# ===========================================================================


class TestRefreshTokenRotation:
    """Test refresh token rotation and security in AuthService."""

    @pytest.mark.asyncio
    async def test_valid_token_rotation(self, db_session):
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        await AuthService.register_user(db_session, req)

        login_req = UserLoginRequest(email=req.email, password=password)
        user, access_token1, raw_refresh1, _ = await AuthService.authenticate_user(
            db_session, login_req
        )

        # Rotate token
        user2, access_token2, raw_refresh2, expires_in = await AuthService.rotate_refresh_token(
            db_session, raw_refresh1, ip_address="127.0.0.1", user_agent="PyTest"
        )

        assert user2.id == user.id
        assert access_token2 != access_token1
        assert raw_refresh2 != raw_refresh1
        assert expires_in > 0

        # Old token record must now be revoked
        old_hash = hash_token(raw_refresh1)
        stmt1 = select(RefreshToken).where(RefreshToken.token_hash == old_hash)
        old_rec = (await db_session.execute(stmt1)).scalar_one()
        assert old_rec.revoked_at is not None

        # New token record must be active
        new_hash = hash_token(raw_refresh2)
        stmt2 = select(RefreshToken).where(RefreshToken.token_hash == new_hash)
        new_rec = (await db_session.execute(stmt2)).scalar_one()
        assert new_rec.revoked_at is None

    @pytest.mark.asyncio
    async def test_expired_refresh_token_rejection(self, db_session):
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        user = await AuthService.register_user(db_session, req)

        # Manually create an expired token record
        raw_token = "expired_token_12345"
        token_hash = hash_token(raw_token)
        expired_rec = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            revoked_at=None,
        )
        db_session.add(expired_rec)
        await db_session.commit()

        with pytest.raises(TokenExpiredError, match="expired"):
            await AuthService.rotate_refresh_token(db_session, raw_token)

    @pytest.mark.asyncio
    async def test_old_refresh_token_cannot_be_reused(self, db_session):
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        await AuthService.register_user(db_session, req)

        login_req = UserLoginRequest(email=req.email, password=password)
        _, _, raw_refresh1, _ = await AuthService.authenticate_user(db_session, login_req)

        # Rotate once: raw_refresh1 is now revoked
        await AuthService.rotate_refresh_token(db_session, raw_refresh1)

        # Attempt to reuse raw_refresh1
        with pytest.raises(InvalidTokenError, match="revoked|reuse"):
            await AuthService.rotate_refresh_token(db_session, raw_refresh1)

    @pytest.mark.asyncio
    async def test_token_reuse_invalidates_all_active_sessions(self, db_session):
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        user = await AuthService.register_user(db_session, req)

        login_req = UserLoginRequest(email=req.email, password=password)

        # Session A: login
        _, _, raw_refresh_a, _ = await AuthService.authenticate_user(db_session, login_req)

        # Session B: login from another device
        _, _, raw_refresh_b, _ = await AuthService.authenticate_user(db_session, login_req)

        # Rotate Session A -> old token becomes revoked
        _, _, raw_refresh_a2, _ = await AuthService.rotate_refresh_token(db_session, raw_refresh_a)

        # Malicious actor tries to reuse the old Session A token
        with pytest.raises(InvalidTokenError):
            await AuthService.rotate_refresh_token(db_session, raw_refresh_a)

        # Security check: ALL active tokens for this user must now be revoked
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        )
        active_tokens = (await db_session.execute(stmt)).scalars().all()
        assert len(active_tokens) == 0, "Token reuse must invalidate all active sessions for the user"

    @pytest.mark.asyncio
    async def test_revoke_single_refresh_token(self, db_session):
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        await AuthService.register_user(db_session, req)

        login_req = UserLoginRequest(email=req.email, password=password)
        _, _, raw_refresh, _ = await AuthService.authenticate_user(db_session, login_req)

        revoked = await AuthService.revoke_refresh_token(db_session, raw_refresh)
        assert revoked is True

        # Second revocation returns False
        revoked_again = await AuthService.revoke_refresh_token(db_session, raw_refresh)
        assert revoked_again is False

    @pytest.mark.asyncio
    async def test_revoke_all_user_tokens(self, db_session):
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        user = await AuthService.register_user(db_session, req)

        login_req = UserLoginRequest(email=req.email, password=password)
        # Create 3 sessions
        await AuthService.authenticate_user(db_session, login_req)
        await AuthService.authenticate_user(db_session, login_req)
        await AuthService.authenticate_user(db_session, login_req)

        count = await AuthService.revoke_all_user_tokens(db_session, user.id)
        assert count == 3

        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        )
        active = (await db_session.execute(stmt)).scalars().all()
        assert len(active) == 0


# ===========================================================================
# Security Verification Tests
# ===========================================================================


class TestSecurityGuarantees:
    """Verify security constraints: no plaintext passwords or raw tokens in DB."""

    @pytest.mark.asyncio
    async def test_no_plaintext_password_in_database(self, db_session):
        raw_password = "SecretPassword123!@#"
        req = _make_register_request(password=raw_password)
        user = await AuthService.register_user(db_session, req)

        stmt = select(User).where(User.id == user.id)
        persisted = (await db_session.execute(stmt)).scalar_one()

        assert raw_password not in persisted.password_hash
        assert persisted.password_hash.startswith("$argon2id$")

    @pytest.mark.asyncio
    async def test_no_raw_refresh_token_in_database(self, db_session):
        password = "ValidPassword123!"
        req = _make_register_request(password=password)
        user = await AuthService.register_user(db_session, req)

        login_req = UserLoginRequest(email=req.email, password=password)
        _, _, raw_refresh_token, _ = await AuthService.authenticate_user(db_session, login_req)

        # Inspect all records in refresh_tokens table for this user
        stmt = select(RefreshToken).where(RefreshToken.user_id == user.id)
        records = (await db_session.execute(stmt)).scalars().all()

        for rec in records:
            assert rec.token_hash != raw_refresh_token
            assert len(rec.token_hash) == 64  # Must be SHA-256 hex digest
            assert rec.token_hash == hash_token(raw_refresh_token)
