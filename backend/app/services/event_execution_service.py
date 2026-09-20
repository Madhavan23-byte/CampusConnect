"""
CampusConnect — Event Execution & Post-Event Delivery Service

Encapsulates downstream event execution lifecycle, post-event reporting,
attendance tracking, revision snapshots, and statutory Faculty Advisor certification.

Design Principles:
- SELECT ... FOR UPDATE row locking on Event and PostEventReport prevents race conditions.
- Strict non-bypassable statutory authorization: Only designated Faculty Advisor can certify.
- SYSTEM_ADMIN has no ordinary secretary execution powers (must use explicit admin-start).
- Submitter self-certification is strictly rejected (Conflict of Interest prevention).
- Atomic database transactions ensure no partial state leaks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    WorkflowStateError,
)
from app.models.domain import (
    AuditLog,
    Club,
    ClubMember,
    Event,
    PostEventReport,
    User,
)
from app.models.enums import (
    AuditAction,
    ClubMemberRole,
    EventStatus,
    NotificationType,
    PostEventReportStatus,
    UserRole,
)
from app.schemas.post_event_report import (
    AdminStartEventRequest,
    ConfirmedEventResponse,
    PostEventReportCertify,
    PostEventReportCreate,
    PostEventReportResponse,
    PostEventReportRevisionRequest,
    PostEventReportUpdate,
)
from app.services.notification_service import NotificationService


def to_post_event_report_response(report: PostEventReport) -> PostEventReportResponse:
    """Format a PostEventReport model into a safe public schema without lazy loads."""
    insp = inspect(report)

    submitted_by_name = None
    submitted_by_email = None
    if "submitter" in insp.attrs:
        u = insp.attrs.submitter.loaded_value
        if u is not None:
            submitted_by_name = getattr(u, "full_name", None)
            submitted_by_email = getattr(u, "email", None)

    certified_by_name = None
    certified_by_email = None
    if "certifier" in insp.attrs:
        u = insp.attrs.certifier.loaded_value
        if u is not None:
            certified_by_name = getattr(u, "full_name", None)
            certified_by_email = getattr(u, "email", None)

    return PostEventReportResponse(
        id=report.id,
        event_id=report.event_id,
        revision_number=report.revision_number,
        actual_attendance=report.actual_attendance,
        summary=report.summary,
        objectives_achieved=report.objectives_achieved,
        outcomes=report.outcomes,
        challenges=report.challenges,
        status=report.status,
        submitted_by=report.submitted_by,
        submitted_by_name=submitted_by_name,
        submitted_by_email=submitted_by_email,
        submitted_at=report.submitted_at,
        certified_by=report.certified_by,
        certified_by_name=certified_by_name,
        certified_by_email=certified_by_email,
        certified_at=report.certified_at,
        certification_remarks=report.certification_remarks,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


def to_confirmed_event_response(event: Event) -> ConfirmedEventResponse:
    """Format an Event model into a safe public schema."""
    return ConfirmedEventResponse(
        id=event.id,
        event_request_id=event.event_request_id,
        club_id=event.club_id,
        hall_id=event.hall_id,
        title=event.title,
        description=event.description,
        event_type=event.event_type,
        event_date=event.event_date,
        start_time=event.start_time,
        end_time=event.end_time,
        expected_attendees=event.expected_attendees,
        status=event.status,
        academic_year=event.academic_year,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


class EventExecutionService:
    """Domain service managing the operational lifecycle of confirmed events."""

    @classmethod
    async def _resolve_event(
        cls,
        db: AsyncSession,
        event_identifier: uuid.UUID,
        for_update: bool = False,
    ) -> Event:
        """Resolve confirmed event by either Event.id or Event.event_request_id."""
        query = select(Event).where(
            (Event.id == event_identifier) | (Event.event_request_id == event_identifier)
        )
        if for_update:
            query = query.with_for_update()
        event = await db.scalar(query)
        if not event:
            raise NotFoundError(f"Confirmed event '{event_identifier}' not found.")
        return event

    @classmethod
    async def _verify_secretary_ownership(
        cls,
        db: AsyncSession,
        club_id: uuid.UUID,
        actor: User,
        action_description: str,
    ) -> None:
        """Verify actor is an active secretary of the specified club. SYSTEM_ADMIN cannot bypass."""
        member = await db.scalar(
            select(ClubMember).where(
                ClubMember.club_id == club_id,
                ClubMember.user_id == actor.id,
                ClubMember.member_role == ClubMemberRole.SECRETARY,
                ClubMember.is_active.is_(True),
            )
        )
        if not member:
            raise ForbiddenError(
                f"Access denied: You must be an active Club Secretary to {action_description}."
            )

    @classmethod
    async def _verify_advisor_eligibility(
        cls,
        db: AsyncSession,
        club_id: uuid.UUID,
        actor: User,
        action_description: str,
    ) -> Club:
        """
        Verify actor is the assigned Faculty Advisor of the club.
        Enforces statutory separation of duties: SYSTEM_ADMIN and submitters are blocked.
        """
        if actor.role == UserRole.SYSTEM_ADMIN:
            raise ForbiddenError(
                "Access denied: SYSTEM_ADMIN cannot substitute for Faculty Advisor certification."
            )

        club = await db.scalar(select(Club).where(Club.id == club_id))
        if not club:
            raise NotFoundError(f"Club '{club_id}' not found.")

        if club.faculty_advisor_id != actor.id:
            raise ForbiddenError(
                f"Access denied: Only designated Faculty Advisor can {action_description}."
            )
        return club

    # -----------------------------------------------------------------------
    # 1. Event Execution Lifecycle
    # -----------------------------------------------------------------------

    @classmethod
    async def start_event(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Event:
        """
        Transition event status from SCHEDULED to IN_PROGRESS.
        Restricted to active Club Secretary.
        """
        event = await cls._resolve_event(db, event_id, for_update=True)

        # Verify club secretary role (blocks unauthorized users and ordinary SYSTEM_ADMIN bypass)
        await cls._verify_secretary_ownership(db, event.club_id, actor, "start this event")

        # State check
        if event.status != EventStatus.SCHEDULED:
            st = event.status.value if hasattr(event.status, "value") else str(event.status)
            raise WorkflowStateError(
                f"Cannot start event in '{st}' status. Only SCHEDULED events can be started."
            )

        # Operational time window check (allows starting up to 2 hours before scheduled start)
        now_utc = datetime.now(UTC)
        start_tz = (
            event.start_time if event.start_time.tzinfo else event.start_time.replace(tzinfo=UTC)
        )
        if now_utc < (start_tz - timedelta(hours=2)):
            raise BadRequestError(
                f"Event cannot start before scheduled window ({start_tz.isoformat()})."
            )

        event.status = EventStatus.IN_PROGRESS

        # Audit log
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor.role.value if hasattr(actor.role, "value") else str(actor.role),
                action=AuditAction.EVENT_STARTED,
                entity_type="event",
                entity_id=str(event.id),
                previous_state={"status": EventStatus.SCHEDULED.value},
                new_state={"status": EventStatus.IN_PROGRESS.value},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await db.flush()
        return event

    @classmethod
    async def admin_start_event(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
        admin_req: AdminStartEventRequest,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Event:
        """
        Administrative emergency intervention to start an event.
        Requires SYSTEM_ADMIN role and explicit justification.
        """
        if actor.role != UserRole.SYSTEM_ADMIN:
            raise ForbiddenError(
                "Access denied: Administrative override requires SYSTEM_ADMIN role."
            )

        event = await cls._resolve_event(db, event_id, for_update=True)

        if event.status != EventStatus.SCHEDULED:
            st = event.status.value if hasattr(event.status, "value") else str(event.status)
            raise WorkflowStateError(
                f"Cannot start event in '{st}' status. Only SCHEDULED events can be started."
            )

        event.status = EventStatus.IN_PROGRESS

        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor.role.value if hasattr(actor.role, "value") else str(actor.role),
                action=AuditAction.ADMIN_EVENT_STARTED,
                entity_type="event",
                entity_id=str(event.id),
                previous_state={"status": EventStatus.SCHEDULED.value},
                new_state={
                    "status": EventStatus.IN_PROGRESS.value,
                    "admin_reason": admin_req.reason,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await db.flush()
        return event

    # -----------------------------------------------------------------------
    # 2. Post-Event Report Submission & Conclude Event
    # -----------------------------------------------------------------------

    @classmethod
    async def complete_and_submit_report(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        report_in: PostEventReportCreate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[Event, PostEventReport]:
        """
        Declare event execution finished (COMPLETED) and submit post-event report.
        Transitions Event status to COMPLETED and creates PostEventReport in SUBMITTED status.
        Emits notification to the club's designated Faculty Advisor.
        """
        event = await cls._resolve_event(db, event_id, for_update=True)

        # Verify club secretary
        await cls._verify_secretary_ownership(
            db, event.club_id, actor, "complete event and submit report"
        )

        # Status validation: Event must be IN_PROGRESS or SCHEDULED
        if event.status not in (EventStatus.IN_PROGRESS, EventStatus.SCHEDULED):
            st = event.status.value if hasattr(event.status, "value") else str(event.status)
            if event.status == EventStatus.COMPLETED:
                raise ConflictError("Event is already marked COMPLETED.")
            raise WorkflowStateError(f"Cannot complete event in '{st}' status.")

        # Check existing report for idempotency
        existing_report = await db.scalar(
            select(PostEventReport).where(PostEventReport.event_id == event.id)
        )
        if existing_report:
            if existing_report.status in (
                PostEventReportStatus.SUBMITTED,
                PostEventReportStatus.CERTIFIED,
            ):
                raise ConflictError(
                    "A post-event report has already been submitted for this event."
                )
            elif existing_report.status == PostEventReportStatus.REVISION_REQUIRED:
                raise WorkflowStateError(
                    "A report already exists and requires revision. Use the resubmit endpoint."
                )

        now_utc = datetime.now(UTC)
        report = PostEventReport(
            id=uuid.uuid4(),
            event_id=event.id,
            revision_number=1,
            actual_attendance=report_in.actual_attendance,
            summary=report_in.summary,
            objectives_achieved=report_in.objectives_achieved,
            outcomes=report_in.outcomes,
            challenges=report_in.challenges,
            status=PostEventReportStatus.SUBMITTED,
            submitted_by=actor.id,
            submitted_at=now_utc,
        )
        db.add(report)

        # Transition Event to COMPLETED
        event.status = EventStatus.COMPLETED

        # Audit logs
        actor_role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role,
                action=AuditAction.EVENT_COMPLETED,
                entity_type="event",
                entity_id=str(event.id),
                previous_state={
                    "status": event.status.value
                    if hasattr(event.status, "value")
                    else str(event.status)
                },
                new_state={"status": EventStatus.COMPLETED.value},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role,
                action=AuditAction.POST_EVENT_REPORT_SUBMITTED,
                entity_type="post_event_report",
                entity_id=str(report.id),
                previous_state=None,
                new_state={
                    "event_id": str(event.id),
                    "revision_number": 1,
                    "actual_attendance": report.actual_attendance,
                    "status": PostEventReportStatus.SUBMITTED.value,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # Notify Faculty Advisor
        club = await db.scalar(select(Club).where(Club.id == event.club_id))
        if club and club.faculty_advisor_id:
            await NotificationService.create_notification(
                db=db,
                recipient_id=club.faculty_advisor_id,
                notification_type=NotificationType.POST_EVENT_REPORT_SUBMITTED,
                title="Post-Event Report Awaiting Delivery Certification",
                message=f"Secretary submitted report for '{event.title}'. Please verify delivery.",
                event_request_id=event.event_request_id,
            )

        await db.flush()
        return event, report

    # -----------------------------------------------------------------------
    # 3. Report Revision & Resubmission Lifecycle
    # -----------------------------------------------------------------------

    @classmethod
    async def update_report(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        update_in: PostEventReportUpdate,
        actor: User,
    ) -> PostEventReport:
        """
        Amend a report returned for revision.
        Only allowed when report status is REVISION_REQUIRED.
        """
        event = await cls._resolve_event(db, event_id)
        await cls._verify_secretary_ownership(db, event.club_id, actor, "edit this report")

        report = await db.scalar(
            select(PostEventReport).where(PostEventReport.event_id == event.id).with_for_update()
        )
        if not report:
            raise NotFoundError("Post-event report not found.")

        if report.status != PostEventReportStatus.REVISION_REQUIRED:
            st = report.status.value if hasattr(report.status, "value") else str(report.status)
            raise WorkflowStateError(
                f"Cannot edit report in '{st}' status. Must be in REVISION_REQUIRED status."
            )

        if update_in.actual_attendance is not None:
            report.actual_attendance = update_in.actual_attendance
        if update_in.summary is not None:
            report.summary = update_in.summary
        if update_in.objectives_achieved is not None:
            report.objectives_achieved = update_in.objectives_achieved
        if update_in.outcomes is not None:
            report.outcomes = update_in.outcomes
        if update_in.challenges is not None:
            report.challenges = update_in.challenges

        await db.flush()
        return report

    @classmethod
    async def resubmit_report(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PostEventReport:
        """
        Resubmit an amended report after revisions.
        Increments revision_number, snapshots historical state into AuditLog, and notifies Advisor.
        """
        event = await cls._resolve_event(db, event_id)
        await cls._verify_secretary_ownership(db, event.club_id, actor, "resubmit report")

        report = await db.scalar(
            select(PostEventReport).where(PostEventReport.event_id == event.id).with_for_update()
        )
        if not report:
            raise NotFoundError("Post-event report not found.")

        if report.status != PostEventReportStatus.REVISION_REQUIRED:
            st = report.status.value if hasattr(report.status, "value") else str(report.status)
            raise WorkflowStateError(
                f"Cannot resubmit report in '{st}' status. Must be in REVISION_REQUIRED status."
            )

        # Snapshot previous revision state into AuditLog
        prior_revision = report.revision_number
        report.revision_number += 1
        report.status = PostEventReportStatus.SUBMITTED
        report.submitted_at = datetime.now(UTC)

        actor_role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role,
                action=AuditAction.POST_EVENT_REPORT_SUBMITTED,
                entity_type="post_event_report",
                entity_id=str(report.id),
                previous_state={
                    "revision_number": prior_revision,
                    "status": PostEventReportStatus.REVISION_REQUIRED.value,
                },
                new_state={
                    "revision_number": report.revision_number,
                    "status": PostEventReportStatus.SUBMITTED.value,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # Notify Faculty Advisor of resubmission
        club = await db.scalar(select(Club).where(Club.id == event.club_id))
        if club and club.faculty_advisor_id:
            await NotificationService.create_notification(
                db=db,
                recipient_id=club.faculty_advisor_id,
                notification_type=NotificationType.POST_EVENT_REPORT_SUBMITTED,
                title="Revised Post-Event Report Resubmitted",
                message=f"Resubmitted report v{report.revision_number} for '{event.title}'.",
                event_request_id=event.event_request_id,
            )

        await db.flush()
        return report

    # -----------------------------------------------------------------------
    # 4. Faculty Advisor Delivery Certification
    # -----------------------------------------------------------------------

    @classmethod
    async def certify_report(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        certify_in: PostEventReportCertify,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PostEventReport:
        """
        Faculty Advisor certifies event delivery.
        Statutory role non-bypassable: only assigned advisor can certify.
        """
        event = await cls._resolve_event(db, event_id)
        report = await db.scalar(
            select(PostEventReport).where(PostEventReport.event_id == event.id).with_for_update()
        )
        if not report:
            raise NotFoundError("Post-event report not found.")

        # Self-certification check (Conflict of Interest)
        if report.submitted_by == actor.id:
            raise ForbiddenError(
                "Access denied: Submitter cannot certify own report (Conflict of Interest)."
            )

        # Verify advisor statutory authority
        await cls._verify_advisor_eligibility(db, event.club_id, actor, "certify event delivery")

        if report.status != PostEventReportStatus.SUBMITTED:
            st = report.status.value if hasattr(report.status, "value") else str(report.status)
            if report.status == PostEventReportStatus.CERTIFIED:
                raise ConflictError("Report has already been certified.")
            raise WorkflowStateError(f"Cannot certify report in '{st}' status. Must be SUBMITTED.")

        now_utc = datetime.now(UTC)
        report.status = PostEventReportStatus.CERTIFIED
        report.certified_by = actor.id
        report.certified_at = now_utc
        report.certification_remarks = certify_in.remarks

        actor_role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role,
                action=AuditAction.POST_EVENT_REPORT_CERTIFIED,
                entity_type="post_event_report",
                entity_id=str(report.id),
                previous_state={"status": PostEventReportStatus.SUBMITTED.value},
                new_state={
                    "status": PostEventReportStatus.CERTIFIED.value,
                    "certified_by": str(actor.id),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # Notify submitter (Club Secretary)
        await NotificationService.create_notification(
            db=db,
            recipient_id=report.submitted_by,
            notification_type=NotificationType.POST_EVENT_REPORT_CERTIFIED,
            title="Post-Event Delivery Certified",
            message=f"Faculty Advisor has formally certified delivery for event '{event.title}'.",
            event_request_id=event.event_request_id,
        )

        await db.flush()
        return report

    @classmethod
    async def request_revision(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        revision_in: PostEventReportRevisionRequest,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PostEventReport:
        """
        Faculty Advisor requests corrections to post-event report.
        Remarks are mandatory (>= 5 chars).
        """
        event = await cls._resolve_event(db, event_id)
        report = await db.scalar(
            select(PostEventReport).where(PostEventReport.event_id == event.id).with_for_update()
        )
        if not report:
            raise NotFoundError("Post-event report not found.")

        if report.submitted_by == actor.id:
            raise ForbiddenError("Access denied: Submitter cannot act on their own report.")

        await cls._verify_advisor_eligibility(db, event.club_id, actor, "request report revision")

        if report.status != PostEventReportStatus.SUBMITTED:
            st = report.status.value if hasattr(report.status, "value") else str(report.status)
            raise WorkflowStateError(
                f"Cannot request revision on report in '{st}' status. Must be SUBMITTED."
            )

        report.status = PostEventReportStatus.REVISION_REQUIRED
        report.certification_remarks = revision_in.remarks

        actor_role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role,
                action=AuditAction.POST_EVENT_REPORT_REVISION_REQUESTED,
                entity_type="post_event_report",
                entity_id=str(report.id),
                previous_state={"status": PostEventReportStatus.SUBMITTED.value},
                new_state={
                    "status": PostEventReportStatus.REVISION_REQUIRED.value,
                    "remarks": revision_in.remarks,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # Notify submitter of requested revision
        await NotificationService.create_notification(
            db=db,
            recipient_id=report.submitted_by,
            notification_type=NotificationType.POST_EVENT_REPORT_REVISION_REQUESTED,
            title="Post-Event Report Revision Requested",
            message=f"Advisor requested revisions for '{event.title}': {revision_in.remarks}",
            event_request_id=event.event_request_id,
        )

        await db.flush()
        return report

    # -----------------------------------------------------------------------
    # 5. Queries
    # -----------------------------------------------------------------------

    @classmethod
    async def get_report(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
    ) -> PostEventReport:
        """Retrieve the post-event report for an event."""
        event = await cls._resolve_event(db, event_id)
        report = await db.scalar(
            select(PostEventReport).where(PostEventReport.event_id == event.id)
        )
        if not report:
            raise NotFoundError(f"Post-event report for event '{event_id}' not found.")
        return report

    @classmethod
    async def get_confirmed_event(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
    ) -> Event:
        """Retrieve confirmed event details."""
        return await cls._resolve_event(db, event_id)
