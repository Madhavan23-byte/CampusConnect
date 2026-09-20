"""
CampusConnect - Notifications Endpoints
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.domain import User
from app.schemas.notification import (
    NotificationBatchReadResponse,
    NotificationCountResponse,
    NotificationResponse,
)
from app.services.notification_service import NotificationService

router = APIRouter()


@router.get("", response_model=list[NotificationResponse])
async def get_my_notifications(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    unread_only: bool = Query(default=False, description="Filter for unread notifications only"),
    limit: int = Query(default=50, ge=1, le=100, description="Page limit"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
) -> list[NotificationResponse]:
    """List notifications for the current authenticated user with pagination and unread filter."""
    return await NotificationService.get_notifications(
        db=db,
        recipient_id=current_user.id,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )


@router.get("/count", response_model=NotificationCountResponse)
async def get_my_notification_counts(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> NotificationCountResponse:
    """Get unread and total notification counts for the authenticated user."""
    counts = await NotificationService.get_notification_counts(
        db=db,
        recipient_id=current_user.id,
    )
    return NotificationCountResponse(**counts)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> NotificationResponse:
    """Mark a specific notification as read. Enforces strict recipient ownership."""
    return await NotificationService.mark_as_read(
        db=db,
        notification_id=notification_id,
        recipient_id=current_user.id,
    )


@router.patch("/read-all", response_model=NotificationBatchReadResponse)
async def mark_all_notifications_read(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> NotificationBatchReadResponse:
    """Mark all unread notifications of current user as read."""
    updated = await NotificationService.mark_all_as_read(
        db=db,
        recipient_id=current_user.id,
    )
    return NotificationBatchReadResponse(updated_count=updated)
