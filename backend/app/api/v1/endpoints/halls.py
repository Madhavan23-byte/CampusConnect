"""
CampusConnect Backend — Hall / Venue Inventory API Endpoints

Routes:
- GET    /api/v1/halls                  : List halls with pagination & active filter
- POST   /api/v1/halls                  : Create a new campus hall (HALL_CREATE / SYSTEM_ADMIN)
- GET    /api/v1/halls/{id}             : Retrieve hall details
- GET    /api/v1/halls/{id}/availability: Check bookings & availability for a date/time
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.core.permissions import Permission
from app.models.domain import User
from app.schemas.venue import (
    HallAvailabilityResponse,
    HallCreate,
    HallResponse,
)
from app.services.venue_service import VenueService

router = APIRouter()


@router.get(
    "",
    response_model=list[HallResponse],
    summary="List campus halls",
    description="Retrieve campus venues/halls with optional active status filter and pagination.",
)
async def list_halls(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_VIEW_ALL))],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    is_active: bool | None = Query(True),
) -> list[HallResponse]:
    halls = await VenueService.list_halls(db, skip=skip, limit=limit, is_active=is_active)
    return [HallResponse.model_validate(h) for h in halls]


@router.post(
    "",
    response_model=HallResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new campus hall",
    description="Register a new hall facility. Restricted to SYSTEM_ADMIN.",
)
async def create_hall(
    hall_in: HallCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_permission(Permission.HALL_CREATE))],
) -> HallResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    hall = await VenueService.create_hall(
        db=db,
        hall_in=hall_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return HallResponse.model_validate(hall)


@router.get(
    "/{id}",
    response_model=HallResponse,
    summary="Get hall details",
    description="Retrieve detailed information for a specific campus hall.",
)
async def get_hall(
    id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_VIEW_ALL))],
) -> HallResponse:
    hall = await VenueService.get_hall(db, id)
    return HallResponse.model_validate(hall)


@router.get(
    "/{id}/availability",
    response_model=HallAvailabilityResponse,
    summary="Check hall availability",
    description="Inspect confirmed bookings and check slot availability for a specified date.",
)
async def check_hall_availability(
    id: uuid.UUID,
    date: datetime,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_permission(Permission.EVENT_VIEW_ALL))],
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
) -> HallAvailabilityResponse:
    return await VenueService.check_hall_availability(
        db=db,
        hall_id=id,
        target_date=date,
        start_time=start_time,
        end_time=end_time,
    )
