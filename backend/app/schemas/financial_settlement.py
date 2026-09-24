"""
CampusConnect - Phase 2.3 Financial Settlement Schemas (Pydantic v2)
Authoritative Decimal monetary schemas for Cash Advances, Actual Income,
Settlement Preparation, Reopening Revisions, and Payment Clearance.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.enums import (
    ActualIncomeStatus,
    CashAdvanceStatus,
    DocumentType,
    IncomeSourceType,
    PaymentMethod,
    SettlementPaymentType,
    SettlementStatus,
    SettlementType,
)

# Constrained string types for mandatory text rationale
ReasonText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=5,
        max_length=1000,
    ),
]

TransactionRef = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=100,
    ),
]


# ---------------------------------------------------------------------------
# Cash Advance Schemas
# ---------------------------------------------------------------------------
class CashAdvanceRequestCreate(BaseModel):
    amount_requested: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        decimal_places=2,
        max_digits=12,
        description="Requested cash advance amount (must not exceed sanctioned grant)",
    )
    reason: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Justification and operational necessity for advance",
    )


class CashAdvanceApprove(BaseModel):
    amount_approved: Decimal = Field(
        ...,
        ge=Decimal("0.00"),
        decimal_places=2,
        max_digits=12,
        description="Finance-approved cash advance amount",
    )
    remarks: str | None = Field(default=None, max_length=500, description="Approval notes")


class CashAdvanceReject(BaseModel):
    rejection_reason: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Mandatory rejection rationale",
    )


class CashAdvanceDisburse(BaseModel):
    amount_disbursed: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        decimal_places=2,
        max_digits=12,
        description="Physical disbursed amount",
    )
    payment_reference: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Banking or voucher transaction reference",
    )
    disbursement_date: datetime | None = Field(
        default=None, description="Physical disbursement timestamp"
    )
    notes: str | None = Field(default=None, max_length=500, description="Disbursement remarks")


class CashAdvanceResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    recipient_id: uuid.UUID
    amount_requested: Decimal
    amount_approved: Decimal | None = None
    amount_disbursed: Decimal = Decimal("0.00")
    status: CashAdvanceStatus
    notes: str | None = None
    rejection_reason: str | None = None
    approved_by: uuid.UUID | None = None
    disbursed_by: uuid.UUID | None = None
    disbursement_date: datetime | None = None
    payment_reference: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Actual Income Schemas
# ---------------------------------------------------------------------------
class ActualIncomeCreate(BaseModel):
    source_type: IncomeSourceType = Field(
        ..., description="Approved revenue stream type"
    )
    amount: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        decimal_places=2,
        max_digits=12,
        description="Gross income collected",
    )
    description: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Detailed description of income source",
    )
    payer_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Payer, sponsor, or ticket platform identity",
    )
    received_date: date = Field(..., description="Date money was received")
    evidence_document_id: uuid.UUID = Field(
        ..., description="Document ID of authentic evidence uploaded via DocumentService"
    )
    reference_number: str | None = Field(
        default=None,
        max_length=100,
        description="Receipt or bank transaction reference",
    )


class ActualIncomeVerify(BaseModel):
    finance_remarks: str | None = Field(
        default=None, max_length=500, description="Verification audit observations"
    )


class ActualIncomeReject(BaseModel):
    rejection_reason: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Mandatory justification for rejecting income entry",
    )
    finance_remarks: str | None = Field(
        default=None, max_length=500, description="Additional audit remarks"
    )


class ActualIncomeResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    source_type: IncomeSourceType
    description: str
    payer_name: str
    amount: Decimal
    received_date: date
    reference_number: str | None = None
    evidence_document_id: uuid.UUID
    status: ActualIncomeStatus
    recorded_by: uuid.UUID
    verified_by: uuid.UUID | None = None
    verified_at: datetime | None = None
    finance_remarks: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Settlement Lifecycle Schemas
# ---------------------------------------------------------------------------
class SettlementAuditRequest(BaseModel):
    action: str = Field(
        ...,
        description="'APPROVE' for audit approval or 'QUERY' to raise audit queries",
    )
    remarks: str | None = Field(default=None, max_length=1000, description="Auditor observations")
    query_reason: str | None = Field(
        default=None,
        max_length=1000,
        description="Mandatory clarification details when action is QUERY",
    )


class SettlementReopenRequest(BaseModel):
    reopening_reason: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Mandatory audit justification for reopening settlement",
    )


# ---------------------------------------------------------------------------
# Payment Clearing Schemas
# ---------------------------------------------------------------------------
class SettlementPaymentCreate(BaseModel):
    payment_type: SettlementPaymentType = Field(
        ...,
        description="REIMBURSEMENT_DISBURSEMENT or ADVANCE_REFUND_RECEIPT",
    )
    amount: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        decimal_places=2,
        max_digits=12,
        description="Clearing payment amount",
    )
    payment_method: PaymentMethod = Field(
        ..., description="Institutional clearing method (BANK_TRANSFER_NEFT, CHEQUE, etc.)"
    )
    transaction_reference: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Bank UTR or institutional transaction reference",
    )
    transaction_date: datetime = Field(..., description="Date transaction was executed")
    proof_document_id: uuid.UUID = Field(
        ..., description="Document ID of settlement payment proof (uploaded via DocumentService)"
    )
    notes: str | None = Field(default=None, max_length=500, description="Payment remarks")


class SettlementPaymentResponse(BaseModel):
    id: uuid.UUID
    settlement_id: uuid.UUID
    payment_type: SettlementPaymentType
    amount: Decimal
    payment_method: PaymentMethod
    transaction_reference: str
    transaction_date: datetime
    proof_document_id: uuid.UUID
    recorded_by: uuid.UUID
    notes: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SettlementRevisionResponse(BaseModel):
    id: uuid.UUID
    settlement_id: uuid.UUID
    revision_number: int
    snapshot_data: dict[str, Any]
    reopened_by: uuid.UUID
    reopening_reason: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Comprehensive Settlement Response Schemas
# ---------------------------------------------------------------------------
class FinancialSettlementResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    approved_version_id: uuid.UUID
    sanctioned_grant: Decimal
    sanctioned_expenditure: Decimal
    expected_income: Decimal
    total_claimed_expenditure: Decimal
    total_verified_expenditure: Decimal
    total_disallowed_expenditure: Decimal
    total_verified_income: Decimal
    net_deficit: Decimal
    institutional_payout: Decimal
    cash_advance_disbursed: Decimal
    settlement_balance: Decimal
    reimbursement_due: Decimal
    refund_due: Decimal
    settlement_type: SettlementType
    status: SettlementStatus
    prepared_by: uuid.UUID
    submitted_at: datetime | None = None
    audited_by: uuid.UUID | None = None
    audited_at: datetime | None = None
    finance_remarks: str | None = None
    query_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FinancialSettlementDetailResponse(FinancialSettlementResponse):
    payments: list[SettlementPaymentResponse] = []
    revisions: list[SettlementRevisionResponse] = []


class ClosureEligibilityResponse(BaseModel):
    eligible: bool
    blockers: list[str]
    event_id: uuid.UUID
    settlement_id: uuid.UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class EvidenceUploadResponse(BaseModel):
    document_id: uuid.UUID
    filename: str
    file_size: int
    content_type: str
    document_type: DocumentType
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)
