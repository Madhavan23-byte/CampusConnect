"""
CampusConnect Backend — Authentication Pydantic Schemas

Request and response validation models for:
- User registration
- User login
- Token responses & payloads
- Password validation rules
"""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import UserRole

# ---------------------------------------------------------------------------
# Password Validation Utility
# ---------------------------------------------------------------------------

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


def validate_password_strength(password: str) -> str:
    """
    Validate that password satisfies institutional security policy:
    - Between 8 and 128 characters
    - At least one uppercase letter (A-Z)
    - At least one lowercase letter (a-z)
    - At least one decimal digit (0-9)
    - At least one special character (!@#$%^&*()_+-=[]{}|;:,.<>?)
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"Password cannot exceed {PASSWORD_MAX_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit")
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]", password):
        raise ValueError("Password must contain at least one special character")
    return password


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class UserRegisterRequest(BaseModel):
    """Payload for user account registration."""

    email: EmailStr = Field(description="College email address")
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        description="Password meeting security criteria",
    )
    full_name: str = Field(
        min_length=2,
        max_length=255,
        description="User's full legal/academic name",
    )
    role: UserRole = Field(description="Assigned institutional role")
    department: str | None = Field(default=None, max_length=255)
    designation: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=20)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("full_name")
    @classmethod
    def sanitize_full_name(cls, v: str) -> str:
        cleaned = " ".join(v.strip().split())
        if len(cleaned) < 2:
            raise ValueError("Full name must be at least 2 characters")
        return cleaned

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v)


class UserLoginRequest(BaseModel):
    """Payload for user authentication."""

    email: EmailStr = Field(description="User login email")
    password: str = Field(min_length=1, description="Account password")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


# ---------------------------------------------------------------------------
# Response & Token Schemas
# ---------------------------------------------------------------------------


class TokenResponse(BaseModel):
    """OAuth2-compatible token response with JWT access token."""

    access_token: str = Field(description="Signed JWT access token")
    token_type: str = Field(default="bearer", description="Token authorization scheme")
    expires_in: int = Field(description="Token lifetime in seconds")
    refresh_token: str | None = Field(default=None, description="Optional opaque refresh token")


class TokenPayload(BaseModel):
    """Decoded JWT claims representation."""

    sub: str = Field(description="User ID as string UUID")
    role: str = Field(description="Institutional role name")
    email: str = Field(description="User email address")
    token_type: str = Field(default="access")
    jti: str = Field(description="Unique token identifier")
    iat: int = Field(description="Issued-at timestamp")
    exp: int = Field(description="Expiration timestamp")


class UserAuthResponse(BaseModel):
    """Safe public user information returned upon authentication."""

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    email_verified: bool
    is_active: bool
    department: str | None = None
    designation: str | None = None
    phone: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
