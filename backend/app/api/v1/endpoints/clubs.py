"""
CampusConnect Backend — Club Governance API Endpoints

Routes:
- GET    /api/v1/clubs                    : List active clubs
- GET    /api/v1/clubs/{id}               : Retrieve specific club details
- POST   /api/v1/clubs                    : Register new club charter (CLUB_CREATE)
- PATCH  /api/v1/clubs/{id}               : Update club profile (CLUB_UPDATE + ownership)
- GET    /api/v1/clubs/{id}/members       : View club roster (CLUB_VIEW_ANY)
- POST   /api/v1/clubs/{id}/members       : Enroll member in club (CLUB_MANAGE_MEMBERS + ownership)
- PATCH  /api/v1/clubs/{id}/members/{uid} : Update member role (CLUB_MANAGE_MEMBERS + ownership)
- DELETE /api/v1/clubs/{id}/members/{uid} : Remove/deactivate member (CLUB_MANAGE_MEMBERS + ownership)
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.core.permissions import Permission
from app.models.domain import User
from app.schemas.club import (
    ClubCreate,
    ClubMemberAdd,
    ClubMemberResponse,
    ClubMemberUpdate,
    ClubResponse,
    ClubUpdate,
)
from app.services.club_service import ClubService, to_club_response, to_member_response

router = APIRouter()


@router.get(
    "",
    response_model=list[ClubResponse],
    summary="List active clubs",
    description="Retrieve all registered, non-deleted college clubs with optional status filter and pagination.",
)
async def list_clubs(
    current_user: Annotated[User, Depends(require_permission(Permission.CLUB_VIEW_ANY))],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0, description="Offset for pagination"),
    limit: int = Query(default=50, ge=1, le=100, description="Max records to return"),
    is_active: bool | None = Query(default=None, description="Filter by active status"),
) -> list[ClubResponse]:
    """Return paginated list of clubs formatted safely."""
    clubs = await ClubService.list_clubs(db=db, skip=skip, limit=limit, is_active=is_active)
    return [to_club_response(c) for c in clubs]


@router.get(
    "/{id}",
    response_model=ClubResponse,
    summary="Get club details",
    description="Retrieve full public profile and faculty advisor information for a specific club.",
)
async def get_club(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(require_permission(Permission.CLUB_VIEW_ANY))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClubResponse:
    """Return specific club details by primary key."""
    club = await ClubService.get_club(db=db, club_id=id)
    return to_club_response(club)


@router.post(
    "",
    response_model=ClubResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new club",
    description="Charter a new student organization or official club. Requires CLUB_CREATE permission.",
)
async def create_club(
    club_in: ClubCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.CLUB_CREATE))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClubResponse:
    """Create a new club charter, assign faculty advisor, and record audit log."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    club = await ClubService.create_club(
        db=db,
        club_in=club_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_club_response(club)


@router.patch(
    "/{id}",
    response_model=ClubResponse,
    summary="Update club profile",
    description="Modify club details. Requires CLUB_UPDATE permission AND club secretary ownership or SYSTEM_ADMIN.",
)
async def update_club(
    id: uuid.UUID,
    club_in: ClubUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.CLUB_UPDATE))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClubResponse:
    """Update club metadata and audit the transition."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    club = await ClubService.update_club(
        db=db,
        club_id=id,
        club_in=club_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_club_response(club)


@router.get(
    "/{id}/members",
    response_model=list[ClubMemberResponse],
    summary="List club members",
    description="Retrieve roster of enrolled members for a specific club.",
)
async def list_members(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(require_permission(Permission.CLUB_VIEW_ANY))],
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = Query(default=False, description="Include deactivated members"),
) -> list[ClubMemberResponse]:
    """Retrieve roster of club members."""
    members = await ClubService.list_members(db=db, club_id=id, include_inactive=include_inactive)
    return [to_member_response(m) for m in members]


@router.post(
    "/{id}/members",
    response_model=ClubMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add member to club",
    description="Enroll a user in the club roster. Requires CLUB_MANAGE_MEMBERS permission AND club ownership.",
)
async def add_member(
    id: uuid.UUID,
    member_in: ClubMemberAdd,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.CLUB_MANAGE_MEMBERS))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClubMemberResponse:
    """Enroll a user in club membership."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    member = await ClubService.add_member(
        db=db,
        club_id=id,
        member_in=member_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_member_response(member)


@router.patch(
    "/{id}/members/{user_id}",
    response_model=ClubMemberResponse,
    summary="Update member role or status",
    description="Change a member's role or active status. Requires CLUB_MANAGE_MEMBERS permission AND club ownership.",
)
async def update_member(
    id: uuid.UUID,
    user_id: uuid.UUID,
    member_in: ClubMemberUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.CLUB_MANAGE_MEMBERS))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClubMemberResponse:
    """Update a member's role or status."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    member = await ClubService.update_member(
        db=db,
        club_id=id,
        target_user_id=user_id,
        member_in=member_in,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_member_response(member)


@router.delete(
    "/{id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove club member",
    description="Soft-deactivate a user from the club roster. Requires CLUB_MANAGE_MEMBERS permission AND club ownership.",
)
async def remove_member(
    id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(require_permission(Permission.CLUB_MANAGE_MEMBERS))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Soft-deactivate a club member and record audit log."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    await ClubService.remove_member(
        db=db,
        club_id=id,
        target_user_id=user_id,
        actor=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
