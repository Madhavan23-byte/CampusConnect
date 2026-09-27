"""
CampusConnect - Phase 2.4 Event Closeout, Reopening & Archival Schemas (Pydantic v2)
Authoritative schemas for event closeout requests, statutory certification,
rejection, reopening petitions, reopen approvals, and archival actions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.enums import EventStatus

# Constrained string types for mandatory text rationale
ReasonText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=5,
        max_length=1000,
    ),
]


# ---------------------------------------------------------------------------
# Request Schemas (Command Payloads)
# ---------------------------------------------------------------------------


class EventCloseoutRequestCreate(BaseModel):
    """Payload for Club Secretary closeout request."""

    remarks: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional operational remarks or summary from the Club Secretary.",
    )


class EventCloseoutCertifyRequest(BaseModel):
    """Payload for Dean, Principal, or Faculty Advisor statutory closeout certification."""

    venue_cleared: bool = Field(
        ...,
        description="Mandatory statutory attestation that venue has been cleared.",
    )
    closure_notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional statutory certification remarks.",
    )


class EventCloseoutRejectRequest(BaseModel):
    """Payload for institutional authority closeout rejection."""

    reason: ReasonText = Field(
        ...,
        description="Mandatory non-empty justification for rejecting the closeout request.",
    )


class EventReopenRequestCreate(BaseModel):
    """Payload for Secretary, Advisor, or Finance Officer reopening petition."""

    reason: ReasonText = Field(
        ...,
        description="Mandatory non-empty justification for petitioning event reopening.",
    )


class EventReopenApproveRequest(BaseModel):
    """Payload for Dean or Principal reopen approval."""

    reason: ReasonText = Field(
        ...,
        description="Mandatory statutory justification for approving event reopening.",
    )


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class VenueStatusInfo(BaseModel):
    """Venue clearance and booking status."""

    has_booking: bool
    booking_ended: bool
    hall_id: uuid.UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class CloseoutEligibilityInfo(BaseModel):
    """Comprehensive closeout eligibility evaluation."""

    eligible: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    event_status: str
    settlement_status: str | None = None
    report_status: str | None = None
    venue_status: VenueStatusInfo
    event_id: uuid.UUID
    settlement_id: uuid.UUID | None = None
    report_id: uuid.UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class LatestClosureRequestInfo(BaseModel):
    """Metadata from the latest closure request audit event."""

    requested_by: uuid.UUID | None = None
    requested_at: datetime | None = None
    remarks: str | None = None

    model_config = ConfigDict(from_attributes=True)


class EventClosureResponse(BaseModel):
    """Public representation of certified EventClosure."""

    id: uuid.UUID
    event_id: uuid.UUID
    settlement_id: uuid.UUID
    post_event_report_id: uuid.UUID
    requested_by: uuid.UUID | None = None
    requested_at: datetime | None = None
    certified_by: uuid.UUID
    certified_at: datetime
    closure_notes: str | None = None
    venue_cleared: bool
    certificate_manifest_hash: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EventClosureRevisionResponse(BaseModel):
    """Public representation of immutable EventClosureRevision snapshot."""

    id: uuid.UUID
    event_id: uuid.UUID
    closure_id: uuid.UUID
    revision_number: int
    reopened_by: uuid.UUID
    reopened_at: datetime
    reopening_reason: str
    snapshot_data: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EventCloseoutActionResponse(BaseModel):
    """Generic status/message response for lifecycle commands."""

    event_id: uuid.UUID
    status: EventStatus
    message: str

    model_config = ConfigDict(from_attributes=True)


class EventClosureDetailResponse(BaseModel):
    """Comprehensive closeout state aggregation for UI display."""

    event_id: uuid.UUID
    event_status: EventStatus
    is_archived: bool
    eligibility: CloseoutEligibilityInfo
    closure: EventClosureResponse | None = None
    revisions: list[EventClosureRevisionResponse] = Field(default_factory=list)
    latest_request: LatestClosureRequestInfo | None = None

    model_config = ConfigDict(from_attributes=True)
