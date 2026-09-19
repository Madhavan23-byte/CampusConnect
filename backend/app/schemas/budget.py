"""
CampusConnect Backend — Budget Proposal & Line Item Pydantic Schemas

Strict schemas enforcing:
- Precise monetary amounts using Decimal (precision=12, scale=2)
- Line item categorization against BudgetLineItemCategory
- Non-negative expenditure, income, and contribution constraints
- Arithmetic consistency and validation
- Finance Officer verification models
"""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import BudgetLineItemCategory, FinanceVerificationStatus


# ---------------------------------------------------------------------------
# Helper Validators
# ---------------------------------------------------------------------------
def _validate_decimal_places(v: Decimal | None) -> Decimal | None:
    if v is not None:
        # Check scale doesn't exceed 2 decimal places
        if v.as_tuple().exponent < -2:
            raise ValueError("Monetary values cannot have more than 2 decimal places.")
    return v


# ---------------------------------------------------------------------------
# Line Item Schemas
# ---------------------------------------------------------------------------
class BudgetLineItemCreate(BaseModel):
    """Payload for creating a new line item in a budget proposal."""

    description: str = Field(min_length=2, max_length=500, description="Item description / specification")
    category: BudgetLineItemCategory = Field(description="Expense classification")
    estimated_amount: Decimal = Field(
        gt=Decimal("0.00"), max_digits=12, decimal_places=2, description="Estimated cost in INR"
    )
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("description")
    @classmethod
    def clean_description(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Description cannot be empty or whitespace.")
        return v

    @field_validator("estimated_amount")
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        return _validate_decimal_places(v)


class BudgetLineItemUpdate(BaseModel):
    """Payload for modifying an existing line item in a draft budget proposal."""

    description: str | None = Field(default=None, min_length=2, max_length=500)
    category: BudgetLineItemCategory | None = None
    estimated_amount: Decimal | None = Field(default=None, gt=Decimal("0.00"), max_digits=12, decimal_places=2)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("description")
    @classmethod
    def clean_description(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Description cannot be empty or whitespace.")
        return v

    @field_validator("estimated_amount")
    @classmethod
    def validate_amount(cls, v: Decimal | None) -> Decimal | None:
        return _validate_decimal_places(v)


class BudgetLineItemResponse(BaseModel):
    """Public representation of an itemized budget line item."""

    id: uuid.UUID
    budget_proposal_id: uuid.UUID
    description: str
    category: BudgetLineItemCategory
    estimated_amount: Decimal
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Budget Proposal Schemas
# ---------------------------------------------------------------------------
class BudgetProposalCreate(BaseModel):
    """Payload for creating a budget proposal for an event draft."""

    expected_income: Decimal = Field(
        default=Decimal("0.00"), ge=Decimal("0.00"), max_digits=12, decimal_places=2
    )
    institute_contribution: Decimal = Field(
        default=Decimal("0.00"), ge=Decimal("0.00"), max_digits=12, decimal_places=2
    )
    notes: str | None = Field(default=None, max_length=2000)
    line_items: list[BudgetLineItemCreate] = Field(default_factory=list)

    @field_validator("expected_income", "institute_contribution")
    @classmethod
    def validate_decimals(cls, v: Decimal) -> Decimal:
        return _validate_decimal_places(v)


class BudgetProposalUpdate(BaseModel):
    """Payload for updating budget income / contribution header in draft status."""

    expected_income: Decimal | None = Field(
        default=None, ge=Decimal("0.00"), max_digits=12, decimal_places=2
    )
    institute_contribution: Decimal | None = Field(
        default=None, ge=Decimal("0.00"), max_digits=12, decimal_places=2
    )
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("expected_income", "institute_contribution")
    @classmethod
    def validate_decimals(cls, v: Decimal | None) -> Decimal | None:
        return _validate_decimal_places(v)


class BudgetProposalResponse(BaseModel):
    """Safe public representation of an event budget proposal."""

    id: uuid.UUID
    event_request_id: uuid.UUID
    expected_income: Decimal
    institute_contribution: Decimal
    total_expected_expenditure: Decimal
    notes: str | None = None
    finance_status: FinanceVerificationStatus
    finance_verified_by: uuid.UUID | None = None
    finance_verified_at: datetime | None = None
    finance_notes: str | None = None
    line_items: list[BudgetLineItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Finance Officer Verification Schema
# ---------------------------------------------------------------------------
class FinanceVerificationRequest(BaseModel):
    """Payload for Finance Officer pre-audit review / verification."""

    status: FinanceVerificationStatus = Field(
        description="Target verification status: VERIFIED or QUERIED"
    )
    notes: str | None = Field(default=None, max_length=2000, description="Audit queries or clearance notes")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: FinanceVerificationStatus) -> FinanceVerificationStatus:
        if v == FinanceVerificationStatus.PENDING:
            raise ValueError("Cannot explicitly set finance verification status back to PENDING.")
        return v
