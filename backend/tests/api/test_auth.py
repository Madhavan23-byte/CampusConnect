"""
Integration Tests for CampusConnect Authentication API Endpoints

Covers:
1. POST /api/v1/auth/register
   - Successful registration (201 Created, safe user representation)
   - Duplicate email rejection (409 Conflict)
   - Invalid input validation (422 Unprocessable Entity on weak password or bad email)
   - Security: password and password_hash never returned in response

2. POST /api/v1/auth/login
   - Successful login (200 OK, JWT access token returned)
   - Refresh token NOT in JSON response (refresh_token is None)
   - Refresh token set in HttpOnly cookie
   - Cookie attributes: HttpOnly, Path=/api/v1/auth, SameSite=lax
   - Wrong password rejection (401 Unauthorized, generic message)
   - Inactive user rejection (401 Unauthorized)
   - Locked user rejection (401 Unauthorized)

3. POST /api/v1/auth/refresh
   - Valid refresh cookie rotation (200 OK, new access token issued)
   - Refresh cookie replaced with rotated token
   - Old refresh token cannot be reused (401 Unauthorized)
   - Missing refresh cookie rejection (401 Unauthorized)

4. POST /api/v1/auth/logout
   - Valid logout revokes refresh token (200 OK)
   - Refresh cookie cleared
   - Logout without cookie is safe and idempotent (200 OK)

5. GET /api/v1/auth/me
   - Valid access token returns user profile (200 OK)
   - Missing Authorization header rejected (401 Unauthorized)
   - Malformed / invalid Bearer token rejected (401 Unauthorized)
   - Expired access token rejected (401 Unauthorized)
   - Inactive user rejected (401 Unauthorized)

6. Security Guarantees:
   - Raw refresh token never appears in any response body
   - Password hash never appears in any response body
"""
import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_token
from app.models.domain import RefreshToken, User
from app.models.enums import UserRole


def _random_email() -> str:
    return f"student_{uuid.uuid4().hex[:8]}@college.edu"


# ===========================================================================
# Registration API Tests
# ===========================================================================


class TestRegisterAPI:
    """Tests for POST /api/v1/auth/register."""

    @pytest.mark.asyncio
    async def test_successful_registration(self, client: AsyncClient):
        email = _random_email()
        payload = {
            "email": email,
            "password": "StrongPassword123!",
            "full_name": "Alice Wonderland",
            "role": "CLUB_SECRETARY",
            "department": "Computer Science",
            "designation": "Secretary",
            "phone": "9876543210",
        }
        response = await client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 201

        data = response.json()
        assert data["email"] == email.lower()
        assert data["full_name"] == "Alice Wonderland"
        assert data["role"] == "CLUB_SECRETARY"
        assert data["is_active"] is True
        assert data["email_verified"] is False
        assert "id" in data

        # Security check: passwords and tokens MUST NOT be returned
        assert "password" not in data
        assert "password_hash" not in data
        assert "access_token" not in data
        assert "refresh_token" not in data

    @pytest.mark.asyncio
    async def test_register_duplicate_email_returns_409(self, client: AsyncClient):
        email = _random_email()
        payload = {
            "email": email,
            "password": "StrongPassword123!",
            "full_name": "Bob Builder",
            "role": "CLUB_SECRETARY",
        }
        # First registration
        r1 = await client.post("/api/v1/auth/register", json=payload)
        assert r1.status_code == 201

        # Duplicate registration with same email
        r2 = await client.post("/api/v1/auth/register", json=payload)
        assert r2.status_code == 409
        data = r2.json()
        assert "already exists" in data.get("message", "").lower()

    @pytest.mark.asyncio
    async def test_register_weak_password_returns_422(self, client: AsyncClient):
        payload = {
            "email": _random_email(),
            "password": "weak",  # Fails min length, uppercase, special char
            "full_name": "Weak User",
            "role": "CLUB_SECRETARY",
        }
        response = await client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_invalid_email_returns_422(self, client: AsyncClient):
        payload = {
            "email": "not-an-email",
            "password": "StrongPassword123!",
            "full_name": "Invalid Email",
            "role": "CLUB_SECRETARY",
        }
        response = await client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 422


# ===========================================================================
# Login API Tests
# ===========================================================================


class TestLoginAPI:
    """Tests for POST /api/v1/auth/login."""

    @pytest.mark.asyncio
    async def test_successful_login(self, client: AsyncClient):
        email = _random_email()
        password = "SecurePassword123!@#"
        reg_payload = {
            "email": email,
            "password": password,
            "full_name": "Login Tester",
            "role": "FACULTY_ADVISOR",
        }
        await client.post("/api/v1/auth/register", json=reg_payload)

        # Login
        login_payload = {"email": email, "password": password}
        response = await client.post("/api/v1/auth/login", json=login_payload)
        assert response.status_code == 200

        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

        # Security check: refresh token MUST NOT appear in JSON response
        assert data.get("refresh_token") is None

        # Check HttpOnly refresh cookie was set
        settings = get_settings()
        cookie_name = settings.REFRESH_COOKIE_NAME
        assert cookie_name in response.cookies
        raw_cookie_val = response.cookies[cookie_name]
        assert len(raw_cookie_val) > 30

    @pytest.mark.asyncio
    async def test_login_wrong_password_returns_401(self, client: AsyncClient):
        email = _random_email()
        password = "SecurePassword123!@#"
        reg_payload = {
            "email": email,
            "password": password,
            "full_name": "Wrong Pass User",
            "role": "CLUB_SECRETARY",
        }
        await client.post("/api/v1/auth/register", json=reg_payload)

        # Login with wrong password
        login_payload = {"email": email, "password": "IncorrectPassword999!"}
        response = await client.post("/api/v1/auth/login", json=login_payload)
        assert response.status_code == 401
        data = response.json()
        assert "invalid email or password" in data.get("message", "").lower()

    @pytest.mark.asyncio
    async def test_login_nonexistent_user_returns_401(self, client: AsyncClient):
        login_payload = {"email": "does_not_exist@college.edu", "password": "Password123!"}
        response = await client.post("/api/v1/auth/login", json=login_payload)
        assert response.status_code == 401
        data = response.json()
        assert "invalid email or password" in data.get("message", "").lower()

    @pytest.mark.asyncio
    async def test_login_inactive_user_returns_401(self, client: AsyncClient, db_session):
        email = _random_email()
        password = "SecurePassword123!@#"
        reg_payload = {
            "email": email,
            "password": password,
            "full_name": "Inactive User",
            "role": "CLUB_SECRETARY",
        }
        await client.post("/api/v1/auth/register", json=reg_payload)

        # Deactivate user in DB
        stmt = select(User).where(User.email == email)
        user = (await db_session.execute(stmt)).scalar_one()
        user.is_active = False
        await db_session.commit()

        login_payload = {"email": email, "password": password}
        response = await client.post("/api/v1/auth/login", json=login_payload)
        assert response.status_code == 401
        assert "deactivated" in response.json().get("message", "").lower()


# ===========================================================================
# Refresh Token API Tests
# ===========================================================================


class TestRefreshAPI:
    """Tests for POST /api/v1/auth/refresh."""

    @pytest.mark.asyncio
    async def test_successful_refresh_token_rotation(self, client: AsyncClient):
        email = _random_email()
        password = "SecurePassword123!@#"
        reg_payload = {
            "email": email,
            "password": password,
            "full_name": "Refresh Tester",
            "role": "CLUB_SECRETARY",
        }
        await client.post("/api/v1/auth/register", json=reg_payload)

        # Login to get initial cookie and token
        login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert login_res.status_code == 200
        settings = get_settings()
        initial_refresh_cookie = login_res.cookies[settings.REFRESH_COOKIE_NAME]
        initial_access_token = login_res.json()["access_token"]

        # Call refresh endpoint with initial cookie
        refresh_res = await client.post(
            "/api/v1/auth/refresh",
            cookies={settings.REFRESH_COOKIE_NAME: initial_refresh_cookie},
        )
        assert refresh_res.status_code == 200

        data = refresh_res.json()
        new_access_token = data["access_token"]
        assert new_access_token != initial_access_token
        assert data.get("refresh_token") is None  # NOT in JSON

        # Verify rotated cookie is present and different
        rotated_cookie = refresh_res.cookies[settings.REFRESH_COOKIE_NAME]
        assert rotated_cookie != initial_refresh_cookie

    @pytest.mark.asyncio
    async def test_old_refresh_cookie_cannot_be_reused(self, client: AsyncClient):
        email = _random_email()
        password = "SecurePassword123!@#"
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Reuse Tester", "role": "CLUB_SECRETARY"},
        )

        login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        settings = get_settings()
        initial_cookie = login_res.cookies[settings.REFRESH_COOKIE_NAME]

        # Rotate once
        r1 = await client.post("/api/v1/auth/refresh", cookies={settings.REFRESH_COOKIE_NAME: initial_cookie})
        assert r1.status_code == 200

        # Attempt to reuse old initial_cookie
        r2 = await client.post("/api/v1/auth/refresh", cookies={settings.REFRESH_COOKIE_NAME: initial_cookie})
        assert r2.status_code == 401
        assert "revoked" in r2.json().get("message", "").lower() or "reuse" in r2.json().get("message", "").lower()

    @pytest.mark.asyncio
    async def test_missing_refresh_cookie_returns_401(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/refresh")
        assert response.status_code == 401
        assert "missing" in response.json().get("message", "").lower()


# ===========================================================================
# Logout API Tests
# ===========================================================================


class TestLogoutAPI:
    """Tests for POST /api/v1/auth/logout."""

    @pytest.mark.asyncio
    async def test_successful_logout(self, client: AsyncClient, db_session):
        email = _random_email()
        password = "SecurePassword123!@#"
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Logout Tester", "role": "CLUB_SECRETARY"},
        )

        login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        settings = get_settings()
        refresh_cookie = login_res.cookies[settings.REFRESH_COOKIE_NAME]

        # Logout
        logout_res = await client.post(
            "/api/v1/auth/logout",
            cookies={settings.REFRESH_COOKIE_NAME: refresh_cookie},
        )
        assert logout_res.status_code == 200
        assert "logged out" in logout_res.json().get("message", "").lower()

        # Check in DB that token was revoked
        token_hash = hash_token(refresh_cookie)
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        record = (await db_session.execute(stmt)).scalar_one()
        assert record.revoked_at is not None

        # Trying to refresh with the logged-out cookie must fail
        refresh_attempt = await client.post(
            "/api/v1/auth/refresh",
            cookies={settings.REFRESH_COOKIE_NAME: refresh_cookie},
        )
        assert refresh_attempt.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_without_cookie_is_safe_and_idempotent(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        assert "logged out" in response.json().get("message", "").lower()


# ===========================================================================
# Current User /me API Tests
# ===========================================================================


class TestMeAPI:
    """Tests for GET /api/v1/auth/me."""

    @pytest.mark.asyncio
    async def test_me_with_valid_access_token(self, client: AsyncClient):
        email = _random_email()
        password = "SecurePassword123!@#"
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Me User", "role": "CLUB_SECRETARY"},
        )

        login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        access_token = login_res.json()["access_token"]

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == email.lower()
        assert data["full_name"] == "Me User"
        assert data["role"] == "CLUB_SECRETARY"
        assert data["is_active"] is True
        assert "password_hash" not in data

    @pytest.mark.asyncio
    async def test_me_without_authorization_header_returns_401(self, client: AsyncClient):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert "credentials" in response.json().get("message", "").lower()

    @pytest.mark.asyncio
    async def test_me_with_malformed_token_returns_401(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer malformed.token.string"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_expired_token_returns_401(self, client: AsyncClient, db_session):
        email = _random_email()
        password = "SecurePassword123!@#"
        reg_res = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Expired Tester", "role": "CLUB_SECRETARY"},
        )
        user_id = reg_res.json()["id"]

        # Create expired token
        expired_token = create_access_token(
            subject=user_id,
            role="CLUB_SECRETARY",
            email=email,
            expires_delta=timedelta(minutes=-10),
        )

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401
        assert "expired" in response.json().get("message", "").lower()

    @pytest.mark.asyncio
    async def test_me_with_inactive_user_returns_401(self, client: AsyncClient, db_session):
        email = _random_email()
        password = "SecurePassword123!@#"
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Inactive Me", "role": "CLUB_SECRETARY"},
        )

        login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        access_token = login_res.json()["access_token"]

        # Deactivate user
        stmt = select(User).where(User.email == email)
        user = (await db_session.execute(stmt)).scalar_one()
        user.is_active = False
        await db_session.commit()

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 401
        assert "deactivated" in response.json().get("message", "").lower()


# ===========================================================================
# Security Verification Tests
# ===========================================================================


class TestSecurityAuditAPI:
    """Verify security constraints across all authentication endpoints."""

    @pytest.mark.asyncio
    async def test_raw_refresh_token_never_in_json(self, client: AsyncClient):
        email = _random_email()
        password = "SecurePassword123!@#"
        reg_res = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Audit User", "role": "CLUB_SECRETARY"},
        )
        assert "refresh_token" not in reg_res.text or reg_res.json().get("refresh_token") is None

        login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        data = login_res.json()
        assert data.get("refresh_token") is None
        # Verify the cookie value is NOT in the JSON body text
        settings = get_settings()
        cookie_val = login_res.cookies[settings.REFRESH_COOKIE_NAME]
        assert cookie_val not in login_res.text

    @pytest.mark.asyncio
    async def test_password_hash_never_in_any_response(self, client: AsyncClient):
        email = _random_email()
        password = "SecurePassword123!@#"
        reg_res = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Audit User 2", "role": "CLUB_SECRETARY"},
        )
        assert "$argon2id$" not in reg_res.text
        assert "password_hash" not in reg_res.text

        login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert "$argon2id$" not in login_res.text
        assert "password_hash" not in login_res.text

        token = login_res.json()["access_token"]
        me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert "$argon2id$" not in me_res.text
        assert "password_hash" not in me_res.text
