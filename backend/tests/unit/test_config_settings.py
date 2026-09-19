"""
CampusConnect — Real Settings & Environment Configuration Verification
Imports the actual application Settings and get_settings() singleton,
verifying canonical JSON array parsing for CORS_ALLOWED_ORIGINS, MIME types,
and extensions, with zero markdown or malformed syntax.
"""
import os
import pytest
from app.core.config import Settings, get_settings


def test_real_settings_loads_successfully():
    """Verify actual application Settings singleton loads without error."""
    get_settings.cache_clear()
    settings = get_settings()
    assert settings is not None
    assert settings.APP_NAME == "CampusConnect"
    assert settings.ALLOWED_EMAIL_DOMAIN == "college.edu"


def test_cors_allowed_origins_parsed_correctly():
    """Verify CORS_ALLOWED_ORIGINS is a valid list of URL strings without markdown or quotes."""
    get_settings.cache_clear()
    settings = get_settings()

    assert isinstance(settings.CORS_ALLOWED_ORIGINS, list)
    assert len(settings.CORS_ALLOWED_ORIGINS) >= 2
    assert "http://localhost:5173" in settings.CORS_ALLOWED_ORIGINS
    assert "http://localhost:3000" in settings.CORS_ALLOWED_ORIGINS

    # Verify no accidental markdown syntax or quotes in any origin
    for origin in settings.CORS_ALLOWED_ORIGINS:
        assert isinstance(origin, str)
        assert not origin.startswith("[") and not origin.endswith(")")  # No markdown [url](url)
        assert not origin.startswith('"') and not origin.endswith('"')
        assert not origin.startswith("'") and not origin.endswith("'")
        assert origin.startswith("http://") or origin.startswith("https://")


def test_allowed_mime_types_and_extensions():
    """Verify file upload settings are canonical list[str] types."""
    get_settings.cache_clear()
    settings = get_settings()

    assert isinstance(settings.ALLOWED_MIME_TYPES, list)
    assert "application/pdf" in settings.ALLOWED_MIME_TYPES
    assert "image/jpeg" in settings.ALLOWED_MIME_TYPES
    assert "image/png" in settings.ALLOWED_MIME_TYPES

    assert isinstance(settings.ALLOWED_EXTENSIONS, list)
    assert "pdf" in settings.ALLOWED_EXTENSIONS
    assert "png" in settings.ALLOWED_EXTENSIONS
    assert "docx" in settings.ALLOWED_EXTENSIONS


def test_custom_cors_json_array_loading(monkeypatch):
    """Verify that setting CORS_ALLOWED_ORIGINS via environment JSON array works cleanly."""
    custom_origins_json = '["https://portal.college.edu", "https://admin.college.edu"]'
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", custom_origins_json)

    # Instantiate real Settings directly
    custom_settings = Settings()
    assert custom_settings.CORS_ALLOWED_ORIGINS == [
        "https://portal.college.edu",
        "https://admin.college.edu",
    ]


def test_database_url_and_sync_property():
    """Verify database URLs are configured with correct schemes."""
    get_settings.cache_clear()
    settings = get_settings()

    assert "postgresql" in settings.DATABASE_URL or "sqlite" in settings.DATABASE_URL
    assert "psycopg" in settings.DATABASE_URL_SYNC or "sqlite" in settings.DATABASE_URL_SYNC
