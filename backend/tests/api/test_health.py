"""
Day 1 Smoke Tests — CampusConnect Backend
Verifies the application starts, health endpoint responds,
and database models load correctly.
Run with: pytest tests/api/test_health.py -v
"""
import pytest


class TestHealthEndpoint:
    """GET /api/v1/health — no authentication required."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        response = await client.get("/api/v1/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_response_structure(self, client):
        response = await client.get("/api/v1/health")
        data = response.json()
        # Required top-level fields
        assert "status" in data
        assert "app" in data
        assert "version" in data
        assert "environment" in data
        assert "timestamp" in data
        assert "checks" in data

    @pytest.mark.asyncio
    async def test_health_app_name(self, client):
        response = await client.get("/api/v1/health")
        data = response.json()
        assert data["app"] == "CampusConnect"

    @pytest.mark.asyncio
    async def test_health_checks_include_database(self, client):
        response = await client.get("/api/v1/health")
        data = response.json()
        assert "database" in data["checks"]
        assert "status" in data["checks"]["database"]

    @pytest.mark.asyncio
    async def test_health_environment_is_test(self, client):
        response = await client.get("/api/v1/health")
        data = response.json()
        # In test environment, ENV is set to "test"
        assert data["environment"] == "test"

    @pytest.mark.asyncio
    async def test_security_headers_present(self, client):
        response = await client.get("/api/v1/health")
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("x-frame-options") == "DENY"


class TestModelImport:
    """Verifies all domain models load without error."""

    def test_all_models_importable(self):
        from app.models import (
            AuditLog,
            BudgetLineItem,
            BudgetProposal,
            Club,
            ClubMember,
            Document,
            EmailVerificationToken,
            Event,
            EventRequest,
            EventRequestVersion,
            Hall,
            HallBookingConfirmed,
            IdempotencyRecord,
            Notification,
            PasswordResetToken,
            RefreshToken,
            ResourceRequest,
            User,
            VenueRequest,
            WorkflowInstance,
            WorkflowInstanceStep,
            WorkflowTemplate,
            WorkflowTemplateStep,
        )
        # If we reach here, all models imported successfully
        assert User.__tablename__ == "users"
        assert EventRequest.__tablename__ == "event_requests"
        assert HallBookingConfirmed.__tablename__ == "hall_bookings_confirmed"
        assert AuditLog.__tablename__ == "audit_logs"

    def test_enum_values_are_correct(self):
        from app.models.enums import (
            EventRequestStatus,
            UserRole,
            WorkflowStepStatus,
        )
        assert UserRole.SYSTEM_ADMIN == "SYSTEM_ADMIN"
        assert UserRole.PRINCIPAL == "PRINCIPAL"
        assert EventRequestStatus.DRAFT == "DRAFT"
        assert EventRequestStatus.APPROVED == "APPROVED"
        assert WorkflowStepStatus.PENDING == "PENDING"

    def test_settings_loaded(self):
        from app.core.config import get_settings
        settings = get_settings()
        assert settings.APP_NAME == "CampusConnect"
        assert settings.ENV == "test"
        assert settings.ALLOWED_EMAIL_DOMAIN is not None
        assert len(settings.ALLOWED_EMAIL_DOMAIN) > 0


class TestNonExistentRoutes:
    """Verify non-existent routes return proper 404, not exceptions."""

    @pytest.mark.asyncio
    async def test_nonexistent_route_returns_404(self, client):
        response = await client.get("/api/v1/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_no_stack_trace_in_404_response(self, client):
        response = await client.get("/api/v1/nonexistent")
        body = response.text
        # Stack traces must never be exposed
        assert "Traceback" not in body
        assert "Exception" not in body
