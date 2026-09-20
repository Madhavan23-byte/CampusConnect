"""
CampusConnect — Event Execution & Post-Event Delivery Endpoints
Provides explicit REST endpoints for:
- Event execution start and conclusion
- Post-event report submission, revision, and statutory certification
- Secure post-event photographic evidence attachment
"""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.models.domain import User
from app.models.enums import UserRole
from app.schemas.post_event_report import (
    AdminStartEventRequest,
    ConfirmedEventResponse,
    EvidenceUploadResponse,
    PostEventReportCertify,
    PostEventReportCreate,
    PostEventReportResponse,
    PostEventReportRevisionRequest,
    PostEventReportUpdate,
)
from app.services.document_service import DocumentService
from app.services.event_execution_service import (
    EventExecutionService,
    to_confirmed_event_response,
    to_post_event_report_response,
)

router = APIRouter()


@router.post(
    "/{id}/start",
    response_model=ConfirmedEventResponse,
    status_code=status.HTTP_200_OK,
    summary="Start confirmed event execution",
    description="Transitions confirmed event from SCHEDULED to IN_PROGRESS. Secretary only.",
)
async def start_event(
    id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConfirmedEventResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    event = await EventExecutionService.start_event(
        db=db,
        event_id=id,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(event)
    return to_confirmed_event_response(event)


@router.post(
    "/{id}/admin-start",
    response_model=ConfirmedEventResponse,
    status_code=status.HTTP_200_OK,
    summary="Emergency administrative event start",
    description="Allows SYSTEM_ADMIN to start an event in emergencies with justification.",
)
async def admin_start_event(
    id: uuid.UUID,
    admin_req: AdminStartEventRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.SYSTEM_ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConfirmedEventResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    event = await EventExecutionService.admin_start_event(
        db=db,
        event_id=id,
        actor=current_user,
        admin_req=admin_req,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(event)
    return to_confirmed_event_response(event)


@router.post(
    "/{id}/complete",
    response_model=PostEventReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Complete event and submit post-event report",
    description="Concludes event and registers post-event report for Advisor review.",
)
async def complete_and_report_event(
    id: uuid.UUID,
    report_in: PostEventReportCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostEventReportResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    event, report = await EventExecutionService.complete_and_submit_report(
        db=db,
        event_id=id,
        report_in=report_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(report)
    return to_post_event_report_response(report)


@router.get(
    "/{id}/post-event-report",
    response_model=PostEventReportResponse,
    summary="Retrieve post-event report",
    description="Fetch the post-event execution report for an event.",
)
async def get_post_event_report(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostEventReportResponse:
    report = await EventExecutionService.get_report(db=db, event_id=id, actor=current_user)
    return to_post_event_report_response(report)


@router.patch(
    "/{id}/post-event-report",
    response_model=PostEventReportResponse,
    summary="Amend post-event report during revision",
    description="Modify report details. Only allowed when report status is REVISION_REQUIRED.",
)
async def update_post_event_report(
    id: uuid.UUID,
    update_in: PostEventReportUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostEventReportResponse:
    report = await EventExecutionService.update_report(
        db=db, event_id=id, update_in=update_in, actor=current_user
    )
    await db.commit()
    await db.refresh(report)
    return to_post_event_report_response(report)


@router.post(
    "/{id}/post-event-report/resubmit",
    response_model=PostEventReportResponse,
    summary="Resubmit amended post-event report",
    description="Resubmits report after addressing Faculty Advisor comments.",
)
async def resubmit_post_event_report(
    id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostEventReportResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    report = await EventExecutionService.resubmit_report(
        db=db, event_id=id, actor=current_user, ip_address=ip_address, user_agent=user_agent
    )
    await db.commit()
    await db.refresh(report)
    return to_post_event_report_response(report)


@router.post(
    "/{id}/post-event-report/certify",
    response_model=PostEventReportResponse,
    summary="Faculty Advisor delivery certification",
    description="Formally certifies event delivery. Restricted to designated Faculty Advisor.",
)
async def certify_post_event_report(
    id: uuid.UUID,
    certify_in: PostEventReportCertify,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostEventReportResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    report = await EventExecutionService.certify_report(
        db=db,
        event_id=id,
        certify_in=certify_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(report)
    return to_post_event_report_response(report)


@router.post(
    "/{id}/post-event-report/revise",
    response_model=PostEventReportResponse,
    summary="Faculty Advisor request report revision",
    description="Requests corrections before certifying. Remarks are mandatory (>= 5 chars).",
)
async def request_post_event_report_revision(
    id: uuid.UUID,
    revision_in: PostEventReportRevisionRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostEventReportResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    report = await EventExecutionService.request_revision(
        db=db,
        event_id=id,
        revision_in=revision_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(report)
    return to_post_event_report_response(report)


@router.post(
    "/{id}/evidence",
    response_model=EvidenceUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload post-event photographic/documentary evidence",
    description="Upload post-event photos/evidence with magic-byte validation and geo metadata.",
)
async def upload_post_event_evidence(
    id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(description="Evidence image or PDF file"),
    geo_latitude: Decimal | None = Form(
        default=None, description="Client-declared latitude (-90 to 90)"
    ),
    geo_longitude: Decimal | None = Form(
        default=None, description="Client-declared longitude (-180 to 180)"
    ),
    geo_source: str | None = Form(
        default=None, description="Source indicator (e.g. EXIF, CLIENT_DECLARED)"
    ),
) -> EvidenceUploadResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    doc = await DocumentService.upload_post_event_evidence(
        db=db,
        event_id=id,
        file=file,
        actor=current_user,
        geo_latitude=geo_latitude,
        geo_longitude=geo_longitude,
        geo_source=geo_source,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(doc)
    return EvidenceUploadResponse(
        id=doc.id,
        event_id=doc.event_id or id,
        document_type=doc.document_type,
        original_filename=doc.original_filename,
        file_size_bytes=doc.file_size_bytes,
        mime_type=doc.mime_type,
        geo_latitude=doc.geo_latitude,
        geo_longitude=doc.geo_longitude,
        geo_source=doc.geo_source,
        created_at=doc.created_at,
    )


@router.get(
    "/{id}/evidence",
    response_model=list[EvidenceUploadResponse],
    summary="List post-event evidence",
    description="List active post-event photos and evidence attached to a confirmed event.",
)
async def list_post_event_evidence(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[EvidenceUploadResponse]:
    docs = await DocumentService.list_post_event_evidence(db=db, event_id=id, actor=current_user)
    return [
        EvidenceUploadResponse(
            id=d.id,
            event_id=d.event_id or id,
            document_type=d.document_type,
            original_filename=d.original_filename,
            file_size_bytes=d.file_size_bytes,
            mime_type=d.mime_type,
            geo_latitude=d.geo_latitude,
            geo_longitude=d.geo_longitude,
            geo_source=d.geo_source,
            created_at=d.created_at,
        )
        for d in docs
    ]


@router.get(
    "/{id}/confirmed",
    response_model=ConfirmedEventResponse,
    summary="Get confirmed event details",
    description="Retrieve confirmed event execution record by proposal ID or event ID.",
)
async def get_confirmed_event(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConfirmedEventResponse:
    event = await EventExecutionService.get_confirmed_event(db=db, event_id=id, actor=current_user)
    return to_confirmed_event_response(event)
