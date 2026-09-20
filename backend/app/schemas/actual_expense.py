"""CampusConnect - Actual Expense Ledger & Bill Schemas (Pydantic v2)"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ActualExpenseStatus, BudgetLineItemCategory


class ActualExpenseCreate(BaseModel):
    """Payload for creating a new draft expense line item."""

    category: BudgetLineItemCategory = Field(description="Budget category")
    description: str = Field(min_length=3, max_length=500, description="Description of expenditure")
    vendor_name: str = Field(min_length=2, max_length=255, description="Vendor or payee name")
    vendor_gstin: str | None = Field(
        default=None, max_length=20, description="Vendor GSTIN tax identifier"
    )
    invoice_number: str | None = Field(
        default=None, max_length=100, description="Invoice or receipt number (optional)"
    )
    invoice_date: date = Field(description="Date on the invoice or receipt")
    claimed_amount: Decimal = Field(
        gt=Decimal("0.00"),
        decimal_places=2,
        description="Gross claimed expenditure amount (> 0.00)",
    )
    bill_document_id: uuid.UUID = Field(
        description="Mandatory ID of the uploaded supporting bill/receipt document"
    )
    budget_line_item_id: uuid.UUID | None = Field(
        default=None, description="Optional ID of approved budget line item"
    )

    @field_validator("vendor_name", "description")
    @classmethod
    def strip_text(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Field cannot be whitespace only")
        return s

    @field_validator("invoice_number", "vendor_gstin")
    @classmethod
    def clean_optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s if s else None


class ActualExpenseUpdate(BaseModel):
    """Payload for updating a DRAFT or QUERIED expense line item."""

    category: BudgetLineItemCategory | None = None
    description: str | None = Field(default=None, min_length=3, max_length=500)
    vendor_name: str | None = Field(default=None, min_length=2, max_length=255)
    vendor_gstin: str | None = Field(default=None, max_length=20)
    invoice_number: str | None = Field(default=None, max_length=100)
    invoice_date: date | None = None
    claimed_amount: Decimal | None = Field(default=None, gt=Decimal("0.00"), decimal_places=2)
    bill_document_id: uuid.UUID | None = None
    budget_line_item_id: uuid.UUID | None = None


class ActualExpenseSubmit(BaseModel):
    """Optional payload to submit specific draft expenses."""

    expense_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="List of specific expense IDs to submit, or None to submit all drafts",
    )


class ActualExpenseVerify(BaseModel):
    """Payload for full verification by Finance Officer (claimed == verified)."""

    remarks: str | None = Field(default=None, max_length=1000, description="Optional audit remarks")


class ActualExpensePartialVerify(BaseModel):
    """Payload for partial verification by Finance Officer (0 < verified < claimed)."""

    verified_amount: Decimal = Field(
        gt=Decimal("0.00"),
        decimal_places=2,
        description="Approved expenditure amount (must be strictly less than claimed)",
    )
    remarks: str = Field(
        min_length=5,
        max_length=1000,
        description="Mandatory Finance explanation for the disallowed difference",
    )

    @field_validator("remarks")
    @classmethod
    def validate_remarks(cls, v: str) -> str:
        s = v.strip()
        if len(s) < 5:
            raise ValueError("Remarks must be at least 5 non-whitespace characters")
        return s


class ActualExpenseQuery(BaseModel):
    """Payload for querying an expense by Finance Officer."""

    remarks: str = Field(
        min_length=5,
        max_length=1000,
        description="Mandatory query reason explaining required clarification/amendment",
    )

    @field_validator("remarks")
    @classmethod
    def validate_remarks(cls, v: str) -> str:
        s = v.strip()
        if len(s) < 5:
            raise ValueError("Query reason must be at least 5 non-whitespace characters")
        return s


class ActualExpenseDisallow(BaseModel):
    """Payload for completely disallowing an expense by Finance Officer."""

    remarks: str = Field(
        min_length=5,
        max_length=1000,
        description="Mandatory justification for total disallowance",
    )

    @field_validator("remarks")
    @classmethod
    def validate_remarks(cls, v: str) -> str:
        s = v.strip()
        if len(s) < 5:
            raise ValueError("Justification must be at least 5 non-whitespace characters")
        return s


class ActualExpenseResponse(BaseModel):
    """Public representation of an ActualExpense ledger record."""

    id: uuid.UUID
    event_id: uuid.UUID
    budget_line_item_id: uuid.UUID | None
    category: BudgetLineItemCategory
    description: str
    vendor_name: str
    vendor_gstin: str | None
    invoice_number: str | None
    invoice_date: date
    claimed_amount: Decimal
    verified_amount: Decimal | None
    disallowed_amount: Decimal
    status: ActualExpenseStatus
    bill_document_id: uuid.UUID
    submitted_by: uuid.UUID
    submitted_by_name: str | None = None
    submitted_by_email: str | None = None
    submitted_at: datetime | None
    verified_by: uuid.UUID | None
    verified_by_name: str | None = None
    verified_by_email: str | None = None
    verified_at: datetime | None
    finance_remarks: str | None
    query_reason: str | None
    is_flagged_for_review: bool
    review_notes: str | None
    bill_original_filename: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExpenseCategorySummary(BaseModel):
    """Aggregate statistics for a single budget category."""

    category: str
    claimed_amount: Decimal
    verified_amount: Decimal
    disallowed_amount: Decimal
    count: int


class ExpenseLedgerSummaryResponse(BaseModel):
    """Summary financial reconciliation metrics for an event."""

    event_id: uuid.UUID
    sanctioned_budget: Decimal
    total_claimed_spend: Decimal
    total_verified_spend: Decimal
    total_disallowed_spend: Decimal
    total_expenses_count: int
    status_counts: dict[str, int]
    category_breakdown: list[ExpenseCategorySummary]
    can_submit: bool
    can_audit: bool
    delivery_certified: bool
    items: list[ActualExpenseResponse]

    model_config = ConfigDict(from_attributes=True)


class BillUploadResponse(BaseModel):
    """Metadata response after uploading a bill or invoice document."""

    id: uuid.UUID
    original_filename: str
    file_size_bytes: int
    mime_type: str
    file_hash: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
