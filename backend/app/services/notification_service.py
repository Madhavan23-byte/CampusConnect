"""
CampusConnect - Notification Service
Manages persistent in-app notifications with strict recipient isolation.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.domain import Notification
from app.models.enums import NotificationType


class NotificationService:
    @classmethod
    async def create_notification(
        cls,
        db: AsyncSession,
        recipient_id: uuid.UUID,
        notification_type: NotificationType | str,
        title: str,
        message: str,
        event_request_id: uuid.UUID | None = None,
    ) -> Notification:
        """
        Create a persistent notification for a user.
        Participates in the caller's active database transaction.
        """
        type_str = (
            notification_type.value
            if hasattr(notification_type, "value")
            else str(notification_type)
        )
        notification = Notification(
            id=uuid.uuid4(),
            recipient_id=recipient_id,
            event_request_id=event_request_id,
            notification_type=type_str,
            title=title,
            message=message,
            is_read=False,
            read_at=None,
        )
        db.add(notification)
        await db.flush()
        return notification

    @classmethod
    async def get_notifications(
        cls,
        db: AsyncSession,
        recipient_id: uuid.UUID,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Notification]:
        """Retrieve notifications strictly isolated to the recipient."""
        stmt = (
            select(Notification)
            .where(Notification.recipient_id == recipient_id)
            .order_by(Notification.created_at.desc())
        )
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        stmt = stmt.limit(limit).offset(offset)
        result = await db.scalars(stmt)
        return list(result.all())

    @classmethod
    async def get_notification_counts(
        cls,
        db: AsyncSession,
        recipient_id: uuid.UUID,
    ) -> dict[str, int]:
        """Get total and unread counts for the recipient."""
        unread_stmt = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.recipient_id == recipient_id,
                Notification.is_read.is_(False),
            )
        )
        total_stmt = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.recipient_id == recipient_id)
        )
        unread_count = await db.scalar(unread_stmt) or 0
        total_count = await db.scalar(total_stmt) or 0
        return {"unread_count": unread_count, "total_count": total_count}

    @classmethod
    async def mark_as_read(
        cls,
        db: AsyncSession,
        notification_id: uuid.UUID,
        recipient_id: uuid.UUID,
    ) -> Notification:
        """Mark a single notification as read, enforcing strict recipient isolation."""
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_id == recipient_id,
        )
        notif = await db.scalar(stmt)
        if not notif:
            raise NotFoundError("Notification not found.")
        if not notif.is_read:
            notif.is_read = True
            notif.read_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(notif)
        return notif

    @classmethod
    async def mark_all_as_read(
        cls,
        db: AsyncSession,
        recipient_id: uuid.UUID,
    ) -> int:
        """Mark all unread notifications of recipient as read."""
        stmt = (
            update(Notification)
            .where(
                Notification.recipient_id == recipient_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True, read_at=datetime.now(UTC))
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount or 0
