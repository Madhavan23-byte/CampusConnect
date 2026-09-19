"""
CampusConnect Backend — Budget Proposal & Line Item Domain Service

Encapsulates all domain and financial logic for:
1. Budget proposal lifecycle bound to EventRequest drafts
2. Itemized expenditure tracking across categories (BudgetLineItemCategory)
3. Strict server-side recalculation of total_expected_expenditure
4. Enforcement of the configurable institutional contribution cap (BUDGET_INSTITUTE_CONTRIBUTION_CAP)
5. Non-negative checks and arithmetic consistency
6. Proposal lifecycle boundary enforcement (immutability upon submission)
7. Finance Officer pre-audit review and verification (VERIFIED / QUERIED)
8. Transactional audit logging (PROPOSAL_UPDATED, BUDGET_VERIFIED, BUDGET_QUERIED)
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.base import NO_VALUE

from app.core.config import get_settings
from app.core.exceptions import (
    BadRequestError,
    BudgetCapExceededError,
    ConflictError,
    NotFoundError,
    WorkflowStateError,
)
from app.models.domain import (
    AuditLog,
    BudgetLineItem,
    BudgetProposal,
    Club,
    EventRequest,
    User,
)
from app.models.enums import (
    AuditAction,
    BudgetLineItemCategory,
    EventRequestStatus,
    FinanceVerificationStatus,
    UserRole,
)
from app.schemas.budget import (
    BudgetLineItemCreate,
    BudgetLineItemResponse,
    BudgetLineItemUpdate,
    BudgetProposalCreate,
    BudgetProposalResponse,
    BudgetProposalUpdate,
    FinanceVerificationRequest,
)
from app.services.club_service import ClubService


def to_line_item_response(item: BudgetLineItem) -> BudgetLineItemResponse:
    """Safely convert a BudgetLineItem into a response schema."""
    return BudgetLineItemResponse(
        id=item.id,
        budget_proposal_id=item.budget_proposal_id,
        description=item.description,
        category=item.category,
        estimated_amount=item.estimated_amount,
        notes=item.notes,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def to_budget_response(bp: BudgetProposal) -> BudgetProposalResponse:
    """Format a BudgetProposal model into a safe public response without triggering lazy loads."""
    insp = inspect(bp)
    items: list[BudgetLineItemResponse] = []
    if "line_items" in insp.attrs:
        raw_items = insp.attrs.line_items.loaded_value
        if raw_items is not NO_VALUE and raw_items is not None:
            items = [to_line_item_response(i) for i in raw_items]

    return BudgetProposalResponse(
        id=bp.id,
        event_request_id=bp.event_request_id,
        expected_income=bp.expected_income,
        institute_contribution=bp.institute_contribution,
        total_expected_expenditure=bp.total_expected_expenditure,
        notes=bp.notes,
        finance_status=bp.finance_status,
        finance_verified_by=bp.finance_verified_by,
        finance_verified_at=bp.finance_verified_at,
        finance_notes=bp.finance_notes,
        line_items=items,
        created_at=bp.created_at,
        updated_at=bp.updated_at,
    )


class BudgetService:
    """Domain service managing event budget proposals, line items, and finance verification."""

    # ------------------------------------------------------------------
    # 1. Budget Proposal Management
    # ------------------------------------------------------------------

    @classmethod
    async def create_budget_proposal(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        budget_in: BudgetProposalCreate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BudgetProposal:
        """Create a budget proposal for an event draft."""
        settings = get_settings()

        # 1. Fetch EventRequest
        event_stmt = (
            select(EventRequest)
            .options(selectinload(EventRequest.club))
            .where(EventRequest.id == event_id, EventRequest.deleted_at.is_(None))
        )
        event = await db.scalar(event_stmt)
        if not event:
            raise NotFoundError(f"Event proposal with ID '{event_id}' was not found.")

        # 2. Lifecycle boundary: Only DRAFT or REVISION_REQUIRED can attach/modify budget
        if event.status not in (EventRequestStatus.DRAFT, EventRequestStatus.REVISION_REQUIRED):
            status_str = event.status.value if hasattr(event.status, "value") else str(event.status)
            raise WorkflowStateError(
                f"Cannot create budget for proposal in '{status_str}' status. "
                "Only proposals in DRAFT or REVISION_REQUIRED state can configure budget requirements."
            )

        # 3. Ownership & active club check
        club = await ClubService.verify_club_ownership(
            db, event.club_id, actor, "create a budget proposal for this event"
        )
        if not club.is_active:
            raise BadRequestError(f"Club '{club.name}' is currently inactive and cannot propose budgets.")

        # 4. Enforce 1-to-1: Check if budget already exists
        existing_bp = await db.scalar(
            select(BudgetProposal).where(BudgetProposal.event_request_id == event_id)
        )
        if existing_bp:
            raise ConflictError("A budget proposal already exists for this event proposal.")

        # 5. Calculate total expenditure from line items
        total_expenditure = Decimal("0.00")
        line_item_models: list[BudgetLineItem] = []
        bp_id = uuid.uuid4()

        for item_in in budget_in.line_items:
            if item_in.estimated_amount <= Decimal("0.00"):
                raise BadRequestError("Line item estimated amount must be strictly greater than zero.")
            total_expenditure += item_in.estimated_amount
            line_item_models.append(
                BudgetLineItem(
                    id=uuid.uuid4(),
                    budget_proposal_id=bp_id,
                    description=item_in.description,
                    category=item_in.category,
                    estimated_amount=item_in.estimated_amount,
                    notes=item_in.notes,
                )
            )

        # 6. Policy checks: Institutional Contribution Cap
        cap = Decimal(str(settings.BUDGET_INSTITUTE_CONTRIBUTION_CAP))
        if budget_in.institute_contribution > cap:
            raise BudgetCapExceededError(
                f"Requested institutional contribution (₹{budget_in.institute_contribution:,.2f}) "
                f"exceeds the institutional policy ceiling of ₹{cap:,.2f} per event."
            )

        # 7. Balance check: income + contribution should not exceed total expenditure (if line items exist)
        if line_item_models and (budget_in.expected_income + budget_in.institute_contribution > total_expenditure):
            raise BadRequestError(
                f"Sum of expected income (₹{budget_in.expected_income:,.2f}) and institute contribution "
                f"(₹{budget_in.institute_contribution:,.2f}) cannot exceed total expenditure (₹{total_expenditure:,.2f})."
            )

        bp = BudgetProposal(
            id=bp_id,
            event_request_id=event_id,
            expected_income=budget_in.expected_income,
            institute_contribution=budget_in.institute_contribution,
            total_expected_expenditure=total_expenditure,
            notes=budget_in.notes,
            finance_status=FinanceVerificationStatus.PENDING,
        )
        db.add(bp)
        for lim in line_item_models:
            db.add(lim)

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_UPDATED,
                entity_type="budget_proposal",
                entity_id=str(bp_id),
                previous_state=None,
                new_state={
                    "event_id": str(event_id),
                    "total_expenditure": str(total_expenditure),
                    "institute_contribution": str(budget_in.institute_contribution),
                    "line_items_count": len(line_item_models),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        try:
            await db.commit()
            await db.refresh(bp)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("Could not create budget proposal due to database conflict.") from exc

        loaded = await db.scalar(
            select(BudgetProposal)
            .options(selectinload(BudgetProposal.line_items))
            .where(BudgetProposal.id == bp_id)
        )
        return loaded or bp

    @classmethod
    async def get_budget_proposal(cls, db: AsyncSession, event_id: uuid.UUID) -> BudgetProposal:
        """Retrieve the budget proposal attached to an event proposal."""
        stmt = (
            select(BudgetProposal)
            .options(selectinload(BudgetProposal.line_items))
            .where(BudgetProposal.event_request_id == event_id)
        )
        bp = await db.scalar(stmt)
        if not bp:
            raise NotFoundError(f"No budget proposal found for event proposal '{event_id}'.")
        return bp

    @classmethod
    async def update_budget_proposal(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        budget_in: BudgetProposalUpdate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BudgetProposal:
        """Modify header values (income, contribution, notes) for a draft budget."""
        settings = get_settings()

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
                f"Cannot update budget for proposal in '{status_str}' status. "
                "Only proposals in DRAFT or REVISION_REQUIRED state can modify budget details."
            )

        club = await ClubService.verify_club_ownership(
            db, event.club_id, actor, "modify budget proposal for this event"
        )
        if not club.is_active:
            raise BadRequestError(f"Club '{club.name}' is currently inactive.")

        bp = await cls.get_budget_proposal(db, event_id)

        target_income = budget_in.expected_income if budget_in.expected_income is not None else bp.expected_income
        target_contribution = (
            budget_in.institute_contribution
            if budget_in.institute_contribution is not None
            else bp.institute_contribution
        )

        cap = Decimal(str(settings.BUDGET_INSTITUTE_CONTRIBUTION_CAP))
        if target_contribution > cap:
            raise BudgetCapExceededError(
                f"Requested institutional contribution (₹{target_contribution:,.2f}) "
                f"exceeds the institutional policy ceiling of ₹{cap:,.2f} per event."
            )

        if bp.total_expected_expenditure > Decimal("0.00"):
            if target_income + target_contribution > bp.total_expected_expenditure:
                raise BadRequestError(
                    f"Sum of expected income (₹{target_income:,.2f}) and institute contribution "
                    f"(₹{target_contribution:,.2f}) cannot exceed total expenditure (₹{bp.total_expected_expenditure:,.2f})."
                )

        prev_state = {
            "expected_income": str(bp.expected_income),
            "institute_contribution": str(bp.institute_contribution),
        }

        if budget_in.expected_income is not None:
            bp.expected_income = budget_in.expected_income
        if budget_in.institute_contribution is not None:
            bp.institute_contribution = budget_in.institute_contribution
        if budget_in.notes is not None:
            bp.notes = budget_in.notes

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_UPDATED,
                entity_type="budget_proposal",
                entity_id=str(bp.id),
                previous_state=prev_state,
                new_state={
                    "expected_income": str(bp.expected_income),
                    "institute_contribution": str(bp.institute_contribution),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        try:
            await db.commit()
            await db.refresh(bp)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("Could not update budget proposal due to database conflict.") from exc

        loaded = await db.scalar(
            select(BudgetProposal)
            .options(selectinload(BudgetProposal.line_items))
            .where(BudgetProposal.id == bp.id)
        )
        return loaded or bp

    @classmethod
    async def delete_budget_proposal(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Remove a budget proposal from an event draft."""
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
                f"Cannot delete budget for proposal in '{status_str}' status. "
                "Only proposals in DRAFT or REVISION_REQUIRED state can remove budget details."
            )

        club = await ClubService.verify_club_ownership(
            db, event.club_id, actor, "remove budget proposal for this event"
        )
        if not club.is_active:
            raise BadRequestError(f"Club '{club.name}' is currently inactive.")

        bp = await cls.get_budget_proposal(db, event_id)

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_UPDATED,
                entity_type="budget_proposal",
                entity_id=str(bp.id),
                previous_state={"event_id": str(event_id), "total": str(bp.total_expected_expenditure)},
                new_state=None,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.delete(bp)
        await db.commit()

    # ------------------------------------------------------------------
    # 2. Line Item Operations (Strict Server Recalculation)
    # ------------------------------------------------------------------

    @classmethod
    async def add_line_item(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        item_in: BudgetLineItemCreate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BudgetLineItem:
        """Add a single itemized cost to a draft budget proposal."""
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
                f"Cannot add line items to proposal in '{status_str}' status. "
                "Only proposals in DRAFT or REVISION_REQUIRED state can modify line items."
            )

        club = await ClubService.verify_club_ownership(
            db, event.club_id, actor, "add line items to this event's budget"
        )
        if not club.is_active:
            raise BadRequestError(f"Club '{club.name}' is currently inactive.")

        bp = await cls.get_budget_proposal(db, event_id)

        item = BudgetLineItem(
            id=uuid.uuid4(),
            budget_proposal_id=bp.id,
            description=item_in.description,
            category=item_in.category,
            estimated_amount=item_in.estimated_amount,
            notes=item_in.notes,
        )
        db.add(item)
        await db.flush()

        # Recalculate total expenditure
        stmt = select(BudgetLineItem).where(BudgetLineItem.budget_proposal_id == bp.id)
        all_items = list((await db.scalars(stmt)).all())
        bp.total_expected_expenditure = sum(i.estimated_amount for i in all_items)

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_UPDATED,
                entity_type="budget_line_item",
                entity_id=str(item.id),
                previous_state=None,
                new_state={
                    "description": item.description,
                    "amount": str(item.estimated_amount),
                    "new_total_expenditure": str(bp.total_expected_expenditure),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.commit()
        await db.refresh(item)
        return item

    @classmethod
    async def update_line_item(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        item_id: uuid.UUID,
        item_in: BudgetLineItemUpdate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BudgetLineItem:
        """Modify an existing budget line item in draft status."""
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
                f"Cannot update line items for proposal in '{status_str}' status. "
                "Only proposals in DRAFT or REVISION_REQUIRED state can modify line items."
            )

        club = await ClubService.verify_club_ownership(
            db, event.club_id, actor, "update line items for this event's budget"
        )
        if not club.is_active:
            raise BadRequestError(f"Club '{club.name}' is currently inactive.")

        bp = await cls.get_budget_proposal(db, event_id)

        item = await db.scalar(
            select(BudgetLineItem).where(
                BudgetLineItem.id == item_id, BudgetLineItem.budget_proposal_id == bp.id
            )
        )
        if not item:
            raise NotFoundError(f"Budget line item '{item_id}' not found.")

        prev_state = {
            "description": item.description,
            "category": str(item.category),
            "amount": str(item.estimated_amount),
        }

        if item_in.description is not None:
            item.description = item_in.description
        if item_in.category is not None:
            item.category = item_in.category
        if item_in.estimated_amount is not None:
            item.estimated_amount = item_in.estimated_amount
        if item_in.notes is not None:
            item.notes = item_in.notes

        await db.flush()

        # Recalculate total expenditure
        stmt = select(BudgetLineItem).where(BudgetLineItem.budget_proposal_id == bp.id)
        all_items = list((await db.scalars(stmt)).all())
        bp.total_expected_expenditure = sum(i.estimated_amount for i in all_items)

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_UPDATED,
                entity_type="budget_line_item",
                entity_id=str(item.id),
                previous_state=prev_state,
                new_state={
                    "description": item.description,
                    "category": str(item.category),
                    "amount": str(item.estimated_amount),
                    "new_total_expenditure": str(bp.total_expected_expenditure),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.commit()
        await db.refresh(item)
        return item

    @classmethod
    async def delete_line_item(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        item_id: uuid.UUID,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Delete a line item from a draft budget proposal."""
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
                f"Cannot delete line items for proposal in '{status_str}' status. "
                "Only proposals in DRAFT or REVISION_REQUIRED state can remove line items."
            )

        club = await ClubService.verify_club_ownership(
            db, event.club_id, actor, "delete line items from this event's budget"
        )
        if not club.is_active:
            raise BadRequestError(f"Club '{club.name}' is currently inactive.")

        bp = await cls.get_budget_proposal(db, event_id)

        item = await db.scalar(
            select(BudgetLineItem).where(
                BudgetLineItem.id == item_id, BudgetLineItem.budget_proposal_id == bp.id
            )
        )
        if not item:
            raise NotFoundError(f"Budget line item '{item_id}' not found.")

        prev_state = {
            "description": item.description,
            "amount": str(item.estimated_amount),
        }

        if item in bp.line_items:
            bp.line_items.remove(item)
        else:
            await db.delete(item)
        await db.flush()

        # Recalculate total expenditure
        stmt = select(BudgetLineItem).where(BudgetLineItem.budget_proposal_id == bp.id)
        all_items = list((await db.scalars(stmt)).all())
        bp.total_expected_expenditure = sum(i.estimated_amount for i in all_items)

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.PROPOSAL_UPDATED,
                entity_type="budget_line_item",
                entity_id=str(item.id),
                previous_state=prev_state,
                new_state={"new_total_expenditure": str(bp.total_expected_expenditure)},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.commit()

    # ------------------------------------------------------------------
    # 3. Finance Officer Pre-Audit Verification
    # ------------------------------------------------------------------

    @classmethod
    async def verify_budget(
        cls,
        db: AsyncSession,
        event_id: uuid.UUID,
        verification_in: FinanceVerificationRequest,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BudgetProposal:
        """Finance Officer review marking budget as VERIFIED or QUERIED."""
        bp = await cls.get_budget_proposal(db, event_id)

        prev_status = bp.finance_status
        bp.finance_status = verification_in.status
        bp.finance_verified_by = actor.id
        bp.finance_verified_at = datetime.now(timezone.utc)
        bp.finance_notes = verification_in.notes

        action = (
            AuditAction.BUDGET_VERIFIED
            if verification_in.status == FinanceVerificationStatus.VERIFIED
            else AuditAction.BUDGET_QUERIED
        )

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=action,
                entity_type="budget_proposal",
                entity_id=str(bp.id),
                previous_state={"finance_status": str(prev_status)},
                new_state={
                    "finance_status": str(bp.finance_status),
                    "finance_notes": bp.finance_notes,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.commit()
        await db.refresh(bp)
        return bp
