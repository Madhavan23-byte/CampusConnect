"""CampusConnect — Post-Event Report and Execution Schemas (Pydantic v2)"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import DocumentType, EventStatus, EventType, PostEventReportStatus


class PostEventReportCreate(BaseModel):
    """Payload for submitting a post-event execution report."""

    actual_attendance: int = Field(ge=1, le=100000, description="Actual attendance count (> 0)")
    summary: str = Field(
        min_length=20, max_length=10000, description="Comprehensive executive summary of the event"
    )
    objectives_achieved: str = Field(
        min_length=5, max_length=5000, description="Academic and institutional objectives achieved"
    )
    outcomes: str | None = Field(
        default=None,
        max_length=5000,
        description="Specific takeaways, participant outcomes, feedback",
    )
    challenges: str | None = Field(
        default=None,
        max_length=5000,
        description="Logistical or organizational challenges encountered",
    )

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        cleaned = " ".join(v.strip().split())
        if len(cleaned) < 20:
            raise ValueError("Summary must be at least 20 characters after trimming whitespace")
        return cleaned

    @field_validator("objectives_achieved")
    @classmethod
    def validate_objectives(cls, v: str) -> str:
        cleaned = " ".join(v.strip().split())
        if len(cleaned) < 5:
            raise ValueError(
                "Objectives achieved must be at least 5 characters after trimming whitespace"
            )
        return cleaned


class PostEventReportUpdate(BaseModel):
    """Payload for amending a report returned for revision."""

    actual_attendance: int | None = Field(default=None, ge=1, le=100000)
    summary: str | None = Field(default=None, min_length=20, max_length=10000)
    objectives_achieved: str | None = Field(default=None, min_length=5, max_length=5000)
    outcomes: str | None = Field(default=None, max_length=5000)
    challenges: str | None = Field(default=None, max_length=5000)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, v: str | None) -> str | None:
        if v is not None:
            cleaned = " ".join(v.strip().split())
            if len(cleaned) < 20:
                raise ValueError("Summary must be at least 20 characters after trimming whitespace")
            return cleaned
        return v


class PostEventReportCertify(BaseModel):
    """Payload for Faculty Advisor certification."""

    remarks: str | None = Field(
        default=None, max_length=2000, description="Optional delivery certification remarks"
    )


class PostEventReportRevisionRequest(BaseModel):
    """Payload for Faculty Advisor requesting report revision."""

    remarks: str = Field(
        min_length=5, max_length=2000, description="Mandatory remarks explaining required revisions"
    )

    @field_validator("remarks")
    @classmethod
    def validate_remarks(cls, v: str) -> str:
        cleaned = " ".join(v.strip().split())
        if len(cleaned) < 5:
            raise ValueError("Revision remarks must be at least 5 characters")
        return cleaned


class AdminStartEventRequest(BaseModel):
    """Payload for emergency administrative event start."""

    reason: str = Field(
        min_length=10,
        max_length=1000,
        description="Mandatory administrative justification for override",
    )


class PostEventReportResponse(BaseModel):
    """Safe public representation of a post-event report."""

    id: uuid.UUID
    event_id: uuid.UUID
    revision_number: int
    actual_attendance: int
    summary: str
    objectives_achieved: str
    outcomes: str | None = None
    challenges: str | None = None
    status: PostEventReportStatus
    submitted_by: uuid.UUID
    submitted_by_name: str | None = None
    submitted_by_email: str | None = None
    submitted_at: datetime
    certified_by: uuid.UUID | None = None
    certified_by_name: str | None = None
    certified_by_email: str | None = None
    certified_at: datetime | None = None
    certification_remarks: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConfirmedEventResponse(BaseModel):
    """Public representation of an approved and confirmed event."""

    id: uuid.UUID
    event_request_id: uuid.UUID
    club_id: uuid.UUID
    hall_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    event_type: EventType
    event_date: datetime
    start_time: datetime
    end_time: datetime
    expected_attendees: int | None = None
    status: EventStatus
    academic_year: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvidenceUploadResponse(BaseModel):
    """Public representation of uploaded post-event photographic/documentary evidence."""

    id: uuid.UUID
    event_id: uuid.UUID
    document_type: DocumentType
    original_filename: str
    file_size_bytes: int
    mime_type: str
    geo_latitude: Decimal | None = None
    geo_longitude: Decimal | None = None
    geo_source: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
