"""
CampusConnect Backend — Approval Workflow Domain Service

Encapsulates all domain logic for:
1. Workflow template resolution and standard 6-stage institutional chain seeding
2. Workflow instantiation upon proposal submission & version superseding on resubmission
3. Sequential step progression with strict prerequisite order enforcement
4. Approver authorization & conflict-of-interest (self-approval) prevention
5. Domain interlocks:
   - Step 2 (Hall In-Charge): allocates confirmed hall booking in hall_bookings_confirmed
   - Step 3 (Finance Officer): verifies budget proposal (finance_status = VERIFIED)
   - Step 6 (Principal): statutory executive sanction (event.status = APPROVED)
6. Adverse administrative decisions:
   - Rejection with mandatory justification (workflow and event terminated)
   - Revision request with mandatory feedback (event unlocks for secretary editing)
7. Personal pending queue inspection for institutional approvers
8. Concurrency protection via row locking (with_for_update) and step_version_lock
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.base import NO_VALUE

from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    WorkflowStateError,
)
from app.models.domain import (
    AuditLog,
    BudgetProposal,
    Club,
    EventRequest,
    HallBookingConfirmed,
    User,
    VenueRequest,
    WorkflowInstance,
    WorkflowInstanceStep,
    WorkflowTemplate,
    WorkflowTemplateStep,
)
from app.models.enums import (
    AuditAction,
    EventRequestStatus,
    FinanceVerificationStatus,
    NotificationType,
    UserRole,
    VenueRequestStatus,
    WorkflowInstanceStatus,
    WorkflowStepStatus,
)
from app.schemas.workflow import (
    WorkflowInstanceResponse,
    WorkflowPendingItemResponse,
    WorkflowStepResponse,
)
from app.services.notification_service import NotificationService


def _get_required_role_name(step: WorkflowInstanceStep) -> str:
    """Extract required role string safely from template step."""
    if not step.template_step:
        return "designated reviewer"
    role = step.template_step.required_role
    return role.value if hasattr(role, "value") else str(role)


def to_step_response(step: WorkflowInstanceStep) -> WorkflowStepResponse:
    """Safely format a WorkflowInstanceStep model into a response schema."""
    insp = inspect(step)
    req_role = None
    if "template_step" in insp.attrs:
        ts = insp.attrs.template_step.loaded_value
        if ts is not NO_VALUE and ts is not None:
            req_role = (
                ts.required_role.value
                if hasattr(ts.required_role, "value")
                else str(ts.required_role)
            )

    user_name = None
    user_email = None
    if "assignee" in insp.attrs:
        u = insp.attrs.assignee.loaded_value
        if u is not NO_VALUE and u is not None:
            user_name = u.full_name
            user_email = u.email

    return WorkflowStepResponse(
        id=step.id,
        instance_id=step.instance_id,
        template_step_id=step.template_step_id,
        step_order=step.step_order,
        step_name=step.step_name,
        required_role=req_role,
        assigned_to=step.assigned_to,
        assigned_to_name=user_name,
        assigned_to_email=user_email,
        status=step.status,
        action_taken_at=step.action_taken_at,
        comments=step.comments,
        version_reviewed=step.version_reviewed,
        created_at=step.created_at,
        updated_at=step.updated_at,
    )


def to_instance_response(instance: WorkflowInstance) -> WorkflowInstanceResponse:
    """Safely format a WorkflowInstance model into a response schema."""
    insp = inspect(instance)
    tmpl_name = None
    if "template" in insp.attrs:
        t = insp.attrs.template.loaded_value
        if t is not NO_VALUE and t is not None:
            tmpl_name = t.name

    steps: list[WorkflowStepResponse] = []
    if "steps" in insp.attrs:
        raw_steps = insp.attrs.steps.loaded_value
        if raw_steps is not NO_VALUE and raw_steps is not None:
            steps = [to_step_response(s) for s in sorted(raw_steps, key=lambda s: s.step_order)]

    return WorkflowInstanceResponse(
        id=instance.id,
        template_id=instance.template_id,
        template_name=tmpl_name,
        event_request_id=instance.event_request_id,
        current_step_order=instance.current_step_order,
        status=instance.status,
        version_number=instance.version_number,
        steps=steps,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
    )


class WorkflowService:
    """Domain service managing multi-stage approval workflows."""

    # ------------------------------------------------------------------
    # 1. Template Management & Seeding
    # ------------------------------------------------------------------

    @classmethod
    async def ensure_default_template(
        cls, db: AsyncSession, admin_id: uuid.UUID | None = None
    ) -> WorkflowTemplate:
        """Ensure standard 6-stage institutional approval template exists."""
        stmt = (
            select(WorkflowTemplate)
            .options(selectinload(WorkflowTemplate.steps))
            .where(WorkflowTemplate.is_default.is_(True), WorkflowTemplate.deleted_at.is_(None))
        )
        template = await db.scalar(stmt)
        if template:
            return template

        # Find an admin if admin_id not provided
        if not admin_id:
            admin_user = await db.scalar(
                select(User)
                .where(User.role == UserRole.SYSTEM_ADMIN)
                .order_by(User.created_at.asc())
            )
            if not admin_user:
                admin_user = await db.scalar(select(User).order_by(User.created_at.asc()))
            admin_id = admin_user.id if admin_user else uuid.uuid4()

        template_id = uuid.uuid4()
        template = WorkflowTemplate(
            id=template_id,
            name="Standard Institutional Event Approval",
            description="Default 6-stage collegiate governance approval chain",
            is_active=True,
            is_default=True,
            created_by=admin_id,
        )
        db.add(template)

        # Define standard 6 steps
        standard_steps = [
            (
                1,
                "Faculty Advisor Review",
                UserRole.FACULTY_ADVISOR,
                "Academic and departmental endorsement",
            ),
            (
                2,
                "Hall In-Charge Review",
                UserRole.HALL_INCHARGE,
                "Venue availability and physical space clearance",
            ),
            (
                3,
                "Finance Officer Pre-Audit",
                UserRole.FINANCE_OFFICER,
                "Budget compliance, cap verification, and expense audit",
            ),
            (
                4,
                "Advisor Students Union Review",
                UserRole.ADVISOR_STUDENTS_UNION,
                "Student body calendar harmony",
            ),
            (
                5,
                "Dean of Student Affairs Review",
                UserRole.DEAN_STUDENT_AFFAIRS,
                "Institutional administration clearance",
            ),
            (
                6,
                "Principal Executive Sanction",
                UserRole.PRINCIPAL,
                "Final statutory authority event sanction",
            ),
        ]

        for order, name, role, desc in standard_steps:
            db.add(
                WorkflowTemplateStep(
                    id=uuid.uuid4(),
                    template_id=template_id,
                    step_order=order,
                    step_name=name,
                    required_role=role,
                    assigned_user_id=None,  # dynamically resolved at instance creation
                    is_optional=False,
                    description=desc,
                )
            )

        await db.flush()
        loaded = await db.scalar(
            select(WorkflowTemplate)
            .options(selectinload(WorkflowTemplate.steps))
            .where(WorkflowTemplate.id == template_id)
        )
        return loaded or template

    # ------------------------------------------------------------------
    # 2. Workflow Instantiation (Hooked on Proposal Submission)
    # ------------------------------------------------------------------

    @classmethod
    async def instantiate_workflow(
        cls,
        db: AsyncSession,
        event: EventRequest,
        actor: User,
    ) -> WorkflowInstance:
        """
        Instantiate workflow when proposal is formally submitted.
        If a prior instance exists, mark it SUPERSEDED.
        Dynamically resolve step approvers.
        """
        # 1. Supersede any existing active workflow instance
        if event.workflow_instance_id:
            prior_instance = await db.scalar(
                select(WorkflowInstance).where(WorkflowInstance.id == event.workflow_instance_id)
            )
            if prior_instance and prior_instance.status == WorkflowInstanceStatus.IN_PROGRESS:
                prior_instance.status = WorkflowInstanceStatus.SUPERSEDED

        # 2. Resolve template
        template = await cls.ensure_default_template(db, actor.id)

        # 3. Create WorkflowInstance
        instance_id = uuid.uuid4()
        instance = WorkflowInstance(
            id=instance_id,
            template_id=template.id,
            event_request_id=event.id,
            current_step_order=1,
            status=WorkflowInstanceStatus.IN_PROGRESS,
            version_number=event.current_version,
        )
        db.add(instance)
        await db.flush()

        # 4. Resolve approvers and create concrete steps
        club_stmt = select(Club).where(Club.id == event.club_id)
        club = await db.scalar(club_stmt)

        users_stmt = select(User).where(User.is_active.is_(True), User.deleted_at.is_(None))
        all_active_users = list((await db.scalars(users_stmt)).all())
        admin_user = next((u for u in all_active_users if u.role == UserRole.SYSTEM_ADMIN), None)

        sorted_template_steps = sorted(template.steps, key=lambda s: s.step_order)
        for t_step in sorted_template_steps:
            assigned_user_id = t_step.assigned_user_id

            if not assigned_user_id:
                if t_step.required_role == UserRole.FACULTY_ADVISOR:
                    if club and club.faculty_advisor_id:
                        assigned_user_id = club.faculty_advisor_id
                    else:
                        fa_user = next(
                            (u for u in all_active_users if u.role == UserRole.FACULTY_ADVISOR),
                            None,
                        )
                        assigned_user_id = (
                            fa_user.id if fa_user else (admin_user.id if admin_user else actor.id)
                        )
                else:
                    role_user = next(
                        (u for u in all_active_users if u.role == t_step.required_role),
                        None,
                    )
                    if role_user:
                        assigned_user_id = role_user.id
                    elif admin_user:
                        assigned_user_id = admin_user.id
                    else:
                        assigned_user_id = actor.id

            step = WorkflowInstanceStep(
                id=uuid.uuid4(),
                instance_id=instance_id,
                template_step_id=t_step.id,
                step_order=t_step.step_order,
                step_name=t_step.step_name,
                assigned_to=assigned_user_id,
                status=WorkflowStepStatus.PENDING,
                version_reviewed=event.current_version,
                step_version_lock=0,
            )
            db.add(step)

        # Link to event
        event.workflow_instance_id = instance_id
        await db.flush()

        # Notify Step 1 assignee: ACTION_REQUIRED
        first_step_stmt = select(WorkflowInstanceStep).where(
            WorkflowInstanceStep.instance_id == instance_id,
            WorkflowInstanceStep.step_order == 1,
        )
        first_step = await db.scalar(first_step_stmt)
        if first_step and first_step.assigned_to:
            await NotificationService.create_notification(
                db=db,
                recipient_id=first_step.assigned_to,
                notification_type=NotificationType.ACTION_REQUIRED,
                title=f"Action Required: Proposal '{event.title}' submitted",
                message=(
                    f"Event proposal '{event.title}' has been submitted and awaits your review "
                    f"as Step 1 ({first_step.step_name})."
                ),
                event_request_id=event.id,
            )

        return instance

    # ------------------------------------------------------------------
    # 3. Step Action Execution (Approve, Reject, Request Revision)
    # ------------------------------------------------------------------

    @classmethod
    async def approve_step(
        cls,
        db: AsyncSession,
        step_id: uuid.UUID,
        actor: User,
        comments: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> WorkflowInstanceStep:
        """Approve current step, execute domain interlocks, and advance pointer."""
        stmt = (
            select(WorkflowInstanceStep)
            .options(
                selectinload(WorkflowInstanceStep.instance).selectinload(
                    WorkflowInstance.event_request
                ),
                selectinload(WorkflowInstanceStep.template_step),
                selectinload(WorkflowInstanceStep.assignee),
            )
            .where(WorkflowInstanceStep.id == step_id)
            .with_for_update()
        )
        step = await db.scalar(stmt)
        if not step:
            raise NotFoundError(f"Workflow step with ID '{step_id}' was not found.")

        instance = step.instance
        event = instance.event_request

        # 1. State machine guards
        if step.status != WorkflowStepStatus.PENDING:
            raise WorkflowStateError(
                f"Step '{step.step_name}' is already in '{step.status}' status."
            )

        if instance.status != WorkflowInstanceStatus.IN_PROGRESS:
            raise WorkflowStateError(f"Workflow instance is '{instance.status}', not IN_PROGRESS.")

        if step.step_order != instance.current_step_order:
            raise WorkflowStateError(
                f"Step '{step.step_name}' (Order {step.step_order}) "
                f"cannot be approved out-of-order. "
                f"Currently awaiting Step {instance.current_step_order}."
            )

        # 2. Conflict of interest guard: Submitter cannot approve own proposal
        if event.submitted_by == actor.id:
            raise ForbiddenError(
                "Conflict of interest: You cannot approve your own submitted proposal."
            )

        # 3. Role / Actor authorization guard
        # Step 1 (Faculty Advisor): personal assignment required; SYSTEM_ADMIN may
        # substitute because role-match alone is too broad (each club has one advisor).
        # Steps 2-6 (statutory institutional approvers): SYSTEM_ADMIN must NOT
        # substitute for HALL_INCHARGE, FINANCE_OFFICER, ADVISOR_STUDENTS_UNION,
        # DEAN_STUDENT_AFFAIRS, or PRINCIPAL. Only the assigned user or any user
        # legitimately holding the required institutional role may act.
        is_assigned = step.assigned_to == actor.id
        is_role_match = (
            step.template_step.required_role == actor.role if step.template_step else False
        )

        if step.step_order == 1:
            is_admin = actor.role == UserRole.SYSTEM_ADMIN
            can_act = is_assigned or is_admin
        else:
            can_act = is_assigned or is_role_match

        if not can_act:
            req_role = _get_required_role_name(step)
            raise ForbiddenError(
                f"Unauthorized: Step requires '{req_role}' or designated assignment."
            )

        # 4. Mark step approved
        step.status = WorkflowStepStatus.APPROVED
        step.action_taken_at = datetime.now(UTC)
        step.comments = comments
        step.version_reviewed = instance.version_number
        step.step_version_lock += 1

        # 5. Domain Interlocks
        # Step 2: Hall In-Charge -> Confirm venue & insert hall_bookings_confirmed
        if step.step_order == 2:
            vr_stmt = select(VenueRequest).where(VenueRequest.event_request_id == event.id)
            vr = await db.scalar(vr_stmt)
            if vr:
                conflict = await db.scalar(
                    select(HallBookingConfirmed).where(
                        HallBookingConfirmed.hall_id == vr.hall_id,
                        HallBookingConfirmed.booking_date == vr.requested_date,
                        HallBookingConfirmed.is_active.is_(True),
                        HallBookingConfirmed.event_request_id != event.id,
                        HallBookingConfirmed.start_time < vr.end_time,
                        HallBookingConfirmed.end_time > vr.start_time,
                    )
                )
                if conflict:
                    raise ConflictError(
                        "Venue conflict: Hall is already confirmed for another booking "
                        "during this time slot."
                    )

                vr.status = VenueRequestStatus.APPROVED
                vr.reviewed_by = actor.id
                vr.reviewed_at = datetime.now(UTC)

                existing_booking = await db.scalar(
                    select(HallBookingConfirmed).where(
                        HallBookingConfirmed.event_request_id == event.id
                    )
                )
                if not existing_booking:
                    booking = HallBookingConfirmed(
                        id=uuid.uuid4(),
                        hall_id=vr.hall_id,
                        event_request_id=event.id,
                        venue_request_id=vr.id,
                        booking_date=vr.requested_date,
                        start_time=vr.start_time,
                        end_time=vr.end_time,
                        is_active=True,
                    )
                    db.add(booking)
                else:
                    existing_booking.is_active = True

        # Step 3: Finance Officer -> Mark budget verified
        if step.step_order == 3:
            bp_stmt = select(BudgetProposal).where(BudgetProposal.event_request_id == event.id)
            bp = await db.scalar(bp_stmt)
            if bp:
                bp.finance_status = FinanceVerificationStatus.VERIFIED
                bp.finance_verified_by = actor.id
                bp.finance_verified_at = datetime.now(UTC)
                bp.finance_notes = comments

        # 6. Advance workflow pointer or complete
        next_step_stmt = select(WorkflowInstanceStep).where(
            WorkflowInstanceStep.instance_id == instance.id,
            WorkflowInstanceStep.step_order == step.step_order + 1,
        )
        next_step = await db.scalar(next_step_stmt)

        if next_step:
            instance.current_step_order = next_step.step_order
            if event.status == EventRequestStatus.SUBMITTED:
                event.status = EventRequestStatus.IN_REVIEW

            # Notify next reviewer: ACTION_REQUIRED
            if next_step.assigned_to:
                await NotificationService.create_notification(
                    db=db,
                    recipient_id=next_step.assigned_to,
                    notification_type=NotificationType.ACTION_REQUIRED,
                    title=f"Action Required: Step {next_step.step_order} - {next_step.step_name}",
                    message=(
                        f"Proposal '{event.title}' has advanced to Step {next_step.step_order} "
                        f"({next_step.step_name}) and requires your review."
                    ),
                    event_request_id=event.id,
                )
            # Notify secretary: STEP_APPROVED
            if event.submitted_by:
                await NotificationService.create_notification(
                    db=db,
                    recipient_id=event.submitted_by,
                    notification_type=NotificationType.STEP_APPROVED,
                    title=f"Step Approved: {step.step_name}",
                    message=(
                        f"Step {step.step_order} ({step.step_name}) for proposal '{event.title}' "
                        f"has been approved."
                    ),
                    event_request_id=event.id,
                )
        else:
            instance.status = WorkflowInstanceStatus.COMPLETED
            event.status = EventRequestStatus.APPROVED

            # Create confirmed Event (Idempotent)
            from app.services.event_service import EventService

            await EventService.create_confirmed_event(db=db, event=event, actor=actor)

            # Notify secretary: PROPOSAL_APPROVED
            if event.submitted_by:
                await NotificationService.create_notification(
                    db=db,
                    recipient_id=event.submitted_by,
                    notification_type=NotificationType.PROPOSAL_APPROVED,
                    title=f"Proposal Approved: '{event.title}'",
                    message=(
                        f"Your event proposal '{event.title}' has received final sanction "
                        "and is officially approved!"
                    ),
                    event_request_id=event.id,
                )

        # 7. Audit log
        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_APPROVED,
                entity_type="workflow_step",
                entity_id=str(step.id),
                previous_state={"step_order": step.step_order, "status": "PENDING"},
                new_state={
                    "step_order": step.step_order,
                    "status": "APPROVED",
                    "next_step_order": instance.current_step_order,
                    "event_status": str(event.status),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.commit()
        await db.refresh(step)
        return step

    @classmethod
    async def reject_step(
        cls,
        db: AsyncSession,
        step_id: uuid.UUID,
        actor: User,
        comments: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> WorkflowInstanceStep:
        """Reject step with mandatory justification; terminates workflow and rejects event."""
        if not comments or len(comments.strip()) < 5:
            raise BadRequestError(
                "Mandatory detailed rejection reason must be provided (minimum 5 characters)."
            )

        stmt = (
            select(WorkflowInstanceStep)
            .options(
                selectinload(WorkflowInstanceStep.instance).selectinload(
                    WorkflowInstance.event_request
                ),
                selectinload(WorkflowInstanceStep.template_step),
                selectinload(WorkflowInstanceStep.assignee),
            )
            .where(WorkflowInstanceStep.id == step_id)
            .with_for_update()
        )
        step = await db.scalar(stmt)
        if not step:
            raise NotFoundError(f"Workflow step with ID '{step_id}' was not found.")

        instance = step.instance
        event = instance.event_request

        if step.status != WorkflowStepStatus.PENDING:
            raise WorkflowStateError(
                f"Step '{step.step_name}' is already in '{step.status}' status."
            )

        if instance.status != WorkflowInstanceStatus.IN_PROGRESS:
            raise WorkflowStateError(f"Workflow instance is '{instance.status}', not IN_PROGRESS.")

        if step.step_order != instance.current_step_order:
            raise WorkflowStateError(
                f"Step '{step.step_name}' (Order {step.step_order}) "
                f"cannot be rejected out-of-order. "
                f"Currently awaiting Step {instance.current_step_order}."
            )

        if event.submitted_by == actor.id:
            raise ForbiddenError(
                "Conflict of interest: You cannot reject your own submitted proposal."
            )

        # Step 1 (Faculty Advisor): personal assignment required; SYSTEM_ADMIN may
        # substitute because role-match alone is too broad (each club has one advisor).
        # Steps 2-6 (statutory institutional approvers): SYSTEM_ADMIN must NOT
        # substitute for HALL_INCHARGE, FINANCE_OFFICER, ADVISOR_STUDENTS_UNION,
        # DEAN_STUDENT_AFFAIRS, or PRINCIPAL. Only the assigned user or any user
        # legitimately holding the required institutional role may act.
        is_assigned = step.assigned_to == actor.id
        is_role_match = (
            step.template_step.required_role == actor.role if step.template_step else False
        )

        if step.step_order == 1:
            is_admin = actor.role == UserRole.SYSTEM_ADMIN
            can_act = is_assigned or is_admin
        else:
            can_act = is_assigned or is_role_match

        if not can_act:
            req_role = _get_required_role_name(step)
            raise ForbiddenError(
                f"Unauthorized: Step requires '{req_role}' or designated assignment."
            )

        step.status = WorkflowStepStatus.REJECTED
        step.action_taken_at = datetime.now(UTC)
        step.comments = comments
        step.version_reviewed = instance.version_number
        step.step_version_lock += 1

        instance.status = WorkflowInstanceStatus.REJECTED
        event.status = EventRequestStatus.REJECTED

        # Update venue request if present
        vr_stmt = select(VenueRequest).where(VenueRequest.event_request_id == event.id)
        vr = await db.scalar(vr_stmt)
        if vr:
            vr.status = VenueRequestStatus.REJECTED
            vr.rejection_reason = comments

        # Deactivate confirmed booking if one was created
        booking_stmt = select(HallBookingConfirmed).where(
            HallBookingConfirmed.event_request_id == event.id
        )
        booking = await db.scalar(booking_stmt)
        if booking:
            booking.is_active = False

        # Notify secretary: PROPOSAL_REJECTED
        if event.submitted_by:
            await NotificationService.create_notification(
                db=db,
                recipient_id=event.submitted_by,
                notification_type=NotificationType.PROPOSAL_REJECTED,
                title=f"Proposal Rejected: '{event.title}'",
                message=(
                    f"Your proposal '{event.title}' was rejected at Step {step.step_order} "
                    f"({step.step_name}). Reason: {comments}"
                ),
                event_request_id=event.id,
            )

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_REJECTED,
                entity_type="workflow_step",
                entity_id=str(step.id),
                previous_state={"step_order": step.step_order, "status": "PENDING"},
                new_state={
                    "step_order": step.step_order,
                    "status": "REJECTED",
                    "comments": comments,
                    "event_status": "REJECTED",
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.commit()
        await db.refresh(step)
        return step

    @classmethod
    async def request_revision(
        cls,
        db: AsyncSession,
        step_id: uuid.UUID,
        actor: User,
        comments: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> WorkflowInstanceStep:
        """Request changes with mandatory instructions; unlocks event for secretary editing."""
        if not comments or len(comments.strip()) < 5:
            raise BadRequestError(
                "Mandatory detailed revision instructions must be provided (minimum 5 characters)."
            )

        stmt = (
            select(WorkflowInstanceStep)
            .options(
                selectinload(WorkflowInstanceStep.instance).selectinload(
                    WorkflowInstance.event_request
                ),
                selectinload(WorkflowInstanceStep.template_step),
                selectinload(WorkflowInstanceStep.assignee),
            )
            .where(WorkflowInstanceStep.id == step_id)
            .with_for_update()
        )
        step = await db.scalar(stmt)
        if not step:
            raise NotFoundError(f"Workflow step with ID '{step_id}' was not found.")

        instance = step.instance
        event = instance.event_request

        if step.status != WorkflowStepStatus.PENDING:
            raise WorkflowStateError(
                f"Step '{step.step_name}' is already in '{step.status}' status."
            )

        if instance.status != WorkflowInstanceStatus.IN_PROGRESS:
            raise WorkflowStateError(f"Workflow instance is '{instance.status}', not IN_PROGRESS.")

        if step.step_order != instance.current_step_order:
            raise WorkflowStateError(
                f"Step '{step.step_name}' (Order {step.step_order}) "
                f"cannot request revision out-of-order. "
                f"Currently awaiting Step {instance.current_step_order}."
            )

        if event.submitted_by == actor.id:
            raise ForbiddenError(
                "Conflict of interest: You cannot request revision on your own submitted proposal."
            )

        # Step 1 (Faculty Advisor): personal assignment required; SYSTEM_ADMIN may
        # substitute because role-match alone is too broad (each club has one advisor).
        # Steps 2-6 (statutory institutional approvers): SYSTEM_ADMIN must NOT
        # substitute for HALL_INCHARGE, FINANCE_OFFICER, ADVISOR_STUDENTS_UNION,
        # DEAN_STUDENT_AFFAIRS, or PRINCIPAL. Only the assigned user or any user
        # legitimately holding the required institutional role may act.
        is_assigned = step.assigned_to == actor.id
        is_role_match = (
            step.template_step.required_role == actor.role if step.template_step else False
        )

        if step.step_order == 1:
            is_admin = actor.role == UserRole.SYSTEM_ADMIN
            can_act = is_assigned or is_admin
        else:
            can_act = is_assigned or is_role_match

        if not can_act:
            req_role = _get_required_role_name(step)
            raise ForbiddenError(
                f"Unauthorized: Step requires '{req_role}' or designated assignment."
            )

        step.status = WorkflowStepStatus.REVISION_REQUESTED
        step.action_taken_at = datetime.now(UTC)
        step.comments = comments
        step.version_reviewed = instance.version_number
        step.step_version_lock += 1

        # Unlock proposal for secretary modification
        event.status = EventRequestStatus.REVISION_REQUIRED

        # Notify secretary: REVISION_REQUIRED
        if event.submitted_by:
            await NotificationService.create_notification(
                db=db,
                recipient_id=event.submitted_by,
                notification_type=NotificationType.REVISION_REQUIRED,
                title=f"Revision Required: '{event.title}'",
                message=(
                    f"Changes were requested at Step {step.step_order} ({step.step_name}) "
                    f"for proposal '{event.title}'. Instructions: {comments}"
                ),
                event_request_id=event.id,
            )

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.REVISION_REQUESTED,
                entity_type="workflow_step",
                entity_id=str(step.id),
                previous_state={"step_order": step.step_order, "status": "PENDING"},
                new_state={
                    "step_order": step.step_order,
                    "status": "REVISION_REQUESTED",
                    "comments": comments,
                    "event_status": "REVISION_REQUIRED",
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.commit()
        await db.refresh(step)
        return step

    # ------------------------------------------------------------------
    # 4. Queries (Pending Queue & Workflow Inspection)
    # ------------------------------------------------------------------

    @classmethod
    async def get_pending_queue(
        cls,
        db: AsyncSession,
        actor: User,
        skip: int = 0,
        limit: int = 50,
    ) -> list[WorkflowPendingItemResponse]:
        """Retrieve items currently awaiting caller's action in the workflow chain."""
        stmt = (
            select(WorkflowInstanceStep)
            .join(WorkflowInstance, WorkflowInstanceStep.instance_id == WorkflowInstance.id)
            .join(EventRequest, WorkflowInstance.event_request_id == EventRequest.id)
            .join(Club, EventRequest.club_id == Club.id)
            .join(
                WorkflowTemplateStep,
                WorkflowInstanceStep.template_step_id == WorkflowTemplateStep.id,
            )
            .options(
                selectinload(WorkflowInstanceStep.instance)
                .selectinload(WorkflowInstance.event_request)
                .selectinload(EventRequest.club),
            )
            .where(
                WorkflowInstanceStep.status == WorkflowStepStatus.PENDING,
                WorkflowInstanceStep.step_order == WorkflowInstance.current_step_order,
                WorkflowInstance.status == WorkflowInstanceStatus.IN_PROGRESS,
                EventRequest.deleted_at.is_(None),
                EventRequest.submitted_by != actor.id,  # prevent self-approval from queue
            )
        )

        # Scoping by role or assignment unless SYSTEM_ADMIN
        if actor.role != UserRole.SYSTEM_ADMIN:
            if actor.role == UserRole.FACULTY_ADVISOR:
                stmt = stmt.where(WorkflowInstanceStep.assigned_to == actor.id)
            else:
                stmt = stmt.where(
                    (WorkflowInstanceStep.assigned_to == actor.id)
                    | (WorkflowTemplateStep.required_role == actor.role)
                )

        stmt = stmt.order_by(WorkflowInstanceStep.created_at.asc()).offset(skip).limit(limit)
        steps = list((await db.scalars(stmt)).all())

        items = []
        for s in steps:
            ev = s.instance.event_request
            items.append(
                WorkflowPendingItemResponse(
                    step_id=s.id,
                    instance_id=s.instance_id,
                    event_request_id=ev.id,
                    event_title=ev.title,
                    club_name=ev.club.name if ev.club else "Club",
                    step_order=s.step_order,
                    step_name=s.step_name,
                    version_number=s.instance.version_number,
                    submitted_at=s.created_at,
                    assigned_to=s.assigned_to,
                )
            )
        return items

    @classmethod
    async def get_event_workflow(
        cls, db: AsyncSession, event_id: uuid.UUID
    ) -> WorkflowInstanceResponse:
        """Retrieve active or latest workflow instance for an event proposal."""
        stmt = (
            select(WorkflowInstance)
            .options(
                selectinload(WorkflowInstance.template),
                selectinload(WorkflowInstance.steps).selectinload(
                    WorkflowInstanceStep.template_step
                ),
                selectinload(WorkflowInstance.steps).selectinload(WorkflowInstanceStep.assignee),
            )
            .where(WorkflowInstance.event_request_id == event_id)
            .order_by(
                WorkflowInstance.version_number.desc(),
                WorkflowInstance.created_at.desc(),
            )
        )
        instance = await db.scalar(stmt)
        if not instance:
            raise NotFoundError(f"No workflow instance found for event '{event_id}'.")
        return to_instance_response(instance)

    @classmethod
    async def get_workflow_instance(
        cls, db: AsyncSession, instance_id: uuid.UUID
    ) -> WorkflowInstanceResponse:
        """Retrieve workflow instance by its UUID."""
        stmt = (
            select(WorkflowInstance)
            .options(
                selectinload(WorkflowInstance.template),
                selectinload(WorkflowInstance.steps).selectinload(
                    WorkflowInstanceStep.template_step
                ),
                selectinload(WorkflowInstance.steps).selectinload(WorkflowInstanceStep.assignee),
            )
            .where(WorkflowInstance.id == instance_id)
        )
        instance = await db.scalar(stmt)
        if not instance:
            raise NotFoundError(f"Workflow instance with ID '{instance_id}' was not found.")
        return to_instance_response(instance)
