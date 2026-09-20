"""
CampusConnect Backend — Approval Workflow Schemas

Strict schemas for:
- Step review actions (Approve, Reject, Request Revision)
- Mandatory reason enforcement on adverse administrative actions
- Workflow step representation and chain inspection
- Approver pending action queues
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import WorkflowInstanceStatus, WorkflowStepStatus


class WorkflowStepApproveRequest(BaseModel):
    """Payload for approving an assigned workflow step."""

    comments: str | None = Field(
        default=None, max_length=2000, description="Optional approval remarks"
    )


class WorkflowStepRejectRequest(BaseModel):
    """Payload for rejecting a workflow step. Comments are mandatory."""

    comments: str = Field(
        min_length=5, max_length=2000, description="Mandatory detailed reason for rejection"
    )

    @field_validator("comments")
    @classmethod
    def validate_comments(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 5:
            raise ValueError("Rejection reason must be at least 5 non-whitespace characters.")
        return v


class WorkflowStepRevisionRequest(BaseModel):
    """Payload for requesting revisions on a proposal. Comments are mandatory."""

    comments: str = Field(
        min_length=5, max_length=2000, description="Mandatory instructions for required revisions"
    )

    @field_validator("comments")
    @classmethod
    def validate_comments(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 5:
            raise ValueError("Revision instructions must be at least 5 non-whitespace characters.")
        return v


class WorkflowStepResponse(BaseModel):
    """Public representation of an instantiated workflow step."""

    id: uuid.UUID
    instance_id: uuid.UUID
    template_step_id: uuid.UUID
    step_order: int
    step_name: str
    required_role: str | None = None
    assigned_to: uuid.UUID
    assigned_to_name: str | None = None
    assigned_to_email: str | None = None
    status: WorkflowStepStatus
    action_taken_at: datetime | None = None
    comments: str | None = None
    version_reviewed: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkflowInstanceResponse(BaseModel):
    """Public representation of an active or historical workflow instance."""

    id: uuid.UUID
    template_id: uuid.UUID
    template_name: str | None = None
    event_request_id: uuid.UUID
    current_step_order: int
    status: WorkflowInstanceStatus
    version_number: int
    steps: list[WorkflowStepResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkflowPendingItemResponse(BaseModel):
    """Item in an approver's pending work queue."""

    step_id: uuid.UUID
    instance_id: uuid.UUID
    event_request_id: uuid.UUID
    event_title: str
    club_name: str
    step_order: int
    step_name: str
    version_number: int
    submitted_at: datetime | None = None
    assigned_to: uuid.UUID
