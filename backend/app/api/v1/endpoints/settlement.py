"""
CampusConnect - Financial Settlement, Cash Advances, and Actual Income Endpoints (Phase 2.3)

Provides REST endpoints for:
- Secretary cash advance requisition
- Finance Officer cash advance approval, rejection, and disbursement
- Secretary actual income recording and income evidence upload
- Finance Officer actual income verification and rejection
- Secretary financial settlement preparation and submission
- Finance Officer settlement audit (approval with cumulative reconciliation or query)
- Finance Officer and Principal settlement reopening
- Finance Officer settlement payment recording and proof upload
- Payment and revision ledger inspection
- Institutional event closure eligibility evaluation
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_any_role, require_role
from app.core.exceptions import NotFoundError
from app.models.domain import User
from app.models.enums import UserRole
from app.schemas.financial_settlement import (
    ActualIncomeCreate,
    ActualIncomeReject,
    ActualIncomeResponse,
    ActualIncomeVerify,
    CashAdvanceApprove,
    CashAdvanceDisburse,
    CashAdvanceReject,
    CashAdvanceRequestCreate,
    CashAdvanceResponse,
    ClosureEligibilityResponse,
    EvidenceUploadResponse,
    FinancialSettlementDetailResponse,
    FinancialSettlementResponse,
    SettlementAuditRequest,
    SettlementPaymentCreate,
    SettlementPaymentResponse,
    SettlementReopenRequest,
    SettlementRevisionResponse,
)
from app.services.document_service import DocumentService
from app.services.settlement_service import SettlementService

router = APIRouter()


def _get_client_meta(request: Request) -> tuple[str | None, str | None]:
    """Extract client IP address and User-Agent header from request."""
    ip_address = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None
    return ip_address, user_agent


# ===========================================================================
# 1. Cash Advance Endpoints
# ===========================================================================
@router.post(
    "/{event_id}/advances",
    response_model=CashAdvanceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Requisition an operational cash advance for an event",
)
async def request_cash_advance(
    event_id: uuid.UUID,
    payload: CashAdvanceRequestCreate,
    current_user: Annotated[User, Depends(require_role(UserRole.CLUB_SECRETARY))],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> CashAdvanceResponse:
    ip, ua = _get_client_meta(request)
    advance = await SettlementService.request_advance(
        db=db,
        event_id=event_id,
        amount_requested=payload.amount_requested,
        reason=payload.reason,
        actor=current_user,
        ip_address=ip,
        user_agent=ua,
    )
    await db.refresh(advance)
    return CashAdvanceResponse.model_validate(advance)


@router.get(
    "/{event_id}/advances",
    response_model=CashAdvanceResponse | None,
    status_code=status.HTTP_200_OK,
    summary="Retrieve cash advance requisition status for an event",
)
async def get_cash_advance(
    event_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CashAdvanceResponse | None:
    advance = await SettlementService.get_advances_for_event(
        db=db,
        event_id=event_id,
        actor=current_user,
    )
    if not advance:
        return None
    return CashAdvanceResponse.model_validate(advance)


@router.post(
    "/{event_id}/advances/{advance_id}/approve",
    response_model=CashAdvanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Finance Officer approves a cash advance request",
)
async def approve_cash_advance(
    event_id: uuid.UUID,
    advance_id: uuid.UUID,
    payload: CashAdvanceApprove,
    current_user: Annotated[User, Depends(require_role(UserRole.FINANCE_OFFICER))],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> CashAdvanceResponse:
    ip, ua = _get_client_meta(request)
    advance = await SettlementService.approve_advance(
        db=db,
        advance_id=advance_id,
        amount_approved=payload.amount_approved,
        actor=current_user,
        remarks=payload.remarks,
        ip_address=ip,
        user_agent=ua,
    )
    await db.refresh(advance)
    return CashAdvanceResponse.model_validate(advance)


@router.post(
    "/{event_id}/advances/{advance_id}/reject",
    response_model=CashAdvanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Finance Officer rejects a cash advance request",
)
async def reject_cash_advance(
    event_id: uuid.UUID,
    advance_id: uuid.UUID,
    payload: CashAdvanceReject,
    current_user: Annotated[User, Depends(require_role(UserRole.FINANCE_OFFICER))],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> CashAdvanceResponse:
    ip, ua = _get_client_meta(request)
    advance = await SettlementService.reject_advance(
        db=db,
        advance_id=advance_id,
        rejection_reason=payload.rejection_reason,
        actor=current_user,
        ip_address=ip,
        user_agent=ua,
    )
    await db.refresh(advance)
    return CashAdvanceResponse.model_validate(advance)


@router.post(
    "/{event_id}/advances/{advance_id}/disburse",
    response_model=CashAdvanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Finance Officer records the disbursement of an approved advance",
)
async def disburse_cash_advance(
    event_id: uuid.UUID,
    advance_id: uuid.UUID,
    payload: CashAdvanceDisburse,
    current_user: Annotated[User, Depends(require_role(UserRole.FINANCE_OFFICER))],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> CashAdvanceResponse:
    ip, ua = _get_client_meta(request)
    advance = await SettlementService.disburse_advance(
        db=db,
        advance_id=advance_id,
        amount_disbursed=payload.amount_disbursed,
        payment_reference=payload.payment_reference,
        disbursement_date=payload.disbursement_date,
        actor=current_user,
        notes=payload.notes,
        ip_address=ip,
        user_agent=ua,
    )
    await db.refresh(advance)
    return CashAdvanceResponse.model_validate(advance)


# ===========================================================================
# 2. Actual Income Endpoints
# ===========================================================================
@router.post(
    "/{event_id}/incomes/upload-evidence",
    response_model=EvidenceUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload authentic evidence document for actual event income",
)
async def upload_income_evidence_doc(
    event_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="Evidence document")],
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLUB_SECRETARY))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EvidenceUploadResponse:
    ip, ua = _get_client_meta(request)
    doc = await DocumentService.upload_income_evidence(
        db=db,
        event_id=event_id,
        file=file,
        actor=current_user,
        ip_address=ip,
        user_agent=ua,
    )
    return EvidenceUploadResponse(
        document_id=doc.id,
        filename=doc.original_filename,
        file_size=doc.file_size_bytes,
        content_type=doc.mime_type,
        document_type=doc.document_type,
        uploaded_at=doc.created_at,
    )


@router.post(
    "/{event_id}/incomes",
    response_model=ActualIncomeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record external self-generated event revenue",
)
async def record_actual_income(
    event_id: uuid.UUID,
    payload: ActualIncomeCreate,
    current_user: Annotated[User, Depends(require_role(UserRole.CLUB_SECRETARY))],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> ActualIncomeResponse:
    ip, ua = _get_client_meta(request)
    income = await SettlementService.record_income(
        db=db,
        event_id=event_id,
        source_type=payload.source_type,
        amount=payload.amount,
        description=payload.description,
        payer_name=payload.payer_name,
        received_date=payload.received_date,
        evidence_document_id=payload.evidence_document_id,
        actor=current_user,
        reference_number=payload.reference_number,
        ip_address=ip,
        user_agent=ua,
    )
    await db.refresh(income)
    return ActualIncomeResponse.model_validate(income)


@router.get(
    "/{event_id}/incomes",
    response_model=list[ActualIncomeResponse],
    status_code=status.HTTP_200_OK,
    summary="List all recorded income ledger entries for an event",
)
async def list_actual_incomes(
    event_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ActualIncomeResponse]:
    incomes = await SettlementService.get_incomes_for_event(
        db=db,
        event_id=event_id,
        actor=current_user,
    )
    return [ActualIncomeResponse.model_validate(i) for i in incomes]


@router.post(
    "/{event_id}/incomes/{income_id}/verify",
    response_model=ActualIncomeResponse,
    status_code=status.HTTP_200_OK,
    summary="Finance Officer verifies recorded income entry",
)
async def verify_actual_income(
    event_id: uuid.UUID,
    income_id: uuid.UUID,
    payload: ActualIncomeVerify,
    current_user: Annotated[User, Depends(require_role(UserRole.FINANCE_OFFICER))],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> ActualIncomeResponse:
    ip, ua = _get_client_meta(request)
    income = await SettlementService.verify_income(
        db=db,
        income_id=income_id,
        actor=current_user,
        finance_remarks=payload.finance_remarks,
        ip_address=ip,
        user_agent=ua,
    )
    await db.refresh(income)
    return ActualIncomeResponse.model_validate(income)


@router.post(
    "/{event_id}/incomes/{income_id}/reject",
    response_model=ActualIncomeResponse,
    status_code=status.HTTP_200_OK,
    summary="Finance Officer rejects recorded income entry",
)
async def reject_actual_income(
    event_id: uuid.UUID,
    income_id: uuid.UUID,
    payload: ActualIncomeReject,
    current_user: Annotated[User, Depends(require_role(UserRole.FINANCE_OFFICER))],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> ActualIncomeResponse:
    ip, ua = _get_client_meta(request)
    income = await SettlementService.reject_income(
        db=db,
        income_id=income_id,
        rejection_reason=payload.rejection_reason,
        actor=current_user,
        finance_remarks=payload.finance_remarks,
        ip_address=ip,
        user_agent=ua,
    )
    await db.refresh(income)
    return ActualIncomeResponse.model_validate(income)


# ===========================================================================
# 3. Financial Settlement Endpoints
# ===========================================================================
@router.post(
    "/{event_id}/settlement/prepare",
    response_model=FinancialSettlementResponse,
    status_code=status.HTTP_200_OK,
    summary="Club Secretary compiles/recalculates the draft financial settlement",
)
async def prepare_financial_settlement(
    event_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role(UserRole.CLUB_SECRETARY))],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> FinancialSettlementResponse:
    ip, ua = _get_client_meta(request)
    settlement = await SettlementService.prepare_settlement(
        db=db,
        event_id=event_id,
        actor=current_user,
        ip_address=ip,
        user_agent=ua,
    )
    await db.refresh(settlement)
    return FinancialSettlementResponse.model_validate(settlement)


@router.get(
    "/{event_id}/settlement",
    response_model=FinancialSettlementDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve financial settlement details, clearing ledger, and revisions",
)
async def get_financial_settlement(
    event_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FinancialSettlementDetailResponse:
    settlement = await SettlementService.get_settlement(
        db=db,
        event_id=event_id,
        actor=current_user,
    )
    if not settlement:
        raise NotFoundError(f"Financial settlement has not been prepared for event '{event_id}'.")

    payments = await SettlementService.get_settlement_payments(
        db=db,
        settlement_id=settlement.id,
        actor=current_user,
    )
    revisions = await SettlementService.get_settlement_revisions(
        db=db,
        settlement_id=settlement.id,
        actor=current_user,
    )

    resp = FinancialSettlementDetailResponse.model_validate(settlement)
    resp.payments = [SettlementPaymentResponse.model_validate(p) for p in payments]
    resp.revisions = [SettlementRevisionResponse.model_validate(r) for r in revisions]
    return resp


@router.post(
    "/{event_id}/settlement/submit",
    response_model=FinancialSettlementResponse,
    status_code=status.HTTP_200_OK,
    summary="Club Secretary submits draft or queried settlement to Finance for audit",
)
async def submit_financial_settlement(
    event_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role(UserRole.CLUB_SECRETARY))],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> FinancialSettlementResponse:
    ip, ua = _get_client_meta(request)
    settlement = await SettlementService.get_settlement(
        db=db, event_id=event_id, actor=current_user
    )
    if not settlement:
        raise NotFoundError(f"Financial settlement has not been prepared for event '{event_id}'.")

    submitted = await SettlementService.submit_settlement(
        db=db,
        settlement_id=settlement.id,
        actor=current_user,
        ip_address=ip,
        user_agent=ua,
    )
    await db.refresh(submitted)
    return FinancialSettlementResponse.model_validate(submitted)


@router.post(
    "/{event_id}/settlement/audit",
    response_model=FinancialSettlementResponse,
    status_code=status.HTTP_200_OK,
    summary="Finance Officer audits the settlement under review (APPROVE or QUERY)",
)
async def audit_financial_settlement(
    event_id: uuid.UUID,
    payload: SettlementAuditRequest,
    current_user: Annotated[User, Depends(require_role(UserRole.FINANCE_OFFICER))],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> FinancialSettlementResponse:
    ip, ua = _get_client_meta(request)
    settlement = await SettlementService.get_settlement(
        db=db, event_id=event_id, actor=current_user
    )
    if not settlement:
        raise NotFoundError(f"Financial settlement has not been prepared for event '{event_id}'.")

    audited = await SettlementService.audit_settlement(
        db=db,
        settlement_id=settlement.id,
        action=payload.action,
        actor=current_user,
        remarks=payload.remarks,
        query_reason=payload.query_reason,
        ip_address=ip,
        user_agent=ua,
    )
    await db.refresh(audited)
    return FinancialSettlementResponse.model_validate(audited)


@router.post(
    "/{event_id}/settlement/reopen",
    response_model=SettlementRevisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Finance Officer or Principal reopens a SETTLED settlement for revision",
)
async def reopen_financial_settlement(
    event_id: uuid.UUID,
    payload: SettlementReopenRequest,
    current_user: Annotated[
        User, Depends(require_any_role(UserRole.FINANCE_OFFICER, UserRole.PRINCIPAL))
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> SettlementRevisionResponse:
    ip, ua = _get_client_meta(request)
    settlement = await SettlementService.get_settlement(
        db=db, event_id=event_id, actor=current_user
    )
    if not settlement:
        raise NotFoundError(f"Financial settlement has not been prepared for event '{event_id}'.")

    revision = await SettlementService.reopen_settlement(
        db=db,
        settlement_id=settlement.id,
        reopening_reason=payload.reopening_reason,
        actor=current_user,
        ip_address=ip,
        user_agent=ua,
    )
    await db.refresh(revision)
    return SettlementRevisionResponse.model_validate(revision)


# ===========================================================================
# 4. Settlement Payments & Clearing Endpoints
# ===========================================================================
@router.post(
    "/{event_id}/settlement/upload-proof",
    response_model=EvidenceUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an institutional settlement payment proof voucher",
)
async def upload_payment_proof_doc(
    event_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="Evidence document")],
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.FINANCE_OFFICER))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EvidenceUploadResponse:
    ip, ua = _get_client_meta(request)
    doc = await DocumentService.upload_settlement_payment_proof(
        db=db,
        event_id=event_id,
        file=file,
        actor=current_user,
        ip_address=ip,
        user_agent=ua,
    )
    return EvidenceUploadResponse(
        document_id=doc.id,
        filename=doc.original_filename,
        file_size=doc.file_size_bytes,
        content_type=doc.mime_type,
        document_type=doc.document_type,
        uploaded_at=doc.created_at,
    )


@router.post(
    "/{event_id}/settlement/payments",
    response_model=SettlementPaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Finance Officer records a settlement reimbursement or refund recovery payment",
)
async def record_settlement_payment(
    event_id: uuid.UUID,
    payload: SettlementPaymentCreate,
    current_user: Annotated[User, Depends(require_role(UserRole.FINANCE_OFFICER))],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> SettlementPaymentResponse:
    ip, ua = _get_client_meta(request)
    settlement = await SettlementService.get_settlement(
        db=db, event_id=event_id, actor=current_user
    )
    if not settlement:
        raise NotFoundError(f"Financial settlement has not been prepared for event '{event_id}'.")

    payment = await SettlementService.record_payment(
        db=db,
        settlement_id=settlement.id,
        payment_type=payload.payment_type,
        amount=payload.amount,
        payment_method=payload.payment_method,
        transaction_reference=payload.transaction_reference,
        transaction_date=payload.transaction_date,
        proof_document_id=payload.proof_document_id,
        actor=current_user,
        notes=payload.notes,
        ip_address=ip,
        user_agent=ua,
    )
    await db.refresh(payment)
    return SettlementPaymentResponse.model_validate(payment)


@router.get(
    "/{event_id}/settlement/payments",
    response_model=list[SettlementPaymentResponse],
    status_code=status.HTTP_200_OK,
    summary="List all recorded clearing payments for an event settlement",
)
async def list_settlement_payments(
    event_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SettlementPaymentResponse]:
    settlement = await SettlementService.get_settlement(
        db=db, event_id=event_id, actor=current_user
    )
    if not settlement:
        raise NotFoundError(f"Financial settlement has not been prepared for event '{event_id}'.")

    payments = await SettlementService.get_settlement_payments(
        db=db,
        settlement_id=settlement.id,
        actor=current_user,
    )
    return [SettlementPaymentResponse.model_validate(p) for p in payments]


@router.get(
    "/{event_id}/settlement/revisions",
    response_model=list[SettlementRevisionResponse],
    status_code=status.HTTP_200_OK,
    summary="List immutable historical revision snapshots for a reopened settlement",
)
async def list_settlement_revisions(
    event_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SettlementRevisionResponse]:
    settlement = await SettlementService.get_settlement(
        db=db, event_id=event_id, actor=current_user
    )
    if not settlement:
        raise NotFoundError(f"Financial settlement has not been prepared for event '{event_id}'.")

    revisions = await SettlementService.get_settlement_revisions(
        db=db,
        settlement_id=settlement.id,
        actor=current_user,
    )
    return [SettlementRevisionResponse.model_validate(r) for r in revisions]


# ===========================================================================
# 5. Closure Readiness Evaluation
# ===========================================================================
@router.get(
    "/{event_id}/settlement/closure-eligibility",
    response_model=ClosureEligibilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate institutional closure eligibility and active blockers",
)
async def get_settlement_closure_eligibility(
    event_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClosureEligibilityResponse:
    eval_result = await SettlementService.get_closure_eligibility(
        db=db,
        event_id=event_id,
        actor=current_user,
    )
    return ClosureEligibilityResponse(
        eligible=eval_result["eligible"],
        blockers=eval_result["blockers"],
        event_id=uuid.UUID(eval_result["event_id"]),
        settlement_id=(
            uuid.UUID(eval_result["settlement_id"])
            if eval_result.get("settlement_id")
            else None
        ),
    )
