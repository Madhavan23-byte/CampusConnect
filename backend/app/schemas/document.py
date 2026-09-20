"""
CampusConnect - Document Schemas
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import DocumentType


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_request_id: uuid.UUID
    uploaded_by: uuid.UUID
    document_type: DocumentType
    original_filename: str
    file_size_bytes: int
    mime_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None
