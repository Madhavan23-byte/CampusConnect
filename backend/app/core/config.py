"""
CampusConnect Backend — Core Settings
All configuration is loaded from environment variables.
Never hard-code secrets or business rules here.
"""
import json
from functools import lru_cache
from typing import Any, Literal, Union

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Application
    # ------------------------------------------------------------------ #
    APP_NAME: str = "CampusConnect"
    APP_VERSION: str = "1.0.0"
    ENV: Literal["development", "production", "test"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    DATABASE_URL: str = "postgresql+asyncpg://campusconnect:campusconnect@localhost:5432/campusconnect"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Synchronous URL used by Alembic migrations only
    @property
    def DATABASE_URL_SYNC(self) -> str:
        try:
            import psycopg  # noqa: F401
            driver = "postgresql+psycopg://"
        except ImportError:
            driver = "postgresql+psycopg2://"
        return self.DATABASE_URL.replace("postgresql+asyncpg://", driver)

    # ------------------------------------------------------------------ #
    # Auth / JWT
    # ------------------------------------------------------------------ #
    JWT_SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_USE_A_LONG_RANDOM_SECRET"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    REFRESH_COOKIE_NAME: str = "campusconnect_refresh"
    COOKIE_SECURE: bool | None = None
    COOKIE_SAMESITE: str = "lax"
    COOKIE_PATH: str = "/api/v1/auth"

    @property
    def is_cookie_secure(self) -> bool:
        if self.COOKIE_SECURE is not None:
            return self.COOKIE_SECURE
        return self.ENV == "production"

    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 60
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24

    # ------------------------------------------------------------------ #
    # Email / Domain
    # ------------------------------------------------------------------ #
    # College email domain restriction. Configurable via ALLOWED_EMAIL_DOMAIN env var.
    # Default is a generic placeholder domain. Production deployments must set this to their institution's domain.
    ALLOWED_EMAIL_DOMAIN: str = "college.edu"

    # Email service: "development" (logs to console) | "smtp" (production)
    EMAIL_PROVIDER: Literal["development", "smtp"] = "development"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@campusconnect.local"
    SMTP_FROM_NAME: str = "CampusConnect"
    SMTP_USE_TLS: bool = True

    # ------------------------------------------------------------------ #
    # File Storage
    # ------------------------------------------------------------------ #
    # Phase 1: local filesystem. Abstracted behind StorageService.
    STORAGE_PROVIDER: Literal["local"] = "local"
    UPLOAD_BASE_DIR: str = "/app/uploads"
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB
    ALLOWED_MIME_TYPES: list[str] = [
        "application/pdf",
        "image/jpeg",
        "image/png",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    ALLOWED_EXTENSIONS: list[str] = ["pdf", "jpg", "jpeg", "png", "docx"]

    # ------------------------------------------------------------------ #
    # Security / Rate Limiting
    # ------------------------------------------------------------------ #
    # Canonical format for list environment variables: JSON array.
    # Example in .env: CORS_ALLOWED_ORIGINS=["http://localhost:5173","http://localhost:3000"]
    CORS_ALLOWED_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 10
    MAX_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 15

    # ------------------------------------------------------------------ #
    # Business Rules (configurable — not hard-coded)
    # ------------------------------------------------------------------ #
    # Minimum days before event date that a booking must be submitted
    HALL_BOOKING_MIN_ADVANCE_DAYS: int = 7
    # Idempotency key TTL in hours
    IDEMPOTENCY_KEY_TTL_HOURS: int = 24
    # Default academic year format: "2026-27"
    CURRENT_ACADEMIC_YEAR: str = "2026-27"

    # ------------------------------------------------------------------ #
    # Argon2 password hashing
    # ------------------------------------------------------------------ #
    ARGON2_TIME_COST: int = 3
    ARGON2_MEMORY_COST: int = 65536  # 64MB
    ARGON2_PARALLELISM: int = 4

    @field_validator("CORS_ALLOWED_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, v: list[str]) -> list[str]:
        """Validate and sanitize CORS origins list."""
        cleaned = []
        for origin in v:
            clean_str = str(origin).strip().strip("\"'")
            if clean_str:
                cleaned.append(clean_str)
        return cleaned

    @field_validator("ALLOWED_EMAIL_DOMAIN")
    @classmethod
    def domain_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("ALLOWED_EMAIL_DOMAIN must not be empty")
        return v.lower().strip()


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton. Use this everywhere."""
    return Settings()
