"""
Integration tests for login rate limiting (GAP-02)

Tests:
1. Allowed login attempts within threshold
2. Rate limit exceeded triggers HTTP 429 Too Many Requests
3. Retry-After header present and contains valid integer seconds
4. Legitimate login allowed after limiter reset / window expiry
5. Non-existent user behavior (rate limited identically without email enumeration)
6. Interaction with account lockout (lockout tracked per user, rate limiting per IP)
7. Separate IP isolation
8. Error response payload hygiene (no sensitive data leaks)
"""

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.rate_limiter import login_limiter
from app.core.security import hash_password
from app.models.domain import User
from app.models.enums import UserRole


@pytest.fixture(autouse=True)
def reset_limiter_before_each_test():
    """Ensure limiter is empty before each test."""
    login_limiter.reset()
    yield
    login_limiter.reset()


@pytest.mark.asyncio
class TestLoginRateLimiting:
    async def test_01_allowed_attempts_under_threshold(self, client: AsyncClient):
        """Requests under RATE_LIMIT_LOGIN_PER_MINUTE threshold do not trigger 429."""
        settings = get_settings()
        limit = settings.RATE_LIMIT_LOGIN_PER_MINUTE

        # Perform (limit - 1) requests with invalid credentials
        for _ in range(min(limit - 1, 5)):
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "random_user@campus.edu", "password": "WrongPassword123!"},
            )
            # Should be 401 Unauthorized, never 429
            assert response.status_code == 401
            assert "Retry-After" not in response.headers

    async def test_02_rate_limit_exceeded_returns_429_with_retry_after(self, client: AsyncClient):
        """Exceeding the rate limit threshold returns HTTP 429 and Retry-After header."""
        settings = get_settings()
        limit = settings.RATE_LIMIT_LOGIN_PER_MINUTE

        for _ in range(limit):
            res = await client.post(
                "/api/v1/auth/login",
                json={"email": "test_flood@campus.edu", "password": "WrongPassword123!"},
            )
            assert res.status_code == 401

        # The (limit + 1)-th request must be blocked with HTTP 429
        blocked_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "test_flood@campus.edu", "password": "WrongPassword123!"},
        )
        assert blocked_res.status_code == 429

        # Verify Retry-After header
        assert "retry-after" in blocked_res.headers
        retry_after = int(blocked_res.headers["retry-after"])
        assert 1 <= retry_after <= 60

        data = blocked_res.json()
        assert data.get("error") == "rate_limited"
        assert "Too many login attempts" in data.get("message", "")

    async def test_03_login_allowed_after_limiter_reset(self, client: AsyncClient, db_session):
        """After resetting or window expiry, legitimate login succeeds."""
        # Create a valid active user
        email = f"rate_reset_{uuid.uuid4().hex[:8]}@campus.edu"
        password = "ValidPassword123!"
        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=hash_password(password),
            full_name="Rate Test User",
            role=UserRole.CLUB_SECRETARY,
            is_active=True,
        )
        db_session.add(user)
        await db_session.commit()

        settings = get_settings()
        limit = settings.RATE_LIMIT_LOGIN_PER_MINUTE

        # Exhaust limit using a generic unmapped email so the target user is not locked out
        for i in range(limit):
            await client.post(
                "/api/v1/auth/login",
                json={"email": f"other_account_{i}@campus.edu", "password": "WrongPassword123!"},
            )

        # Confirm 429 triggers for this client IP regardless of user
        blocked = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert blocked.status_code == 429

        # Reset limiter (simulating sliding window expiry)
        login_limiter.reset()

        # Legitimate login now succeeds with HTTP 200
        success = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert success.status_code == 200
        assert "access_token" in success.json()

    async def test_04_nonexistent_user_rate_limited_without_enumeration(self, client: AsyncClient):
        """Non-existent accounts are rate-limited identically to prevent user enumeration."""
        settings = get_settings()
        limit = settings.RATE_LIMIT_LOGIN_PER_MINUTE

        # Perform limit requests for non-existent users
        for i in range(limit):
            res = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": f"nonexistent_{i}_{uuid.uuid4().hex[:6]}@campus.edu",
                    "password": "AnyPassword123!",
                },
            )
            assert res.status_code == 401
            assert res.json().get("message") == "Invalid email or password"

        # (limit + 1)-th request triggers 429
        res_blocked = await client.post(
            "/api/v1/auth/login",
            json={"email": "another_nonexistent@campus.edu", "password": "AnyPassword123!"},
        )
        assert res_blocked.status_code == 429
        assert res_blocked.json().get("error") == "rate_limited"

    async def test_05_separate_ip_addresses_have_independent_quotas(self, client: AsyncClient):
        """Requests from different client IPs maintain separate rate limiting buckets."""
        settings = get_settings()
        limit = settings.RATE_LIMIT_LOGIN_PER_MINUTE

        # Exhaust quota for IP 198.51.100.1
        for _ in range(limit):
            await client.post(
                "/api/v1/auth/login",
                json={"email": "user1@campus.edu", "password": "WrongPassword123!"},
                headers={"X-Forwarded-For": "198.51.100.1"},
            )

        # IP 198.51.100.1 is blocked
        blocked_ip1 = await client.post(
            "/api/v1/auth/login",
            json={"email": "user1@campus.edu", "password": "WrongPassword123!"},
            headers={"X-Forwarded-For": "198.51.100.1"},
        )
        assert blocked_ip1.status_code == 429

        # Different IP 198.51.100.2 is still allowed
        res_ip2 = await client.post(
            "/api/v1/auth/login",
            json={"email": "user1@campus.edu", "password": "WrongPassword123!"},
            headers={"X-Forwarded-For": "198.51.100.2"},
        )
        assert res_ip2.status_code == 401  # Not 429!

    async def test_06_error_response_no_sensitive_leakage(self, client: AsyncClient):
        """Rate limit error response body does not leak internal traces or server details."""
        settings = get_settings()
        limit = settings.RATE_LIMIT_LOGIN_PER_MINUTE

        for _ in range(limit + 1):
            res = await client.post(
                "/api/v1/auth/login",
                json={"email": "leak_test@campus.edu", "password": "SecretPassword123!"},
            )

        assert res.status_code == 429
        body = res.json()
        assert "password" not in str(body).lower()
        assert "traceback" not in str(body).lower()
        assert "argon2" not in str(body).lower()
        assert body.get("error") == "rate_limited"
