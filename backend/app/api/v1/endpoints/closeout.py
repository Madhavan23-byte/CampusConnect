"""
CampusConnect - Event Closeout, Reopening & Archival Endpoints
RESTful commands and state inspections for the post-completion event governance lifecycle.

Endpoints:
- GET  /api/v1/events/{event_id}/closure                : Comprehensive closeout state & eligibility
- POST /api/v1/events/{event_id}/closure/request        : Club Secretary requests closeout
- POST /api/v1/events/{event_id}/closure/certify        : Dean/Principal/Advisor certifies closeout
- POST /api/v1/events/{event_id}/closure/reject         : Certifier rejects closeout
- POST /api/v1/events/{event_id}/closure/reopen-request : Petition to reopen closed event
- POST /api/v1/events/{event_id}/closure/reopen-approve : Dean/Principal approves event reopening
- POST /api/v1/events/{event_id}/archive                : System Admin archives closed event
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_any_role, require_role
from app.models.domain import User
from app.models.enums import EventStatus, UserRole
from app.schemas.closeout import (
    EventCloseoutActionResponse,
    EventCloseoutCertifyRequest,
    EventCloseoutRejectRequest,
    EventCloseoutRequestCreate,
    EventClosureDetailResponse,
    EventClosureResponse,
    EventClosureRevisionResponse,
    EventReopenApproveRequest,
    EventReopenRequestCreate,
)
from app.services.closeout_service import CloseoutService

router = APIRouter()


def _get_client_meta(request: Request) -> tuple[str | None, str | None]:
    """Extract client IP address and User-Agent header from incoming request."""
    ip_address = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None
    return ip_address, user_agent


# ---------------------------------------------------------------------------
# 1. Inspect Closeout State & Eligibility
# ---------------------------------------------------------------------------


@router.get(
    "/{event_id}/closure",
    response_model=EventClosureDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get event closeout state & eligibility",
    description=(
        "Retrieve comprehensive closeout state, eligibility evaluation, active closure "
        "record, certification metadata, reopening revisions, and request history. "
        "Authorized to club members, assigned advisor, and campus executives."
    ),
    responses={
        401: {"description": "Unauthenticated access"},
        403: {"description": "Forbidden - unauthorized viewer"},
        404: {"description": "Event not found"},
    },
)
async def get_event_closure(
    event_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> EventClosureDetailResponse:
    """Retrieve closeout details and eligibility for an event."""
    details = await CloseoutService.get_closure_details(
        db=db,
        event_id=event_id,
        actor=current_user,
    )
    return EventClosureDetailResponse(**details)


# ---------------------------------------------------------------------------
# 2. Club Secretary Requests Closeout
# ---------------------------------------------------------------------------


@router.post(
    "/{event_id}/closure/request",
    response_model=EventCloseoutActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Request event closeout",
    description=(
        "Active Club Secretary initiates institutional closeout for a COMPLETED event. "
        "Re-evaluates financial and operational eligibility inside a locked transaction. "
        "Idempotent: returns existing state if already CLOSURE_REQUESTED."
    ),
    responses={
        401: {"description": "Unauthenticated"},
        403: {"description": "Forbidden - requires active secretary of owning club"},
        404: {"description": "Event not found"},
        409: {"description": "Conflict - event not in COMPLETED status"},
        422: {"description": "Unprocessable Entity - eligibility gates failed"},
    },
)
async def request_event_closeout(
    event_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.CLUB_SECRETARY))],
    request: Request,
    body: EventCloseoutRequestCreate | None = None,
) -> EventCloseoutActionResponse:
    """Submit closeout request for institutional review."""
    ip, ua = _get_client_meta(request)
    remarks = body.remarks if body else None
    result = await CloseoutService.request_closeout(
        db=db,
        event_id=event_id,
        actor=current_user,
        remarks=remarks,
        ip_address=ip,
        user_agent=ua,
    )
    return EventCloseoutActionResponse(
        event_id=uuid.UUID(result["event_id"]),
        status=EventStatus(result["status"]),
        message=result["message"],
    )


# ---------------------------------------------------------------------------
# 3. Certify Closeout
# ---------------------------------------------------------------------------


@router.post(
    "/{event_id}/closure/certify",
    response_model=EventClosureResponse,
    status_code=status.HTTP_200_OK,
    summary="Certify event closeout",
    description=(
        "Dean of Student Affairs, Principal, or authorized Faculty Advisor (when "
        "delegation is enabled) certifies event closeout. Explicit venue_cleared=True "
        "attestation is mandatory. Computes a deterministic 64-character SHA-256 "
        "certificate manifest hash and seals the event."
    ),
    responses={
        401: {"description": "Unauthenticated"},
        403: {"description": "Forbidden - unauthorized certifier or delegation disabled"},
        404: {"description": "Event not found"},
        409: {"description": "Conflict - event not in CLOSURE_REQUESTED status"},
        422: {"description": "Unprocessable Entity - venue_cleared=false or eligibility changed"},
    },
)
async def certify_event_closeout(
    event_id: uuid.UUID,
    body: EventCloseoutCertifyRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(
            require_any_role(
                UserRole.DEAN_STUDENT_AFFAIRS,
                UserRole.PRINCIPAL,
                UserRole.FACULTY_ADVISOR,
            )
        ),
    ],
    request: Request,
) -> EventClosureResponse:
    """Formally certify and seal event closeout."""
    ip, ua = _get_client_meta(request)
    closure = await CloseoutService.certify_closeout(
        db=db,
        event_id=event_id,
        actor=current_user,
        closure_notes=body.closure_notes,
        venue_cleared=body.venue_cleared,
        ip_address=ip,
        user_agent=ua,
    )
    return EventClosureResponse.model_validate(closure)


# ---------------------------------------------------------------------------
# 4. Reject Closeout Request
# ---------------------------------------------------------------------------


@router.post(
    "/{event_id}/closure/reject",
    response_model=EventCloseoutActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject event closeout request",
    description=(
        "Institutional authority rejects closeout request with a mandatory non-empty reason. "
        "Returns the event to COMPLETED status and preserves the rejection audit trail."
    ),
    responses={
        401: {"description": "Unauthenticated"},
        403: {"description": "Forbidden - unauthorized certifier"},
        404: {"description": "Event not found"},
        409: {"description": "Conflict - event not in CLOSURE_REQUESTED status"},
        422: {"description": "Unprocessable Entity - missing rejection reason"},
    },
)
async def reject_event_closeout(
    event_id: uuid.UUID,
    body: EventCloseoutRejectRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(
            require_any_role(
                UserRole.DEAN_STUDENT_AFFAIRS,
                UserRole.PRINCIPAL,
                UserRole.FACULTY_ADVISOR,
            )
        ),
    ],
    request: Request,
) -> EventCloseoutActionResponse:
    """Reject closeout request and return event to COMPLETED."""
    ip, ua = _get_client_meta(request)
    event = await CloseoutService.reject_closeout(
        db=db,
        event_id=event_id,
        actor=current_user,
        reason=body.reason,
        ip_address=ip,
        user_agent=ua,
    )
    return EventCloseoutActionResponse(
        event_id=event.id,
        status=event.status,
        message="Event closeout request rejected; returned to COMPLETED status.",
    )


# ---------------------------------------------------------------------------
# 5. Petition Reopening (Stage 1)
# ---------------------------------------------------------------------------


@router.post(
    "/{event_id}/closure/reopen-request",
    response_model=EventCloseoutActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Petition to reopen closed event",
    description=(
        "Stage 1 of reopening: Active Club Secretary, assigned Faculty Advisor, or Finance "
        "Officer submits a formal petition with mandatory reason. Event remains in CLOSED "
        "status until approved by Dean or Principal."
    ),
    responses={
        401: {"description": "Unauthenticated"},
        403: {"description": "Forbidden - unauthorized petitioner or System Admin"},
        404: {"description": "Event not found"},
        409: {"description": "Conflict - event not in CLOSED status"},
        422: {"description": "Unprocessable Entity - validation error"},
    },
)
async def request_event_reopen(
    event_id: uuid.UUID,
    body: EventReopenRequestCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(
            require_any_role(
                UserRole.CLUB_SECRETARY,
                UserRole.FACULTY_ADVISOR,
                UserRole.FINANCE_OFFICER,
            )
        ),
    ],
    request: Request,
) -> EventCloseoutActionResponse:
    """Submit reopening petition for executive consideration."""
    ip, ua = _get_client_meta(request)
    result = await CloseoutService.request_reopen(
        db=db,
        event_id=event_id,
        actor=current_user,
        reason=body.reason,
        ip_address=ip,
        user_agent=ua,
    )
    return EventCloseoutActionResponse(
        event_id=uuid.UUID(result["event_id"]),
        status=EventStatus(result["status"]),
        message=result["message"],
    )


# ---------------------------------------------------------------------------
# 6. Approve Reopening (Stage 2)
# ---------------------------------------------------------------------------


@router.post(
    "/{event_id}/closure/reopen-approve",
    response_model=EventClosureRevisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve event reopening",
    description=(
        "Stage 2 of reopening: Dean of Student Affairs or Principal approves reopening with "
        "mandatory reason. Captures immutable EventClosureRevision snapshot, unseals the "
        "financial settlement (SETTLED -> REOPENED), and transitions Event to COMPLETED."
    ),
    responses={
        401: {"description": "Unauthenticated"},
        403: {"description": "Forbidden - requires Dean or Principal role"},
        404: {"description": "Event not found"},
        409: {"description": "Conflict - event not in CLOSED status"},
        422: {"description": "Unprocessable Entity - validation error"},
    },
)
async def approve_event_reopen(
    event_id: uuid.UUID,
    body: EventReopenApproveRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(
            require_any_role(
                UserRole.DEAN_STUDENT_AFFAIRS,
                UserRole.PRINCIPAL,
            )
        ),
    ],
    request: Request,
) -> EventClosureRevisionResponse:
    """Statutory executive approval to reopen a closed event."""
    ip, ua = _get_client_meta(request)
    revision = await CloseoutService.approve_reopen(
        db=db,
        event_id=event_id,
        actor=current_user,
        reason=body.reason,
        ip_address=ip,
        user_agent=ua,
    )
    return EventClosureRevisionResponse.model_validate(revision)


# ---------------------------------------------------------------------------
# 7. System Admin Archives Event
# ---------------------------------------------------------------------------


@router.post(
    "/{event_id}/archive",
    response_model=EventCloseoutActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive closed event",
    description=(
        "System Administrator archives a CLOSED event into historical retention. "
        "Strictly restricted to SYSTEM_ADMIN. Logical state transition only "
        "(no physical deletion). Idempotent: returns existing state if already ARCHIVED."
    ),
    responses={
        401: {"description": "Unauthenticated"},
        403: {"description": "Forbidden - strictly requires SYSTEM_ADMIN"},
        404: {"description": "Event not found"},
        409: {"description": "Conflict - event not in CLOSED status"},
        422: {"description": "Unprocessable Entity - closeout record missing"},
    },
)
async def archive_event(
    event_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.SYSTEM_ADMIN))],
    request: Request,
) -> EventCloseoutActionResponse:
    """Archive closed event into permanent retention."""
    ip, ua = _get_client_meta(request)
    event = await CloseoutService.archive_event(
        db=db,
        event_id=event_id,
        actor=current_user,
        ip_address=ip,
        user_agent=ua,
    )
    return EventCloseoutActionResponse(
        event_id=event.id,
        status=event.status,
        message="Event successfully archived.",
    )
