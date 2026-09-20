"""
CampusConnect - Resource Request Schemas
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ResourceRequestStatus, ResourceType


class ResourceRequestCreate(BaseModel):
    resource_type: ResourceType
    quantity: int = Field(gt=0, description="Quantity must be positive integer")
    notes: str | None = None


class ResourceRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_request_id: uuid.UUID
    resource_type: ResourceType
    quantity: int
    notes: str | None
    status: ResourceRequestStatus
    managed_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime | None = None
