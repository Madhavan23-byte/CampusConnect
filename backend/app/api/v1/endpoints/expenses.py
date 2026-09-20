"""
CampusConnect - Actual Expenses Ledger & Finance Verification Endpoints (Phase 2.2)

Provides REST endpoints for:
- Secretary bill document upload
- Secretary draft expense line creation, editing, and deletion
- Secretary expense submission & resubmission
- Finance Officer verification (full and partial)
- Finance Officer query & disallowance
- Event expense ledger arithmetic summaries
"""

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

from app.api.deps import get_current_user, get_db
from app.models.domain import User
from app.schemas.actual_expense import (
    ActualExpenseCreate,
    ActualExpenseDisallow,
    ActualExpensePartialVerify,
    ActualExpenseQuery,
    ActualExpenseResponse,
    ActualExpenseSubmit,
    ActualExpenseUpdate,
    ActualExpenseVerify,
    BillUploadResponse,
    ExpenseLedgerSummaryResponse,
)
from app.services.document_service import DocumentService
from app.services.expense_service import ExpenseService

router = APIRouter()


@router.post(
    "/{id}/expenses/upload-bill",
    response_model=BillUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload authentic bill/receipt document",
)
async def upload_expense_bill(
    id: uuid.UUID,
    file: Annotated[UploadFile, File(description="Bill or invoice document (PDF, PNG, JPG)")],
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BillUploadResponse:
    """Upload a verified bill/receipt document to support actual expense claims."""
    doc = await DocumentService.upload_expense_invoice(
        db=db,
        event_id=id,
        file=file,
        actor=current_user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return BillUploadResponse(
        id=doc.id,
        original_filename=doc.original_filename,
        file_size_bytes=doc.file_size_bytes,
        mime_type=doc.mime_type,
        file_hash=doc.file_hash,
        created_at=doc.created_at,
    )


@router.post(
    "/{id}/expenses",
    response_model=ActualExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create draft expense line item",
)
async def create_expense(
    id: uuid.UUID,
    payload: ActualExpenseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActualExpenseResponse:
    """Create a new draft actual expense line item referencing an authentic bill document."""
    return await ExpenseService.create_draft_expense(
        db=db,
        event_id=id,
        payload=payload,
        actor=current_user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.get(
    "/{id}/expenses/summary",
    response_model=ExpenseLedgerSummaryResponse,
    summary="Get ledger financial summary and category statistics",
)
async def get_expense_summary(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExpenseLedgerSummaryResponse:
    """Retrieve financial reconciliation aggregates, budget variance, and status breakdowns."""
    return await ExpenseService.get_ledger_summary(
        db=db,
        event_id=id,
        actor=current_user,
    )


@router.get(
    "/{id}/expenses",
    response_model=list[ActualExpenseResponse],
    summary="List all actual expenses for an event",
)
async def list_expenses(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ActualExpenseResponse]:
    """List all recorded actual expenses for the specified event."""
    return await ExpenseService.get_event_expenses(
        db=db,
        event_id=id,
        actor=current_user,
    )


@router.get(
    "/{id}/expenses/{expense_id}",
    response_model=ActualExpenseResponse,
    summary="Get details of a single actual expense",
)
async def get_expense(
    id: uuid.UUID,
    expense_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActualExpenseResponse:
    """Get single actual expense by ID."""
    return await ExpenseService.get_single_expense(
        db=db,
        event_id=id,
        expense_id=expense_id,
        actor=current_user,
    )


@router.patch(
    "/{id}/expenses/{expense_id}",
    response_model=ActualExpenseResponse,
    summary="Update a DRAFT or QUERIED expense line item",
)
async def update_expense(
    id: uuid.UUID,
    expense_id: uuid.UUID,
    payload: ActualExpenseUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActualExpenseResponse:
    """Update editable fields of a draft or queried expense item."""
    return await ExpenseService.update_expense(
        db=db,
        event_id=id,
        expense_id=expense_id,
        payload=payload,
        actor=current_user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.delete(
    "/{id}/expenses/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a DRAFT or QUERIED expense line item",
)
async def delete_expense(
    id: uuid.UUID,
    expense_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a draft or queried expense item."""
    await ExpenseService.delete_draft_expense(
        db=db,
        event_id=id,
        expense_id=expense_id,
        actor=current_user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.post(
    "/{id}/expenses/submit",
    response_model=list[ActualExpenseResponse],
    summary="Submit draft expenses for Finance Officer audit",
)
async def submit_expenses(
    id: uuid.UUID,
    payload: ActualExpenseSubmit | None = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ActualExpenseResponse]:
    """Submit draft or queried expense claims to the Finance audit queue."""
    submit_payload = payload or ActualExpenseSubmit()
    return await ExpenseService.submit_expenses(
        db=db,
        event_id=id,
        payload=submit_payload,
        actor=current_user,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )


@router.post(
    "/{id}/expenses/{expense_id}/submit",
    response_model=ActualExpenseResponse,
    summary="Submit a single draft or queried expense",
)
async def submit_single_expense(
    id: uuid.UUID,
    expense_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActualExpenseResponse:
    """Submit a single draft or queried expense claim to Finance audit queue."""
    results = await ExpenseService.submit_expenses(
        db=db,
        event_id=id,
        payload=ActualExpenseSubmit(expense_ids=[expense_id]),
        actor=current_user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return results[0]


@router.post(
    "/{id}/expenses/{expense_id}/verify",
    response_model=ActualExpenseResponse,
    summary="Finance Officer full claim verification",
)
async def verify_expense(
    id: uuid.UUID,
    expense_id: uuid.UUID,
    payload: ActualExpenseVerify,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActualExpenseResponse:
    """Approve full claimed amount (verified_amount == claimed_amount)."""
    return await ExpenseService.verify_expense(
        db=db,
        event_id=id,
        expense_id=expense_id,
        payload=payload,
        actor=current_user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.post(
    "/{id}/expenses/{expense_id}/partial-verify",
    response_model=ActualExpenseResponse,
    summary="Finance Officer partial claim verification",
)
async def partial_verify_expense(
    id: uuid.UUID,
    expense_id: uuid.UUID,
    payload: ActualExpensePartialVerify,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActualExpenseResponse:
    """Approve claim with reduction (0 < verified_amount < claimed_amount)."""
    return await ExpenseService.partial_verify_expense(
        db=db,
        event_id=id,
        expense_id=expense_id,
        payload=payload,
        actor=current_user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.post(
    "/{id}/expenses/{expense_id}/query",
    response_model=ActualExpenseResponse,
    summary="Finance Officer query on expense item",
)
async def query_expense(
    id: uuid.UUID,
    expense_id: uuid.UUID,
    payload: ActualExpenseQuery,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActualExpenseResponse:
    """Request clarification or document re-scan with mandatory remarks."""
    return await ExpenseService.query_expense(
        db=db,
        event_id=id,
        expense_id=expense_id,
        payload=payload,
        actor=current_user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.post(
    "/{id}/expenses/{expense_id}/disallow",
    response_model=ActualExpenseResponse,
    summary="Finance Officer complete claim disallowance",
)
async def disallow_expense(
    id: uuid.UUID,
    expense_id: uuid.UUID,
    payload: ActualExpenseDisallow,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActualExpenseResponse:
    """Completely reject an expense claim (verified_amount = 0.00)."""
    return await ExpenseService.disallow_expense(
        db=db,
        event_id=id,
        expense_id=expense_id,
        payload=payload,
        actor=current_user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
