"""
CampusConnect - Secure Document Service
Enforces strict MIME/magic-number validation, path traversal containment,
event request lifecycle permissions, and audit logging.
"""

import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    WorkflowStateError,
)
from app.models.domain import AuditLog, Club, ClubMember, Document, EventRequest, User
from app.models.enums import AuditAction, ClubMemberRole, DocumentType, EventRequestStatus, UserRole

MAGIC_SIGNATURES = {
    "pdf": [b"%PDF-"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "docx": [b"PK\x03\x04"],
}

MIME_TYPE_MAP = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def get_storage_root() -> Path:
    settings = get_settings()
    base_dir = Path(settings.UPLOAD_BASE_DIR)
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir.resolve()
    except OSError:
        fallback = Path("uploads").resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


class DocumentService:
    @classmethod
    async def verify_document_access(
        cls,
        db: AsyncSession,
        event: EventRequest,
        actor: User,
    ) -> bool:
        """Centralized authorization check for event documents."""
        # 1. System admin
        if actor.role == UserRole.SYSTEM_ADMIN:
            return True

        # 2. Institutional workflow reviewers
        reviewer_roles = {
            UserRole.HALL_INCHARGE,
            UserRole.FINANCE_OFFICER,
            UserRole.ADVISOR_STUDENTS_UNION,
            UserRole.DEAN_STUDENT_AFFAIRS,
            UserRole.PRINCIPAL,
        }
        if actor.role in reviewer_roles:
            return True

        # 3. Club Faculty Advisor
        club = await db.scalar(select(Club).where(Club.id == event.club_id))
        if club and club.faculty_advisor_id == actor.id:
            return True

        # 4. Proposal submitter
        if event.submitted_by == actor.id:
            return True

        # 5. Active club member
        member = await db.scalar(
            select(ClubMember).where(
                ClubMember.club_id == event.club_id,
                ClubMember.user_id == actor.id,
                ClubMember.is_active.is_(True),
            )
        )
        return bool(member)

    @classmethod
    async def verify_upload_permission(
        cls,
        db: AsyncSession,
        event: EventRequest,
        actor: User,
    ) -> None:
        """Check if actor is authorized to upload/modify documents for this event."""
        # Check event status first
        if event.status not in (EventRequestStatus.DRAFT, EventRequestStatus.REVISION_REQUIRED):
            st = event.status.value if hasattr(event.status, "value") else event.status
            raise WorkflowStateError(
                f"Documents can only be uploaded in DRAFT or REVISION_REQUIRED status. "
                f"Current status is '{st}'."
            )

        if actor.role == UserRole.SYSTEM_ADMIN:
            return

        # Secretary of the club or submitter
        if event.submitted_by == actor.id:
            return

        member = await db.scalar(
            select(ClubMember).where(
                ClubMember.club_id == event.club_id,
                ClubMember.user_id == actor.id,
                ClubMember.club_role == ClubMemberRole.SECRETARY
                if hasattr(ClubMember, "club_role")
                else ClubMember.member_role == ClubMemberRole.SECRETARY,
                ClubMember.is_active.is_(True),
            )
        )
        if not member:
            raise ForbiddenError("Only club secretary or proposal submitter may modify documents.")

    @classmethod
    async def upload_document(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        file: UploadFile,
        document_type: DocumentType,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Document:
        """Upload and safely store a document with strict MIME and containment checks."""
        settings = get_settings()

        event = await db.scalar(select(EventRequest).where(EventRequest.id == event_id))
        if not event:
            raise NotFoundError(f"Event request '{event_id}' not found.")

        await cls.verify_upload_permission(db, event, actor)

        raw_filename = file.filename or "file.pdf"
        # Sanitize / extract extension
        ext = raw_filename.rsplit(".", 1)[-1].lower() if "." in raw_filename else ""
        if ext not in settings.ALLOWED_EXTENSIONS:
            allowed = ", ".join(settings.ALLOWED_EXTENSIONS)
            raise BadRequestError(
                f"Extension '{ext}' is not allowed. Allowed extensions: {allowed}"
            )

        # Read content and validate size
        content = await file.read()
        file_size = len(content)
        if file_size == 0:
            raise BadRequestError("Cannot upload an empty file.")
        if file_size > settings.MAX_FILE_SIZE_BYTES:
            max_mb = settings.MAX_FILE_SIZE_BYTES / (1024 * 1024)
            raise BadRequestError(f"File size exceeds maximum limit of {max_mb:.1f} MB.")

        # Magic number inspection (never trust client Content-Type alone)
        expected_sigs = MAGIC_SIGNATURES.get(ext, [])
        matches_magic = any(content.startswith(sig) for sig in expected_sigs)
        if not matches_magic:
            raise BadRequestError(
                f"File content does not match expected signature for extension '{ext}'."
            )

        mime_type = MIME_TYPE_MAP.get(ext, file.content_type or "application/octet-stream")

        # Storage key and path traversal prevention
        storage_root = get_storage_root()
        stored_filename = f"{uuid.uuid4().hex}.{ext}"
        rel_storage_path = Path(str(event_id)) / stored_filename
        full_path = (storage_root / rel_storage_path).resolve()

        if not full_path.is_relative_to(storage_root):
            raise BadRequestError("Path traversal detected.")

        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(content)

        doc = Document(
            id=uuid.uuid4(),
            event_request_id=event_id,
            uploaded_by=actor.id,
            document_type=document_type,
            original_filename=raw_filename,
            stored_filename=stored_filename,
            file_size_bytes=file_size,
            mime_type=mime_type,
            storage_path=str(rel_storage_path).replace("\\", "/"),
            is_active=True,
        )
        db.add(doc)

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.FILE_UPLOADED,
                entity_type="document",
                entity_id=str(doc.id),
                previous_state=None,
                new_state={
                    "event_request_id": str(event_id),
                    "original_filename": raw_filename,
                    "document_type": document_type.value
                    if hasattr(document_type, "value")
                    else str(document_type),
                    "file_size_bytes": file_size,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await db.commit()
        await db.refresh(doc)
        return doc

    @classmethod
    async def list_documents(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
    ) -> list[Document]:
        """List active documents for an event."""
        event = await db.scalar(select(EventRequest).where(EventRequest.id == event_id))
        if not event:
            raise NotFoundError(f"Event request '{event_id}' not found.")

        can_access = await cls.verify_document_access(db, event, actor)
        if not can_access:
            raise ForbiddenError(
                "Access denied: You do not have permission to view event documents."
            )

        stmt = (
            select(Document)
            .where(Document.event_request_id == event_id, Document.is_active.is_(True))
            .order_by(Document.created_at.asc())
        )
        result = await db.scalars(stmt)
        return list(result.all())

    @classmethod
    async def get_document_for_download(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        doc_id: uuid.UUID,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[Document, Path]:
        """Verify authorization and return Document and physical path for download."""
        event = await db.scalar(select(EventRequest).where(EventRequest.id == event_id))
        if not event:
            raise NotFoundError(f"Event request '{event_id}' not found.")

        can_access = await cls.verify_document_access(db, event, actor)
        if not can_access:
            raise ForbiddenError("Access denied to download this document.")

        doc = await db.scalar(
            select(Document).where(
                Document.id == doc_id,
                Document.event_request_id == event_id,
            )
        )
        if not doc or not doc.is_active:
            raise NotFoundError("Document not found or inactive.")

        storage_root = get_storage_root()
        full_path = (storage_root / Path(doc.storage_path)).resolve()
        if not full_path.is_relative_to(storage_root) or not full_path.exists():
            raise NotFoundError("Stored physical file not found.")

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.FILE_DOWNLOADED,
                entity_type="document",
                entity_id=str(doc.id),
                previous_state=None,
                new_state={"original_filename": doc.original_filename},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await db.commit()
        return doc, full_path

    @classmethod
    async def delete_document(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        doc_id: uuid.UUID,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Document:
        """Soft delete a document (is_active = False), preserving physical file."""
        event = await db.scalar(select(EventRequest).where(EventRequest.id == event_id))
        if not event:
            raise NotFoundError(f"Event request '{event_id}' not found.")

        await cls.verify_upload_permission(db, event, actor)

        doc = await db.scalar(
            select(Document).where(
                Document.id == doc_id,
                Document.event_request_id == event_id,
            )
        )
        if not doc or not doc.is_active:
            raise NotFoundError("Document not found or already inactive.")

        doc.is_active = False

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.FILE_DELETED,
                entity_type="document",
                entity_id=str(doc.id),
                previous_state={"is_active": True},
                new_state={"is_active": False},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await db.commit()
        await db.refresh(doc)
        return doc
