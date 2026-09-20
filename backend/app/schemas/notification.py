"""
CampusConnect - Notification Schemas
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recipient_id: uuid.UUID
    event_request_id: uuid.UUID | None
    notification_type: str
    title: str
    message: str
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class NotificationCountResponse(BaseModel):
    unread_count: int
    total_count: int


class NotificationBatchReadResponse(BaseModel):
    updated_count: int
