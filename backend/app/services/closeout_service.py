"""
CampusConnect - Event Closeout & Archival Service (Phase 2.4)

Authoritative institutional closeout business layer for:
- Authoritative institutional closure eligibility computation
- Closeout request initiation by active Club Secretary with ownership guards & idempotency
- Statutory closure certification by Dean / Principal (or Faculty Advisor via delegation)
  with row-locking, prerequisite recomputation, explicit venue clearance attestation,
  and deterministic canonical SHA-256 certificate manifest generation
- Rejection of closure requests with mandatory rationale, returning event to COMPLETED
- Controlled event reopening petition (Secretary, Advisor, Finance Officer) and statutory
  approval (Dean, Principal), capturing immutable EventClosureRevision snapshots and
  synchronously unsealing the financial settlement
- Safe revision numbering with pessimistic row-locking and collision safety
- Archival of finalized events strictly restricted to System Administrators
- Strict closed-event immutability enforcement preventing downstream mutations
- Append-only audit logging and transactional in-app notifications
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    BadRequestError,
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    InvalidWorkflowTransitionError,
    NotFoundError,
    ResourceOwnershipError,
)
from app.models.domain import (
    AuditLog,
    Club,
    ClubMember,
    Event,
    EventClosure,
    EventClosureRevision,
    FinancialSettlement,
    HallBookingConfirmed,
    PostEventReport,
    User,
)
from app.models.enums import (
    AuditAction,
    ClubMemberRole,
    EventStatus,
    NotificationType,
    PostEventReportStatus,
    SettlementStatus,
    UserRole,
)
from app.services.notification_service import NotificationService
from app.services.settlement_service import SettlementService


def _val(x: Any) -> str:
    """Safely extract string value from Enum or str."""
    return x.value if hasattr(x, "value") else str(x)


def ensure_event_mutable(event: Event) -> None:
    """
    Enforce that an event in CLOSED or ARCHIVED status cannot be modified.
    Raises ConflictError (HTTP 409).
    """
    if event.status in (EventStatus.CLOSED, EventStatus.ARCHIVED):
        status_str = _val(event.status)
        raise ConflictError(
            f"Event '{event.id}' is in terminal status '{status_str}' and cannot be modified."
        )


class CloseoutService:
    """Authoritative institutional closeout business layer for CampusConnect Phase 2.4."""

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    @classmethod
    async def _get_event(
        cls, db: AsyncSession, event_id: uuid.UUID, for_update: bool = False
    ) -> Event:
        """Fetch Event by primary key or event_request_id, optionally row-locking."""
        stmt = select(Event).where((Event.id == event_id) | (Event.event_request_id == event_id))
        if for_update:
            stmt = stmt.with_for_update()
        event = await db.scalar(stmt)
        if not event:
            raise NotFoundError(f"Confirmed event '{event_id}' not found.")
        return event

    @classmethod
    async def _verify_secretary_ownership(
        cls, db: AsyncSession, event: Event, actor: User
    ) -> None:
        """
        Enforce that actor is the active CLUB_SECRETARY of the owning club.
        System Admin has no secretary powers.
        """
        if actor.role == UserRole.SYSTEM_ADMIN:
            raise ForbiddenError(
                "System administrators are strictly barred from acting as club secretaries."
            )
        member = await db.scalar(
            select(ClubMember).where(
                ClubMember.club_id == event.club_id,
                ClubMember.user_id == actor.id,
                ClubMember.member_role == ClubMemberRole.SECRETARY,
                ClubMember.is_active.is_(True),
            )
        )
        if not member:
            raise ResourceOwnershipError(
                "Only the active Club Secretary of the owning club can perform this action "
                "for this event."
            )

    @classmethod
    async def _verify_certifier_authority(
        cls, db: AsyncSession, event: Event, actor: User
    ) -> None:
        """
        Enforce statutory closeout certification authority.
        Allowed: DEAN_STUDENT_AFFAIRS, PRINCIPAL.
        Optional configurable delegation: FACULTY_ADVISOR only when closeout delegation is active
        and assigned to the owning club.
        SYSTEM_ADMIN is strictly forbidden (403).
        """
        if actor.role == UserRole.SYSTEM_ADMIN:
            raise ForbiddenError(
                "System administrators are strictly barred from certifying event closeout."
            )

        if actor.role == UserRole.FACULTY_ADVISOR:
            settings = get_settings()
            if not settings.ALLOW_ADVISOR_EVENT_CLOSEOUT:
                raise ForbiddenError(
                    "Faculty Advisors are not permitted to certify event closure under "
                    "current institutional policy."
                )
            club = await db.scalar(select(Club).where(Club.id == event.club_id))
            if not club or club.faculty_advisor_id != actor.id:
                raise ForbiddenError(
                    "Only the designated Faculty Advisor for the owning club can certify closeout."
                )
            return

        if actor.role not in (UserRole.DEAN_STUDENT_AFFAIRS, UserRole.PRINCIPAL):
            raise ForbiddenError(
                f"User role '{_val(actor.role)}' is not authorized to certify event closeout."
            )

    @classmethod
    async def _verify_reopen_petition_authority(
        cls, db: AsyncSession, event: Event, actor: User
    ) -> None:
        """
        Enforce reopen petition authority.
        Allowed petitioners: CLUB_SECRETARY, FACULTY_ADVISOR, FINANCE_OFFICER.
        SYSTEM_ADMIN is strictly forbidden (403).
        """
        if actor.role == UserRole.SYSTEM_ADMIN:
            raise ForbiddenError(
                "System administrators cannot petition for event reopening."
            )

        if actor.role == UserRole.FINANCE_OFFICER:
            return

        if actor.role == UserRole.FACULTY_ADVISOR:
            club = await db.scalar(select(Club).where(Club.id == event.club_id))
            if not club or club.faculty_advisor_id != actor.id:
                raise ForbiddenError(
                    "Only the designated Faculty Advisor for this club can petition for reopening."
                )
            return

        # Check if active secretary of owning club
        member = await db.scalar(
            select(ClubMember).where(
                ClubMember.club_id == event.club_id,
                ClubMember.user_id == actor.id,
                ClubMember.member_role == ClubMemberRole.SECRETARY,
                ClubMember.is_active.is_(True),
            )
        )
        if not member:
            raise ForbiddenError(
                "Only the active Club Secretary, Faculty Advisor of the owning club, or a "
                "Finance Officer may petition to reopen a closed event."
            )

    @classmethod
    def _create_audit_entry(
        cls,
        db: AsyncSession,
        actor: User,
        action: AuditAction,
        entity_type: str,
        entity_id: uuid.UUID | str,
        previous_state: dict[str, Any] | None,
        new_state: dict[str, Any] | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Record an immutable state transition in the system audit log."""
        actor_role_str = _val(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id),
                previous_state=previous_state,
                new_state=new_state,
                ip_address=ip_address,
                user_agent=user_agent,
                created_at=datetime.now(UTC),
            )
        )

    # =========================================================================
    # ELIGIBILITY EVALUATION
    # =========================================================================

    @classmethod
    async def get_closure_eligibility(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
    ) -> dict[str, Any]:
        """
        Authoritative evaluation of institutional closeout prerequisites.
        Reuses SettlementService.get_closure_eligibility for financial and report checks,
        and adds institutional venue booking checks and structural state checks.
        Never mutates Event or settlement state.
        """
        event = await cls._get_event(db, event_id, for_update=False)

        # Check event cancellation / soft-delete
        blockers: list[str] = []
        if getattr(event, "is_deleted", False):
            blockers.append("EVENT_DELETED")
        if event.cancelled_at is not None or event.status == EventStatus.CANCELLED:
            blockers.append("EVENT_CANCELLED")

        # Reuse SettlementService.get_closure_eligibility for financial & report state
        settlement_elig = await SettlementService.get_closure_eligibility(db, event.id, actor)
        for b in settlement_elig.get("blockers", []):
            # If event is in CLOSURE_REQUESTED, CLOSED, or ARCHIVED, it has passed completion
            if b == "EVENT_NOT_COMPLETED" and event.status in (
                EventStatus.CLOSURE_REQUESTED,
                EventStatus.CLOSED,
                EventStatus.ARCHIVED,
            ):
                continue
            if b not in blockers:
                blockers.append(b)

        # Confirmed hall booking end-time check
        booking = await db.scalar(
            select(HallBookingConfirmed).where(
                HallBookingConfirmed.event_request_id == event.event_request_id,
                HallBookingConfirmed.is_active.is_(True),
            )
        )
        has_booking = booking is not None
        booking_ended = False
        if booking:
            now_utc = datetime.now(UTC)
            booking_ended = booking.end_time <= now_utc
            if not booking_ended:
                blockers.append("VENUE_BOOKING_NOT_ENDED")

        report = await db.scalar(
            select(PostEventReport).where(PostEventReport.event_id == event.id)
        )
        settlement = await db.scalar(
            select(FinancialSettlement).where(FinancialSettlement.event_id == event.id)
        )

        return {
            "eligible": len(blockers) == 0,
            "blockers": blockers,
            "warnings": [],
            "event_status": _val(event.status),
            "settlement_status": _val(settlement.status) if settlement else None,
            "report_status": _val(report.status) if report else None,
            "venue_status": {
                "has_booking": has_booking,
                "booking_ended": booking_ended,
                "hall_id": str(event.hall_id) if event.hall_id else None,
            },
            "event_id": str(event.id),
            "settlement_id": str(settlement.id) if settlement else None,
            "report_id": str(report.id) if report else None,
        }

    @classmethod
    async def get_closure_details(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
    ) -> dict[str, Any]:
        """
        Retrieve comprehensive closeout state, eligibility, active closure,
        reopening revisions, and request history.
        Enforces viewer authorization via SettlementService._verify_event_viewer.
        """
        event = await cls._get_event(db, event_id, for_update=False)
        await SettlementService._verify_event_viewer(db, event, actor)

        eligibility = await cls.get_closure_eligibility(db, event.id, actor)

        closure = await db.scalar(
            select(EventClosure).where(EventClosure.event_id == event.id)
        )

        revisions = list(
            (
                await db.scalars(
                    select(EventClosureRevision)
                    .where(EventClosureRevision.event_id == event.id)
                    .order_by(EventClosureRevision.revision_number.asc())
                )
            ).all()
        )

        latest_req_audit = await db.scalar(
            select(AuditLog)
            .where(
                AuditLog.entity_id == str(event.id),
                AuditLog.action == AuditAction.CLOSURE_REQUESTED,
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        latest_request = None
        if latest_req_audit:
            remarks = None
            if latest_req_audit.new_state and isinstance(latest_req_audit.new_state, dict):
                remarks = latest_req_audit.new_state.get("remarks")
            latest_request = {
                "requested_by": latest_req_audit.actor_id,
                "requested_at": latest_req_audit.created_at,
                "remarks": remarks,
            }

        return {
            "event_id": event.id,
            "event_status": event.status,
            "is_archived": event.status == EventStatus.ARCHIVED,
            "eligibility": eligibility,
            "closure": closure,
            "revisions": revisions,
            "latest_request": latest_request,
        }

    # =========================================================================
    # CLOSEOUT REQUEST
    # =========================================================================

    @classmethod
    async def request_closeout(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
        remarks: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """
        Active Club Secretary initiates institutional event closeout.
        Enforces:
        - Pessimistic row lock on Event
        - Ownership / scoping: actor must be active secretary of the owning club
        - Idempotency: if already CLOSURE_REQUESTED, returns existing state safely
        - Prerequisites: EventStatus == COMPLETED and all eligibility gates pass
        - Transition: COMPLETED -> CLOSURE_REQUESTED
        - AuditLog: CLOSURE_REQUESTED
        - Notification: EVENT_CLOSURE_REQUESTED to institutional certifiers
        """
        event = await cls._get_event(db, event_id, for_update=True)
        await cls._verify_secretary_ownership(db, event, actor)

        # Idempotency check
        if event.status == EventStatus.CLOSURE_REQUESTED:
            return {
                "event_id": str(event.id),
                "status": EventStatus.CLOSURE_REQUESTED.value,
                "message": "Event closeout has already been requested.",
            }

        if event.status != EventStatus.COMPLETED:
            raise InvalidWorkflowTransitionError(
                f"Cannot request closeout for event in '{_val(event.status)}' status. "
                "Event must be in 'COMPLETED' status."
            )

        # Re-compute eligibility inside the transaction
        eligibility = await cls.get_closure_eligibility(db, event.id, actor)
        if not eligibility["eligible"]:
            raise BusinessRuleError(
                f"Event is not eligible for closeout: {', '.join(eligibility['blockers'])}"
            )

        prev_state = {"status": _val(event.status)}
        event.status = EventStatus.CLOSURE_REQUESTED

        # Record audit log
        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.CLOSURE_REQUESTED,
            entity_type="event",
            entity_id=event.id,
            previous_state=prev_state,
            new_state={
                "status": EventStatus.CLOSURE_REQUESTED.value,
                "remarks": remarks.strip() if remarks else None,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Notify statutory certifiers
        settings = get_settings()
        certifier_roles = [UserRole.DEAN_STUDENT_AFFAIRS, UserRole.PRINCIPAL]
        certifiers = (
            await db.scalars(
                select(User).where(
                    User.role.in_(certifier_roles),
                    User.is_active.is_(True),
                )
            )
        ).all()

        recipients = list(certifiers)
        if settings.ALLOW_ADVISOR_EVENT_CLOSEOUT:
            club = await db.scalar(select(Club).where(Club.id == event.club_id))
            if club and club.faculty_advisor_id:
                advisor = await db.scalar(
                    select(User).where(User.id == club.faculty_advisor_id, User.is_active.is_(True))
                )
                if advisor and advisor not in recipients:
                    recipients.append(advisor)

        for certifier in recipients:
            await NotificationService.create_notification(
                db=db,
                recipient_id=certifier.id,
                notification_type=NotificationType.EVENT_CLOSURE_REQUESTED,
                title="Event Closeout Requested",
                message=f"Closeout requested for event '{event.title}' by {actor.email}.",
                event_request_id=event.event_request_id,
            )

        await db.flush()
        return {
            "event_id": str(event.id),
            "status": EventStatus.CLOSURE_REQUESTED.value,
            "message": "Event closeout successfully requested.",
        }

    # =========================================================================
    # CLOSURE CERTIFICATION
    # =========================================================================

    @classmethod
    async def certify_closeout(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
        closure_notes: str | None = None,
        venue_cleared: bool = False,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EventClosure:
        """
        Dean, Principal, or delegated Faculty Advisor certifies closeout.
        Enforces:
        - Pessimistic row lock on Event
        - Authority verification: Dean/Principal or Advisor (if configured)
        - System Admin is strictly barred (403)
        - Re-checks EventStatus == CLOSURE_REQUESTED
        - Recomputes full closure eligibility
        - Explicit venue_cleared == True attestation is mandatory
        - Generates deterministic 64-char SHA-256 certificate manifest hash
        - Persists EventClosure record
        - Transitions EventStatus: CLOSURE_REQUESTED -> CLOSED
        - AuditLog: EVENT_CLOSED
        - Notification: EVENT_CLOSED
        """
        event = await cls._get_event(db, event_id, for_update=True)
        await cls._verify_certifier_authority(db, event, actor)

        if not venue_cleared:
            raise BusinessRuleError(
                "Explicit venue clearance attestation (venue_cleared=True) is mandatory "
                "to certify event closeout."
            )

        if event.status != EventStatus.CLOSURE_REQUESTED:
            raise InvalidWorkflowTransitionError(
                f"Cannot certify event in '{_val(event.status)}' status. "
                "Event must be in 'CLOSURE_REQUESTED' status."
            )

        # Re-check eligibility
        eligibility = await cls.get_closure_eligibility(db, event.id, actor)
        if not eligibility["eligible"]:
            raise BusinessRuleError(
                f"Event closeout eligibility check failed: {', '.join(eligibility['blockers'])}"
            )

        settlement = await db.scalar(
            select(FinancialSettlement).where(FinancialSettlement.event_id == event.id)
        )
        if not settlement or settlement.status != SettlementStatus.SETTLED:
            raise BusinessRuleError("Financial settlement is not in SETTLED status.")

        report = await db.scalar(
            select(PostEventReport).where(PostEventReport.event_id == event.id)
        )
        if not report or report.status != PostEventReportStatus.CERTIFIED:
            raise BusinessRuleError("Post-event report is not in CERTIFIED status.")

        # Resolve requested_by and requested_at from the latest CLOSURE_REQUESTED audit log
        closure_req_audit = await db.scalar(
            select(AuditLog)
            .where(
                AuditLog.entity_id == str(event.id),
                AuditLog.action == AuditAction.CLOSURE_REQUESTED,
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        requested_by = closure_req_audit.actor_id if closure_req_audit else None
        requested_at = closure_req_audit.created_at if closure_req_audit else None

        # Build canonical manifest payload & deterministic SHA-256 digest
        manifest_payload = {
            "certified_by": str(actor.id),
            "club_id": str(event.club_id),
            "event_id": str(event.id),
            "event_request_id": str(event.event_request_id),
            "institutional_payout": str(settlement.institutional_payout),
            "post_event_report_id": str(report.id),
            "sanctioned_grant": str(settlement.sanctioned_grant),
            "settlement_balance": str(settlement.settlement_balance),
            "settlement_id": str(settlement.id),
            "total_verified_expenditure": str(settlement.total_verified_expenditure),
            "total_verified_income": str(settlement.total_verified_income),
            "venue_cleared": True,
        }
        canonical_json = json.dumps(manifest_payload, sort_keys=True, separators=(",", ":"))
        manifest_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        now_utc = datetime.now(UTC)

        # Persist EventClosure (insert or update on re-closure)
        closure = await db.scalar(
            select(EventClosure).where(EventClosure.event_id == event.id)
        )
        if not closure:
            closure = EventClosure(
                id=uuid.uuid4(),
                event_id=event.id,
                settlement_id=settlement.id,
                post_event_report_id=report.id,
                requested_by=requested_by,
                requested_at=requested_at,
                certified_by=actor.id,
                certified_at=now_utc,
                closure_notes=closure_notes.strip() if closure_notes else None,
                venue_cleared=True,
                certificate_manifest_hash=manifest_hash,
            )
            db.add(closure)
        else:
            closure.settlement_id = settlement.id
            closure.post_event_report_id = report.id
            closure.requested_by = requested_by
            closure.requested_at = requested_at
            closure.certified_by = actor.id
            closure.certified_at = now_utc
            closure.closure_notes = closure_notes.strip() if closure_notes else None
            closure.venue_cleared = True
            closure.certificate_manifest_hash = manifest_hash

        prev_state = {"status": _val(event.status)}
        event.status = EventStatus.CLOSED

        await db.flush()

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.EVENT_CLOSED,
            entity_type="event",
            entity_id=event.id,
            previous_state=prev_state,
            new_state={
                "status": EventStatus.CLOSED.value,
                "closure_id": str(closure.id),
                "certificate_manifest_hash": manifest_hash,
                "venue_cleared": True,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Notify club members / secretary
        sec_members = (
            await db.scalars(
                select(ClubMember).where(
                    ClubMember.club_id == event.club_id,
                    ClubMember.member_role == ClubMemberRole.SECRETARY,
                    ClubMember.is_active.is_(True),
                )
            )
        ).all()
        for sec in sec_members:
            await NotificationService.create_notification(
                db=db,
                recipient_id=sec.user_id,
                notification_type=NotificationType.EVENT_CLOSED,
                title="Event Certified Closed",
                message=f"Event '{event.title}' has been certified closed by {actor.email}.",
                event_request_id=event.event_request_id,
            )

        return closure

    # =========================================================================
    # CLOSURE REJECTION
    # =========================================================================

    @classmethod
    async def reject_closeout(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
        reason: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Event:
        """
        Institutional authority rejects closure request.
        Mandatory reason. Returns event to COMPLETED.
        Preserves rejection in AuditLog.
        Generates EVENT_CLOSURE_REJECTED notification.
        """
        if not reason or not reason.strip():
            raise BadRequestError("Rejection reason is mandatory.")

        event = await cls._get_event(db, event_id, for_update=True)
        await cls._verify_certifier_authority(db, event, actor)

        if event.status != EventStatus.CLOSURE_REQUESTED:
            raise InvalidWorkflowTransitionError(
                f"Cannot reject closeout for event in '{_val(event.status)}' status. "
                "Event must be in 'CLOSURE_REQUESTED' status."
            )

        prev_state = {"status": _val(event.status)}
        event.status = EventStatus.COMPLETED

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.CLOSURE_REJECTED,
            entity_type="event",
            entity_id=event.id,
            previous_state=prev_state,
            new_state={
                "status": EventStatus.COMPLETED.value,
                "rejection_reason": reason.strip(),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Notify club secretaries
        sec_members = (
            await db.scalars(
                select(ClubMember).where(
                    ClubMember.club_id == event.club_id,
                    ClubMember.member_role == ClubMemberRole.SECRETARY,
                    ClubMember.is_active.is_(True),
                )
            )
        ).all()
        for sec in sec_members:
            await NotificationService.create_notification(
                db=db,
                recipient_id=sec.user_id,
                notification_type=NotificationType.EVENT_CLOSURE_REJECTED,
                title="Event Closeout Rejected",
                message=(
                    f"Closeout for event '{event.title}' was rejected by {actor.email}. "
                    f"Reason: {reason.strip()}"
                ),
                event_request_id=event.event_request_id,
            )

        await db.flush()
        return event

    # =========================================================================
    # REOPEN REQUEST (PETITION)
    # =========================================================================

    @classmethod
    async def request_reopen(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
        reason: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """
        Stage 1 of reopening: Petition by Secretary, Faculty Advisor, or Finance Officer.
        Mandatory reason.
        Event must be in CLOSED status.
        System Admin is strictly forbidden (403).
        AuditLog: EVENT_REOPEN_REQUESTED
        Notification sent to Dean and Principal.
        EventStatus remains CLOSED until approved.
        """
        if not reason or not reason.strip():
            raise BadRequestError("Reopening petition reason is mandatory.")

        event = await cls._get_event(db, event_id, for_update=True)
        await cls._verify_reopen_petition_authority(db, event, actor)

        if event.status != EventStatus.CLOSED:
            raise InvalidWorkflowTransitionError(
                f"Cannot petition to reopen event in '{_val(event.status)}' status. "
                "Only 'CLOSED' events can be petitioned for reopening."
            )

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.EVENT_REOPEN_REQUESTED,
            entity_type="event",
            entity_id=event.id,
            previous_state={"status": EventStatus.CLOSED.value},
            new_state={
                "status": EventStatus.CLOSED.value,
                "petition_reason": reason.strip(),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Notify Dean and Principal
        executives = (
            await db.scalars(
                select(User).where(
                    User.role.in_([UserRole.DEAN_STUDENT_AFFAIRS, UserRole.PRINCIPAL]),
                    User.is_active.is_(True),
                )
            )
        ).all()
        for exec_user in executives:
            await NotificationService.create_notification(
                db=db,
                recipient_id=exec_user.id,
                notification_type=NotificationType.EVENT_CLOSURE_REQUESTED,
                title="Event Reopening Petition Submitted",
                message=(
                    f"Petition to reopen closed event '{event.title}' submitted by "
                    f"{actor.email}. Reason: {reason.strip()}"
                ),
                event_request_id=event.event_request_id,
            )

        await db.flush()
        return {
            "event_id": str(event.id),
            "status": EventStatus.CLOSED.value,
            "message": "Event reopening petition submitted successfully.",
        }

    # =========================================================================
    # REOPEN APPROVAL
    # =========================================================================

    @classmethod
    async def approve_reopen(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
        reason: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EventClosureRevision:
        """
        Stage 2 of reopening: Approved strictly by Dean of Student Affairs or Principal.
        Enforces:
        - Pessimistic row lock on Event
        - Authority: DEAN_STUDENT_AFFAIRS or PRINCIPAL ONLY. System Admin 403.
        - Event must be CLOSED
        - Sequential, collision-safe revision numbering: UNIQUE(event_id, revision_number)
        - Immutable EventClosureRevision snapshot captured
        - EventStatus transitions: CLOSED -> COMPLETED
        - Financial settlement transitions: SETTLED -> REOPENED via reopen_settlement
        - AuditLog: EVENT_REOPENED
        - Notification: EVENT_REOPENED
        """
        if not reason or not reason.strip():
            raise BadRequestError("Reopen approval reason is mandatory.")

        if actor.role == UserRole.SYSTEM_ADMIN:
            raise ForbiddenError(
                "System administrators are strictly barred from approving event reopening."
            )
        if actor.role not in (UserRole.DEAN_STUDENT_AFFAIRS, UserRole.PRINCIPAL):
            raise ForbiddenError(
                "Only the Dean of Student Affairs or the Principal can approve event reopening."
            )

        event = await cls._get_event(db, event_id, for_update=True)

        if event.status != EventStatus.CLOSED:
            raise InvalidWorkflowTransitionError(
                f"Cannot approve reopen for event in '{_val(event.status)}' status. "
                "Event must be in 'CLOSED' status."
            )

        closure = await db.scalar(
            select(EventClosure).where(EventClosure.event_id == event.id).with_for_update()
        )
        if not closure:
            raise BusinessRuleError("Cannot reopen event: institutional closeout record missing.")

        settlement = await db.scalar(
            select(FinancialSettlement)
            .where(FinancialSettlement.id == closure.settlement_id)
            .with_for_update()
        )
        if not settlement:
            raise BusinessRuleError("Cannot reopen event: financial settlement record missing.")

        # Determine next revision number safely inside locked event transaction
        rev_count = (
            await db.scalar(
                select(func.count())
                .select_from(EventClosureRevision)
                .where(EventClosureRevision.event_id == event.id)
            )
            or 0
        )
        next_revision = rev_count + 1

        now_utc = datetime.now(UTC)

        snapshot_data = {
            "closure_id": str(closure.id),
            "event_id": str(event.id),
            "certified_by": str(closure.certified_by),
            "certified_at": closure.certified_at.isoformat(),
            "certificate_manifest_hash": closure.certificate_manifest_hash,
            "closure_notes": closure.closure_notes,
            "venue_cleared": closure.venue_cleared,
            "settlement_id": str(closure.settlement_id),
            "post_event_report_id": str(closure.post_event_report_id),
            "requested_by": str(closure.requested_by) if closure.requested_by else None,
            "requested_at": closure.requested_at.isoformat() if closure.requested_at else None,
            "settlement_snapshot": {
                "status": _val(settlement.status),
                "sanctioned_grant": str(settlement.sanctioned_grant),
                "total_verified_expenditure": str(settlement.total_verified_expenditure),
                "total_verified_income": str(settlement.total_verified_income),
                "institutional_payout": str(settlement.institutional_payout),
                "settlement_balance": str(settlement.settlement_balance),
            },
            "reopened_by": str(actor.id),
            "reopened_at": now_utc.isoformat(),
            "reopening_reason": reason.strip(),
        }

        revision = EventClosureRevision(
            id=uuid.uuid4(),
            event_id=event.id,
            closure_id=closure.id,
            revision_number=next_revision,
            reopened_by=actor.id,
            reopened_at=now_utc,
            reopening_reason=reason.strip(),
            snapshot_data=snapshot_data,
            created_at=now_utc,
        )
        db.add(revision)

        prev_state = {"status": _val(event.status)}
        event.status = EventStatus.COMPLETED

        # Synchronously unseal the financial settlement using canonical settlement reopen
        await SettlementService.reopen_settlement(
            db=db,
            settlement_id=settlement.id,
            reopening_reason=reason.strip(),
            actor=actor,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.EVENT_REOPENED,
            entity_type="event",
            entity_id=event.id,
            previous_state=prev_state,
            new_state={
                "status": EventStatus.COMPLETED.value,
                "revision_number": next_revision,
                "reopened_by": str(actor.id),
                "reopening_reason": reason.strip(),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Notify club secretaries
        sec_members = (
            await db.scalars(
                select(ClubMember).where(
                    ClubMember.club_id == event.club_id,
                    ClubMember.member_role == ClubMemberRole.SECRETARY,
                    ClubMember.is_active.is_(True),
                )
            )
        ).all()
        for sec in sec_members:
            await NotificationService.create_notification(
                db=db,
                recipient_id=sec.user_id,
                notification_type=NotificationType.EVENT_REOPENED,
                title="Event Reopened",
                message=(
                    f"Event '{event.title}' has been reopened by {actor.email}. "
                    f"Reason: {reason.strip()}"
                ),
                event_request_id=event.event_request_id,
            )

        await db.flush()
        return revision

    # =========================================================================
    # ARCHIVAL
    # =========================================================================

    @classmethod
    async def archive_event(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Event:
        """
        System Administrator archives a CLOSED event.
        Enforces:
        - Authority: SYSTEM_ADMIN ONLY.
        - Event must be in CLOSED status.
        - EventClosure must exist.
        - Idempotent if already ARCHIVED.
        - Logical state change only (no physical deletion).
        - AuditLog: EVENT_ARCHIVED.
        """
        if actor.role != UserRole.SYSTEM_ADMIN:
            raise ForbiddenError(
                "Only System Administrators are authorized to archive closed events."
            )

        event = await cls._get_event(db, event_id, for_update=True)

        if event.status == EventStatus.ARCHIVED:
            return event

        if event.status != EventStatus.CLOSED:
            raise InvalidWorkflowTransitionError(
                f"Cannot archive event in '{_val(event.status)}' status. "
                "Only 'CLOSED' events can be archived."
            )

        closure = await db.scalar(
            select(EventClosure).where(EventClosure.event_id == event.id)
        )
        if not closure:
            raise BusinessRuleError("Cannot archive event: institutional closeout record missing.")

        prev_state = {"status": _val(event.status)}
        event.status = EventStatus.ARCHIVED

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.EVENT_ARCHIVED,
            entity_type="event",
            entity_id=event.id,
            previous_state=prev_state,
            new_state={"status": EventStatus.ARCHIVED.value},
            ip_address=ip_address,
            user_agent=user_agent,
        )

        await db.flush()
        return event
