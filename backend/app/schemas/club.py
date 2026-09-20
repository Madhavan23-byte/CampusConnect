"""
CampusConnect Backend — Club Governance Schemas

Pydantic v2 schemas for:
- Club creation and updates
- Club responses with safe relational data
- Member additions and role updates
- Safe member responses without sensitive credentials
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ClubMemberRole


class ClubCreate(BaseModel):
    """Payload for registering a new college club."""

    name: str = Field(min_length=2, max_length=255, description="Official club name")
    description: str | None = Field(
        default=None, max_length=2000, description="Club purpose and mission"
    )
    faculty_advisor_id: uuid.UUID | None = Field(
        default=None, description="Assigned Faculty Advisor user ID"
    )
    academic_year: str = Field(
        min_length=4, max_length=10, description="Charter academic year, e.g. 2026-27"
    )
    logo_url: str | None = Field(
        default=None, max_length=500, description="URL or relative path to club logo"
    )

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        cleaned = " ".join(v.strip().split())
        if len(cleaned) < 2:
            raise ValueError("Club name must be at least 2 characters")
        return cleaned

    @field_validator("academic_year")
    @classmethod
    def clean_academic_year(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Academic year cannot be empty")
        return cleaned


class ClubUpdate(BaseModel):
    """Payload for updating an existing club's profile."""

    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    logo_url: str | None = Field(default=None, max_length=500)
    is_active: bool | None = Field(default=None, description="Active status")
    faculty_advisor_id: uuid.UUID | None = Field(
        default=None, description="New Faculty Advisor user ID"
    )
    academic_year: str | None = Field(default=None, min_length=4, max_length=10)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str | None) -> str | None:
        if v is not None:
            cleaned = " ".join(v.strip().split())
            if len(cleaned) < 2:
                raise ValueError("Club name must be at least 2 characters")
            return cleaned
        return v


class ClubResponse(BaseModel):
    """Safe public representation of a club."""

    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    faculty_advisor_id: uuid.UUID | None = None
    faculty_advisor_name: str | None = None
    faculty_advisor_email: str | None = None
    academic_year: str
    is_active: bool
    logo_url: str | None = None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    member_count: int | None = None

    model_config = ConfigDict(from_attributes=True)


class ClubMemberAdd(BaseModel):
    """Payload for adding a student or officer to a club roster."""

    user_id: uuid.UUID = Field(description="User ID to enroll as a member")
    member_role: ClubMemberRole = Field(
        default=ClubMemberRole.MEMBER,
        description="Internal club role (SECRETARY, TREASURER, MEMBER)",
    )


class ClubMemberUpdate(BaseModel):
    """Payload for updating an existing member's role or active status."""

    member_role: ClubMemberRole | None = Field(default=None, description="New member role")
    is_active: bool | None = Field(default=None, description="Member status flag")


class ClubMemberResponse(BaseModel):
    """Safe representation of club membership."""

    id: uuid.UUID
    club_id: uuid.UUID
    user_id: uuid.UUID
    user_full_name: str | None = None
    user_email: str | None = None
    member_role: ClubMemberRole
    is_active: bool
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)
