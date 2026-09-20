"""Phase 2.2 Actual Expenses Ledger and Bill Evidence schema

Creates actual_expenses table with financial check constraints and extends documents with file_hash.

Revision ID: 0003_phase2_2_actual_expenses
Revises: 0002_phase2_1_post_event_report
Create Date: 2026-09-20
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_phase2_2_actual_expenses"
down_revision: str | None = "0002_phase2_1_post_event_report"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. Extend documents table with file_hash for duplicate detection
    # -----------------------------------------------------------------------
    op.add_column(
        "documents",
        sa.Column("file_hash", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_documents_file_hash", "documents", ["file_hash"], unique=False)

    # -----------------------------------------------------------------------
    # 2. Create actual_expenses table
    # -----------------------------------------------------------------------
    op.create_table(
        "actual_expenses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "budget_line_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("budget_line_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("vendor_name", sa.String(length=255), nullable=False),
        sa.Column("vendor_gstin", sa.String(length=20), nullable=True),
        sa.Column("invoice_number", sa.String(length=100), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column(
            "claimed_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
        ),
        sa.Column(
            "verified_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column(
            "bill_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "verified_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finance_remarks", sa.Text(), nullable=True),
        sa.Column("query_reason", sa.Text(), nullable=True),
        sa.Column(
            "is_flagged_for_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("review_notes", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "claimed_amount > 0.00",
            name="chk_actual_expenses_claimed_positive",
        ),
        sa.CheckConstraint(
            "verified_amount IS NULL OR verified_amount >= 0.00",
            name="chk_actual_expenses_verified_non_negative",
        ),
        sa.CheckConstraint(
            "verified_amount IS NULL OR verified_amount <= claimed_amount",
            name="chk_actual_expenses_verified_le_claimed",
        ),
    )
    op.create_index("ix_actual_expenses_event_id", "actual_expenses", ["event_id"], unique=False)
    op.create_index("ix_actual_expenses_status", "actual_expenses", ["status"], unique=False)
    op.create_index(
        "ix_actual_expenses_bill_doc", "actual_expenses", ["bill_document_id"], unique=False
    )
    op.create_index(
        "ix_actual_expenses_budget_line_item_id",
        "actual_expenses",
        ["budget_line_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_actual_expenses_budget_line_item_id", table_name="actual_expenses")
    op.drop_index("ix_actual_expenses_bill_doc", table_name="actual_expenses")
    op.drop_index("ix_actual_expenses_status", table_name="actual_expenses")
    op.drop_index("ix_actual_expenses_event_id", table_name="actual_expenses")
    op.drop_table("actual_expenses")

    op.drop_index("ix_documents_file_hash", table_name="documents")
    op.drop_column("documents", "file_hash")
