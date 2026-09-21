"""
CampusConnect - Financial Settlement Service (Phase 2.3)

Authoritative financial business layer for:
- Cash Advance requisition, approval, and full disbursement tracking
- Actual Income recording, evidence verification, and rejection
- Authoritative accounting engine with locked formulas:
    V = SUM(verified expenses)
    I_actual = SUM(verified income)
    NetDeficit = max(0, V - I_actual)
    P = min(G_sanctioned, NetDeficit)
    B = P - A
    B > 0 -> REIMBURSEMENT_DUE
    B < 0 -> REFUND_DUE
    B = 0 -> BALANCED
- Immutable sanctioned financial snapshot capture from approved EventRequestVersion
- Complete settlement preparation with eligibility gates & pessimistic row locks
- Stale-data protection (verifies live source consistency before submission & approval)
- Finance audit (query & approval)
- Settlement payment recording, directional enforcement & automatic settlement clearance
- Controlled settlement reopening with immutable revisions (Event remains COMPLETED)
- Read-only institutional closure eligibility evaluation
- Strict Segregation of Duties (SOD):
    Club Secretary: submits requests/claims/records/prepares own club event
    Finance Officer: verifies/approves/disburses/audits/records payments/reopens
    Principal: exceptional reopening
    System Admin: strictly barred from financial verifications, approvals, payments
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    BadRequestError,
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    InvalidWorkflowTransitionError,
    NotFoundError,
    WorkflowStateError,
)
from app.models.domain import (
    ActualExpense,
    ActualIncome,
    AuditLog,
    BudgetProposal,
    CashAdvance,
    ClubMember,
    Document,
    Event,
    EventRequestVersion,
    FinancialSettlement,
    PostEventReport,
    SettlementPayment,
    SettlementRevision,
    User,
)
from app.models.enums import (
    ActualExpenseStatus,
    ActualIncomeStatus,
    AuditAction,
    CashAdvanceStatus,
    ClubMemberRole,
    DocumentType,
    EventStatus,
    IncomeSourceType,
    NotificationType,
    PaymentMethod,
    PostEventReportStatus,
    SettlementPaymentType,
    SettlementStatus,
    SettlementType,
    UserRole,
)
from app.services.notification_service import NotificationService


def _val(x: Any) -> str:
    """Safely extract string value from Enum or str."""
    return x.value if hasattr(x, "value") else str(x)


class SettlementStaleDataError(BusinessRuleError):
    """Raised when underlying financial records have changed after settlement preparation."""


class SettlementService:
    """Authoritative financial business layer for CampusConnect Phase 2.3."""

    # =========================================================================
    # INTERNAL HELPERS & AUTHORIZATION
    # =========================================================================

    @classmethod
    def _verify_finance_officer(cls, actor: User) -> None:
        """
        Enforce that only a FINANCE_OFFICER can perform financial actions.
        SYSTEM_ADMIN is explicitly and strictly barred.
        """
        if actor.role == UserRole.SYSTEM_ADMIN:
            raise ForbiddenError(
                "System administrators are strictly barred from financial verifications, "
                "approvals, disbursements, and settlement decisions."
            )
        if actor.role != UserRole.FINANCE_OFFICER:
            raise ForbiddenError(
                "Only Finance Officers are authorized to perform this financial action."
            )

    @classmethod
    def _verify_reopen_authority(cls, actor: User) -> None:
        """
        Enforce that only FINANCE_OFFICER or PRINCIPAL can reopen a settled settlement.
        SYSTEM_ADMIN is barred.
        """
        if actor.role == UserRole.SYSTEM_ADMIN:
            raise ForbiddenError(
                "System administrators are strictly barred from reopening financial settlements."
            )
        if actor.role not in (UserRole.FINANCE_OFFICER, UserRole.PRINCIPAL):
            raise ForbiddenError(
                "Only Finance Officers and the Principal are authorized to reopen a settlement."
            )

    @classmethod
    async def _verify_club_secretary(cls, db: AsyncSession, event: Event, actor: User) -> None:
        """
        Enforce that actor is the designated active CLUB_SECRETARY of the owning club.
        SYSTEM_ADMIN has no secretary powers.
        """
        if actor.role == UserRole.SYSTEM_ADMIN:
            raise ForbiddenError(
                "System administrators have no ordinary club secretary execution authority."
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
            raise ForbiddenError(
                "Only the active Club Secretary of the owning club can perform this action "
                "for this event."
            )

    @classmethod
    async def _verify_event_viewer(cls, db: AsyncSession, event: Event, actor: User) -> None:
        """
        Verify read-only access to event financial details.
        Finance Officer, Admin, Principal, and Club members can view.
        """
        if actor.role in (
            UserRole.FINANCE_OFFICER,
            UserRole.SYSTEM_ADMIN,
            UserRole.PRINCIPAL,
            UserRole.DEAN_STUDENT_AFFAIRS,
            UserRole.ADVISOR_STUDENTS_UNION,
        ):
            return

        # Check club membership
        member = await db.scalar(
            select(ClubMember).where(
                ClubMember.club_id == event.club_id,
                ClubMember.user_id == actor.id,
                ClubMember.is_active.is_(True),
            )
        )
        if not member:
            raise ForbiddenError("You are not authorized to view financial records for this event.")

    @classmethod
    async def _get_confirmed_event(
        cls, db: AsyncSession, event_id: uuid.UUID, for_update: bool = False
    ) -> Event:
        """Fetch Event by primary key, optionally acquiring a row lock."""
        stmt = select(Event).where(Event.id == event_id)
        if for_update:
            stmt = stmt.with_for_update()
        event = await db.scalar(stmt)
        if not event:
            raise NotFoundError(f"Event '{event_id}' not found.")
        return event

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
        """Record a state transition in the system audit log."""
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
            )
        )

    # =========================================================================
    # SANCTIONED SNAPSHOT RESOLUTION
    # =========================================================================

    @classmethod
    async def _resolve_sanctioned_snapshot(
        cls, db: AsyncSession, event: Event
    ) -> tuple[uuid.UUID, Decimal, Decimal, Decimal]:
        """
        Resolve the immutable sanctioned financial snapshot from the approved EventRequestVersion.
        Returns: (approved_version_id, sanctioned_grant, sanctioned_expenditure, expected_income)
        """
        approved_version = None
        if event.approved_version_id:
            approved_version = await db.scalar(
                select(EventRequestVersion).where(
                    EventRequestVersion.id == event.approved_version_id
                )
            )

        if not approved_version:
            approved_version = await db.scalar(
                select(EventRequestVersion)
                .where(EventRequestVersion.event_request_id == event.event_request_id)
                .order_by(EventRequestVersion.version_number.desc())
            )

        if not approved_version or not approved_version.snapshot:
            # Fallback: check BudgetProposal if snapshot was not serialized in older test data
            bp = await db.scalar(
                select(BudgetProposal).where(
                    BudgetProposal.event_request_id == event.event_request_id
                )
            )
            if bp:
                return (
                    approved_version.id if approved_version else event.id,
                    Decimal(str(bp.institute_contribution)),
                    Decimal(str(bp.total_expected_expenditure)),
                    Decimal(str(bp.expected_income)),
                )
            raise BusinessRuleError(
                "Authoritative approved EventRequestVersion financial snapshot cannot be "
                "identified for this event."
            )

        snapshot = approved_version.snapshot
        budget = snapshot.get("budget") or {}

        grant_val = (
            budget.get("institute_contribution")
            or snapshot.get("institute_contribution")
            or snapshot.get("sanctioned_grant")
        )
        exp_val = (
            budget.get("total_expected_expenditure")
            or snapshot.get("total_expected_expenditure")
            or snapshot.get("sanctioned_expenditure")
        )
        inc_val = budget.get("expected_income") or snapshot.get("expected_income") or "0.00"

        if grant_val is None or exp_val is None:
            # Check BudgetProposal before failing
            bp = await db.scalar(
                select(BudgetProposal).where(
                    BudgetProposal.event_request_id == event.event_request_id
                )
            )
            if bp:
                return (
                    approved_version.id,
                    Decimal(str(bp.institute_contribution)),
                    Decimal(str(bp.total_expected_expenditure)),
                    Decimal(str(bp.expected_income)),
                )
            raise BusinessRuleError(
                "Authoritative sanctioned budget figures missing in approved version snapshot."
            )

        return (
            approved_version.id,
            Decimal(str(grant_val)),
            Decimal(str(exp_val)),
            Decimal(str(inc_val)),
        )

    # =========================================================================
    # CASH ADVANCE SERVICE
    # =========================================================================

    @classmethod
    async def request_advance(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        amount_requested: Decimal,
        reason: str,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> CashAdvance:
        """
        Club Secretary requests a cash advance for an event.
        One advance per event invariant enforced.
        """
        event = await cls._get_confirmed_event(db, event_id, for_update=True)
        await cls._verify_club_secretary(db, event, actor)

        if event.cancelled_at is not None or event.status == EventStatus.CANCELLED:
            raise WorkflowStateError("Cannot request cash advance for a cancelled event.")

        # Check if financially settled
        existing_settlement = await db.scalar(
            select(FinancialSettlement).where(FinancialSettlement.event_id == event.id)
        )
        if existing_settlement and existing_settlement.status == SettlementStatus.SETTLED:
            raise WorkflowStateError("Cannot request cash advance for an already settled event.")

        # Invariant: single advance per event
        existing_advance = await db.scalar(
            select(CashAdvance).where(CashAdvance.event_id == event.id)
        )
        if existing_advance:
            raise ConflictError("A cash advance has already been requested for this event.")

        if amount_requested <= Decimal("0.00"):
            raise BadRequestError("Advance amount requested must be greater than zero.")

        advance = CashAdvance(
            id=uuid.uuid4(),
            event_id=event.id,
            amount_requested=amount_requested,
            amount_approved=None,
            amount_disbursed=Decimal("0.00"),
            status=CashAdvanceStatus.REQUESTED,
            recipient_id=actor.id,
            notes=reason.strip() if reason else None,
        )
        db.add(advance)
        await db.flush()

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.ADVANCE_REQUESTED,
            entity_type="cash_advance",
            entity_id=advance.id,
            previous_state=None,
            new_state={
                "event_id": str(event.id),
                "amount_requested": str(amount_requested),
                "reason": reason,
                "status": CashAdvanceStatus.REQUESTED.value,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return advance

    @classmethod
    async def approve_advance(
        cls,
        db: AsyncSession,
        advance_id: uuid.UUID,
        amount_approved: Decimal,
        actor: User,
        remarks: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> CashAdvance:
        """
        Finance Officer approves a cash advance request.
        Row-locks the CashAdvance.
        Validates: 0 < amount_approved <= sanctioned_grant.
        """
        cls._verify_finance_officer(actor)

        advance = await db.scalar(
            select(CashAdvance).where(CashAdvance.id == advance_id).with_for_update()
        )
        if not advance:
            raise NotFoundError(f"Cash advance '{advance_id}' not found.")

        if advance.status != CashAdvanceStatus.REQUESTED:
            raise InvalidWorkflowTransitionError(
                f"Cannot approve advance in '{advance.status}' status. Must be 'REQUESTED'."
            )

        if amount_approved <= Decimal("0.00"):
            raise BadRequestError("Approved advance amount must be greater than zero.")

        event = await cls._get_confirmed_event(db, advance.event_id)
        _, sanctioned_grant, _, _ = await cls._resolve_sanctioned_snapshot(db, event)

        if amount_approved > sanctioned_grant:
            raise BusinessRuleError(
                f"Approved advance amount ({amount_approved}) cannot exceed sanctioned "
                f"institutional grant ({sanctioned_grant})."
            )

        prev_state = {
            "status": _val(advance.status),
            "amount_approved": str(advance.amount_approved) if advance.amount_approved else None,
        }

        advance.amount_approved = amount_approved
        advance.approved_by = actor.id
        advance.status = CashAdvanceStatus.APPROVED
        if remarks:
            advance.notes = f"{advance.notes or ''} [Approval Notes: {remarks.strip()}]".strip()

        await db.flush()

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.ADVANCE_APPROVED,
            entity_type="cash_advance",
            entity_id=advance.id,
            previous_state=prev_state,
            new_state={
                "status": CashAdvanceStatus.APPROVED.value,
                "amount_approved": str(amount_approved),
                "remarks": remarks,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        await NotificationService.create_notification(
            db=db,
            recipient_id=advance.recipient_id,
            notification_type=NotificationType.ADVANCE_APPROVED,
            title="Cash Advance Approved",
            message=(
                f"Your cash advance request of ₹{amount_approved} " "has been approved by Finance."
            ),
            event_request_id=event.event_request_id,
        )

        return advance

    @classmethod
    async def reject_advance(
        cls,
        db: AsyncSession,
        advance_id: uuid.UUID,
        rejection_reason: str,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> CashAdvance:
        """
        Finance Officer rejects a cash advance request. Mandatory rejection reason.
        """
        cls._verify_finance_officer(actor)

        advance = await db.scalar(
            select(CashAdvance).where(CashAdvance.id == advance_id).with_for_update()
        )
        if not advance:
            raise NotFoundError(f"Cash advance '{advance_id}' not found.")

        if advance.status != CashAdvanceStatus.REQUESTED:
            raise InvalidWorkflowTransitionError(
                f"Cannot reject advance in '{advance.status}' status. Must be 'REQUESTED'."
            )

        if not rejection_reason or not rejection_reason.strip():
            raise BadRequestError("Rejection reason is mandatory.")

        prev_state = {"status": _val(advance.status)}

        advance.status = CashAdvanceStatus.REJECTED
        advance.approved_by = actor.id
        advance.rejection_reason = rejection_reason.strip()

        await db.flush()

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.ADVANCE_REJECTED,
            entity_type="cash_advance",
            entity_id=advance.id,
            previous_state=prev_state,
            new_state={
                "status": CashAdvanceStatus.REJECTED.value,
                "rejection_reason": rejection_reason,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        event = await cls._get_confirmed_event(db, advance.event_id)
        await NotificationService.create_notification(
            db=db,
            recipient_id=advance.recipient_id,
            notification_type=NotificationType.ADVANCE_REJECTED,
            title="Cash Advance Rejected",
            message=(
                f"Your cash advance request was rejected by Finance. " f"Reason: {rejection_reason}"
            ),
            event_request_id=event.event_request_id,
        )

        return advance

    @classmethod
    async def disburse_advance(
        cls,
        db: AsyncSession,
        advance_id: uuid.UUID,
        amount_disbursed: Decimal,
        payment_reference: str,
        disbursement_date: datetime | None,
        actor: User,
        notes: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> CashAdvance:
        """
        Finance Officer records the disbursement of an approved advance.
        Locked rule: amount_disbursed == amount_approved.
        """
        cls._verify_finance_officer(actor)

        advance = await db.scalar(
            select(CashAdvance).where(CashAdvance.id == advance_id).with_for_update()
        )
        if not advance:
            raise NotFoundError(f"Cash advance '{advance_id}' not found.")

        if advance.status != CashAdvanceStatus.APPROVED:
            raise InvalidWorkflowTransitionError(
                f"Cannot disburse advance in '{advance.status}' status. Must be 'APPROVED'."
            )

        if not payment_reference or not payment_reference.strip():
            raise BadRequestError("Payment reference is required for cash advance disbursement.")

        if amount_disbursed <= Decimal("0.00"):
            raise BadRequestError("Disbursed amount must be greater than zero.")

        if advance.amount_approved is None or amount_disbursed != advance.amount_approved:
            raise BusinessRuleError(
                f"Partial or excess disbursement not permitted. Disbursed amount "
                f"({amount_disbursed}) must strictly equal approved amount "
                f"({advance.amount_approved})."
            )

        prev_state = {
            "status": _val(advance.status),
            "amount_disbursed": str(advance.amount_disbursed),
        }

        d_date = disbursement_date or datetime.now(UTC)
        if d_date.tzinfo is None:
            d_date = d_date.replace(tzinfo=UTC)

        advance.amount_disbursed = amount_disbursed
        advance.disbursed_by = actor.id
        advance.disbursement_date = d_date
        advance.payment_reference = payment_reference.strip()
        advance.status = CashAdvanceStatus.DISBURSED
        if notes:
            advance.notes = f"{advance.notes or ''} [Disbursement Notes: {notes.strip()}]".strip()

        await db.flush()

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.ADVANCE_DISBURSED,
            entity_type="cash_advance",
            entity_id=advance.id,
            previous_state=prev_state,
            new_state={
                "status": CashAdvanceStatus.DISBURSED.value,
                "amount_disbursed": str(amount_disbursed),
                "payment_reference": payment_reference,
                "disbursement_date": d_date.isoformat(),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        event = await cls._get_confirmed_event(db, advance.event_id)
        await NotificationService.create_notification(
            db=db,
            recipient_id=advance.recipient_id,
            notification_type=NotificationType.ADVANCE_DISBURSED,
            title="Cash Advance Disbursed",
            message=f"Cash advance of ₹{amount_disbursed} disbursed (Ref: {payment_reference}).",
            event_request_id=event.event_request_id,
        )

        return advance

    # =========================================================================
    # ACTUAL INCOME LEDGER
    # =========================================================================

    @classmethod
    async def record_income(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        source_type: IncomeSourceType | str,
        amount: Decimal,
        description: str,
        payer_name: str,
        received_date: date,
        evidence_document_id: uuid.UUID,
        actor: User,
        reference_number: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActualIncome:
        """
        Club Secretary records self-generated income for an event.
        Enforces evidence document validity and strict event ownership.
        """
        event = await cls._get_confirmed_event(db, event_id, for_update=True)
        await cls._verify_club_secretary(db, event, actor)

        if event.cancelled_at is not None or event.status == EventStatus.CANCELLED:
            raise WorkflowStateError("Cannot record income for a cancelled event.")

        existing_settlement = await db.scalar(
            select(FinancialSettlement).where(FinancialSettlement.event_id == event.id)
        )
        if existing_settlement and existing_settlement.status == SettlementStatus.SETTLED:
            raise WorkflowStateError("Cannot record income for an already settled event.")

        if amount <= Decimal("0.00"):
            raise BadRequestError("Income amount must be greater than zero.")

        if not description or not description.strip():
            raise BadRequestError("Income description is required.")

        if not payer_name or not payer_name.strip():
            raise BadRequestError("Payer name is required.")

        # Verify evidence document
        doc = await db.scalar(
            select(Document).where(
                Document.id == evidence_document_id,
                Document.is_active.is_(True),
            )
        )
        if not doc:
            raise NotFoundError(
                f"Evidence document '{evidence_document_id}' not found or inactive."
            )

        if doc.document_type != DocumentType.INCOME_EVIDENCE:
            raise BadRequestError("Document must have DocumentType.INCOME_EVIDENCE.")

        if doc.event_id != event.id and doc.event_request_id != event.event_request_id:
            raise BadRequestError(
                "Income evidence document does not belong to this event "
                "(cross-event reuse forbidden)."
            )

        src_str = _val(source_type)
        income = ActualIncome(
            id=uuid.uuid4(),
            event_id=event.id,
            source_type=src_str,
            description=description.strip(),
            payer_name=payer_name.strip(),
            amount=amount,
            received_date=received_date,
            reference_number=reference_number.strip() if reference_number else None,
            evidence_document_id=evidence_document_id,
            status=ActualIncomeStatus.RECORDED,
            recorded_by=actor.id,
        )
        db.add(income)
        await db.flush()

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.INCOME_RECORDED,
            entity_type="actual_income",
            entity_id=income.id,
            previous_state=None,
            new_state={
                "event_id": str(event.id),
                "source_type": src_str,
                "amount": str(amount),
                "payer_name": payer_name,
                "evidence_document_id": str(evidence_document_id),
                "status": ActualIncomeStatus.RECORDED.value,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return income

    @classmethod
    async def verify_income(
        cls,
        db: AsyncSession,
        income_id: uuid.UUID,
        actor: User,
        finance_remarks: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActualIncome:
        """
        Finance Officer verifies recorded income.
        Secretary self-verification and System Admin verification strictly forbidden.
        """
        cls._verify_finance_officer(actor)

        income = await db.scalar(
            select(ActualIncome).where(ActualIncome.id == income_id).with_for_update()
        )
        if not income:
            raise NotFoundError(f"Actual income '{income_id}' not found.")

        if actor.id == income.recorded_by:
            raise ForbiddenError("Club Secretary cannot self-verify recorded income.")

        if income.status != ActualIncomeStatus.RECORDED:
            raise InvalidWorkflowTransitionError(
                f"Cannot verify income in '{income.status}' status. Must be 'RECORDED'."
            )

        prev_state = {"status": _val(income.status)}

        income.status = ActualIncomeStatus.VERIFIED
        income.verified_by = actor.id
        income.verified_at = datetime.now(UTC)
        income.finance_remarks = finance_remarks.strip() if finance_remarks else None

        await db.flush()

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.INCOME_VERIFIED,
            entity_type="actual_income",
            entity_id=income.id,
            previous_state=prev_state,
            new_state={
                "status": ActualIncomeStatus.VERIFIED.value,
                "amount": str(income.amount),
                "finance_remarks": finance_remarks,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        event = await cls._get_confirmed_event(db, income.event_id)
        await NotificationService.create_notification(
            db=db,
            recipient_id=income.recorded_by,
            notification_type=NotificationType.INCOME_VERIFIED,
            title="Actual Income Verified",
            message=(
                f"Income entry of ₹{income.amount} ({income.description}) "
                "was verified by Finance."
            ),
            event_request_id=event.event_request_id,
        )

        return income

    @classmethod
    async def reject_income(
        cls,
        db: AsyncSession,
        income_id: uuid.UUID,
        rejection_reason: str,
        actor: User,
        finance_remarks: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActualIncome:
        """
        Finance Officer rejects recorded income. Mandatory rejection reason.
        """
        cls._verify_finance_officer(actor)

        income = await db.scalar(
            select(ActualIncome).where(ActualIncome.id == income_id).with_for_update()
        )
        if not income:
            raise NotFoundError(f"Actual income '{income_id}' not found.")

        if actor.id == income.recorded_by:
            raise ForbiddenError(
                "Club Secretary cannot reject own recorded income via audit action."
            )

        if income.status != ActualIncomeStatus.RECORDED:
            raise InvalidWorkflowTransitionError(
                f"Cannot reject income in '{income.status}' status. Must be 'RECORDED'."
            )

        if not rejection_reason or not rejection_reason.strip():
            raise BadRequestError("Rejection reason is mandatory.")

        prev_state = {"status": _val(income.status)}

        remarks_combined = f"REJECTED: {rejection_reason.strip()}"
        if finance_remarks:
            remarks_combined = f"{remarks_combined}. {finance_remarks.strip()}"

        income.status = ActualIncomeStatus.REJECTED
        income.verified_by = actor.id
        income.verified_at = datetime.now(UTC)
        income.finance_remarks = remarks_combined

        await db.flush()

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.INCOME_REJECTED,
            entity_type="actual_income",
            entity_id=income.id,
            previous_state=prev_state,
            new_state={
                "status": ActualIncomeStatus.REJECTED.value,
                "rejection_reason": rejection_reason,
                "finance_remarks": remarks_combined,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        event = await cls._get_confirmed_event(db, income.event_id)
        await NotificationService.create_notification(
            db=db,
            recipient_id=income.recorded_by,
            notification_type=NotificationType.INCOME_REJECTED,
            title="Actual Income Rejected",
            message=f"Income entry of ₹{income.amount} was rejected by Finance. "
            f"Reason: {rejection_reason}",
            event_request_id=event.event_request_id,
        )

        return income

    # =========================================================================
    # SETTLEMENT PREPARATION & CALCULATION ENGINE
    # =========================================================================

    # =========================================================================
    # SOURCE FINGERPRINTING & STALE PROTECTION
    # =========================================================================

    @classmethod
    def _compute_source_fingerprint(
        cls,
        approved_version_id: uuid.UUID,
        sanctioned_grant: Decimal,
        expenses: list[ActualExpense],
        incomes: list[ActualIncome],
        advance: CashAdvance | None,
    ) -> str:
        """
        Compute deterministic SHA-256 fingerprint over all underlying source records.
        Detects:
        - Expense replacement with same total
        - Expense addition/removal
        - Expense status substitution
        - Claimed or verified amount changes
        - Income replacement with same total
        - Income status or amount changes
        - Advance mutation
        - Approved EventRequestVersion change
        """
        sorted_expenses = [
            {
                "id": str(e.id),
                "status": _val(e.status),
                "claimed_amount": f"{Decimal(str(e.claimed_amount)):.2f}",
                "verified_amount": (
                    f"{Decimal(str(e.verified_amount)):.2f}"
                    if e.verified_amount is not None
                    else None
                ),
            }
            for e in sorted(expenses, key=lambda x: str(x.id))
        ]

        sorted_incomes = [
            {
                "id": str(i.id),
                "status": _val(i.status),
                "amount": f"{Decimal(str(i.amount)):.2f}",
            }
            for i in sorted(incomes, key=lambda x: str(x.id))
        ]

        advance_data = None
        if advance:
            advance_data = {
                "id": str(advance.id),
                "status": _val(advance.status),
                "amount_approved": (
                    f"{Decimal(str(advance.amount_approved)):.2f}"
                    if advance.amount_approved is not None
                    else None
                ),
                "amount_disbursed": (
                    f"{Decimal(str(advance.amount_disbursed)):.2f}"
                    if advance.amount_disbursed is not None
                    else None
                ),
            }

        payload = {
            "approved_version_id": str(approved_version_id),
            "sanctioned_grant": f"{Decimal(str(sanctioned_grant)):.2f}",
            "expenses": sorted_expenses,
            "incomes": sorted_incomes,
            "advance": advance_data,
        }

        canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    @classmethod
    async def _get_prepared_source_fingerprint(
        cls, db: AsyncSession, settlement: FinancialSettlement
    ) -> str | None:
        """
        Retrieve the source fingerprint captured at the most recent settlement preparation.
        Checks in-memory attribute first, then queries the latest SETTLEMENT_PREPARED AuditLog.
        """
        cached = getattr(settlement, "_source_fingerprint", None)
        if cached:
            return str(cached)

        stmt = (
            select(AuditLog)
            .where(
                AuditLog.entity_type == "financial_settlement",
                AuditLog.entity_id == settlement.id,
                AuditLog.action == AuditAction.SETTLEMENT_PREPARED,
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        log_entry = await db.scalar(stmt)
        if log_entry and isinstance(log_entry.new_state, dict):
            fp = log_entry.new_state.get("source_fingerprint")
            if fp:
                settlement._source_fingerprint = str(fp)
                return str(fp)

        return None

    @classmethod
    async def _compute_settlement_totals(
        cls,
        db: AsyncSession,
        event: Event,
        sanctioned_grant: Decimal,
        settlement: FinancialSettlement | None = None,
    ) -> dict[str, Any]:
        """
        Execute the authoritative cumulative accounting formulas against live database records.
        Returns calculated dictionary of Decimal, status values, and underlying record sets.
        """
        # 1. Inspect ActualExpenses
        expenses = (
            await db.scalars(select(ActualExpense).where(ActualExpense.event_id == event.id))
        ).all()

        unresolved_exp = [
            e
            for e in expenses
            if e.status
            in (
                ActualExpenseStatus.DRAFT,
                ActualExpenseStatus.SUBMITTED,
                ActualExpenseStatus.QUERIED,
            )
        ]
        if unresolved_exp:
            statuses = {_val(e.status) for e in unresolved_exp}
            raise BusinessRuleError(
                f"Settlement cannot be prepared while {len(unresolved_exp)} expense claim(s) "
                f"remain unresolved (statuses: {', '.join(statuses)}). Every claim "
                "must be terminal (VERIFIED, PARTIALLY_VERIFIED, or DISALLOWED)."
            )

        total_claimed = Decimal("0.00")
        total_verified = Decimal("0.00")
        total_disallowed = Decimal("0.00")

        for exp in expenses:
            c_amt = Decimal(str(exp.claimed_amount))
            total_claimed += c_amt

            if exp.status in (ActualExpenseStatus.VERIFIED, ActualExpenseStatus.PARTIALLY_VERIFIED):
                v_amt = (
                    Decimal(str(exp.verified_amount)) if exp.verified_amount is not None else c_amt
                )
                total_verified += v_amt
                if c_amt > v_amt:
                    total_disallowed += c_amt - v_amt
            elif exp.status == ActualExpenseStatus.DISALLOWED:
                total_disallowed += c_amt

        # 2. Inspect ActualIncomes
        incomes = (
            await db.scalars(select(ActualIncome).where(ActualIncome.event_id == event.id))
        ).all()

        unresolved_inc = [inc for inc in incomes if inc.status == ActualIncomeStatus.RECORDED]
        if unresolved_inc:
            raise BusinessRuleError(
                f"Settlement cannot be prepared while {len(unresolved_inc)} income entry(ies) "
                "remain in RECORDED status. All must be VERIFIED or REJECTED by Finance."
            )

        total_income = Decimal("0.00")
        for inc in incomes:
            if inc.status == ActualIncomeStatus.VERIFIED:
                total_income += Decimal(str(inc.amount))

        # 3. Inspect CashAdvance
        advance = await db.scalar(select(CashAdvance).where(CashAdvance.event_id == event.id))
        if advance and advance.status in (CashAdvanceStatus.REQUESTED, CashAdvanceStatus.APPROVED):
            raise BusinessRuleError(
                f"Cash advance for this event is still in '{advance.status}' status. "
                "Advance must be fully DISBURSED or REJECTED before settlement preparation."
            )

        disbursed_advance = (
            Decimal(str(advance.amount_disbursed))
            if advance and advance.status == CashAdvanceStatus.DISBURSED
            else Decimal("0.00")
        )

        # 4. Authoritative Locked Cumulative Formulas
        # V = total_verified
        # I_actual = total_income
        # NetDeficit = max(0, V - I_actual)
        # P_entitled = min(G, NetDeficit)
        net_deficit = max(Decimal("0.00"), total_verified - total_income)
        institutional_payout = min(sanctioned_grant, net_deficit)

        # 5. Cumulative Historical Payment Reconciliation across All Revisions
        target_settlement = settlement
        if target_settlement is None:
            target_settlement = await db.scalar(
                select(FinancialSettlement).where(FinancialSettlement.event_id == event.id)
            )

        r_cleared = Decimal("0.00")
        f_cleared = Decimal("0.00")
        if target_settlement:
            existing_payments = (
                await db.scalars(
                    select(SettlementPayment).where(
                        SettlementPayment.settlement_id == target_settlement.id
                    )
                )
            ).all()
            for p in existing_payments:
                p_type = _val(p.payment_type)
                if p_type == SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value:
                    r_cleared += Decimal(str(p.amount))
                elif p_type == SettlementPaymentType.ADVANCE_REFUND_RECEIPT.value:
                    f_cleared += Decimal(str(p.amount))

        net_cash_transferred = disbursed_advance + r_cleared - f_cleared
        settlement_balance = institutional_payout - net_cash_transferred

        if settlement_balance > Decimal("0.00"):
            reimbursement_due = settlement_balance
            refund_due = Decimal("0.00")
            settlement_type = SettlementType.REIMBURSEMENT_DUE
        elif settlement_balance < Decimal("0.00"):
            reimbursement_due = Decimal("0.00")
            refund_due = abs(settlement_balance)
            settlement_type = SettlementType.REFUND_DUE
        else:
            reimbursement_due = Decimal("0.00")
            refund_due = Decimal("0.00")
            settlement_type = SettlementType.BALANCED

        return {
            "total_claimed_expenditure": total_claimed,
            "total_verified_expenditure": total_verified,
            "total_disallowed_expenditure": total_disallowed,
            "total_verified_income": total_income,
            "net_deficit": net_deficit,
            "institutional_payout": institutional_payout,
            "cash_advance_disbursed": disbursed_advance,
            "r_cleared": r_cleared,
            "f_cleared": f_cleared,
            "net_cash_transferred": net_cash_transferred,
            "settlement_balance": settlement_balance,
            "reimbursement_due": reimbursement_due,
            "refund_due": refund_due,
            "settlement_type": settlement_type,
            "expenses": expenses,
            "incomes": incomes,
            "advance": advance,
        }

    @classmethod
    async def prepare_settlement(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FinancialSettlement:
        """
        Club Secretary prepares the draft financial settlement.
        Pessimistically locks the Event.
        Validates all eligibility gates:
        1. Event.status == COMPLETED
        2. PostEventReport.status == CERTIFIED
        3. Zero unresolved expenses
        4. Zero unverified income
        5. No pending unresolved cash advance
        6. Single active settlement invariant
        7. Authoritative approved snapshot resolution
        8. Record-level source fingerprint generation
        """
        event = await cls._get_confirmed_event(db, event_id, for_update=True)
        await cls._verify_club_secretary(db, event, actor)

        if event.status != EventStatus.COMPLETED:
            raise WorkflowStateError(
                f"Event must be in COMPLETED status to prepare settlement "
                f"(current: '{event.status}')."
            )

        report = await db.scalar(
            select(PostEventReport).where(PostEventReport.event_id == event.id)
        )
        if not report or report.status != PostEventReportStatus.CERTIFIED:
            raise WorkflowStateError(
                "Financial settlement preparation is blocked until the designated Faculty Advisor "
                "has certified delivery of the post-event report."
            )

        existing_settlement = await db.scalar(
            select(FinancialSettlement)
            .where(FinancialSettlement.event_id == event.id)
            .with_for_update()
        )
        if existing_settlement and existing_settlement.status != SettlementStatus.REOPENED:
            raise ConflictError(
                "A financial settlement already exists for this event. "
                "Duplicate settlements are forbidden."
            )

        version_id, grant, exp, inc = await cls._resolve_sanctioned_snapshot(db, event)
        totals = await cls._compute_settlement_totals(
            db, event, grant, settlement=existing_settlement
        )

        source_fingerprint = cls._compute_source_fingerprint(
            version_id, grant, totals["expenses"], totals["incomes"], totals["advance"]
        )

        if existing_settlement and existing_settlement.status == SettlementStatus.REOPENED:
            # Re-compile existing settlement record after reopening
            settlement = existing_settlement
            settlement.approved_version_id = version_id
            settlement.sanctioned_grant = grant
            settlement.sanctioned_expenditure = exp
            settlement.expected_income = inc
            settlement.total_claimed_expenditure = totals["total_claimed_expenditure"]
            settlement.total_verified_expenditure = totals["total_verified_expenditure"]
            settlement.total_disallowed_expenditure = totals["total_disallowed_expenditure"]
            settlement.total_verified_income = totals["total_verified_income"]
            settlement.net_deficit = totals["net_deficit"]
            settlement.institutional_payout = totals["institutional_payout"]
            settlement.cash_advance_disbursed = totals["cash_advance_disbursed"]
            settlement.settlement_balance = totals["settlement_balance"]
            settlement.reimbursement_due = totals["reimbursement_due"]
            settlement.refund_due = totals["refund_due"]
            settlement.settlement_type = totals["settlement_type"]
            settlement.status = SettlementStatus.DRAFT
            settlement.prepared_by = actor.id
            settlement.query_reason = None
        else:
            settlement = FinancialSettlement(
                id=uuid.uuid4(),
                event_id=event.id,
                approved_version_id=version_id,
                sanctioned_grant=grant,
                sanctioned_expenditure=exp,
                expected_income=inc,
                total_claimed_expenditure=totals["total_claimed_expenditure"],
                total_verified_expenditure=totals["total_verified_expenditure"],
                total_disallowed_expenditure=totals["total_disallowed_expenditure"],
                total_verified_income=totals["total_verified_income"],
                net_deficit=totals["net_deficit"],
                institutional_payout=totals["institutional_payout"],
                cash_advance_disbursed=totals["cash_advance_disbursed"],
                settlement_balance=totals["settlement_balance"],
                reimbursement_due=totals["reimbursement_due"],
                refund_due=totals["refund_due"],
                settlement_type=totals["settlement_type"],
                status=SettlementStatus.DRAFT,
                prepared_by=actor.id,
            )
            db.add(settlement)

        settlement._source_fingerprint = source_fingerprint

        try:
            await db.flush()
        except IntegrityError as exc:
            raise ConflictError(
                "A financial settlement already exists for this event "
                "(database uniqueness violation)."
            ) from exc

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.SETTLEMENT_PREPARED,
            entity_type="financial_settlement",
            entity_id=settlement.id,
            previous_state=None,
            new_state={
                "event_id": str(event.id),
                "status": SettlementStatus.DRAFT.value,
                "sanctioned_grant": str(grant),
                "total_verified_expenditure": str(totals["total_verified_expenditure"]),
                "total_verified_income": str(totals["total_verified_income"]),
                "cash_advance_disbursed": str(totals["cash_advance_disbursed"]),
                "institutional_payout": str(totals["institutional_payout"]),
                "settlement_balance": str(totals["settlement_balance"]),
                "settlement_type": _val(totals["settlement_type"]),
                "approved_version_id": str(version_id),
                "source_fingerprint": source_fingerprint,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return settlement

    # =========================================================================
    # STALE DATA VERIFICATION
    # =========================================================================

    @classmethod
    async def _verify_live_source_consistency(
        cls, db: AsyncSession, settlement: FinancialSettlement, event: Event
    ) -> None:
        """
        Enforce stale-data protection:
        1. Verifies that approved_version_id has not changed.
        2. Verifies that the deterministic source fingerprint matches the prepared fingerprint.
        3. Verifies that current database inputs match the snapshotted settlement totals.
        Prevents approving or submitting stale calculations if underlying financial
        records were altered.
        """
        current_version_id, current_grant, _, _ = await cls._resolve_sanctioned_snapshot(
            db, event
        )
        current_totals = await cls._compute_settlement_totals(
            db, event, current_grant, settlement=settlement
        )

        mismatches: list[str] = []

        # 1. Approved EventRequestVersion check
        if settlement.approved_version_id != current_version_id:
            mismatches.append(
                f"Approved event proposal version changed "
                f"({settlement.approved_version_id} -> {current_version_id})"
            )

        # 2. Sanctioned grant check
        if settlement.sanctioned_grant != current_grant:
            mismatches.append(
                f"Sanctioned grant changed ({settlement.sanctioned_grant} -> {current_grant})"
            )

        # 3. Source fingerprint check
        current_fingerprint = cls._compute_source_fingerprint(
            current_version_id,
            current_grant,
            current_totals["expenses"],
            current_totals["incomes"],
            current_totals["advance"],
        )
        prepared_fingerprint = await cls._get_prepared_source_fingerprint(db, settlement)

        if prepared_fingerprint and current_fingerprint != prepared_fingerprint:
            mismatches.append(
                f"Source records fingerprint mismatch "
                f"(prepared: {prepared_fingerprint[:8]}..., live: {current_fingerprint[:8]}...)"
            )

        # 4. Aggregate totals check
        if settlement.total_verified_expenditure != current_totals["total_verified_expenditure"]:
            mismatches.append(
                f"Verified expenditure changed ({settlement.total_verified_expenditure} -> "
                f"{current_totals['total_verified_expenditure']})"
            )
        if settlement.total_verified_income != current_totals["total_verified_income"]:
            mismatches.append(
                f"Verified income changed ({settlement.total_verified_income} -> "
                f"{current_totals['total_verified_income']})"
            )
        if settlement.cash_advance_disbursed != current_totals["cash_advance_disbursed"]:
            mismatches.append(
                f"Disbursed advance changed ({settlement.cash_advance_disbursed} -> "
                f"{current_totals['cash_advance_disbursed']})"
            )

        if mismatches:
            raise SettlementStaleDataError(
                "Settlement source data has changed since preparation: "
                + "; ".join(mismatches)
                + ". The settlement calculation is stale and must be recalculated."
            )

    # =========================================================================
    # SETTLEMENT SUBMISSION
    # =========================================================================

    @classmethod
    async def submit_settlement(
        cls,
        db: AsyncSession,
        settlement_id: uuid.UUID,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FinancialSettlement:
        """
        Club Secretary submits the draft or queried settlement for Finance audit.
        Allowed: DRAFT -> UNDER_AUDIT, QUERIED -> UNDER_AUDIT, REOPENED -> UNDER_AUDIT.
        Enforces live source consistency (rejects stale submission).
        """
        settlement = await db.scalar(
            select(FinancialSettlement)
            .where(FinancialSettlement.id == settlement_id)
            .with_for_update()
        )
        if not settlement:
            raise NotFoundError(f"Financial settlement '{settlement_id}' not found.")

        event = await cls._get_confirmed_event(db, settlement.event_id)
        await cls._verify_club_secretary(db, event, actor)

        if settlement.status not in (
            SettlementStatus.DRAFT,
            SettlementStatus.QUERIED,
            SettlementStatus.REOPENED,
        ):
            raise InvalidWorkflowTransitionError(
                f"Cannot submit settlement in '{settlement.status}' status. "
                "Must be in DRAFT, QUERIED, or REOPENED status."
            )

        # Enforce source consistency against current live database rows
        await cls._verify_live_source_consistency(db, settlement, event)

        prev_state = {"status": _val(settlement.status)}

        settlement.status = SettlementStatus.UNDER_AUDIT
        settlement.submitted_at = datetime.now(UTC)

        await db.flush()

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.SETTLEMENT_SUBMITTED,
            entity_type="financial_settlement",
            entity_id=settlement.id,
            previous_state=prev_state,
            new_state={
                "status": SettlementStatus.UNDER_AUDIT.value,
                "submitted_at": settlement.submitted_at.isoformat(),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return settlement

    # =========================================================================
    # FINANCE AUDIT (QUERY & APPROVAL)
    # =========================================================================

    @classmethod
    async def audit_settlement(
        cls,
        db: AsyncSession,
        settlement_id: uuid.UUID,
        action: str,
        actor: User,
        remarks: str | None = None,
        query_reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FinancialSettlement:
        """
        Finance Officer audits the settlement under review.
        Actions: 'APPROVE' or 'QUERY'.
        SYSTEM_ADMIN is strictly barred from approving/querying.
        Under 'APPROVE':
        - If B == 0: transitions directly to SETTLED (no payments required).
        - If B > 0: transitions to PENDING_REIMBURSEMENT.
        - If B < 0: transitions to PENDING_REFUND.
        Under 'QUERY':
        - Requires mandatory query_reason; transitions to QUERIED.
        """
        cls._verify_finance_officer(actor)

        action_norm = action.strip().upper()
        if action_norm not in ("APPROVE", "QUERY"):
            raise BadRequestError("Audit action must be either 'APPROVE' or 'QUERY'.")

        settlement = await db.scalar(
            select(FinancialSettlement)
            .where(FinancialSettlement.id == settlement_id)
            .with_for_update()
        )
        if not settlement:
            raise NotFoundError(f"Financial settlement '{settlement_id}' not found.")

        if settlement.status != SettlementStatus.UNDER_AUDIT:
            raise InvalidWorkflowTransitionError(
                f"Cannot audit settlement in '{settlement.status}' status. Must be 'UNDER_AUDIT'."
            )

        event = await cls._get_confirmed_event(db, settlement.event_id)

        # Enforce source consistency: cannot approve or query if source records mutated
        await cls._verify_live_source_consistency(db, settlement, event)

        prev_state = {"status": _val(settlement.status)}

        if action_norm == "QUERY":
            if not query_reason or not query_reason.strip():
                raise BadRequestError("Query reason is mandatory when querying a settlement.")

            settlement.status = SettlementStatus.QUERIED
            settlement.query_reason = query_reason.strip()
            settlement.finance_remarks = remarks.strip() if remarks else settlement.finance_remarks

            await db.flush()

            cls._create_audit_entry(
                db=db,
                actor=actor,
                action=AuditAction.SETTLEMENT_QUERIED,
                entity_type="financial_settlement",
                entity_id=settlement.id,
                previous_state=prev_state,
                new_state={
                    "status": SettlementStatus.QUERIED.value,
                    "query_reason": query_reason,
                    "finance_remarks": remarks,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )

            await NotificationService.create_notification(
                db=db,
                recipient_id=settlement.prepared_by,
                notification_type=NotificationType.SETTLEMENT_QUERIED,
                title="Financial Settlement Queried",
                message=f"Finance queried the settlement for '{event.title}'. "
                f"Reason: {query_reason}",
                event_request_id=event.event_request_id,
            )

            return settlement

        # APPROVE action
        now = datetime.now(UTC)
        settlement.audited_by = actor.id
        settlement.audited_at = now
        settlement.finance_remarks = remarks.strip() if remarks else settlement.finance_remarks
        settlement.query_reason = None

        if settlement.settlement_type == SettlementType.BALANCED:
            # Balanced settlement requires no payments -> settles immediately
            settlement.status = SettlementStatus.SETTLED
            target_notif = NotificationType.SETTLEMENT_SETTLED
            notif_msg = f"Financial settlement for '{event.title}' is balanced and marked SETTLED."
        elif settlement.settlement_type == SettlementType.REIMBURSEMENT_DUE:
            settlement.status = SettlementStatus.PENDING_REIMBURSEMENT
            target_notif = NotificationType.SETTLEMENT_REIMBURSEMENT_PENDING
            notif_msg = (
                f"Settlement for '{event.title}' approved. "
                f"Reimbursement of ₹{settlement.reimbursement_due} pending."
            )
        elif settlement.settlement_type == SettlementType.REFUND_DUE:
            settlement.status = SettlementStatus.PENDING_REFUND
            target_notif = NotificationType.SETTLEMENT_REFUND_PENDING
            notif_msg = (
                f"Settlement for '{event.title}' approved. "
                f"Advance refund of ₹{settlement.refund_due} pending."
            )
        else:
            raise BusinessRuleError(f"Unsupported settlement type '{settlement.settlement_type}'.")

        await db.flush()

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.SETTLEMENT_APPROVED,
            entity_type="financial_settlement",
            entity_id=settlement.id,
            previous_state=prev_state,
            new_state={
                "status": _val(settlement.status),
                "settlement_type": _val(settlement.settlement_type),
                "reimbursement_due": str(settlement.reimbursement_due),
                "refund_due": str(settlement.refund_due),
                "audited_at": now.isoformat(),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        if settlement.status == SettlementStatus.SETTLED:
            cls._create_audit_entry(
                db=db,
                actor=actor,
                action=AuditAction.SETTLEMENT_SETTLED,
                entity_type="financial_settlement",
                entity_id=settlement.id,
                previous_state=prev_state,
                new_state={"status": SettlementStatus.SETTLED.value},
                ip_address=ip_address,
                user_agent=user_agent,
            )

        await NotificationService.create_notification(
            db=db,
            recipient_id=settlement.prepared_by,
            notification_type=target_notif,
            title="Financial Settlement Approved",
            message=notif_msg,
            event_request_id=event.event_request_id,
        )

        return settlement

    # =========================================================================
    # PAYMENT RECORDING & CLEARANCE
    # =========================================================================

    @classmethod
    async def record_payment(
        cls,
        db: AsyncSession,
        settlement_id: uuid.UUID,
        payment_type: SettlementPaymentType | str,
        amount: Decimal,
        payment_method: PaymentMethod | str,
        transaction_reference: str,
        transaction_date: datetime,
        proof_document_id: uuid.UUID,
        actor: User,
        notes: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SettlementPayment:
        """
        Finance Officer records a settlement payment.
        Validates:
        - Direction matches settlement type:
            REIMBURSEMENT_DUE -> REIMBURSEMENT_DISBURSEMENT
            REFUND_DUE -> ADVANCE_REFUND_RECEIPT
        - BALANCED settlements permit no payment (never create ₹0 records)
        - Proof document exists, active, type == SETTLEMENT_PAYMENT_PROOF, belongs to event
        - Cumulative remaining balance evaluation across all historical payments
        - Amount > 0 and amount <= remaining balance due (prevents overpayment)
        - When cumulative net cash equals entitled grant, settlement marks SETTLED automatically.
        """
        cls._verify_finance_officer(actor)

        settlement = await db.scalar(
            select(FinancialSettlement)
            .where(FinancialSettlement.id == settlement_id)
            .with_for_update()
        )
        if not settlement:
            raise NotFoundError(f"Financial settlement '{settlement_id}' not found.")

        if settlement.status not in (
            SettlementStatus.PENDING_REIMBURSEMENT,
            SettlementStatus.PENDING_REFUND,
        ):
            raise InvalidWorkflowTransitionError(
                f"Cannot record payment for settlement in '{settlement.status}' status. "
                "Settlement must be PENDING_REIMBURSEMENT or PENDING_REFUND."
            )

        p_type_str = _val(payment_type)
        if settlement.settlement_type == SettlementType.BALANCED:
            raise BusinessRuleError("Balanced settlements require no payment.")

        # Calculate current cumulative historical cash flows across all revisions
        existing_payments = (
            await db.scalars(
                select(SettlementPayment).where(SettlementPayment.settlement_id == settlement.id)
            )
        ).all()

        r_cleared = sum(
            (
                Decimal(str(p.amount))
                for p in existing_payments
                if _val(p.payment_type)
                == SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value
            ),
            Decimal("0.00"),
        )
        f_cleared = sum(
            (
                Decimal(str(p.amount))
                for p in existing_payments
                if _val(p.payment_type)
                == SettlementPaymentType.ADVANCE_REFUND_RECEIPT.value
            ),
            Decimal("0.00"),
        )

        net_cash_transferred = (
            Decimal(str(settlement.cash_advance_disbursed)) + r_cleared - f_cleared
        )
        institutional_payout = Decimal(str(settlement.institutional_payout))

        if settlement.settlement_type == SettlementType.REIMBURSEMENT_DUE:
            if p_type_str != SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value:
                raise BusinessRuleError(
                    f"Invalid payment type '{p_type_str}' for reimbursement settlement. "
                    "Must be 'REIMBURSEMENT_DISBURSEMENT'."
                )
            remaining_due = institutional_payout - net_cash_transferred
        elif settlement.settlement_type == SettlementType.REFUND_DUE:
            if p_type_str != SettlementPaymentType.ADVANCE_REFUND_RECEIPT.value:
                raise BusinessRuleError(
                    f"Invalid payment type '{p_type_str}' for refund settlement. "
                    "Must be 'ADVANCE_REFUND_RECEIPT'."
                )
            remaining_due = net_cash_transferred - institutional_payout
        else:
            raise BusinessRuleError(f"Unsupported settlement type '{settlement.settlement_type}'.")

        if amount <= Decimal("0.00"):
            raise BadRequestError("Payment amount must be greater than zero.")

        if not transaction_reference or not transaction_reference.strip():
            raise BadRequestError("Transaction reference is mandatory.")

        # Check proof document
        doc = await db.scalar(
            select(Document).where(
                Document.id == proof_document_id,
                Document.is_active.is_(True),
            )
        )
        if not doc:
            raise NotFoundError(f"Payment proof doc '{proof_document_id}' not found or inactive.")

        if doc.document_type != DocumentType.SETTLEMENT_PAYMENT_PROOF:
            raise BadRequestError("Document must have DocumentType.SETTLEMENT_PAYMENT_PROOF.")

        event = await cls._get_confirmed_event(db, settlement.event_id)
        if doc.event_id != event.id and doc.event_request_id != event.event_request_id:
            raise BadRequestError(
                "Payment proof document does not belong to this event "
                "(cross-event reuse forbidden)."
            )

        if amount > remaining_due:
            raise BusinessRuleError(
                f"Payment amount ({amount}) exceeds remaining balance due ({remaining_due}). "
                "Overpayments are strictly forbidden."
            )

        t_date = transaction_date
        if t_date.tzinfo is None:
            t_date = t_date.replace(tzinfo=UTC)

        payment = SettlementPayment(
            id=uuid.uuid4(),
            settlement_id=settlement.id,
            payment_type=p_type_str,
            amount=amount,
            payment_method=_val(payment_method),
            transaction_reference=transaction_reference.strip(),
            transaction_date=t_date,
            proof_document_id=proof_document_id,
            recorded_by=actor.id,
            notes=notes.strip() if notes else None,
        )
        db.add(payment)
        await db.flush()

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.SETTLEMENT_PAYMENT_RECORDED,
            entity_type="settlement_payment",
            entity_id=payment.id,
            previous_state=None,
            new_state={
                "settlement_id": str(settlement.id),
                "payment_type": p_type_str,
                "amount": str(amount),
                "transaction_reference": transaction_reference,
                "proof_document_id": str(proof_document_id),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Check if fully cleared under cumulative reconciliation
        if settlement.settlement_type == SettlementType.REIMBURSEMENT_DUE:
            new_r_cleared = r_cleared + amount
            new_net_cash = (
                Decimal(str(settlement.cash_advance_disbursed)) + new_r_cleared - f_cleared
            )
            new_remaining = institutional_payout - new_net_cash
        else:
            new_f_cleared = f_cleared + amount
            new_net_cash = (
                Decimal(str(settlement.cash_advance_disbursed)) + r_cleared - new_f_cleared
            )
            new_remaining = new_net_cash - institutional_payout

        if new_remaining <= Decimal("0.00"):
            prev_settlement_state = {"status": _val(settlement.status)}
            settlement.status = SettlementStatus.SETTLED
            await db.flush()

            cls._create_audit_entry(
                db=db,
                actor=actor,
                action=AuditAction.SETTLEMENT_SETTLED,
                entity_type="financial_settlement",
                entity_id=settlement.id,
                previous_state=prev_settlement_state,
                new_state={
                    "status": SettlementStatus.SETTLED.value,
                    "net_cash_transferred": str(new_net_cash),
                    "institutional_payout": str(institutional_payout),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )

            await NotificationService.create_notification(
                db=db,
                recipient_id=settlement.prepared_by,
                notification_type=NotificationType.SETTLEMENT_SETTLED,
                title="Financial Settlement Fully Cleared & Settled",
                message=(
                    f"All balance payments for '{event.title}' are complete. "
                    "The settlement is now SETTLED."
                ),
                event_request_id=event.event_request_id,
            )

        return payment

    # =========================================================================
    # CONTROLLED SETTLEMENT REOPENING
    # =========================================================================

    @classmethod
    async def reopen_settlement(
        cls,
        db: AsyncSession,
        settlement_id: uuid.UUID,
        reopening_reason: str,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SettlementRevision:
        """
        Finance Officer or Principal reopens a SETTLED settlement.
        SYSTEM_ADMIN is strictly barred.
        Requires mandatory reopening_reason.
        Captures full prior state snapshot into SettlementRevision with sequential revision_number.
        Event status remains COMPLETED (never altered).
        """
        cls._verify_reopen_authority(actor)

        if not reopening_reason or not reopening_reason.strip():
            raise BadRequestError("Reopening reason is mandatory.")

        settlement = await db.scalar(
            select(FinancialSettlement)
            .options(selectinload(FinancialSettlement.payments))
            .where(FinancialSettlement.id == settlement_id)
            .with_for_update()
        )
        if not settlement:
            raise NotFoundError(f"Financial settlement '{settlement_id}' not found.")

        if settlement.status != SettlementStatus.SETTLED:
            raise BusinessRuleError(
                f"Cannot reopen settlement in '{settlement.status}' status. "
                "Only 'SETTLED' settlements can be reopened."
            )

        # Determine next revision number
        rev_count = (
            await db.scalar(
                select(func.count())
                .select_from(SettlementRevision)
                .where(SettlementRevision.settlement_id == settlement.id)
            )
            or 0
        )
        next_revision = rev_count + 1

        # Capture complete immutable prior state snapshot
        snapshot_data = {
            "settlement_id": str(settlement.id),
            "event_id": str(settlement.event_id),
            "approved_version_id": str(settlement.approved_version_id),
            "sanctioned_grant": str(settlement.sanctioned_grant),
            "sanctioned_expenditure": str(settlement.sanctioned_expenditure),
            "expected_income": str(settlement.expected_income),
            "total_claimed_expenditure": str(settlement.total_claimed_expenditure),
            "total_verified_expenditure": str(settlement.total_verified_expenditure),
            "total_disallowed_expenditure": str(settlement.total_disallowed_expenditure),
            "total_verified_income": str(settlement.total_verified_income),
            "net_deficit": str(settlement.net_deficit),
            "institutional_payout": str(settlement.institutional_payout),
            "cash_advance_disbursed": str(settlement.cash_advance_disbursed),
            "settlement_balance": str(settlement.settlement_balance),
            "reimbursement_due": str(settlement.reimbursement_due),
            "refund_due": str(settlement.refund_due),
            "settlement_type": _val(settlement.settlement_type),
            "status": _val(settlement.status),
            "prepared_by": str(settlement.prepared_by),
            "audited_by": str(settlement.audited_by) if settlement.audited_by else None,
            "audited_at": settlement.audited_at.isoformat() if settlement.audited_at else None,
            "submitted_at": settlement.submitted_at.isoformat()
            if settlement.submitted_at
            else None,
            "finance_remarks": settlement.finance_remarks,
            "query_reason": settlement.query_reason,
            "payments": [
                {
                    "id": str(p.id),
                    "payment_type": _val(p.payment_type),
                    "amount": str(p.amount),
                    "payment_method": _val(p.payment_method),
                    "transaction_reference": p.transaction_reference,
                    "transaction_date": p.transaction_date.isoformat(),
                    "proof_document_id": str(p.proof_document_id),
                }
                for p in settlement.payments
            ],
        }

        revision = SettlementRevision(
            id=uuid.uuid4(),
            settlement_id=settlement.id,
            revision_number=next_revision,
            snapshot_data=snapshot_data,
            reopened_by=actor.id,
            reopening_reason=reopening_reason.strip(),
        )
        db.add(revision)

        prev_state = {"status": _val(settlement.status)}
        settlement.status = SettlementStatus.REOPENED

        await db.flush()

        cls._create_audit_entry(
            db=db,
            actor=actor,
            action=AuditAction.SETTLEMENT_REOPENED,
            entity_type="financial_settlement",
            entity_id=settlement.id,
            previous_state=prev_state,
            new_state={
                "status": SettlementStatus.REOPENED.value,
                "revision_number": next_revision,
                "reopening_reason": reopening_reason,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        event = await cls._get_confirmed_event(db, settlement.event_id)
        await NotificationService.create_notification(
            db=db,
            recipient_id=settlement.prepared_by,
            notification_type=NotificationType.SETTLEMENT_REOPENED,
            title="Financial Settlement Reopened",
            message=(
                f"Settlement for '{event.title}' was reopened by {actor.full_name}. "
                f"Reason: {reopening_reason}"
            ),
            event_request_id=event.event_request_id,
        )

        return revision

    # =========================================================================
    # CLOSURE ELIGIBILITY EVALUATION (READ-ONLY)
    # =========================================================================

    @classmethod
    async def get_closure_eligibility(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
    ) -> dict[str, Any]:
        """
        Read-only evaluation of institutional closure prerequisites.
        Never mutates Event or settlement state.
        Never adds or transitions to CLOSED EventStatus.
        Returns structured dictionary with boolean eligibility and machine-readable blockers.
        """
        event = await cls._get_confirmed_event(db, event_id, for_update=False)
        await cls._verify_event_viewer(db, event, actor)

        blockers: list[str] = []

        # 1. Event completed
        if event.status != EventStatus.COMPLETED:
            blockers.append("EVENT_NOT_COMPLETED")

        # 2. Post-event report certified
        report = await db.scalar(
            select(PostEventReport).where(PostEventReport.event_id == event.id)
        )
        if not report or report.status != PostEventReportStatus.CERTIFIED:
            blockers.append("POST_EVENT_REPORT_NOT_CERTIFIED")

        # 3. Expense ledger zero unresolved claims
        expenses = (
            await db.scalars(select(ActualExpense).where(ActualExpense.event_id == event.id))
        ).all()
        unresolved_exp = [
            e
            for e in expenses
            if e.status
            in (
                ActualExpenseStatus.DRAFT,
                ActualExpenseStatus.SUBMITTED,
                ActualExpenseStatus.QUERIED,
            )
        ]
        if unresolved_exp:
            blockers.append("UNRESOLVED_EXPENSES")

        # 4. Income ledger zero unresolved claims
        incomes = (
            await db.scalars(select(ActualIncome).where(ActualIncome.event_id == event.id))
        ).all()
        unresolved_inc = [inc for inc in incomes if inc.status == ActualIncomeStatus.RECORDED]
        if unresolved_inc:
            blockers.append("UNVERIFIED_INCOME")

        # 5. Cash advance must not be pending/unresolved
        advance = await db.scalar(select(CashAdvance).where(CashAdvance.event_id == event.id))
        if advance and advance.status in (CashAdvanceStatus.REQUESTED, CashAdvanceStatus.APPROVED):
            blockers.append("ADVANCE_UNRESOLVED")

        # 6 & 7. Settlement existence and state
        settlement = await db.scalar(
            select(FinancialSettlement).where(FinancialSettlement.event_id == event.id)
        )
        if not settlement:
            blockers.append("SETTLEMENT_MISSING")
        elif settlement.status != SettlementStatus.SETTLED:
            blockers.append("SETTLEMENT_NOT_SETTLED")
        else:
            # 8. All balance payments confirmed under cumulative reconciliation
            payments = (
                await db.scalars(
                    select(SettlementPayment).where(
                        SettlementPayment.settlement_id == settlement.id
                    )
                )
            ).all()

            r_cleared = sum(
                (
                    Decimal(str(p.amount))
                    for p in payments
                    if _val(p.payment_type)
                    == SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT.value
                ),
                Decimal("0.00"),
            )
            f_cleared = sum(
                (
                    Decimal(str(p.amount))
                    for p in payments
                    if _val(p.payment_type)
                    == SettlementPaymentType.ADVANCE_REFUND_RECEIPT.value
                ),
                Decimal("0.00"),
            )

            net_cash = (
                Decimal(str(settlement.cash_advance_disbursed)) + r_cleared - f_cleared
            )
            if net_cash != Decimal(str(settlement.institutional_payout)):
                blockers.append("PAYMENT_OUTSTANDING")

        return {
            "eligible": len(blockers) == 0,
            "blockers": blockers,
            "event_id": str(event.id),
            "settlement_id": str(settlement.id) if settlement else None,
        }

    # =========================================================================
    # READ-ONLY GETTERS
    # =========================================================================

    @classmethod
    async def get_settlement(
        cls, db: AsyncSession, event_id: uuid.UUID, actor: User
    ) -> FinancialSettlement | None:
        """Retrieve financial settlement for an event."""
        event = await cls._get_confirmed_event(db, event_id)
        await cls._verify_event_viewer(db, event, actor)

        return await db.scalar(
            select(FinancialSettlement)
            .options(
                selectinload(FinancialSettlement.payments),
                selectinload(FinancialSettlement.revisions),
            )
            .where(FinancialSettlement.event_id == event_id)
        )

    @classmethod
    async def get_settlement_by_id(
        cls, db: AsyncSession, settlement_id: uuid.UUID, actor: User
    ) -> FinancialSettlement:
        """Retrieve financial settlement by primary key."""
        settlement = await db.scalar(
            select(FinancialSettlement)
            .options(
                selectinload(FinancialSettlement.payments),
                selectinload(FinancialSettlement.revisions),
            )
            .where(FinancialSettlement.id == settlement_id)
        )
        if not settlement:
            raise NotFoundError(f"Financial settlement '{settlement_id}' not found.")

        event = await cls._get_confirmed_event(db, settlement.event_id)
        await cls._verify_event_viewer(db, event, actor)
        return settlement

    @classmethod
    async def get_advances_for_event(
        cls, db: AsyncSession, event_id: uuid.UUID, actor: User
    ) -> CashAdvance | None:
        """Retrieve cash advance requisition for an event."""
        event = await cls._get_confirmed_event(db, event_id)
        await cls._verify_event_viewer(db, event, actor)

        return await db.scalar(select(CashAdvance).where(CashAdvance.event_id == event_id))

    @classmethod
    async def get_incomes_for_event(
        cls, db: AsyncSession, event_id: uuid.UUID, actor: User
    ) -> list[ActualIncome]:
        """Retrieve actual income ledger entries for an event."""
        event = await cls._get_confirmed_event(db, event_id)
        await cls._verify_event_viewer(db, event, actor)

        return list(
            (
                await db.scalars(
                    select(ActualIncome)
                    .where(ActualIncome.event_id == event_id)
                    .order_by(ActualIncome.received_date.desc())
                )
            ).all()
        )

    @classmethod
    async def get_settlement_revisions(
        cls, db: AsyncSession, settlement_id: uuid.UUID, actor: User
    ) -> list[SettlementRevision]:
        """Retrieve audit revision snapshots for a settlement."""
        settlement = await cls.get_settlement_by_id(db, settlement_id, actor)
        return list(
            (
                await db.scalars(
                    select(SettlementRevision)
                    .where(SettlementRevision.settlement_id == settlement.id)
                    .order_by(SettlementRevision.revision_number.asc())
                )
            ).all()
        )

    @classmethod
    async def get_settlement_payments(
        cls, db: AsyncSession, settlement_id: uuid.UUID, actor: User
    ) -> list[SettlementPayment]:
        """Retrieve payment clearing ledger for a settlement."""
        settlement = await cls.get_settlement_by_id(db, settlement_id, actor)
        return list(
            (
                await db.scalars(
                    select(SettlementPayment)
                    .where(SettlementPayment.settlement_id == settlement.id)
                    .order_by(SettlementPayment.created_at.asc())
                )
            ).all()
        )
