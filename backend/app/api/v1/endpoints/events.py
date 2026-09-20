"""
CampusConnect Backend — Event Proposal API Endpoints

Routes:
- POST   /api/v1/events            : Create new event proposal draft (EVENT_PROPOSE)
- GET    /api/v1/events            : List proposals with filters & pagination (EVENT_VIEW_ALL)
- GET    /api/v1/events/{id}       : Retrieve proposal details (EVENT_VIEW_ALL)
- PATCH  /api/v1/events/{id}       : Modify event proposal draft (EVENT_EDIT_DRAFT)
- POST   /api/v1/events/{id}/submit : Submit proposal into approval workflow (EVENT_PROPOSE)
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.core.permissions import Permission
from app.models.domain import User
from app.models.enums import EventRequestStatus
from app.schemas.budget import (
    BudgetLineItemCreate,
    BudgetLineItemResponse,
    BudgetLineItemUpdate,
    BudgetProposalCreate,
    BudgetProposalResponse,
    BudgetProposalUpdate,
    FinanceVerificationRequest,
)
from app.schemas.event import (
    EventRequestCreate,
    EventRequestResponse,
    EventRequestSubmit,
    EventRequestUpdate,
)
from app.schemas.venue import VenueRequestCreate, VenueRequestResponse, VenueRequestUpdate
from app.schemas.workflow import WorkflowInstanceResponse
from app.services.budget_service import (
    BudgetService,
    to_budget_response,
    to_line_item_response,
)
from app.services.event_service import EventService, to_event_response
from app.services.venue_service import VenueService, to_venue_response
from app.services.workflow_service import WorkflowService

router = APIRouter()


@router.post(
    "",
    response_model=EventRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create event proposal draft",
    description="Initialize a new event proposal draft for an authorized club. Requires EVENT_PROPOSE permission and club ownership.",
)
async def create_event_draft(
    event_in: EventRequestCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_PROPOSE))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EventRequestResponse:
    """Create an event proposal draft bound to an active club charter."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    event = await EventService.create_draft(
        db=db,
        event_in=event_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_event_response(event)


@router.get(
    "",
    response_model=list[EventRequestResponse],
    summary="List event proposals",
    description="Retrieve event proposals with optional filtering by club ID or status, and pagination.",
)
async def list_events(
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_VIEW_ALL))],
    db: Annotated[AsyncSession, Depends(get_db)],
    club_id: uuid.UUID | None = Query(default=None, description="Filter by club ID"),
    status: EventRequestStatus | None = Query(
        default=None, description="Filter by proposal status"
    ),
    skip: int = Query(default=0, ge=0, description="Offset for pagination"),
    limit: int = Query(default=50, ge=1, le=100, description="Max records to return"),
) -> list[EventRequestResponse]:
    """List event proposals safely without leaking sensitive information."""
    events = await EventService.list_events(
        db=db, club_id=club_id, status=status, skip=skip, limit=limit, actor=current_user
    )
    return [to_event_response(e) for e in events]


@router.get(
    "/{id}",
    response_model=EventRequestResponse,
    summary="Get event proposal details",
    description="Retrieve full details for a specific event proposal.",
)
async def get_event(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_VIEW_ALL))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EventRequestResponse:
    """Get event proposal by primary key ID."""
    event = await EventService.get_event(db=db, event_id=id, actor=current_user)
    return to_event_response(event)


@router.patch(
    "/{id}",
    response_model=EventRequestResponse,
    summary="Edit event proposal draft",
    description="Modify draft proposal fields. Only allowed while proposal is in DRAFT or REVISION_REQUIRED status. Requires EVENT_EDIT_DRAFT permission.",
)
async def update_event_draft(
    id: uuid.UUID,
    event_in: EventRequestUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_EDIT_DRAFT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EventRequestResponse:
    """Update event proposal draft and increment version lock."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    event = await EventService.update_draft(
        db=db,
        event_id=id,
        event_in=event_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_event_response(event)


@router.post(
    "/{id}/submit",
    response_model=EventRequestResponse,
    summary="Submit event proposal",
    description="Formally submit proposal into the institutional review workflow. Freezes an immutable version snapshot. Requires EVENT_PROPOSE permission.",
)
async def submit_event_proposal(
    id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_PROPOSE))],
    db: Annotated[AsyncSession, Depends(get_db)],
    submit_in: EventRequestSubmit | None = None,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> EventRequestResponse:
    """Submit proposal, create version snapshot, and advance lifecycle status."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    event = await EventService.submit_proposal(
        db=db,
        event_id=id,
        submit_in=submit_in,
        actor=current_user,
        idempotency_key=x_idempotency_key,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_event_response(event)


@router.post(
    "/{id}/venue",
    response_model=VenueRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach venue requirement to event proposal",
    description="Reserve hall requirement for an event proposal draft. Requires EVENT_PROPOSE permission and club ownership.",
)
async def create_event_venue(
    id: uuid.UUID,
    venue_in: VenueRequestCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_PROPOSE))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VenueRequestResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    vr = await VenueService.create_venue_request(
        db=db,
        event_id=id,
        venue_in=venue_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_venue_response(vr)


@router.get(
    "/{id}/venue",
    response_model=VenueRequestResponse,
    summary="Get event venue requirement",
    description="Retrieve the venue requirement details attached to an event proposal.",
)
async def get_event_venue(
    id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_VIEW_ALL))],
) -> VenueRequestResponse:
    vr = await VenueService.get_venue_request(db=db, event_id=id)
    return to_venue_response(vr)


@router.patch(
    "/{id}/venue",
    response_model=VenueRequestResponse,
    summary="Update event venue requirement",
    description="Modify hall, timing, or facility requirements for an event proposal in DRAFT or REVISION_REQUIRED state.",
)
async def update_event_venue(
    id: uuid.UUID,
    venue_in: VenueRequestUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_EDIT_DRAFT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VenueRequestResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    vr = await VenueService.update_venue_request(
        db=db,
        event_id=id,
        venue_in=venue_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_venue_response(vr)


@router.delete(
    "/{id}/venue",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete event venue requirement",
    description="Remove the venue requirement from an event proposal draft.",
)
async def delete_event_venue(
    id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_EDIT_DRAFT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    await VenueService.delete_venue_request(
        db=db,
        event_id=id,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# Budget Proposal Endpoints
# ---------------------------------------------------------------------------
@router.post(
    "/{id}/budget",
    response_model=BudgetProposalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create event budget proposal",
    description="Attach an itemized budget proposal to an event proposal draft. Requires EVENT_PROPOSE permission and club ownership.",
)
async def create_event_budget(
    id: uuid.UUID,
    budget_in: BudgetProposalCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_PROPOSE))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BudgetProposalResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    bp = await BudgetService.create_budget_proposal(
        db=db,
        event_id=id,
        budget_in=budget_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_budget_response(bp)


@router.get(
    "/{id}/budget",
    response_model=BudgetProposalResponse,
    summary="Get event budget proposal",
    description="Retrieve the budget proposal and all itemized line items attached to an event proposal.",
)
async def get_event_budget(
    id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_VIEW_ALL))],
) -> BudgetProposalResponse:
    bp = await BudgetService.get_budget_proposal(db=db, event_id=id)
    return to_budget_response(bp)


@router.patch(
    "/{id}/budget",
    response_model=BudgetProposalResponse,
    summary="Update event budget proposal header",
    description="Modify income, contribution, or notes for a budget proposal in DRAFT or REVISION_REQUIRED status.",
)
async def update_event_budget(
    id: uuid.UUID,
    budget_in: BudgetProposalUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_EDIT_DRAFT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BudgetProposalResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    bp = await BudgetService.update_budget_proposal(
        db=db,
        event_id=id,
        budget_in=budget_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_budget_response(bp)


@router.delete(
    "/{id}/budget",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete event budget proposal",
    description="Remove the budget proposal and all line items from a draft event proposal.",
)
async def delete_event_budget(
    id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_EDIT_DRAFT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    await BudgetService.delete_budget_proposal(
        db=db,
        event_id=id,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.post(
    "/{id}/budget/items",
    response_model=BudgetLineItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add budget line item",
    description="Add an itemized expenditure item to a draft budget proposal. Total expenditure is automatically recalculated on the server.",
)
async def add_budget_line_item(
    id: uuid.UUID,
    item_in: BudgetLineItemCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_EDIT_DRAFT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BudgetLineItemResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    item = await BudgetService.add_line_item(
        db=db,
        event_id=id,
        item_in=item_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_line_item_response(item)


@router.patch(
    "/{id}/budget/items/{item_id}",
    response_model=BudgetLineItemResponse,
    summary="Update budget line item",
    description="Modify description, category, or amount of an itemized line item in draft status. Server recalculates total.",
)
async def update_budget_line_item(
    id: uuid.UUID,
    item_id: uuid.UUID,
    item_in: BudgetLineItemUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_EDIT_DRAFT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BudgetLineItemResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    item = await BudgetService.update_line_item(
        db=db,
        event_id=id,
        item_id=item_id,
        item_in=item_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_line_item_response(item)


@router.delete(
    "/{id}/budget/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete budget line item",
    description="Remove an itemized expenditure line item from a draft budget proposal.",
)
async def delete_budget_line_item(
    id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_EDIT_DRAFT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    await BudgetService.delete_line_item(
        db=db,
        event_id=id,
        item_id=item_id,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.post(
    "/{id}/budget/verify",
    response_model=BudgetProposalResponse,
    summary="Verify event budget proposal",
    description="Institutional pre-audit clearance by Finance Officer or Principal. Marks status as VERIFIED or QUERIED with audit trail.",
)
async def verify_event_budget(
    id: uuid.UUID,
    verification_in: FinanceVerificationRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.BUDGET_APPROVE))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BudgetProposalResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    bp = await BudgetService.verify_budget(
        db=db,
        event_id=id,
        verification_in=verification_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_budget_response(bp)


@router.get(
    "/{id}/workflow",
    response_model=WorkflowInstanceResponse,
    summary="Get event workflow chain",
    description="Retrieve the multi-stage institutional approval workflow chain and current step status for an event proposal.",
)
async def get_event_workflow(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_VIEW_ALL))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowInstanceResponse:
    return await WorkflowService.get_event_workflow(db=db, event_id=id)
