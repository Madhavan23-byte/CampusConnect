"""
Phase 2.5.5 Observability Test Suite
Tests:
- Request ID generation, validation, sanitization, and propagation in headers
- Async contextvar isolation for correlation IDs
- Structured production logging (JSON formatting, field completeness)
- Recursive redaction of sensitive credentials, tokens, and secrets
- Unhandled 500 error sanitization (no stack trace or DB leak, request ID included)
- Health, Readiness (/health/ready), and Liveness (/health/live) probes
"""

import json
import logging
import uuid
import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.logging import (
    StructuredLogFormatter,
    _redact,
    get_request_id,
    is_safe_request_id,
    set_request_id,
    reset_request_id,
)

settings = get_settings()


class TestRequestIdMechanics:
    """Validates X-Request-ID generation, acceptance, sanitization, and propagation."""

    def test_is_safe_request_id_validates_correctly(self):
        # Valid alphanumeric with dash and underscore
        assert is_safe_request_id("valid-request-id-123_abc") is True
        assert is_safe_request_id(str(uuid.uuid4())) is True
        assert is_safe_request_id("a" * 64) is True

        # Invalid formats: too long, special characters, whitespace, control chars, injections
        assert is_safe_request_id("a" * 65) is False
        assert is_safe_request_id("") is False
        assert is_safe_request_id(None) is False
        assert is_safe_request_id("req id with spaces") is False
        assert is_safe_request_id("req\r\ninjection") is False
        assert is_safe_request_id("<script>alert(1)</script>") is False
        assert is_safe_request_id("req;DROP TABLE users;--") is False

    @pytest.mark.asyncio
    async def test_request_generates_request_id_when_omitted(self, client: AsyncClient):
        response = await client.get("/api/v1/health/live")
        assert response.status_code == 200
        rid = response.headers.get("X-Request-ID")
        assert rid is not None
        assert is_safe_request_id(rid) is True

    @pytest.mark.asyncio
    async def test_request_accepts_and_propagates_valid_client_request_id(self, client: AsyncClient):
        custom_rid = "client-trace-id-998877"
        response = await client.get("/api/v1/health/live", headers={"X-Request-ID": custom_rid})
        assert response.status_code == 200
        assert response.headers.get("X-Request-ID") == custom_rid

    @pytest.mark.asyncio
    async def test_request_replaces_malicious_request_id_with_safe_uuid(self, client: AsyncClient):
        malicious_rid = "malicious\r\nX-Injected: true<script>"
        response = await client.get("/api/v1/health/live", headers={"X-Request-ID": malicious_rid})
        assert response.status_code == 200
        returned_rid = response.headers.get("X-Request-ID")
        assert returned_rid is not None
        assert returned_rid != malicious_rid
        assert is_safe_request_id(returned_rid) is True

    @pytest.mark.asyncio
    async def test_process_time_header_included(self, client: AsyncClient):
        response = await client.get("/api/v1/health/live")
        assert "X-Process-Time-Ms" in response.headers
        duration = float(response.headers["X-Process-Time-Ms"])
        assert duration >= 0.0


class TestStructuredLoggingAndRedaction:
    """Validates structured JSON formatting and credential/secret redaction."""

    def test_sensitive_field_redaction_top_level(self):
        payload = {
            "user_id": "u-123",
            "email": "user@college.edu",
            "password": "SuperSecretPassword123!",
            "access_token": "eyJhbGciOi...",
            "refresh_token": "opaque-token-abc",
            "authorization": "Bearer eyJhbGci...",
            "secret_key": "my-app-secret",
            "cookie": "campusconnect_refresh=xyz",
        }
        redacted = _redact(payload)
        assert redacted["user_id"] == "u-123"
        assert redacted["email"] == "user@college.edu"
        assert redacted["password"] == "[REDACTED]"
        assert redacted["access_token"] == "[REDACTED]"
        assert redacted["refresh_token"] == "[REDACTED]"
        assert redacted["authorization"] == "[REDACTED]"
        assert redacted["secret_key"] == "[REDACTED]"
        assert redacted["cookie"] == "[REDACTED]"

    def test_sensitive_field_redaction_nested(self):
        nested_payload = {
            "meta": {"status": "ok"},
            "auth": {
                "token": "secret-jwt",
                "credentials": {
                    "password_hash": "$argon2id$...",
                    "smtp_password": "smtp_pass_123",
                },
            },
            "headers_list": [{"Authorization": "Bearer 123"}, {"Accept": "application/json"}],
        }
        redacted = _redact(nested_payload)
        assert redacted["meta"]["status"] == "ok"
        assert redacted["auth"]["token"] == "[REDACTED]"
        assert redacted["auth"]["credentials"]["password_hash"] == "[REDACTED]"
        assert redacted["auth"]["credentials"]["smtp_password"] == "[REDACTED]"
        assert redacted["headers_list"][0]["Authorization"] == "[REDACTED]"
        assert redacted["headers_list"][1]["Accept"] == "application/json"

    def test_structured_log_formatter_outputs_valid_json(self):
        formatter = StructuredLogFormatter()
        token = set_request_id("log-test-correlation-id")
        try:
            record = logging.LogRecord(
                name="test_logger",
                level=logging.INFO,
                pathname="test.py",
                lineno=10,
                msg="Test structured log message",
                args=(),
                exc_info=None,
            )
            record.method = "POST"
            record.path = "/api/v1/events"
            record.status_code = 201
            record.password = "LeakAttempt"

            formatted_str = formatter.format(record)
            data = json.loads(formatted_str)

            assert data["level"] == "INFO"
            assert data["logger"] == "test_logger"
            assert data["message"] == "Test structured log message"
            assert data["request_id"] == "log-test-correlation-id"
            assert "timestamp" in data
            assert data["extra"]["method"] == "POST"
            assert data["extra"]["path"] == "/api/v1/events"
            assert data["extra"]["status_code"] == 201
            assert data["extra"]["password"] == "[REDACTED]"
        finally:
            reset_request_id(token)


class TestUnhandledExceptionSafety:
    """Ensures 500 error responses contain request_id but never leak stack traces or internal DB info."""

    @pytest.mark.asyncio
    async def test_500_handler_returns_safe_error_with_request_id(self, client: AsyncClient, monkeypatch):
        from app.services.auth_service import AuthService

        async def broken_authenticate(*args, **kwargs):
            raise RuntimeError("Database connection string: postgresql://admin:secretPass@internal-db:5432")

        monkeypatch.setattr(AuthService, "authenticate_user", broken_authenticate)

        from httpx import ASGITransport
        from app.main import app

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as test_client:
            response = await test_client.post(
                "/api/v1/auth/login",
                json={"email": "e2e.admin@college.edu", "password": "Password123!"},
            )
        assert response.status_code == 500
        data = response.json()

        assert data["error"] == "internal_error"
        assert data["message"] == "An unexpected error occurred."
        assert "request_id" in data
        assert is_safe_request_id(data["request_id"]) is True
        assert response.headers.get("X-Request-ID") == data["request_id"]

        # Critical security check: No internal passwords, connections or tracebacks exposed
        raw_body = response.text
        assert "secretPass" not in raw_body
        assert "Traceback" not in raw_body
        assert "RuntimeError" not in raw_body
        assert "internal-db" not in raw_body


class TestHealthAndProbes:
    """Validates composite health, liveness (/health/live), and readiness (/health/ready) endpoints."""

    @pytest.mark.asyncio
    async def test_liveness_probe_returns_alive(self, client: AsyncClient):
        response = await client.get("/api/v1/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"
        assert data["app"] == "CampusConnect"
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_readiness_probe_healthy(self, client: AsyncClient):
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["app"] == "CampusConnect"

    @pytest.mark.asyncio
    async def test_readiness_probe_database_down_returns_503(self, client: AsyncClient, monkeypatch):
        from app.modules import health

        class FailingEngine:
            def connect(self):
                raise RuntimeError("Postgres connection refused: password=supersecret")

        monkeypatch.setattr(health, "engine", FailingEngine())

        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["error"] == "Database unreachable"
        assert "supersecret" not in response.text
