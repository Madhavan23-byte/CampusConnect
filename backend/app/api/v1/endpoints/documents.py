"""
CampusConnect - Documents Endpoints
POST   /api/v1/events/{id}/documents
GET    /api/v1/events/{id}/documents
GET    /api/v1/events/{id}/documents/{doc_id}/download
DELETE /api/v1/events/{id}/documents/{doc_id}
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.domain import User
from app.models.enums import DocumentType
from app.schemas.document import DocumentResponse
from app.services.document_service import DocumentService

router = APIRouter()


@router.post(
    "/{event_id}/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED
)
async def upload_document(
    event_id: uuid.UUID,
    file: UploadFile,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    request: Request,
    document_type: DocumentType = Form(default=DocumentType.SUPPORTING),
) -> DocumentResponse:
    """Upload a document for an event proposal in DRAFT or REVISION_REQUIRED status."""
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return await DocumentService.upload_document(
        db=db,
        event_id=event_id,
        file=file,
        document_type=document_type,
        actor=current_user,
        ip_address=ip_addr,
        user_agent=user_agent,
    )


@router.get("/{event_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    event_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[DocumentResponse]:
    """List all active documents attached to an event proposal."""
    return await DocumentService.list_documents(
        db=db,
        event_id=event_id,
        actor=current_user,
    )


@router.get("/{event_id}/documents/{doc_id}/download")
async def download_document(
    event_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    request: Request,
):
    """Securely download an event document. Requires authorization."""
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    doc, physical_path = await DocumentService.get_document_for_download(
        db=db,
        event_id=event_id,
        doc_id=doc_id,
        actor=current_user,
        ip_address=ip_addr,
        user_agent=user_agent,
    )
    return FileResponse(
        path=physical_path,
        filename=doc.original_filename,
        media_type=doc.mime_type,
    )


@router.delete("/{event_id}/documents/{doc_id}")
async def delete_document(
    event_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    request: Request,
):
    """Soft delete a document from an event proposal in DRAFT or REVISION_REQUIRED status."""
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    await DocumentService.delete_document(
        db=db,
        event_id=event_id,
        doc_id=doc_id,
        actor=current_user,
        ip_address=ip_addr,
        user_agent=user_agent,
    )
    return {"message": "Document deactivated successfully"}
