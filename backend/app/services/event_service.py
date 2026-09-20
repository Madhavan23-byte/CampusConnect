"""
CampusConnect Backend — Event Proposal Service

Encapsulates all domain logic for event proposals (EventRequest):
1. Draft creation:
   - Verifies target club exists, is not soft-deleted, and is active
   - Enforces SECRETARY ownership of the target club via ClubService
   - Initializes EventRequest in DRAFT status with version 0
   - Transactionally consistent audit logging (PROPOSAL_CREATED)
2. Proposal retrieval & listing:
   - Safe filtering excluding soft-deleted records
   - Eager-loading of relational data (club, submitter)
   - Pagination and status/club filtering
3. Draft modification:
   - Verifies proposal status is DRAFT or REVISION_REQUIRED
   - Enforces resource ownership (SECRETARY of specific club or SYSTEM_ADMIN)
   - Rejects editing of SUBMITTED, IN_REVIEW, APPROVED, REJECTED,
     or CANCELLED proposals (WorkflowStateError -> 403)
   - Optimistic concurrency control via version_lock increment
   - Transactionally consistent audit logging (PROPOSAL_UPDATED)
4. Proposal submission:
   - Validates proposal can only be submitted from DRAFT or REVISION_REQUIRED
   - Enforces club secretary resource ownership
   - Idempotency key handling to prevent duplicate submissions
   - Advances status to SUBMITTED
   - Increments current_version
   - Creates immutable EventRequestVersion snapshot (version N)
   - Transactionally consistent audit logging (PROPOSAL_SUBMITTED)
"""

import uuid
from datetime import UTC
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.base import NO_VALUE

from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    WorkflowStateError,
)
from app.models.domain import (
    AuditLog,
    BudgetProposal,
    Event,
    EventRequest,
    EventRequestVersion,
    HallBookingConfirmed,
    User,
    VenueRequest,
)
from app.models.enums import AuditAction, EventRequestStatus, EventStatus
from app.schemas.event import (
    EventRequestCreate,
    EventRequestResponse,
    EventRequestSubmit,
    EventRequestUpdate,
)
from app.services.club_service import ClubService


def to_event_response(event: EventRequest) -> EventRequestResponse:
    """Format an EventRequest domain model into a safe public schema without lazy loads."""
    insp = inspect(event)

    club_name = None
    if "club" in insp.attrs:
        c = insp.attrs.club.loaded_value
        if c is not NO_VALUE and c is not None:
            club_name = c.name

    submitted_by_name = None
    submitted_by_email = None
    if "submitted_by_user" in insp.attrs:
        u = insp.attrs.submitted_by_user.loaded_value
        if u is not NO_VALUE and u is not None:
            submitted_by_name = u.full_name
            submitted_by_email = u.email

    return EventRequestResponse(
        id=event.id,
        club_id=event.club_id,
        club_name=club_name,
        submitted_by=event.submitted_by,
        submitted_by_name=submitted_by_name,
        submitted_by_email=submitted_by_email,
        title=event.title,
        description=event.description,
        event_type=event.event_type,
        expected_attendees=event.expected_attendees,
        event_date=event.event_date,
        chief_guest_name=event.chief_guest_name,
        chief_guest_designation=event.chief_guest_designation,
        chief_guest_institution=event.chief_guest_institution,
        status=event.status,
        workflow_instance_id=event.workflow_instance_id,
        current_version=event.current_version,
        version_lock=event.version_lock,
        academic_year=event.academic_year,
        idempotency_key=event.idempotency_key,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


class EventService:
    """Domain service managing the event proposal lifecycle and version snapshots."""

    @classmethod
    async def create_draft(
        cls,
        db: AsyncSession,
        event_in: EventRequestCreate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EventRequest:
        """
        Create a new event proposal draft.
        Enforces club ownership, active club status, and logs audit record.
        """
        # Verify that actor is an active secretary of the target club (or SYSTEM_ADMIN)
        club = await ClubService.verify_club_ownership(
            db, event_in.club_id, actor, "propose events for this club"
        )
        if not club.is_active:
            raise BadRequestError(
                f"Club '{club.name}' is currently inactive and cannot propose events."
            )

        event_id = uuid.uuid4()
        event = EventRequest(
            id=event_id,
            club_id=event_in.club_id,
            submitted_by=actor.id,
            title=event_in.title,
            description=event_in.description,
            event_type=event_in.event_type,
            expected_attendees=event_in.expected_attendees,
            event_date=event_in.event_date,
            chief_guest_name=event_in.chief_guest_name,
            chief_guest_designation=event_in.chief_guest_designation,
            chief_guest_institution=event_in.chief_guest_institution,
            status=EventRequestStatus.DRAFT,
            current_version=0,
            version_lock=0,
            academic_year=event_in.academic_year,
        )
        db.add(event)

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        event_type_str = (
            event_in.event_type.value
            if hasattr(event_in.event_type, "value")
            else str(event_in.event_type)
        )
        new_state = {
            "title": event.title,
            "club_id": str(event.club_id),
            "event_type": event_type_str,
            "status": EventRequestStatus.DRAFT.value,
            "academic_year": event.academic_year,
            "expected_attendees": event.expected_attendees,
        }

        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_CREATED,
                entity_type="event_request",
                entity_id=str(event.id),
                previous_state=None,
                new_state=new_state,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        try:
            await db.commit()
            await db.refresh(event)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError(
                "Could not create event proposal due to database conflict."
            ) from exc

        # Reload with relationships
        loaded = await db.scalar(
            select(EventRequest)
            .options(selectinload(EventRequest.club), selectinload(EventRequest.submitted_by_user))
            .where(EventRequest.id == event.id)
        )
        return loaded or event

    @staticmethod
    async def get_event(
        db: AsyncSession, event_id: uuid.UUID, actor: User | None = None
    ) -> EventRequest:
        """Retrieve an event proposal by ID. Returns 404 for nonexistent or soft-deleted records."""
        stmt = (
            select(EventRequest)
            .options(selectinload(EventRequest.club), selectinload(EventRequest.submitted_by_user))
            .where(EventRequest.id == event_id, EventRequest.deleted_at.is_(None))
        )
        event = await db.scalar(stmt)
        if not event:
            raise NotFoundError(f"Event proposal with ID '{event_id}' was not found.")
        return event

    @staticmethod
    async def list_events(
        db: AsyncSession,
        club_id: uuid.UUID | None = None,
        status: EventRequestStatus | None = None,
        skip: int = 0,
        limit: int = 50,
        actor: User | None = None,
    ) -> list[EventRequest]:
        """List event proposals excluding soft-deleted records. Supports filtering."""
        stmt = (
            select(EventRequest)
            .options(selectinload(EventRequest.club), selectinload(EventRequest.submitted_by_user))
            .where(EventRequest.deleted_at.is_(None))
        )
        if club_id is not None:
            stmt = stmt.where(EventRequest.club_id == club_id)
        if status is not None:
            stmt = stmt.where(EventRequest.status == status)

        stmt = stmt.order_by(EventRequest.created_at.desc()).offset(skip).limit(limit)
        result = await db.scalars(stmt)
        return list(result.all())

    @classmethod
    async def update_draft(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        event_in: EventRequestUpdate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EventRequest:
        """
        Update an event proposal draft.
        Strictly enforces state machine: ONLY proposals in DRAFT or
        REVISION_REQUIRED can be modified.
        Submitted or in-review proposals are immutable to planners.
        """
        event = await cls.get_event(db, event_id, actor)

        # Enforce lifecycle immutability
        if event.status not in (EventRequestStatus.DRAFT, EventRequestStatus.REVISION_REQUIRED):
            status_str = event.status.value if hasattr(event.status, "value") else str(event.status)
            raise WorkflowStateError(
                f"Cannot edit event proposal in '{status_str}' status. "
                "Only proposals in DRAFT or REVISION_REQUIRED state can be modified."
            )

        # Enforce club secretary ownership
        club = await ClubService.verify_club_ownership(
            db, event.club_id, actor, "edit this event proposal"
        )
        if not club.is_active:
            raise BadRequestError(
                f"Club '{club.name}' is currently inactive and cannot modify proposals."
            )

        prev_state: dict[str, Any] = {
            "title": event.title,
            "description": event.description,
            "event_type": event.event_type.value
            if hasattr(event.event_type, "value")
            else str(event.event_type),
            "expected_attendees": event.expected_attendees,
            "event_date": event.event_date.isoformat() if event.event_date else None,
            "status": event.status.value if hasattr(event.status, "value") else str(event.status),
            "academic_year": event.academic_year,
            "version_lock": event.version_lock,
        }

        if event_in.title is not None:
            event.title = event_in.title
        if event_in.description is not None:
            event.description = event_in.description
        if event_in.event_type is not None:
            event.event_type = event_in.event_type
        if event_in.expected_attendees is not None:
            event.expected_attendees = event_in.expected_attendees
        if event_in.event_date is not None:
            event.event_date = event_in.event_date
        if event_in.chief_guest_name is not None:
            event.chief_guest_name = event_in.chief_guest_name
        if event_in.chief_guest_designation is not None:
            event.chief_guest_designation = event_in.chief_guest_designation
        if event_in.chief_guest_institution is not None:
            event.chief_guest_institution = event_in.chief_guest_institution
        if event_in.academic_year is not None:
            event.academic_year = event_in.academic_year

        # Increment optimistic concurrency lock
        event.version_lock += 1

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        new_state: dict[str, Any] = {
            "title": event.title,
            "description": event.description,
            "event_type": event.event_type.value
            if hasattr(event.event_type, "value")
            else str(event.event_type),
            "expected_attendees": event.expected_attendees,
            "event_date": event.event_date.isoformat() if event.event_date else None,
            "status": event.status.value if hasattr(event.status, "value") else str(event.status),
            "academic_year": event.academic_year,
            "version_lock": event.version_lock,
        }

        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_UPDATED,
                entity_type="event_request",
                entity_id=str(event.id),
                previous_state=prev_state,
                new_state=new_state,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        try:
            await db.commit()
            await db.refresh(event)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError(
                "Could not update event proposal due to concurrent conflict."
            ) from exc

        loaded = await db.scalar(
            select(EventRequest)
            .options(selectinload(EventRequest.club), selectinload(EventRequest.submitted_by_user))
            .where(EventRequest.id == event.id)
        )
        return loaded or event

    @classmethod
    async def submit_proposal(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        submit_in: EventRequestSubmit | None = None,
        actor: User | None = None,
        idempotency_key: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EventRequest:
        """
        Submit an event proposal into the formal institutional workflow.
        1. Verifies state machine (only DRAFT or REVISION_REQUIRED can be submitted).
        2. Idempotency handling: If identical idempotency_key was already processed,
           return existing.
        3. Enforces secretary ownership of the club.
        4. Advances status to SUBMITTED.
        5. Increments current_version and writes immutable EventRequestVersion snapshot.
        6. Records transactional audit log.
        """
        event = await cls.get_event(db, event_id, actor)

        # Check idempotency: If event is already SUBMITTED with the same key, return idempotently
        if (
            idempotency_key
            and event.idempotency_key == idempotency_key
            and event.status == EventRequestStatus.SUBMITTED
        ):
            return event

        # Enforce lifecycle transition
        if event.status not in (EventRequestStatus.DRAFT, EventRequestStatus.REVISION_REQUIRED):
            status_str = event.status.value if hasattr(event.status, "value") else str(event.status)
            raise WorkflowStateError(
                f"Cannot submit proposal in '{status_str}' status. "
                "Only DRAFT or REVISION_REQUIRED proposals can be submitted."
            )

        # Enforce club secretary ownership
        club = await ClubService.verify_club_ownership(
            db, event.club_id, actor, "submit this event proposal"
        )
        if not club.is_active:
            raise BadRequestError(
                f"Club '{club.name}' is currently inactive and cannot submit event proposals."
            )

        # Handle idempotency key uniqueness check across system
        if idempotency_key:
            existing_key_event = await db.scalar(
                select(EventRequest).where(
                    EventRequest.idempotency_key == idempotency_key, EventRequest.id != event.id
                )
            )
            if existing_key_event:
                raise ConflictError("An event proposal with this idempotency key already exists.")
            event.idempotency_key = idempotency_key

        prev_status_str = (
            event.status.value if hasattr(event.status, "value") else str(event.status)
        )

        # Advance state and version
        event.status = EventRequestStatus.SUBMITTED
        event.current_version += 1
        event.version_lock += 1

        # Create immutable snapshot version record
        event_type_str = (
            event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        )
        snapshot = {
            "id": str(event.id),
            "club_id": str(event.club_id),
            "club_name": event.club.name if event.club else None,
            "title": event.title,
            "description": event.description,
            "event_type": event_type_str,
            "expected_attendees": event.expected_attendees,
            "event_date": event.event_date.isoformat() if event.event_date else None,
            "chief_guest_name": event.chief_guest_name,
            "chief_guest_designation": event.chief_guest_designation,
            "chief_guest_institution": event.chief_guest_institution,
            "academic_year": event.academic_year,
            "version_number": event.current_version,
            "submitted_by": str(actor.id),
            "submitted_by_email": actor.email,
        }

        # Enrich snapshot with venue requirement if present
        vr_stmt = (
            select(VenueRequest)
            .options(selectinload(VenueRequest.hall))
            .where(VenueRequest.event_request_id == event.id)
        )
        vr = await db.scalar(vr_stmt)
        if vr:
            snapshot["venue"] = {
                "hall_id": str(vr.hall_id),
                "hall_name": vr.hall.name if vr.hall else None,
                "requested_date": vr.requested_date.isoformat(),
                "start_time": vr.start_time.isoformat(),
                "end_time": vr.end_time.isoformat(),
                "expected_audience": vr.expected_audience,
            }

        # Enrich snapshot with budget proposal and line items if present
        bp_stmt = (
            select(BudgetProposal)
            .options(selectinload(BudgetProposal.line_items))
            .where(BudgetProposal.event_request_id == event.id)
        )
        bp = await db.scalar(bp_stmt)
        if bp:
            snapshot["budget"] = {
                "expected_income": str(bp.expected_income),
                "institute_contribution": str(bp.institute_contribution),
                "total_expected_expenditure": str(bp.total_expected_expenditure),
                "line_items": [
                    {
                        "description": item.description,
                        "category": item.category.value
                        if hasattr(item.category, "value")
                        else str(item.category),
                        "estimated_amount": str(item.estimated_amount),
                        "notes": item.notes,
                    }
                    for item in bp.line_items
                ],
            }

        version_id = uuid.uuid4()
        version = EventRequestVersion(
            id=version_id,
            event_request_id=event.id,
            version_number=event.current_version,
            snapshot=snapshot,
            submitted_by=actor.id,
            change_summary=submit_in.change_summary if submit_in else None,
        )
        db.add(version)

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_SUBMITTED,
                entity_type="event_request",
                entity_id=str(event.id),
                previous_state={"status": prev_status_str, "version": event.current_version - 1},
                new_state={
                    "status": EventRequestStatus.SUBMITTED.value,
                    "version": event.current_version,
                    "version_id": str(version_id),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # Instantiate or supersede institutional approval workflow
        from app.services.workflow_service import WorkflowService

        await WorkflowService.instantiate_workflow(db, event, actor)

        try:
            await db.commit()
            await db.refresh(event)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("Failed to submit proposal due to database conflict.") from exc

        loaded = await db.scalar(
            select(EventRequest)
            .options(selectinload(EventRequest.club), selectinload(EventRequest.submitted_by_user))
            .where(EventRequest.id == event.id)
        )
        return loaded or event

    @classmethod
    async def create_confirmed_event(
        cls,
        db: AsyncSession,
        event: EventRequest,
        actor: User | None = None,
    ) -> Event:
        """
        Create a confirmed Event from an APPROVED EventRequest.
        Idempotent: if an Event already exists for event.id, returns it.
        Uses latest approved EventRequestVersion and confirmed HallBookingConfirmed / VenueRequest.
        """
        # 1. Check idempotency: one event per approved event_request
        existing_stmt = select(Event).where(Event.event_request_id == event.id)
        existing_event = await db.scalar(existing_stmt)
        if existing_event:
            return existing_event

        # 2. Get latest approved version
        version_stmt = (
            select(EventRequestVersion)
            .where(EventRequestVersion.event_request_id == event.id)
            .order_by(EventRequestVersion.version_number.desc())
        )
        approved_version = await db.scalar(version_stmt)

        # 3. Get confirmed booking if present
        booking_stmt = select(HallBookingConfirmed).where(
            HallBookingConfirmed.event_request_id == event.id,
            HallBookingConfirmed.is_active.is_(True),
        )
        booking = await db.scalar(booking_stmt)

        # 4. Get venue request if booking not found
        vr_stmt = select(VenueRequest).where(VenueRequest.event_request_id == event.id)
        vr = await db.scalar(vr_stmt)

        hall_id = booking.hall_id if booking else (vr.hall_id if vr and vr.hall_id else None)
        default_dt = event.event_date if event.event_date else event.created_at
        event_date = (
            booking.booking_date
            if booking
            else (vr.requested_date if vr and vr.requested_date else default_dt)
        )
        start_time = (
            booking.start_time
            if booking
            else (vr.start_time if vr and vr.start_time else default_dt)
        )
        end_time = (
            booking.end_time if booking else (vr.end_time if vr and vr.end_time else default_dt)
        )
        snapshot = (
            approved_version.snapshot if (approved_version and approved_version.snapshot) else {}
        )
        title = snapshot.get("title") or event.title or "Confirmed Event"
        description = snapshot.get("description") or event.description
        event_type = snapshot.get("event_type") or event.event_type
        expected_attendees = (
            snapshot.get("expected_attendees")
            if snapshot.get("expected_attendees") is not None
            else event.expected_attendees
        )
        version_id = approved_version.id if approved_version else event.id

        # Ensure datetime fields have UTC tzinfo
        if hasattr(event_date, "tzinfo") and event_date.tzinfo is None:
            event_date = event_date.replace(tzinfo=UTC)
        if hasattr(start_time, "tzinfo") and start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=UTC)
        if hasattr(end_time, "tzinfo") and end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=UTC)

        confirmed_event = Event(
            id=uuid.uuid4(),
            event_request_id=event.id,
            approved_version_id=version_id,
            club_id=event.club_id,
            hall_id=hall_id,
            title=title,
            description=description,
            event_type=event_type,
            event_date=event_date,
            start_time=start_time,
            end_time=end_time,
            expected_attendees=expected_attendees,
            status=EventStatus.SCHEDULED,
            academic_year=event.academic_year,
        )
        db.add(confirmed_event)
        await db.flush()

        # Audit log
        actor_id = actor.id if actor else event.submitted_by
        actor_email = actor.email if actor else "system"
        actor_role = (
            (actor.role.value if hasattr(actor.role, "value") else str(actor.role))
            if actor
            else "SYSTEM"
        )
        db.add(
            AuditLog(
                actor_id=actor_id,
                actor_email=actor_email,
                actor_role=actor_role,
                action=AuditAction.EVENT_CREATED,
                entity_type="event",
                entity_id=str(confirmed_event.id),
                previous_state=None,
                new_state={
                    "event_request_id": str(event.id),
                    "title": confirmed_event.title,
                    "status": EventStatus.SCHEDULED.value,
                    "hall_id": str(hall_id) if hall_id else None,
                },
            )
        )
        return confirmed_event
