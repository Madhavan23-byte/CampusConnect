"""
CampusConnect Backend — Event Proposal Schemas

Pydantic v2 schemas for:
- Event proposal draft creation
- Event proposal draft updates
- Event proposal submission and snapshotting
- Safe public representations with club and submitter details
"""
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import EventRequestStatus, EventType


class EventRequestCreate(BaseModel):
    """Payload for creating a new event proposal draft."""

    club_id: uuid.UUID = Field(description="Target club charter ID")
    title: str = Field(min_length=3, max_length=500, description="Title of the event")
    description: str | None = Field(default=None, max_length=5000, description="Detailed agenda and description")
    event_type: EventType = Field(description="Institutional category of event")
    expected_attendees: int | None = Field(default=None, ge=1, le=100000, description="Expected participant count")
    event_date: datetime | None = Field(default=None, description="Planned event date / start time")
    chief_guest_name: str | None = Field(default=None, max_length=255)
    chief_guest_designation: str | None = Field(default=None, max_length=255)
    chief_guest_institution: str | None = Field(default=None, max_length=255)
    academic_year: str = Field(min_length=4, max_length=10, description="Charter academic year, e.g. 2026-27")

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str) -> str:
        cleaned = " ".join(v.strip().split())
        if len(cleaned) < 3:
            raise ValueError("Event title must be at least 3 characters")
        return cleaned

    @field_validator("academic_year")
    @classmethod
    def clean_academic_year(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Academic year cannot be empty")
        return cleaned


class EventRequestUpdate(BaseModel):
    """Payload for modifying an event proposal draft."""

    title: str | None = Field(default=None, min_length=3, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    event_type: EventType | None = Field(default=None)
    expected_attendees: int | None = Field(default=None, ge=1, le=100000)
    event_date: datetime | None = Field(default=None)
    chief_guest_name: str | None = Field(default=None, max_length=255)
    chief_guest_designation: str | None = Field(default=None, max_length=255)
    chief_guest_institution: str | None = Field(default=None, max_length=255)
    academic_year: str | None = Field(default=None, min_length=4, max_length=10)

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str | None) -> str | None:
        if v is not None:
            cleaned = " ".join(v.strip().split())
            if len(cleaned) < 3:
                raise ValueError("Event title must be at least 3 characters")
            return cleaned
        return v


class EventRequestSubmit(BaseModel):
    """Payload for submitting an event proposal into the approval workflow."""

    change_summary: str | None = Field(
        default=None, max_length=2000, description="Summary of proposal or changes if resubmitting"
    )


class EventRequestResponse(BaseModel):
    """Safe public representation of an event proposal."""

    id: uuid.UUID
    club_id: uuid.UUID
    club_name: str | None = None
    submitted_by: uuid.UUID
    submitted_by_name: str | None = None
    submitted_by_email: str | None = None
    title: str
    description: str | None = None
    event_type: EventType
    expected_attendees: int | None = None
    event_date: datetime | None = None
    chief_guest_name: str | None = None
    chief_guest_designation: str | None = None
    chief_guest_institution: str | None = None
    status: EventRequestStatus
    workflow_instance_id: uuid.UUID | None = None
    current_version: int
    version_lock: int
    academic_year: str
    idempotency_key: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
