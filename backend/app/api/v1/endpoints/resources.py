"""
CampusConnect - Resource Requests Endpoints
POST   /api/v1/events/{id}/resources
GET    /api/v1/events/{id}/resources
DELETE /api/v1/events/{id}/resources/{rid}
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    WorkflowStateError,
)
from app.models.domain import ClubMember, EventRequest, ResourceRequest, User
from app.models.enums import (
    ClubMemberRole,
    EventRequestStatus,
    ResourceRequestStatus,
    UserRole,
)
from app.schemas.resource import ResourceRequestCreate, ResourceRequestResponse

router = APIRouter()


async def _verify_event_edit_permission(db: AsyncSession, event: EventRequest, actor: User) -> None:
    if event.status not in (EventRequestStatus.DRAFT, EventRequestStatus.REVISION_REQUIRED):
        st = event.status.value if hasattr(event.status, "value") else str(event.status)
        raise WorkflowStateError(
            f"Resource requests can only be modified in DRAFT or REVISION_REQUIRED status. "
            f"Current status is '{st}'."
        )

    if actor.role == UserRole.SYSTEM_ADMIN:
        return
    if event.submitted_by == actor.id:
        return

    member = await db.scalar(
        select(ClubMember).where(
            ClubMember.club_id == event.club_id,
            ClubMember.user_id == actor.id,
            ClubMember.member_role == ClubMemberRole.SECRETARY,
            ClubMember.is_active.is_(True),
        )
    )
    if not member:
        raise ForbiddenError("Only the club secretary or submitter may modify resource requests.")


@router.post(
    "/{event_id}/resources",
    response_model=ResourceRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_resource_request(
    event_id: uuid.UUID,
    data: ResourceRequestCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ResourceRequestResponse:
    """Declare a resource/equipment requirement for an event proposal."""
    event = await db.scalar(select(EventRequest).where(EventRequest.id == event_id))
    if not event or event.deleted_at is not None:
        raise NotFoundError(f"Event request '{event_id}' not found.")

    await _verify_event_edit_permission(db, event, current_user)

    resource = ResourceRequest(
        id=uuid.uuid4(),
        event_request_id=event_id,
        resource_type=data.resource_type,
        quantity=data.quantity,
        notes=data.notes,
        status=ResourceRequestStatus.PENDING,
    )
    db.add(resource)
    await db.commit()
    await db.refresh(resource)
    return resource


@router.get("/{event_id}/resources", response_model=list[ResourceRequestResponse])
async def list_resource_requests(
    event_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[ResourceRequestResponse]:
    """List declared resource requests for an event proposal."""
    event = await db.scalar(select(EventRequest).where(EventRequest.id == event_id))
    if not event or event.deleted_at is not None:
        raise NotFoundError(f"Event request '{event_id}' not found.")

    stmt = (
        select(ResourceRequest)
        .where(ResourceRequest.event_request_id == event_id)
        .order_by(ResourceRequest.created_at.asc())
    )
    result = await db.scalars(stmt)
    return list(result.all())


@router.delete("/{event_id}/resources/{resource_id}")
async def delete_resource_request(
    event_id: uuid.UUID,
    resource_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Delete a declared resource request from an event proposal."""
    event = await db.scalar(select(EventRequest).where(EventRequest.id == event_id))
    if not event or event.deleted_at is not None:
        raise NotFoundError(f"Event request '{event_id}' not found.")

    await _verify_event_edit_permission(db, event, current_user)

    resource = await db.scalar(
        select(ResourceRequest).where(
            ResourceRequest.id == resource_id,
            ResourceRequest.event_request_id == event_id,
        )
    )
    if not resource:
        raise NotFoundError("Resource request not found.")

    await db.delete(resource)
    await db.commit()
    return {"message": "Resource request removed successfully"}
