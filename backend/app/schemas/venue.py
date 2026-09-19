"""
CampusConnect Backend — Venue & Hall Pydantic Schemas

Strict schemas enforcing:
- Hall inventory representation and registration
- Lead-time validation (at least Settings.HALL_BOOKING_MIN_ADVANCE_DAYS notice)
- Logical occupancy intervals: start_time < end_time
- Physical facility requirements (stage, LCD, audio, AC, projector, etc.)
- Hall availability inspection
"""
import uuid
from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import VenueRequestStatus


# ---------------------------------------------------------------------------
# Hall Inventory Schemas
# ---------------------------------------------------------------------------
class HallResponse(BaseModel):
    """Public representation of a campus hall or auditorium."""

    id: uuid.UUID
    name: str
    location: str | None = None
    capacity: int
    available_facilities: list[str] | dict[str, Any] | None = None
    is_active: bool
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class HallCreate(BaseModel):
    """Payload for registering a new campus hall or venue."""

    name: str = Field(min_length=2, max_length=255, description="Official hall name")
    location: str | None = Field(default=None, max_length=500, description="Building / campus location")
    capacity: int = Field(ge=1, le=50000, description="Maximum seated/fire-code capacity")
    available_facilities: list[str] | dict[str, Any] | None = Field(
        default=None, description="Available facilities: projector, audio, stage, etc."
    )
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Hall name cannot be empty or whitespace.")
        return v


# ---------------------------------------------------------------------------
# Availability Query & Response Schemas
# ---------------------------------------------------------------------------
class HallAvailabilitySlot(BaseModel):
    """A booked occupancy interval for a hall."""

    start_time: datetime
    end_time: datetime


class HallAvailabilityResponse(BaseModel):
    """Availability response for a specific hall on a target date."""

    hall_id: uuid.UUID
    hall_name: str
    date: date | datetime
    is_available: bool
    booked_slots: list[HallAvailabilitySlot] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Venue Request (Event Attachment) Schemas
# ---------------------------------------------------------------------------
class VenueRequestCreate(BaseModel):
    """Payload for attaching a venue requirement to an event proposal draft."""

    hall_id: uuid.UUID = Field(description="Selected campus hall ID")
    requested_date: date | datetime = Field(description="Target date for hall reservation")
    start_time: datetime = Field(description="Occupancy start time (inclusive of setup)")
    end_time: datetime = Field(description="Occupancy end time (inclusive of teardown)")
    expected_audience: int | None = Field(
        default=None, ge=1, description="Expected attendee count for this venue"
    )
    requires_stage: bool = False
    requires_audio: bool = False
    requires_lcd: bool = False
    requires_ac: bool = False
    requires_projector: bool = False
    additional_requirements: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_intervals(self) -> "VenueRequestCreate":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be strictly after start_time.")
        return self


class VenueRequestUpdate(BaseModel):
    """Payload for updating venue requirement on a draft or revision-requested proposal."""

    hall_id: uuid.UUID | None = None
    requested_date: date | datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    expected_audience: int | None = Field(default=None, ge=1)
    requires_stage: bool | None = None
    requires_audio: bool | None = None
    requires_lcd: bool | None = None
    requires_ac: bool | None = None
    requires_projector: bool | None = None
    additional_requirements: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_intervals(self) -> "VenueRequestUpdate":
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValueError("end_time must be strictly after start_time.")
        return self


class VenueRequestResponse(BaseModel):
    """Safe public representation of an event venue request."""

    id: uuid.UUID
    event_request_id: uuid.UUID
    hall_id: uuid.UUID
    hall_name: str | None = None
    hall_location: str | None = None
    hall_capacity: int | None = None
    requested_date: date | datetime
    start_time: datetime
    end_time: datetime
    expected_audience: int | None = None
    requires_stage: bool
    requires_audio: bool
    requires_lcd: bool
    requires_ac: bool
    requires_projector: bool
    additional_requirements: str | None = None
    status: VenueRequestStatus
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
