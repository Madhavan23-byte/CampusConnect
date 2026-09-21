"""Phase 2.3 Financial Settlement, Cash Advances, and Actual Income Schema

Creates cash_advances, actual_incomes, financial_settlements, settlement_payments,
and settlement_revisions tables with cascade-hardened restrictive foreign keys and
monetary check constraints.

Revision ID: 0004_phase2_3_financial_settlement
Revises: 0003_phase2_2_actual_expenses
Create Date: 2026-09-21
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_phase2_3_settlement"
down_revision: str | None = "0003_phase2_2_actual_expenses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. Create cash_advances table
    # -----------------------------------------------------------------------
    op.create_table(
        "cash_advances",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_requested", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("amount_approved", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "amount_disbursed",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="REQUESTED",
        ),
        sa.Column(
            "recipient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "disbursed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("disbursement_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_reference", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("event_id", name="uq_cash_advances_event_id"),
        sa.CheckConstraint("amount_requested > 0.00", name="chk_cash_advances_requested_positive"),
        sa.CheckConstraint(
            "amount_approved IS NULL OR amount_approved >= 0.00",
            name="chk_cash_advances_approved_non_negative",
        ),
        sa.CheckConstraint(
            "amount_disbursed >= 0.00",
            name="chk_cash_advances_disbursed_non_negative",
        ),
        sa.CheckConstraint(
            "amount_approved IS NULL OR amount_disbursed <= amount_approved",
            name="chk_cash_advances_disbursed_le_approved",
        ),
    )
    op.create_index("ix_cash_advances_status", "cash_advances", ["status"])

    # -----------------------------------------------------------------------
    # 2. Create actual_incomes table
    # -----------------------------------------------------------------------
    op.create_table(
        "actual_incomes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("payer_name", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column(
            "evidence_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="RECORDED",
        ),
        sa.Column(
            "recorded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "verified_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finance_remarks", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0.00", name="chk_actual_incomes_amount_positive"),
    )
    op.create_index("ix_actual_incomes_event_id", "actual_incomes", ["event_id"])
    op.create_index("ix_actual_incomes_status", "actual_incomes", ["status"])
    op.create_index(
        "ix_actual_incomes_event_id_status", "actual_incomes", ["event_id", "status"]
    )
    op.create_index(
        "ix_actual_incomes_evidence_doc", "actual_incomes", ["evidence_document_id"]
    )

    # -----------------------------------------------------------------------
    # 3. Create financial_settlements table
    # -----------------------------------------------------------------------
    op.create_table(
        "financial_settlements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "approved_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_request_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sanctioned_grant", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("sanctioned_expenditure", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "expected_income",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "total_claimed_expenditure",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "total_verified_expenditure",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "total_disallowed_expenditure",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "total_verified_income",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "net_deficit",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "institutional_payout",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "cash_advance_disbursed",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "settlement_balance",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "reimbursement_due",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "refund_due",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column("settlement_type", sa.String(length=30), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "prepared_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "audited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("audited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finance_remarks", sa.Text(), nullable=True),
        sa.Column("query_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("event_id", name="uq_financial_settlements_event_id"),
        sa.CheckConstraint(
            "sanctioned_grant >= 0.00", name="chk_fin_settlements_grant_non_negative"
        ),
        sa.CheckConstraint(
            "sanctioned_expenditure >= 0.00",
            name="chk_fin_settlements_exp_non_negative",
        ),
        sa.CheckConstraint(
            "total_claimed_expenditure >= 0.00",
            name="chk_fin_settlements_c_exp_non_negative",
        ),
        sa.CheckConstraint(
            "total_verified_expenditure >= 0.00",
            name="chk_fin_settlements_v_exp_non_negative",
        ),
        sa.CheckConstraint(
            "total_disallowed_expenditure >= 0.00",
            name="chk_fin_settlements_d_exp_non_negative",
        ),
        sa.CheckConstraint(
            "total_verified_income >= 0.00",
            name="chk_fin_settlements_v_inc_non_negative",
        ),
        sa.CheckConstraint(
            "net_deficit >= 0.00",
            name="chk_fin_settlements_net_deficit_non_negative",
        ),
        sa.CheckConstraint(
            "institutional_payout >= 0.00",
            name="chk_fin_settlements_payout_non_negative",
        ),
        sa.CheckConstraint(
            "cash_advance_disbursed >= 0.00",
            name="chk_fin_settlements_advance_non_negative",
        ),
        sa.CheckConstraint(
            "reimbursement_due >= 0.00",
            name="chk_fin_settlements_reimb_non_negative",
        ),
        sa.CheckConstraint(
            "refund_due >= 0.00",
            name="chk_fin_settlements_refund_non_negative",
        ),
    )
    op.create_index(
        "ix_financial_settlements_status", "financial_settlements", ["status"]
    )
    op.create_index(
        "ix_financial_settlements_approved_version",
        "financial_settlements",
        ["approved_version_id"],
    )

    # -----------------------------------------------------------------------
    # 4. Create settlement_payments table
    # -----------------------------------------------------------------------
    op.create_table(
        "settlement_payments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "settlement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("financial_settlements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("payment_type", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("transaction_reference", sa.String(length=100), nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "proof_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "recorded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0.00", name="chk_settlement_payments_amount_positive"),
    )
    op.create_index(
        "ix_settlement_payments_settlement_id",
        "settlement_payments",
        ["settlement_id"],
    )
    op.create_index(
        "ix_settlement_payments_reference",
        "settlement_payments",
        ["transaction_reference"],
    )
    op.create_index(
        "ix_settlement_payments_proof_doc",
        "settlement_payments",
        ["proof_document_id"],
    )

    # -----------------------------------------------------------------------
    # 5. Create settlement_revisions table
    # -----------------------------------------------------------------------
    op.create_table(
        "settlement_revisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "settlement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("financial_settlements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("snapshot_data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "reopened_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reopening_reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "settlement_id", "revision_number", name="uq_settlement_revisions_number"
        ),
        sa.CheckConstraint(
            "revision_number >= 1", name="chk_settlement_revisions_number_positive"
        ),
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("settlement_revisions")
    op.drop_table("settlement_payments")
    op.drop_table("financial_settlements")
    op.drop_table("actual_incomes")
    op.drop_table("cash_advances")
