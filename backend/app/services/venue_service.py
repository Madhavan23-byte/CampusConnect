"""
CampusConnect Backend — Venue & Hall Reservation Service

Encapsulates all domain logic for:
1. Campus Hall inventory & availability inspection
2. Event proposal venue requirements (VenueRequest)
3. Lead-time policy enforcement (HALL_BOOKING_MIN_ADVANCE_DAYS)
4. Hall capacity vs expected audience validation
5. Physical occupancy interval validation (end_time > start_time)
6. Conflict pre-checking against confirmed hall bookings
7. Resource ownership enforcement via ClubService
8. Transactionally consistent audit logging (HALL_CREATED, HALL_BOOKED, HALL_RELEASED)
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.base import NO_VALUE

from app.core.config import get_settings
from app.core.exceptions import (
    AdvanceBookingViolationError,
    BadRequestError,
    ConflictError,
    HallConflictError,
    NotFoundError,
    WorkflowStateError,
)
from app.models.domain import (
    AuditLog,
    Club,
    EventRequest,
    Hall,
    HallBookingConfirmed,
    User,
    VenueRequest,
)
from app.models.enums import AuditAction, EventRequestStatus, UserRole, VenueRequestStatus
from app.schemas.venue import (
    HallAvailabilityResponse,
    HallAvailabilitySlot,
    HallCreate,
    HallResponse,
    VenueRequestCreate,
    VenueRequestResponse,
    VenueRequestUpdate,
)
from app.services.club_service import ClubService


def to_venue_response(vr: VenueRequest) -> VenueRequestResponse:
    """Format a VenueRequest model into a safe public VenueRequestResponse without triggering lazy loads."""
    insp = inspect(vr)

    hall_name = None
    hall_location = None
    hall_capacity = None
    if "hall" in insp.attrs:
        h = insp.attrs.hall.loaded_value
        if h is not NO_VALUE and h is not None:
            hall_name = h.name
            hall_location = h.location
            hall_capacity = h.capacity

    return VenueRequestResponse(
        id=vr.id,
        event_request_id=vr.event_request_id,
        hall_id=vr.hall_id,
        hall_name=hall_name,
        hall_location=hall_location,
        hall_capacity=hall_capacity,
        requested_date=vr.requested_date,
        start_time=vr.start_time,
        end_time=vr.end_time,
        expected_audience=vr.expected_audience,
        requires_stage=vr.requires_stage,
        requires_audio=vr.requires_audio,
        requires_lcd=vr.requires_lcd,
        requires_ac=vr.requires_ac,
        requires_projector=vr.requires_projector,
        additional_requirements=vr.additional_requirements,
        status=vr.status,
        reviewed_by=vr.reviewed_by,
        reviewed_at=vr.reviewed_at,
        rejection_reason=vr.rejection_reason,
        created_at=vr.created_at,
        updated_at=vr.updated_at,
    )


class VenueService:
    """Domain service managing halls, availability, and venue requests."""

    # ------------------------------------------------------------------
    # 1. Hall Inventory & Availability
    # ------------------------------------------------------------------

    @classmethod
    async def create_hall(
        cls,
        db: AsyncSession,
        hall_in: HallCreate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Hall:
        """Create a new campus hall or venue facility (restricted to SYSTEM_ADMIN)."""
        existing = await db.scalar(select(Hall).where(Hall.name == hall_in.name))
        if existing:
            raise ConflictError(f"A hall with name '{hall_in.name}' already exists.")

        hall_id = uuid.uuid4()
        hall = Hall(
            id=hall_id,
            name=hall_in.name,
            location=hall_in.location,
            capacity=hall_in.capacity,
            available_facilities=hall_in.available_facilities,
            notes=hall_in.notes,
            is_active=True,
        )
        db.add(hall)

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.HALL_CREATED,
                entity_type="hall",
                entity_id=str(hall_id),
                previous_state=None,
                new_state={"name": hall.name, "capacity": hall.capacity, "location": hall.location},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        try:
            await db.commit()
            await db.refresh(hall)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("Could not create hall due to database conflict.") from exc

        return hall

    @staticmethod
    async def get_hall(db: AsyncSession, hall_id: uuid.UUID) -> Hall:
        """Retrieve a hall by ID."""
        hall = await db.scalar(select(Hall).where(Hall.id == hall_id))
        if not hall:
            raise NotFoundError(f"Hall with ID '{hall_id}' was not found.")
        return hall

    @staticmethod
    async def list_halls(
        db: AsyncSession, skip: int = 0, limit: int = 50, is_active: bool | None = True
    ) -> list[Hall]:
        """List halls with optional active filter and pagination."""
        stmt = select(Hall)
        if is_active is not None:
            stmt = stmt.where(Hall.is_active.is_(is_active))
        stmt = stmt.order_by(Hall.name.asc()).offset(skip).limit(limit)
        result = await db.scalars(stmt)
        return list(result.all())

    @classmethod
    async def check_hall_availability(
        cls,
        db: AsyncSession,
        hall_id: uuid.UUID,
        target_date: datetime,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> HallAvailabilityResponse:
        """Inspect confirmed bookings for a hall on a target date."""
        hall = await cls.get_hall(db, hall_id)

        # Query all active confirmed bookings for this hall where booking_date matches
        stmt = select(HallBookingConfirmed).where(
            HallBookingConfirmed.hall_id == hall_id,
            HallBookingConfirmed.is_active.is_(True),
        )
        bookings = list((await db.scalars(stmt)).all())

        booked_slots = [
            HallAvailabilitySlot(start_time=b.start_time, end_time=b.end_time) for b in bookings
        ]

        is_available = True
        if start_time and end_time:
            # Check if requested slot overlaps with any confirmed booking: [s, e) && [b.s, b.e)
            for b in bookings:
                if b.start_time < end_time and b.end_time > start_time:
                    is_available = False
                    break

        return HallAvailabilityResponse(
            hall_id=hall.id,
            hall_name=hall.name,
            date=target_date,
            is_available=is_available,
            booked_slots=booked_slots,
        )

    # ------------------------------------------------------------------
    # 2. Event Proposal Venue Request Management
    # ------------------------------------------------------------------

    @classmethod
    async def create_venue_request(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        venue_in: VenueRequestCreate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> VenueRequest:
        """Attach a venue requirement to an event proposal draft."""
        # 1. Fetch EventRequest
        event_stmt = (
            select(EventRequest)
            .options(selectinload(EventRequest.club))
            .where(EventRequest.id == event_id, EventRequest.deleted_at.is_(None))
        )
        event = await db.scalar(event_stmt)
        if not event:
            raise NotFoundError(f"Event proposal with ID '{event_id}' was not found.")

        # 2. Enforce state machine: Only DRAFT or REVISION_REQUIRED can attach/modify venue
        if event.status not in (EventRequestStatus.DRAFT, EventRequestStatus.REVISION_REQUIRED):
            status_str = event.status.value if hasattr(event.status, "value") else str(event.status)
            raise WorkflowStateError(
                f"Cannot request venue for proposal in '{status_str}' status. "
                "Only proposals in DRAFT or REVISION_REQUIRED state can request venues."
            )

        # 3. Enforce club secretary ownership
        club = await ClubService.verify_club_ownership(
            db, event.club_id, actor, "request a venue for this event"
        )
        if not club.is_active:
            raise BadRequestError(
                f"Club '{club.name}' is currently inactive and cannot request venues."
            )

        # 4. Check target hall
        hall = await cls.get_hall(db, venue_in.hall_id)
        if not hall.is_active:
            raise BadRequestError(f"Hall '{hall.name}' is currently inactive and cannot be booked.")

        # 5. Validate capacity vs expected audience/attendees
        audience = venue_in.expected_audience or event.expected_attendees
        if audience and audience > hall.capacity:
            raise BadRequestError(
                f"Expected audience ({audience}) exceeds hall capacity ({hall.capacity})."
            )

        # 6. Validate lead time (configurable advance booking notice)
        settings = get_settings()
        now_utc = datetime.now(timezone.utc)
        if (venue_in.start_time - now_utc).total_seconds() < 0:
            raise BadRequestError("Cannot request venue booking in the past.")

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        if actor_role_str != UserRole.SYSTEM_ADMIN.value:
            advance_days = (venue_in.start_time - now_utc).total_seconds() / 86400.0
            if advance_days < settings.HALL_BOOKING_MIN_ADVANCE_DAYS:
                raise AdvanceBookingViolationError(
                    f"Hall bookings must be requested at least {settings.HALL_BOOKING_MIN_ADVANCE_DAYS} days in advance."
                )

        # 7. Check 1-to-1 constraint: One venue request per event request
        existing_vr = await db.scalar(
            select(VenueRequest).where(VenueRequest.event_request_id == event_id)
        )
        if existing_vr:
            raise ConflictError(
                "A venue request already exists for this event proposal. Use PATCH to update it."
            )

        # 8. Friendly pre-check: Check if hall has an active confirmed booking in that window
        overlap_booking = await db.scalar(
            select(HallBookingConfirmed).where(
                HallBookingConfirmed.hall_id == venue_in.hall_id,
                HallBookingConfirmed.is_active.is_(True),
                HallBookingConfirmed.start_time < venue_in.end_time,
                HallBookingConfirmed.end_time > venue_in.start_time,
            )
        )
        if overlap_booking:
            raise HallConflictError(
                f"Hall '{hall.name}' is already confirmed for another booking during the requested time slot."
            )

        # 9. Create VenueRequest
        vr_id = uuid.uuid4()
        vr = VenueRequest(
            id=vr_id,
            event_request_id=event_id,
            hall_id=venue_in.hall_id,
            requested_date=venue_in.requested_date,
            start_time=venue_in.start_time,
            end_time=venue_in.end_time,
            expected_audience=venue_in.expected_audience,
            requires_stage=venue_in.requires_stage,
            requires_audio=venue_in.requires_audio,
            requires_lcd=venue_in.requires_lcd,
            requires_ac=venue_in.requires_ac,
            requires_projector=venue_in.requires_projector,
            additional_requirements=venue_in.additional_requirements,
            status=VenueRequestStatus.PENDING,
        )
        db.add(vr)

        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.HALL_BOOKED,
                entity_type="venue_request",
                entity_id=str(vr_id),
                previous_state=None,
                new_state={
                    "event_id": str(event_id),
                    "hall_id": str(hall.id),
                    "hall_name": hall.name,
                    "start_time": venue_in.start_time.isoformat(),
                    "end_time": venue_in.end_time.isoformat(),
                    "status": VenueRequestStatus.PENDING.value,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        try:
            await db.commit()
            await db.refresh(vr)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("Could not save venue request due to database conflict.") from exc

        loaded = await db.scalar(
            select(VenueRequest)
            .options(selectinload(VenueRequest.hall))
            .where(VenueRequest.id == vr.id)
        )
        return loaded or vr

    @staticmethod
    async def get_venue_request(db: AsyncSession, event_id: uuid.UUID) -> VenueRequest:
        """Retrieve the venue requirement attached to an event proposal."""
        stmt = (
            select(VenueRequest)
            .options(selectinload(VenueRequest.hall))
            .where(VenueRequest.event_request_id == event_id)
        )
        vr = await db.scalar(stmt)
        if not vr:
            raise NotFoundError(f"No venue request found for event proposal '{event_id}'.")
        return vr

    @classmethod
    async def update_venue_request(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        venue_in: VenueRequestUpdate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> VenueRequest:
        """Modify an event's venue requirement while in DRAFT or REVISION_REQUIRED status."""
        event_stmt = (
            select(EventRequest)
            .options(selectinload(EventRequest.club))
            .where(EventRequest.id == event_id, EventRequest.deleted_at.is_(None))
        )
        event = await db.scalar(event_stmt)
        if not event:
            raise NotFoundError(f"Event proposal with ID '{event_id}' was not found.")

        if event.status not in (EventRequestStatus.DRAFT, EventRequestStatus.REVISION_REQUIRED):
            status_str = event.status.value if hasattr(event.status, "value") else str(event.status)
            raise WorkflowStateError(
                f"Cannot update venue for proposal in '{status_str}' status. "
                "Only proposals in DRAFT or REVISION_REQUIRED state can modify venue requirements."
            )

        club = await ClubService.verify_club_ownership(
            db, event.club_id, actor, "modify venue requirements for this event"
        )
        if not club.is_active:
            raise BadRequestError(
                f"Club '{club.name}' is currently inactive and cannot modify venue requests."
            )

        vr = await cls.get_venue_request(db, event_id)

        target_hall_id = venue_in.hall_id or vr.hall_id
        target_start = venue_in.start_time or vr.start_time
        target_end = venue_in.end_time or vr.end_time

        if target_end <= target_start:
            raise BadRequestError("end_time must be strictly after start_time.")

        hall = await cls.get_hall(db, target_hall_id)
        if not hall.is_active:
            raise BadRequestError(f"Hall '{hall.name}' is currently inactive.")

        audience = venue_in.expected_audience or vr.expected_audience or event.expected_attendees
        if audience and audience > hall.capacity:
            raise BadRequestError(
                f"Expected audience ({audience}) exceeds hall capacity ({hall.capacity})."
            )

        # Check confirmed conflict if hall or time changed
        if venue_in.hall_id or venue_in.start_time or venue_in.end_time:
            overlap = await db.scalar(
                select(HallBookingConfirmed).where(
                    HallBookingConfirmed.hall_id == target_hall_id,
                    HallBookingConfirmed.is_active.is_(True),
                    HallBookingConfirmed.start_time < target_end,
                    HallBookingConfirmed.end_time > target_start,
                )
            )
            if overlap:
                raise HallConflictError(
                    f"Hall '{hall.name}' is already confirmed for another booking during the requested time slot."
                )

        prev_state = {
            "hall_id": str(vr.hall_id),
            "start_time": vr.start_time.isoformat(),
            "end_time": vr.end_time.isoformat(),
        }

        if venue_in.hall_id is not None:
            vr.hall_id = venue_in.hall_id
        if venue_in.requested_date is not None:
            vr.requested_date = venue_in.requested_date
        if venue_in.start_time is not None:
            vr.start_time = venue_in.start_time
        if venue_in.end_time is not None:
            vr.end_time = venue_in.end_time
        if venue_in.expected_audience is not None:
            vr.expected_audience = venue_in.expected_audience
        if venue_in.requires_stage is not None:
            vr.requires_stage = venue_in.requires_stage
        if venue_in.requires_audio is not None:
            vr.requires_audio = venue_in.requires_audio
        if venue_in.requires_lcd is not None:
            vr.requires_lcd = venue_in.requires_lcd
        if venue_in.requires_ac is not None:
            vr.requires_ac = venue_in.requires_ac
        if venue_in.requires_projector is not None:
            vr.requires_projector = venue_in.requires_projector
        if venue_in.additional_requirements is not None:
            vr.additional_requirements = venue_in.additional_requirements

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_UPDATED,
                entity_type="venue_request",
                entity_id=str(vr.id),
                previous_state=prev_state,
                new_state={
                    "hall_id": str(vr.hall_id),
                    "start_time": vr.start_time.isoformat(),
                    "end_time": vr.end_time.isoformat(),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        try:
            await db.commit()
            await db.refresh(vr)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("Could not update venue request due to database conflict.") from exc

        loaded = await db.scalar(
            select(VenueRequest)
            .options(selectinload(VenueRequest.hall))
            .where(VenueRequest.id == vr.id)
        )
        return loaded or vr

    @classmethod
    async def delete_venue_request(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Remove a venue requirement from an event proposal draft."""
        event_stmt = (
            select(EventRequest)
            .options(selectinload(EventRequest.club))
            .where(EventRequest.id == event_id, EventRequest.deleted_at.is_(None))
        )
        event = await db.scalar(event_stmt)
        if not event:
            raise NotFoundError(f"Event proposal with ID '{event_id}' was not found.")

        if event.status not in (EventRequestStatus.DRAFT, EventRequestStatus.REVISION_REQUIRED):
            status_str = event.status.value if hasattr(event.status, "value") else str(event.status)
            raise WorkflowStateError(
                f"Cannot delete venue for proposal in '{status_str}' status. "
                "Only proposals in DRAFT or REVISION_REQUIRED state can remove venue requirements."
            )

        club = await ClubService.verify_club_ownership(
            db, event.club_id, actor, "remove venue requirements for this event"
        )
        if not club.is_active:
            raise BadRequestError(
                f"Club '{club.name}' is currently inactive and cannot remove venue requests."
            )

        vr = await cls.get_venue_request(db, event_id)

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.HALL_RELEASED,
                entity_type="venue_request",
                entity_id=str(vr.id),
                previous_state={"hall_id": str(vr.hall_id), "event_id": str(event_id)},
                new_state=None,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.delete(vr)
        await db.commit()
