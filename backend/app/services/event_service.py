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
from datetime import UTC, datetime
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
    OptimisticLockError,
    WorkflowStateError,
)
from app.models.domain import (
    AuditLog,
    BudgetProposal,
    CashAdvance,
    Club,
    Event,
    EventRequest,
    EventRequestVersion,
    HallBookingConfirmed,
    User,
    VenueRequest,
    WorkflowInstance,
    WorkflowInstanceStep,
)
from app.models.enums import (
    AuditAction,
    CashAdvanceStatus,
    EventRequestStatus,
    EventStatus,
    NotificationType,
    UserRole,
    VenueRequestStatus,
    WorkflowInstanceStatus,
    WorkflowStepStatus,
)
from app.schemas.event import (
    EventCancellationRequest,
    EventCancellationResponse,
    EventRequestCreate,
    EventRequestResponse,
    EventRequestSubmit,
    EventRequestUpdate,
)
from app.services.club_service import ClubService
from app.services.notification_service import NotificationService


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
        stmt = (
            select(EventRequest)
            .options(selectinload(EventRequest.club), selectinload(EventRequest.submitted_by_user))
            .where(EventRequest.id == event_id, EventRequest.deleted_at.is_(None))
            .with_for_update()
        )
        event = await db.scalar(stmt)
        if not event:
            raise NotFoundError(f"Event proposal with ID '{event_id}' was not found.")

        # Enforce optimistic concurrency control
        if (
            event_in.expected_version is not None
            and event.version_lock != event_in.expected_version
        ):
            raise OptimisticLockError(
                f"Event proposal draft has been modified concurrently. "
                f"Expected version {event_in.expected_version}, but current version is "
                f"{event.version_lock}. "
                "Please refetch the latest draft and reapply your changes."
            )

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

    # =========================================================================
    # EVENT & PROPOSAL CANCELLATION
    # =========================================================================

    @classmethod
    async def cancel_proposal(
        cls,
        db: AsyncSession,
        proposal_id: uuid.UUID,
        reason: str,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EventCancellationResponse:
        """
        Cancel an event proposal draft or proposal under review.
        Enforces:
        - Authority: CLUB_SECRETARY of owning club or SYSTEM_ADMIN.
        - Status must be DRAFT, SUBMITTED, IN_REVIEW, or REVISION_REQUIRED.
        - Rejects APPROVED (direct to event cancellation), REJECTED, or CANCELLED.
        - Cancels associated WorkflowInstance and marks pending steps SKIPPED.
        - Releases tentative HallBookingConfirmed if step 2 was approved.
        - Emits PROPOSAL_CANCELLED and optionally HALL_RELEASED audit entries.
        - Notifies affected stakeholders.
        """
        stmt = (
            select(EventRequest)
            .where(EventRequest.id == proposal_id, EventRequest.deleted_at.is_(None))
            .with_for_update()
        )
        proposal = await db.scalar(stmt)
        if not proposal:
            raise NotFoundError(f"Event proposal with ID '{proposal_id}' was not found.")

        # Role & Ownership checks
        if actor.role != UserRole.SYSTEM_ADMIN:
            await ClubService.verify_club_ownership(
                db, proposal.club_id, actor, "cancel this event proposal"
            )

        # State machine validations
        if proposal.status == EventRequestStatus.CANCELLED:
            raise WorkflowStateError("Event proposal is already cancelled.")
        if proposal.status == EventRequestStatus.REJECTED:
            raise WorkflowStateError("Cannot cancel an already rejected event proposal.")
        if proposal.status == EventRequestStatus.APPROVED:
            raise WorkflowStateError(
                "Proposal has already been approved and scheduled as an event. "
                "Use event cancellation instead."
            )
        if proposal.status not in (
            EventRequestStatus.DRAFT,
            EventRequestStatus.SUBMITTED,
            EventRequestStatus.IN_REVIEW,
            EventRequestStatus.REVISION_REQUIRED,
        ):
            st = (
                proposal.status.value
                if hasattr(proposal.status, "value")
                else str(proposal.status)
            )
            raise WorkflowStateError(f"Cannot cancel proposal in '{st}' status.")

        now_utc = datetime.now(UTC)
        actor_role_str = (
            actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        )
        workflow_cancelled = False
        hall_released = False

        # 1. Cancel Workflow if active
        wf = None
        if proposal.workflow_instance_id:
            wf = await db.scalar(
                select(WorkflowInstance)
                .where(WorkflowInstance.id == proposal.workflow_instance_id)
                .with_for_update()
            )
            if wf and wf.status == WorkflowInstanceStatus.IN_PROGRESS:
                wf.status = WorkflowInstanceStatus.CANCELLED
                workflow_cancelled = True
                # Skip pending steps
                pending_steps = (
                    await db.scalars(
                        select(WorkflowInstanceStep).where(
                            WorkflowInstanceStep.instance_id == wf.id,
                            WorkflowInstanceStep.status == WorkflowStepStatus.PENDING,
                        )
                    )
                ).all()
                for step in pending_steps:
                    step.status = WorkflowStepStatus.SKIPPED

        # 2. Release HallBookingConfirmed if step 2 was approved
        booking = await db.scalar(
            select(HallBookingConfirmed)
            .where(
                HallBookingConfirmed.event_request_id == proposal.id,
                HallBookingConfirmed.is_active.is_(True),
            )
            .with_for_update()
        )
        if booking:
            booking.is_active = False
            hall_released = True
            db.add(
                AuditLog(
                    actor_id=actor.id,
                    actor_email=actor.email,
                    actor_role=actor_role_str,
                    action=AuditAction.HALL_RELEASED,
                    entity_type="hall_booking_confirmed",
                    entity_id=str(booking.id),
                    previous_state={
                        "is_active": True,
                        "event_request_id": str(proposal.id),
                    },
                    new_state={
                        "is_active": False,
                        "reason": f"Proposal cancelled: {reason}",
                    },
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )

        # 3. Update venue_request status if present
        vr = await db.scalar(
            select(VenueRequest).where(VenueRequest.event_request_id == proposal.id)
        )
        if vr and vr.status == VenueRequestStatus.APPROVED:
            vr.status = VenueRequestStatus.REJECTED

        # 4. Advance proposal status
        prev_status = (
            proposal.status.value
            if hasattr(proposal.status, "value")
            else str(proposal.status)
        )
        proposal.status = EventRequestStatus.CANCELLED
        proposal.version_lock += 1

        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_CANCELLED,
                entity_type="event_request",
                entity_id=str(proposal.id),
                previous_state={"status": prev_status},
                new_state={
                    "status": EventRequestStatus.CANCELLED.value,
                    "cancellation_reason": reason,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # 5. Notifications
        if actor.id != proposal.submitted_by:
            await NotificationService.create_notification(
                db=db,
                recipient_id=proposal.submitted_by,
                notification_type=NotificationType.SYSTEM,
                title=f"Proposal Cancelled: '{proposal.title}'",
                message=f"Your proposal was cancelled by {actor_role_str}: {reason}",
                event_request_id=proposal.id,
            )
        elif wf and wf.current_step_order:
            current_step = await db.scalar(
                select(WorkflowInstanceStep).where(
                    WorkflowInstanceStep.instance_id == wf.id,
                    WorkflowInstanceStep.step_order == wf.current_step_order,
                )
            )
            if current_step and current_step.assigned_to:
                await NotificationService.create_notification(
                    db=db,
                    recipient_id=current_step.assigned_to,
                    notification_type=NotificationType.SYSTEM,
                    title=f"Proposal Withdrawn: '{proposal.title}'",
                    message=(
                        f"Proposal '{proposal.title}' awaiting your review has been "
                        f"cancelled by the club secretary: {reason}"
                    ),
                    event_request_id=proposal.id,
                )

        await db.commit()

        return EventCancellationResponse(
            id=proposal.id,
            entity_type="PROPOSAL",
            title=proposal.title,
            status=EventRequestStatus.CANCELLED.value,
            cancelled_at=now_utc,
            cancelled_by=actor.id,
            cancellation_reason=reason,
            hall_released=hall_released,
            workflow_cancelled=workflow_cancelled,
            advance_status=None,
            message="Event proposal has been successfully cancelled.",
        )

    @classmethod
    async def cancel_confirmed_event(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        reason: str,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EventCancellationResponse:
        """
        Cancel a confirmed (SCHEDULED or IN_PROGRESS) event.
        Enforces:
        - Authority: CLUB_SECRETARY of hosting club, PRINCIPAL, DEAN, or SYSTEM_ADMIN.
        - Status must be SCHEDULED or IN_PROGRESS.
        - Rejects terminal states: CLOSED and ARCHIVED (ConflictError).
        - Rejects COMPLETED and CLOSURE_REQUESTED (WorkflowStateError).
        - Rejects already CANCELLED events.
        - Automatically releases HallBookingConfirmed to clear exclusion constraint.
        - Financial Advance Safety:
          * If advance in REQUESTED or APPROVED: automatically marked REJECTED.
          * If advance in DISBURSED: left in DISBURSED as an institutional liability;
            requires settlement refund before club clearance.
        - Emits EVENT_STATUS_CHANGED, HALL_RELEASED, and ADVANCE_REJECTED audit logs.
        - Dispatches notifications.
        """
        stmt = (
            select(Event)
            .where((Event.id == event_id) | (Event.event_request_id == event_id))
            .with_for_update()
        )
        event = await db.scalar(stmt)
        if not event:
            raise NotFoundError(f"Confirmed event with ID '{event_id}' was not found.")

        # Authority Check
        allowed_institutional_roles = {
            UserRole.PRINCIPAL,
            UserRole.DEAN_STUDENT_AFFAIRS,
            UserRole.SYSTEM_ADMIN,
        }
        if actor.role not in allowed_institutional_roles:
            await ClubService.verify_club_ownership(
                db, event.club_id, actor, "cancel this confirmed event"
            )

        # State validations
        if event.status in (EventStatus.CLOSED, EventStatus.ARCHIVED):
            st = event.status.value if hasattr(event.status, "value") else str(event.status)
            raise ConflictError(
                f"Cannot cancel event in terminal status '{st}'. Certification is locked."
            )
        if event.status == EventStatus.COMPLETED:
            raise WorkflowStateError(
                "Cannot cancel an event that has already completed. "
                "Completed events must proceed through post-event closeout."
            )
        if event.status == EventStatus.CLOSURE_REQUESTED:
            raise WorkflowStateError(
                "Cannot cancel an event currently under closeout review."
            )
        if event.status == EventStatus.CANCELLED:
            raise WorkflowStateError("Event is already cancelled.")
        if event.status not in (EventStatus.SCHEDULED, EventStatus.IN_PROGRESS):
            st = event.status.value if hasattr(event.status, "value") else str(event.status)
            raise WorkflowStateError(f"Cannot cancel event in '{st}' status.")

        now_utc = datetime.now(UTC)
        actor_role_str = (
            actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        )
        hall_released = False
        advance_status_note = None

        # 1. Hall Booking Release
        booking = await db.scalar(
            select(HallBookingConfirmed)
            .where(
                HallBookingConfirmed.event_request_id == event.event_request_id,
                HallBookingConfirmed.is_active.is_(True),
            )
            .with_for_update()
        )
        if booking:
            booking.is_active = False
            hall_released = True
            db.add(
                AuditLog(
                    actor_id=actor.id,
                    actor_email=actor.email,
                    actor_role=actor_role_str,
                    action=AuditAction.HALL_RELEASED,
                    entity_type="hall_booking_confirmed",
                    entity_id=str(booking.id),
                    previous_state={"is_active": True, "event_id": str(event.id)},
                    new_state={
                        "is_active": False,
                        "reason": f"Event cancelled: {reason}",
                    },
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )

        # 2. Financial Advance Safety Check
        advance = await db.scalar(
            select(CashAdvance)
            .where(CashAdvance.event_id == event.id)
            .with_for_update()
        )
        if advance:
            if advance.status in (CashAdvanceStatus.REQUESTED, CashAdvanceStatus.APPROVED):
                adv_prev = (
                    advance.status.value
                    if hasattr(advance.status, "value")
                    else str(advance.status)
                )
                advance.status = CashAdvanceStatus.REJECTED
                advance.rejection_reason = f"Event cancelled: {reason}"
                advance_status_note = "REJECTED_ON_CANCELLATION"
                db.add(
                    AuditLog(
                        actor_id=actor.id,
                        actor_email=actor.email,
                        actor_role=actor_role_str,
                        action=AuditAction.ADVANCE_REJECTED,
                        entity_type="cash_advance",
                        entity_id=str(advance.id),
                        previous_state={"status": adv_prev},
                        new_state={
                            "status": CashAdvanceStatus.REJECTED.value,
                            "rejection_reason": advance.rejection_reason,
                        },
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
                )
            elif advance.status == CashAdvanceStatus.DISBURSED:
                advance_status_note = "DISBURSED_REFUND_REQUIRED"

        # 3. Mutate Event status and cancellation fields
        prev_status = (
            event.status.value if hasattr(event.status, "value") else str(event.status)
        )
        event.status = EventStatus.CANCELLED
        event.cancelled_at = now_utc
        event.cancelled_by = actor.id
        event.cancellation_reason = reason

        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.EVENT_STATUS_CHANGED,
                entity_type="event",
                entity_id=str(event.id),
                previous_state={"status": prev_status},
                new_state={
                    "status": EventStatus.CANCELLED.value,
                    "cancellation_reason": reason,
                    "cancelled_by": str(actor.id),
                    "cancelled_at": now_utc.isoformat(),
                    "advance_status": advance_status_note,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # 4. Notifications
        club = await db.scalar(select(Club).where(Club.id == event.club_id))
        if club and club.faculty_advisor_id and club.faculty_advisor_id != actor.id:
            await NotificationService.create_notification(
                db=db,
                recipient_id=club.faculty_advisor_id,
                notification_type=NotificationType.SYSTEM,
                title=f"Event Cancelled: '{event.title}'",
                message=f"Event '{event.title}' cancelled by {actor_role_str}: {reason}",
                event_request_id=event.event_request_id,
            )

        if advance and advance.status == CashAdvanceStatus.DISBURSED:
            finance_users = (
                await db.scalars(
                    select(User).where(
                        User.role == UserRole.FINANCE_OFFICER,
                        User.is_active.is_(True),
                    )
                )
            ).all()
            for fo in finance_users:
                await NotificationService.create_notification(
                    db=db,
                    recipient_id=fo.id,
                    notification_type=NotificationType.SYSTEM,
                    title=f"Outstanding Advance Refund Required: '{event.title}'",
                    message=(
                        f"Event '{event.title}' was cancelled, but has an active disbursed advance "
                        f"of ₹{advance.amount_disbursed:.2f}. Full refund must be collected."
                    ),
                    event_request_id=event.event_request_id,
                )

        await db.commit()

        msg = "Event has been successfully cancelled."
        if advance_status_note == "DISBURSED_REFUND_REQUIRED":
            msg += (
                " Note: An outstanding cash advance was disbursed for this event and must "
                "be refunded via financial settlement."
            )

        return EventCancellationResponse(
            id=event.id,
            entity_type="CONFIRMED_EVENT",
            title=event.title,
            status=EventStatus.CANCELLED.value,
            cancelled_at=now_utc,
            cancelled_by=actor.id,
            cancellation_reason=reason,
            hall_released=hall_released,
            workflow_cancelled=False,
            advance_status=advance_status_note,
            message=msg,
        )

    @classmethod
    async def cancel_any_event(
        cls,
        db: AsyncSession,
        identifier: uuid.UUID,
        payload: EventCancellationRequest,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EventCancellationResponse:
        """
        Unified cancellation handler.
        Resolves identifier as a confirmed Event first;
        if not found, resolves as EventRequest proposal.
        """
        confirmed = await db.scalar(
            select(Event).where(
                (Event.id == identifier) | (Event.event_request_id == identifier)
            )
        )
        if confirmed:
            return await cls.cancel_confirmed_event(
                db=db,
                event_id=confirmed.id,
                reason=payload.reason,
                actor=actor,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        proposal = await db.scalar(
            select(EventRequest).where(
                EventRequest.id == identifier,
                EventRequest.deleted_at.is_(None),
            )
        )
        if proposal:
            return await cls.cancel_proposal(
                db=db,
                proposal_id=proposal.id,
                reason=payload.reason,
                actor=actor,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        raise NotFoundError(
            f"Event proposal or confirmed event with ID '{identifier}' was not found."
        )
