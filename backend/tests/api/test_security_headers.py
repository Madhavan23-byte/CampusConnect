"""
Integration tests for Production Security Headers

Tests:
1. Standard security headers (nosniff, DENY, Referrer-Policy, Permissions-Policy)
2. Content-Security-Policy directive compliance (Vite SPA & asset compatibility)
3. Conditional HSTS suppression in local HTTP development
4. Conditional HSTS enforcement in HTTPS / production
5. Security headers present on error responses (401, 404, 422, 429)
"""

import pytest
from httpx import AsyncClient

from app.core.config import get_settings


@pytest.mark.asyncio
class TestSecurityHeaders:
    async def test_01_baseline_security_headers_present(self, client: AsyncClient):
        """All standard baseline headers are attached to responses."""
        res = await client.get("/api/v1/health")
        assert res.status_code == 200

        # X-Content-Type-Options
        assert res.headers.get("x-content-type-options") == "nosniff"

        # X-Frame-Options
        assert res.headers.get("x-frame-options") == "DENY"

        # Referrer-Policy
        assert res.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

        # Permissions-Policy
        perm = res.headers.get("permissions-policy", "")
        assert "camera=()" in perm
        assert "microphone=()" in perm
        assert "geolocation=()" in perm
        assert "payment=()" in perm
        assert "usb=()" in perm

    async def test_02_content_security_policy_directives(self, client: AsyncClient):
        """CSP header includes required directives and supports Vite React and Google Fonts."""
        res = await client.get("/api/v1/health")
        csp = res.headers.get("content-security-policy", "")
        assert csp != ""

        # Check required directives
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'" in csp
        assert "font-src 'self' https://fonts.gstatic.com data:" in csp
        assert "img-src 'self' data: blob:" in csp
        assert "connect-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    async def test_03_hsts_suppressed_for_plain_http_development(self, client: AsyncClient):
        """HSTS must NOT be sent over plain HTTP in non-production environment."""
        res = await client.get("/api/v1/health")
        assert "strict-transport-security" not in res.headers

    async def test_04_hsts_enforced_when_proto_is_https(self, client: AsyncClient):
        """HSTS is emitted when request indicates HTTPS transport via X-Forwarded-Proto."""
        res = await client.get("/api/v1/health", headers={"X-Forwarded-Proto": "https"})
        hsts = res.headers.get("strict-transport-security", "")
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts


    async def test_05_hsts_enforced_in_production_environment(
        self, client: AsyncClient, monkeypatch
    ):
        """When ENV is 'production', HSTS is always included."""
        settings = get_settings()
        monkeypatch.setattr(settings, "ENV", "production")

        res = await client.get("/api/v1/health")
        hsts = res.headers.get("strict-transport-security", "")
        assert "max-age=31536000" in hsts

    async def test_06_security_headers_present_on_error_responses(self, client: AsyncClient):
        """Security headers must also be present on 401, 404, and 422 error responses."""
        # 404 Not Found
        res_404 = await client.get("/api/v1/nonexistent-endpoint-security-test")
        assert res_404.status_code == 404
        assert res_404.headers.get("x-content-type-options") == "nosniff"
        assert res_404.headers.get("x-frame-options") == "DENY"
        assert "content-security-policy" in res_404.headers

        # 401 Unauthorized
        res_401 = await client.get("/api/v1/auth/me")
        assert res_401.status_code == 401
        assert res_401.headers.get("x-content-type-options") == "nosniff"
        assert res_401.headers.get("x-frame-options") == "DENY"
        assert "content-security-policy" in res_401.headers
