"""
CampusConnect - Actual Expense Ledger & Finance Verification Service (Phase 2.2)

Encapsulates actual expense management, bill evidence attachment,
non-destructive query/revision workflows, partial verification, and Finance audit queue.

Design Principles:
- SELECT ... FOR UPDATE row locking prevents race conditions and concurrent double-auditing.
- Strict Segregation of Duties (SOD):
  - Club Secretary submits and amends own club's expenses.
  - Finance Officer verifies, partially verifies, queries, and disallows.
  - SYSTEM_ADMIN has no authority to bypass Finance verification or modify claims.
- Delivery Precondition:
  - Event must be COMPLETED to record expenses.
  - PostEventReport must be CERTIFIED by Faculty Advisor before Finance actions can proceed.
- Strict Document Ownership:
  - Bill documents cannot cross event boundaries (expense.event_id == document.event_id).
- Audit Trail:
  - All state transitions preserve full previous/new state JSON snapshots in AuditLog.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import NO_VALUE

from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    WorkflowStateError,
)
from app.models.domain import (
    ActualExpense,
    AuditLog,
    BudgetProposal,
    ClubMember,
    Document,
    Event,
    PostEventReport,
    User,
)
from app.models.enums import (
    ActualExpenseStatus,
    AuditAction,
    BudgetLineItemCategory,
    ClubMemberRole,
    EventStatus,
    NotificationType,
    PostEventReportStatus,
    UserRole,
)
from app.schemas.actual_expense import (
    ActualExpenseCreate,
    ActualExpenseDisallow,
    ActualExpensePartialVerify,
    ActualExpenseQuery,
    ActualExpenseResponse,
    ActualExpenseSubmit,
    ActualExpenseUpdate,
    ActualExpenseVerify,
    ExpenseCategorySummary,
    ExpenseLedgerSummaryResponse,
)
from app.services.notification_service import NotificationService


def _val(x: Any) -> str:
    """Safely extract string value from either Enum or str."""
    return x.value if hasattr(x, "value") else str(x)



def to_actual_expense_response(expense: ActualExpense) -> ActualExpenseResponse:
    """Format an ActualExpense model into a safe public schema without lazy loads."""
    insp = inspect(expense)

    submitted_by_name = None
    submitted_by_email = None
    if "submitter" in insp.attrs:
        u = insp.attrs.submitter.loaded_value
        if u is not None:
            submitted_by_name = getattr(u, "full_name", None)
            submitted_by_email = getattr(u, "email", None)

    verified_by_name = None
    verified_by_email = None
    if "verifier" in insp.attrs:
        u = insp.attrs.verifier.loaded_value
        if u is not None:
            verified_by_name = getattr(u, "full_name", None)
            verified_by_email = getattr(u, "email", None)

    bill_original_filename = None
    if "bill_document" in insp.attrs:
        doc = insp.attrs.bill_document.loaded_value
        if doc is not None:
            bill_original_filename = getattr(doc, "original_filename", None)

    created_at = (
        insp.attrs.created_at.loaded_value
        if "created_at" in insp.attrs and insp.attrs.created_at.loaded_value is not NO_VALUE
        else datetime.now(UTC)
    )
    if created_at is None:
        created_at = datetime.now(UTC)

    updated_at = (
        insp.attrs.updated_at.loaded_value
        if "updated_at" in insp.attrs and insp.attrs.updated_at.loaded_value is not NO_VALUE
        else datetime.now(UTC)
    )
    if updated_at is None:
        updated_at = datetime.now(UTC)

    status_val = expense.status.value if hasattr(expense.status, "value") else str(expense.status)
    category_val = (
        expense.category.value if hasattr(expense.category, "value") else str(expense.category)
    )

    return ActualExpenseResponse(
        id=expense.id,
        event_id=expense.event_id,
        budget_line_item_id=expense.budget_line_item_id,
        category=BudgetLineItemCategory(category_val),
        description=expense.description,
        vendor_name=expense.vendor_name,
        vendor_gstin=expense.vendor_gstin,
        invoice_number=expense.invoice_number,
        invoice_date=expense.invoice_date,
        claimed_amount=expense.claimed_amount,
        verified_amount=expense.verified_amount,
        disallowed_amount=expense.disallowed_amount,
        status=ActualExpenseStatus(status_val),
        bill_document_id=expense.bill_document_id,
        submitted_by=expense.submitted_by,
        submitted_by_name=submitted_by_name,
        submitted_by_email=submitted_by_email,
        submitted_at=expense.submitted_at,
        verified_by=expense.verified_by,
        verified_by_name=verified_by_name,
        verified_by_email=verified_by_email,
        verified_at=expense.verified_at,
        finance_remarks=expense.finance_remarks,
        query_reason=expense.query_reason,
        is_flagged_for_review=expense.is_flagged_for_review,
        review_notes=expense.review_notes,
        bill_original_filename=bill_original_filename,
        created_at=created_at,
        updated_at=updated_at,
    )


class ExpenseService:
    @classmethod
    async def _get_confirmed_event(
        cls, db: AsyncSession, event_id: uuid.UUID, for_update: bool = False
    ) -> Event:
        """Resolve confirmed event with optional pessimistic row lock."""
        stmt = select(Event).where(
            (Event.id == event_id) | (Event.event_request_id == event_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        event = await db.scalar(stmt)
        if not event:
            raise NotFoundError(f"Confirmed event '{event_id}' not found.")
        return event

    @classmethod
    def _require_event_completed(cls, event: Event) -> None:
        """Enforce that actual expenses can only belong to a COMPLETED event."""
        if event.status != EventStatus.COMPLETED:
            st = event.status.value if hasattr(event.status, "value") else str(event.status)
            raise WorkflowStateError(
                f"Expenses can only be recorded for COMPLETED events (current status: '{st}')."
            )

    @classmethod
    async def _verify_club_secretary(
        cls, db: AsyncSession, event: Event, actor: User
    ) -> None:
        """
        Enforce that only the designated CLUB_SECRETARY of the owning club
        can create/submit expenses.
        SYSTEM_ADMIN has no ordinary secretary execution powers.
        """
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
                "Only the active Club Secretary of the owning club can manage expenses for "
                "this event."
            )

    @classmethod
    def _verify_finance_officer(cls, actor: User) -> None:
        """
        Enforce that only a FINANCE_OFFICER can verify, query, or disallow expenses.
        SYSTEM_ADMIN cannot bypass Finance verification.
        """
        if actor.role != UserRole.FINANCE_OFFICER:
            raise ForbiddenError(
                "Only Finance Officers are authorized to perform financial audit actions."
            )

    @classmethod
    async def _verify_delivery_certified(
        cls, db: AsyncSession, event: Event
    ) -> None:
        """
        Enforce institutional precondition:
        Finance verification is blocked until Faculty Advisor has certified delivery.
        """
        report = await db.scalar(
            select(PostEventReport).where(PostEventReport.event_id == event.id)
        )
        if not report or report.status != PostEventReportStatus.CERTIFIED:
            raise WorkflowStateError(
                "Finance audit clearance is blocked until the designated Faculty Advisor "
                "has certified delivery of the post-event report."
            )

    @classmethod
    async def _verify_bill_document(
        cls, db: AsyncSession, event: Event, bill_document_id: uuid.UUID
    ) -> Document:
        """
        Enforce bill document validity and strict event ownership:
        expense.event_id == document.event_id
        """
        doc = await db.scalar(
            select(Document).where(
                Document.id == bill_document_id,
                Document.is_active.is_(True),
            )
        )
        if not doc:
            raise NotFoundError(f"Bill document '{bill_document_id}' not found or inactive.")

        if doc.event_id != event.id and doc.event_request_id != event.event_request_id:
            raise BadRequestError(
                "Bill document does not belong to this event (cross-event reuse forbidden)."
            )

        return doc

    @classmethod
    async def _check_duplicate_invoice(
        cls,
        db: AsyncSession,
        event: Event,
        vendor_name: str,
        invoice_number: str | None,
        invoice_date: Any,
        bill_document_id: uuid.UUID,
        exclude_expense_id: uuid.UUID | None = None,
    ) -> tuple[bool, str | None]:
        """
        Check for duplicate invoice submissions across events and within the same event:
        1. If invoice_number is None -> ALLOWED, but flagged for manual Finance review.
        2. If invoice_number provided:
           - Cross-event match (status != DISALLOWED) -> ConflictError (Hard Block).
           - Same-event match with DIFFERENT bill_document_id -> ConflictError.
           - Same-event match with SAME bill_document_id -> ALLOWED (itemized line item split).
        """
        if not invoice_number or not invoice_number.strip():
            return True, "Voucher submitted without invoice number (Finance review required)"

        norm_vendor = vendor_name.strip().lower()
        norm_invoice = invoice_number.strip().lower()

        # Check across ALL non-disallowed expenses
        stmt = select(ActualExpense).where(
            func.lower(func.trim(ActualExpense.vendor_name)) == norm_vendor,
            func.lower(func.trim(ActualExpense.invoice_number)) == norm_invoice,
            ActualExpense.invoice_date == invoice_date,
            ActualExpense.status != ActualExpenseStatus.DISALLOWED,
        )
        if exclude_expense_id:
            stmt = stmt.where(ActualExpense.id != exclude_expense_id)

        matches = (await db.scalars(stmt)).all()
        for m in matches:
            if m.event_id != event.id:
                raise ConflictError(
                    f"Duplicate invoice detected: vendor '{vendor_name}' invoice #{invoice_number} "
                    f"on {invoice_date} has already been claimed for another event."
                )
            # Same event
            if m.bill_document_id != bill_document_id:
                raise ConflictError(
                    f"Duplicate invoice detected: invoice #{invoice_number} is already attached "
                    "to a different bill document in this event."
                )
            # Same event and same bill document -> Allowed itemized split

        return False, None

    # =========================================================================
    # SECRETARY ACTIONS
    # =========================================================================

    @classmethod
    async def create_draft_expense(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        payload: ActualExpenseCreate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActualExpenseResponse:
        """Create a new draft actual expense line item."""
        event = await cls._get_confirmed_event(db, event_id)
        cls._require_event_completed(event)
        await cls._verify_club_secretary(db, event, actor)

        # Verify bill document ownership
        doc = await cls._verify_bill_document(db, event, payload.bill_document_id)

        # Check duplicate invoice metadata
        flagged, review_notes = await cls._check_duplicate_invoice(
            db=db,
            event=event,
            vendor_name=payload.vendor_name,
            invoice_number=payload.invoice_number,
            invoice_date=payload.invoice_date,
            bill_document_id=payload.bill_document_id,
        )

        expense = ActualExpense(
            id=uuid.uuid4(),
            event_id=event.id,
            budget_line_item_id=payload.budget_line_item_id,
            category=payload.category,
            description=payload.description,
            vendor_name=payload.vendor_name,
            vendor_gstin=payload.vendor_gstin,
            invoice_number=payload.invoice_number,
            invoice_date=payload.invoice_date,
            claimed_amount=payload.claimed_amount,
            verified_amount=None,
            status=ActualExpenseStatus.DRAFT,
            bill_document_id=doc.id,
            submitted_by=actor.id,
            submitted_at=None,
            is_flagged_for_review=flagged,
            review_notes=review_notes,
        )
        db.add(expense)

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.EXPENSE_CREATED,
                entity_type="actual_expense",
                entity_id=str(expense.id),
                previous_state=None,
                new_state={
                    "event_id": str(event.id),
                    "category": payload.category.value,
                    "description": payload.description,
                    "vendor_name": payload.vendor_name,
                    "claimed_amount": str(payload.claimed_amount),
                    "invoice_number": payload.invoice_number,
                    "invoice_date": str(payload.invoice_date),
                    "bill_document_id": str(doc.id),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.flush()
        # Eager load relationships for clean serialization
        expense.bill_document = doc
        expense.submitter = actor
        return to_actual_expense_response(expense)

    @classmethod
    async def update_expense(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        expense_id: uuid.UUID,
        payload: ActualExpenseUpdate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActualExpenseResponse:
        """Update a DRAFT or QUERIED expense line item."""
        event = await cls._get_confirmed_event(db, event_id)
        await cls._verify_club_secretary(db, event, actor)

        expense = await db.scalar(
            select(ActualExpense)
            .where(ActualExpense.id == expense_id, ActualExpense.event_id == event.id)
            .options(
                selectinload(ActualExpense.bill_document),
                selectinload(ActualExpense.submitter),
                selectinload(ActualExpense.verifier),
            )
            .with_for_update()
        )
        if not expense:
            raise NotFoundError(f"Actual expense '{expense_id}' not found.")

        # Immutability guard
        if expense.status in (
            ActualExpenseStatus.VERIFIED,
            ActualExpenseStatus.PARTIALLY_VERIFIED,
            ActualExpenseStatus.DISALLOWED,
        ):
            raise WorkflowStateError(
                f"Expense is in terminal '{_val(expense.status)}' status and cannot be modified."
            )
        if expense.status == ActualExpenseStatus.SUBMITTED:
            raise WorkflowStateError(
                "Submitted expense is under Finance review and cannot be edited. "
                "Wait for review or query."
            )

        # Snapshot prior state for non-destructive audit history
        prior_state = {
            "category": (
                expense.category.value
                if hasattr(expense.category, "value")
                else str(expense.category)
            ),
            "description": expense.description,
            "vendor_name": expense.vendor_name,
            "vendor_gstin": expense.vendor_gstin,
            "invoice_number": expense.invoice_number,
            "invoice_date": str(expense.invoice_date),
            "claimed_amount": str(expense.claimed_amount),
            "bill_document_id": str(expense.bill_document_id),
            "status": _val(expense.status),
        }

        # Validate replacement bill if provided
        if payload.bill_document_id and payload.bill_document_id != expense.bill_document_id:
            doc = await cls._verify_bill_document(db, event, payload.bill_document_id)
            expense.bill_document_id = doc.id
            expense.bill_document = doc

        # Check duplicate metadata if vendor/invoice/date updated
        new_vendor = payload.vendor_name or expense.vendor_name
        new_inv_num = (
            payload.invoice_number
            if payload.invoice_number is not None
            else expense.invoice_number
        )
        new_inv_date = payload.invoice_date or expense.invoice_date
        new_bill_id = payload.bill_document_id or expense.bill_document_id

        flagged, review_notes = await cls._check_duplicate_invoice(
            db=db,
            event=event,
            vendor_name=new_vendor,
            invoice_number=new_inv_num,
            invoice_date=new_inv_date,
            bill_document_id=new_bill_id,
            exclude_expense_id=expense.id,
        )

        # Apply updates
        if payload.category is not None:
            expense.category = payload.category
        if payload.description is not None:
            expense.description = payload.description.strip()
        if payload.vendor_name is not None:
            expense.vendor_name = payload.vendor_name.strip()
        if payload.vendor_gstin is not None:
            expense.vendor_gstin = payload.vendor_gstin.strip() or None
        if payload.invoice_number is not None:
            expense.invoice_number = payload.invoice_number.strip() or None
        if payload.invoice_date is not None:
            expense.invoice_date = payload.invoice_date
        if payload.claimed_amount is not None:
            expense.claimed_amount = payload.claimed_amount
        if payload.budget_line_item_id is not None:
            expense.budget_line_item_id = payload.budget_line_item_id

        expense.is_flagged_for_review = flagged
        expense.review_notes = review_notes

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.EXPENSE_UPDATED,
                entity_type="actual_expense",
                entity_id=str(expense.id),
                previous_state=prior_state,
                new_state={
                    "category": (
                expense.category.value
                if hasattr(expense.category, "value")
                else str(expense.category)
            ),
                    "description": expense.description,
                    "vendor_name": expense.vendor_name,
                    "vendor_gstin": expense.vendor_gstin,
                    "invoice_number": expense.invoice_number,
                    "invoice_date": str(expense.invoice_date),
                    "claimed_amount": str(expense.claimed_amount),
                    "bill_document_id": str(expense.bill_document_id),
                    "status": _val(expense.status),
                },
                reason="Secretary amended expense line item",
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.flush()
        return to_actual_expense_response(expense)

    @classmethod
    async def delete_draft_expense(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        expense_id: uuid.UUID,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Delete a DRAFT or QUERIED expense line item."""
        event = await cls._get_confirmed_event(db, event_id)
        await cls._verify_club_secretary(db, event, actor)

        expense = await db.scalar(
            select(ActualExpense)
            .where(ActualExpense.id == expense_id, ActualExpense.event_id == event.id)
            .with_for_update()
        )
        if not expense:
            raise NotFoundError(f"Actual expense '{expense_id}' not found.")

        if expense.status in (
            ActualExpenseStatus.VERIFIED,
            ActualExpenseStatus.PARTIALLY_VERIFIED,
            ActualExpenseStatus.DISALLOWED,
            ActualExpenseStatus.SUBMITTED,
        ):
            raise WorkflowStateError(
                f"Cannot delete expense in '{_val(expense.status)}' status."
            )

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.EXPENSE_UPDATED,
                entity_type="actual_expense",
                entity_id=str(expense.id),
                previous_state={
                    "status": _val(expense.status),
                    "claimed_amount": str(expense.claimed_amount),
                },
                new_state=None,
                reason="Draft expense discarded by Club Secretary",
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await db.delete(expense)
        await db.flush()

    @classmethod
    async def submit_expenses(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        payload: ActualExpenseSubmit,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> list[ActualExpenseResponse]:
        """
        Submit draft or queried expenses for Finance Officer verification.
        Transitions DRAFT -> SUBMITTED and QUERIED -> SUBMITTED.
        """
        event = await cls._get_confirmed_event(db, event_id, for_update=True)
        cls._require_event_completed(event)
        await cls._verify_club_secretary(db, event, actor)

        stmt = (
            select(ActualExpense)
            .where(
                ActualExpense.event_id == event.id,
                ActualExpense.status.in_([ActualExpenseStatus.DRAFT, ActualExpenseStatus.QUERIED]),
            )
            .options(
                selectinload(ActualExpense.bill_document),
                selectinload(ActualExpense.submitter),
                selectinload(ActualExpense.verifier),
            )
            .with_for_update()
        )
        if payload.expense_ids:
            stmt = stmt.where(ActualExpense.id.in_(payload.expense_ids))

        expenses = (await db.scalars(stmt)).all()
        if not expenses:
            raise BadRequestError("No draft or queried expenses found to submit.")

        now_utc = datetime.now(UTC)
        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        results = []

        for exp in expenses:
            is_resubmission = (exp.status == ActualExpenseStatus.QUERIED)
            prior_status = _val(exp.status)

            exp.status = ActualExpenseStatus.SUBMITTED
            exp.submitted_at = now_utc
            exp.submitted_by = actor.id

            action = (
                AuditAction.EXPENSE_RESUBMITTED
                if is_resubmission
                else AuditAction.EXPENSE_SUBMITTED
            )

            db.add(
                AuditLog(
                    actor_id=actor.id,
                    actor_email=actor.email,
                    actor_role=actor_role_str,
                    action=action,
                    entity_type="actual_expense",
                    entity_id=str(exp.id),
                    previous_state={"status": prior_status},
                    new_state={
                        "status": ActualExpenseStatus.SUBMITTED.value,
                        "claimed_amount": str(exp.claimed_amount),
                        "submitted_at": now_utc.isoformat(),
                    },
                    reason="Expense submitted for Finance verification",
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )
            results.append(to_actual_expense_response(exp))

        # Notify Finance Officers
        finance_officers = (
            await db.scalars(
                select(User).where(
                    User.role == UserRole.FINANCE_OFFICER, User.is_active.is_(True)
                )
            )
        ).all()
        for fo in finance_officers:
            await NotificationService.create_notification(
                db=db,
                recipient_id=fo.id,
                notification_type=NotificationType.EXPENSE_SUBMITTED,
                title="Actual Expenses Submitted for Audit",
                message=f"{len(expenses)} expense claims submitted for event '{event.title}'.",
                event_request_id=event.event_request_id,
            )

        await db.flush()
        return results

    # =========================================================================
    # FINANCE OFFICER AUDIT ACTIONS
    # =========================================================================

    @classmethod
    async def verify_expense(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        expense_id: uuid.UUID,
        payload: ActualExpenseVerify,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActualExpenseResponse:
        """
        Full verification by Finance Officer:
        verified_amount == claimed_amount
        Status -> VERIFIED (terminal).
        """
        cls._verify_finance_officer(actor)
        event = await cls._get_confirmed_event(db, event_id)
        await cls._verify_delivery_certified(db, event)

        expense = await db.scalar(
            select(ActualExpense)
            .where(ActualExpense.id == expense_id, ActualExpense.event_id == event.id)
            .options(
                selectinload(ActualExpense.bill_document),
                selectinload(ActualExpense.submitter),
                selectinload(ActualExpense.verifier),
            )
            .with_for_update()
        )
        if not expense:
            raise NotFoundError(f"Actual expense '{expense_id}' not found.")

        if expense.status != ActualExpenseStatus.SUBMITTED:
            raise WorkflowStateError(
                f"Cannot verify expense in '{_val(expense.status)}' status. Must be SUBMITTED."
            )

        now_utc = datetime.now(UTC)
        prior_state = {
            "status": _val(expense.status),
            "claimed_amount": str(expense.claimed_amount),
            "verified_amount": None,
        }

        expense.verified_amount = expense.claimed_amount
        expense.status = ActualExpenseStatus.VERIFIED
        expense.verified_by = actor.id
        expense.verified_at = now_utc
        expense.updated_at = now_utc
        expense.finance_remarks = payload.remarks
        expense.verifier = actor

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.EXPENSE_VERIFIED,
                entity_type="actual_expense",
                entity_id=str(expense.id),
                previous_state=prior_state,
                new_state={
                    "status": ActualExpenseStatus.VERIFIED.value,
                    "claimed_amount": str(expense.claimed_amount),
                    "verified_amount": str(expense.verified_amount),
                    "disallowed_amount": "0.00",
                    "finance_remarks": payload.remarks,
                },
                reason=payload.remarks or "Full claim verified by Finance Officer",
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # Notify submitter
        await NotificationService.create_notification(
            db=db,
            recipient_id=expense.submitted_by,
            notification_type=NotificationType.EXPENSE_VERIFIED,
            title="Expense Claim Verified",
            message=(
                f"Expense of ₹{expense.claimed_amount} for '{expense.vendor_name}' "
                "was verified in full."
            ),
            event_request_id=event.event_request_id,
        )

        await db.flush()
        return to_actual_expense_response(expense)

    @classmethod
    async def partial_verify_expense(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        expense_id: uuid.UUID,
        payload: ActualExpensePartialVerify,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActualExpenseResponse:
        """
        Partial verification by Finance Officer:
        0 < verified_amount < claimed_amount
        Status -> PARTIALLY_VERIFIED (terminal).
        Mandatory justification required.
        """
        cls._verify_finance_officer(actor)
        event = await cls._get_confirmed_event(db, event_id)
        await cls._verify_delivery_certified(db, event)

        expense = await db.scalar(
            select(ActualExpense)
            .where(ActualExpense.id == expense_id, ActualExpense.event_id == event.id)
            .options(
                selectinload(ActualExpense.bill_document),
                selectinload(ActualExpense.submitter),
                selectinload(ActualExpense.verifier),
            )
            .with_for_update()
        )
        if not expense:
            raise NotFoundError(f"Actual expense '{expense_id}' not found.")

        if expense.status != ActualExpenseStatus.SUBMITTED:
            raise WorkflowStateError(
                f"Cannot verify expense in '{_val(expense.status)}' status. Must be SUBMITTED."
            )

        # Invariant checks
        if payload.verified_amount >= expense.claimed_amount:
            raise BadRequestError(
                f"For partial verification, verified amount (₹{payload.verified_amount}) "
                f"must be strictly less than claimed amount (₹{expense.claimed_amount}). "
                "Use full verification instead."
            )
        if payload.verified_amount <= Decimal("0.00"):
            raise BadRequestError(
                "Verified amount must be greater than zero. For total rejection, use disallow."
            )

        now_utc = datetime.now(UTC)
        prior_state = {
            "status": _val(expense.status),
            "claimed_amount": str(expense.claimed_amount),
            "verified_amount": None,
        }

        expense.verified_amount = payload.verified_amount
        expense.status = ActualExpenseStatus.PARTIALLY_VERIFIED
        expense.verified_by = actor.id
        expense.verified_at = now_utc
        expense.updated_at = now_utc
        expense.finance_remarks = payload.remarks
        expense.verifier = actor

        disallowed = expense.disallowed_amount
        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.EXPENSE_PARTIALLY_VERIFIED,
                entity_type="actual_expense",
                entity_id=str(expense.id),
                previous_state=prior_state,
                new_state={
                    "status": ActualExpenseStatus.PARTIALLY_VERIFIED.value,
                    "claimed_amount": str(expense.claimed_amount),
                    "verified_amount": str(expense.verified_amount),
                    "disallowed_amount": str(disallowed),
                    "finance_remarks": payload.remarks,
                },
                reason=payload.remarks,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # Notify submitter
        await NotificationService.create_notification(
            db=db,
            recipient_id=expense.submitted_by,
            notification_type=NotificationType.EXPENSE_PARTIALLY_VERIFIED,
            title="Expense Partially Verified",
            message=(
                f"Claimed ₹{expense.claimed_amount} partially approved as "
                f"₹{expense.verified_amount} (Disallowed: ₹{disallowed}). "
                f"Reason: {payload.remarks}"
            ),
            event_request_id=event.event_request_id,
        )

        await db.flush()
        return to_actual_expense_response(expense)

    @classmethod
    async def query_expense(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        expense_id: uuid.UUID,
        payload: ActualExpenseQuery,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActualExpenseResponse:
        """
        Query an expense by Finance Officer:
        Status -> QUERIED.
        Re-opens edit rights to Club Secretary to amend and resubmit.
        Mandatory query remarks required.
        """
        cls._verify_finance_officer(actor)
        event = await cls._get_confirmed_event(db, event_id)
        await cls._verify_delivery_certified(db, event)

        expense = await db.scalar(
            select(ActualExpense)
            .where(ActualExpense.id == expense_id, ActualExpense.event_id == event.id)
            .options(
                selectinload(ActualExpense.bill_document),
                selectinload(ActualExpense.submitter),
                selectinload(ActualExpense.verifier),
            )
            .with_for_update()
        )
        if not expense:
            raise NotFoundError(f"Actual expense '{expense_id}' not found.")

        if expense.status != ActualExpenseStatus.SUBMITTED:
            raise WorkflowStateError(
                f"Cannot query expense in '{_val(expense.status)}' status. Must be SUBMITTED."
            )

        prior_state = {
            "status": _val(expense.status),
            "claimed_amount": str(expense.claimed_amount),
            "vendor_name": expense.vendor_name,
            "invoice_number": expense.invoice_number,
            "bill_document_id": str(expense.bill_document_id),
        }

        expense.status = ActualExpenseStatus.QUERIED
        expense.query_reason = payload.remarks
        expense.updated_at = datetime.now(UTC)
        expense.finance_remarks = payload.remarks

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.EXPENSE_QUERIED,
                entity_type="actual_expense",
                entity_id=str(expense.id),
                previous_state=prior_state,
                new_state={
                    "status": ActualExpenseStatus.QUERIED.value,
                    "query_reason": payload.remarks,
                },
                reason=payload.remarks,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # Notify submitter
        await NotificationService.create_notification(
            db=db,
            recipient_id=expense.submitted_by,
            notification_type=NotificationType.EXPENSE_QUERIED,
            title="Expense Claim Queried by Finance",
            message=(
                f"Finance Officer queried expense '{expense.description}' "
                f"(₹{expense.claimed_amount}): {payload.remarks}"
            ),
            event_request_id=event.event_request_id,
        )

        await db.flush()
        return to_actual_expense_response(expense)

    @classmethod
    async def disallow_expense(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        expense_id: uuid.UUID,
        payload: ActualExpenseDisallow,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActualExpenseResponse:
        """
        Disallow an expense completely by Finance Officer:
        verified_amount = 0.00
        Status -> DISALLOWED (terminal).
        Mandatory justification required.
        """
        cls._verify_finance_officer(actor)
        event = await cls._get_confirmed_event(db, event_id)
        await cls._verify_delivery_certified(db, event)

        expense = await db.scalar(
            select(ActualExpense)
            .where(ActualExpense.id == expense_id, ActualExpense.event_id == event.id)
            .options(
                selectinload(ActualExpense.bill_document),
                selectinload(ActualExpense.submitter),
                selectinload(ActualExpense.verifier),
            )
            .with_for_update()
        )
        if not expense:
            raise NotFoundError(f"Actual expense '{expense_id}' not found.")

        if expense.status != ActualExpenseStatus.SUBMITTED:
            raise WorkflowStateError(
                f"Cannot disallow expense in '{_val(expense.status)}' status. Must be SUBMITTED."
            )

        now_utc = datetime.now(UTC)
        prior_state = {
            "status": _val(expense.status),
            "claimed_amount": str(expense.claimed_amount),
            "verified_amount": None,
        }

        expense.verified_amount = Decimal("0.00")
        expense.status = ActualExpenseStatus.DISALLOWED
        expense.verified_by = actor.id
        expense.verified_at = now_utc
        expense.updated_at = now_utc
        expense.finance_remarks = payload.remarks
        expense.verifier = actor

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.EXPENSE_DISALLOWED,
                entity_type="actual_expense",
                entity_id=str(expense.id),
                previous_state=prior_state,
                new_state={
                    "status": ActualExpenseStatus.DISALLOWED.value,
                    "claimed_amount": str(expense.claimed_amount),
                    "verified_amount": "0.00",
                    "disallowed_amount": str(expense.claimed_amount),
                    "finance_remarks": payload.remarks,
                },
                reason=payload.remarks,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # Notify submitter
        await NotificationService.create_notification(
            db=db,
            recipient_id=expense.submitted_by,
            notification_type=NotificationType.EXPENSE_DISALLOWED,
            title="Expense Claim Disallowed",
            message=(
                f"Expense of ₹{expense.claimed_amount} for '{expense.vendor_name}' "
                f"was disallowed. Reason: {payload.remarks}"
            ),
            event_request_id=event.event_request_id,
        )

        await db.flush()
        return to_actual_expense_response(expense)

    # =========================================================================
    # QUERIES & SUMMARIES
    # =========================================================================

    @classmethod
    async def get_event_expenses(
        cls, db: AsyncSession, event_id: uuid.UUID, actor: User
    ) -> list[ActualExpenseResponse]:
        """List all actual expenses for an event with eager loaded relationships."""
        event = await cls._get_confirmed_event(db, event_id)

        # Role checks: Secretary can only view own club
        if actor.role == UserRole.CLUB_SECRETARY:
            member = await db.scalar(
                select(ClubMember).where(
                    ClubMember.club_id == event.club_id,
                    ClubMember.user_id == actor.id,
                    ClubMember.is_active.is_(True),
                )
            )
            if not member:
                raise ForbiddenError("Cannot view financial records of another club's event.")

        expenses = (
            await db.scalars(
                select(ActualExpense)
                .where(ActualExpense.event_id == event.id)
                .options(
                    selectinload(ActualExpense.bill_document),
                    selectinload(ActualExpense.submitter),
                    selectinload(ActualExpense.verifier),
                )
                .order_by(ActualExpense.created_at.asc())
            )
        ).all()

        return [to_actual_expense_response(e) for e in expenses]

    @classmethod
    async def get_single_expense(
        cls, db: AsyncSession, event_id: uuid.UUID, expense_id: uuid.UUID, actor: User
    ) -> ActualExpenseResponse:
        """Get details of a single actual expense."""
        event = await cls._get_confirmed_event(db, event_id)

        if actor.role == UserRole.CLUB_SECRETARY:
            member = await db.scalar(
                select(ClubMember).where(
                    ClubMember.club_id == event.club_id,
                    ClubMember.user_id == actor.id,
                    ClubMember.is_active.is_(True),
                )
            )
            if not member:
                raise ForbiddenError("Cannot access expense record of another club's event.")

        expense = await db.scalar(
            select(ActualExpense)
            .where(ActualExpense.id == expense_id, ActualExpense.event_id == event.id)
            .options(
                selectinload(ActualExpense.bill_document),
                selectinload(ActualExpense.submitter),
                selectinload(ActualExpense.verifier),
            )
        )
        if not expense:
            raise NotFoundError(f"Actual expense '{expense_id}' not found.")

        return to_actual_expense_response(expense)

    @classmethod
    async def get_ledger_summary(
        cls, db: AsyncSession, event_id: uuid.UUID, actor: User
    ) -> ExpenseLedgerSummaryResponse:
        """Compute authoritative financial aggregates and reconciliation metrics."""
        event = await cls._get_confirmed_event(db, event_id)

        if actor.role == UserRole.CLUB_SECRETARY:
            member = await db.scalar(
                select(ClubMember).where(
                    ClubMember.club_id == event.club_id,
                    ClubMember.user_id == actor.id,
                    ClubMember.is_active.is_(True),
                )
            )
            if not member:
                raise ForbiddenError("Cannot access ledger summary of another club's event.")

        expenses = (
            await db.scalars(
                select(ActualExpense)
                .where(ActualExpense.event_id == event.id)
                .options(
                    selectinload(ActualExpense.bill_document),
                    selectinload(ActualExpense.submitter),
                    selectinload(ActualExpense.verifier),
                )
                .order_by(ActualExpense.created_at.asc())
            )
        ).all()

        # Sanctioned budget from approved BudgetProposal
        budget_prop = await db.scalar(
            select(BudgetProposal).where(BudgetProposal.event_request_id == event.event_request_id)
        )
        sanctioned_budget = (
            budget_prop.total_expected_expenditure
            if budget_prop and budget_prop.total_expected_expenditure is not None
            else Decimal("0.00")
        )

        total_claimed = Decimal("0.00")
        total_verified = Decimal("0.00")
        total_disallowed = Decimal("0.00")

        status_counts: dict[str, int] = defaultdict(int)
        cat_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "claimed": Decimal("0.00"),
                "verified": Decimal("0.00"),
                "disallowed": Decimal("0.00"),
                "count": 0,
            }
        )

        for e in expenses:
            st = _val(e.status)
            status_counts[st] += 1
            cat_key = e.category.value if hasattr(e.category, "value") else str(e.category)

            # Claimed Spend excludes DISALLOWED
            if e.status != ActualExpenseStatus.DISALLOWED:
                total_claimed += e.claimed_amount
                cat_stats[cat_key]["claimed"] += e.claimed_amount

            # Verified Spend from VERIFIED and PARTIALLY_VERIFIED
            if (
                e.status in (ActualExpenseStatus.VERIFIED, ActualExpenseStatus.PARTIALLY_VERIFIED)
                and e.verified_amount is not None
            ):
                total_verified += e.verified_amount
                cat_stats[cat_key]["verified"] += e.verified_amount

            # Disallowed Spend
            if e.status in (
                ActualExpenseStatus.VERIFIED,
                ActualExpenseStatus.PARTIALLY_VERIFIED,
                ActualExpenseStatus.DISALLOWED,
            ):
                d = e.disallowed_amount
                total_disallowed += d
                cat_stats[cat_key]["disallowed"] += d

            cat_stats[cat_key]["count"] += 1

        category_breakdown = [
            ExpenseCategorySummary(
                category=k,
                claimed_amount=v["claimed"],
                verified_amount=v["verified"],
                disallowed_amount=v["disallowed"],
                count=v["count"],
            )
            for k, v in sorted(cat_stats.items())
        ]

        # Check delivery certification
        report = await db.scalar(
            select(PostEventReport).where(PostEventReport.event_id == event.id)
        )
        delivery_certified = bool(
            report is not None and report.status == PostEventReportStatus.CERTIFIED
        )

        can_submit = (
            actor.role == UserRole.CLUB_SECRETARY
            and event.status == EventStatus.COMPLETED
            and any(
                e.status in (ActualExpenseStatus.DRAFT, ActualExpenseStatus.QUERIED)
                for e in expenses
            )
        )
        can_audit = (
            actor.role == UserRole.FINANCE_OFFICER
            and delivery_certified
            and any(e.status == ActualExpenseStatus.SUBMITTED for e in expenses)
        )

        items_resp = [to_actual_expense_response(e) for e in expenses]

        return ExpenseLedgerSummaryResponse(
            event_id=event.id,
            sanctioned_budget=sanctioned_budget,
            total_claimed_spend=total_claimed,
            total_verified_spend=total_verified,
            total_disallowed_spend=total_disallowed,
            total_expenses_count=len(expenses),
            status_counts=dict(status_counts),
            category_breakdown=category_breakdown,
            can_submit=can_submit,
            can_audit=can_audit,
            delivery_certified=delivery_certified,
            items=items_resp,
        )
