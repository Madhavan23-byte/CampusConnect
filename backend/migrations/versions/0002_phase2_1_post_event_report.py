"""Phase 2.1 Post-Event Report and Evidence metadata schema

Creates post_event_reports table and adds event_id + geo-location metadata to documents.

Revision ID: 0002_phase2_1_post_event_report
Revises: 0001_initial_schema
Create Date: 2026-09-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_phase2_1_post_event_report"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. Extend documents table for post-event evidence
    # -----------------------------------------------------------------------
    op.add_column(
        "documents",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_documents_event_id", "documents", ["event_id"], unique=False)
    op.add_column(
        "documents",
        sa.Column("geo_latitude", sa.Numeric(precision=9, scale=6), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("geo_longitude", sa.Numeric(precision=9, scale=6), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("geo_source", sa.String(length=50), nullable=True),
    )

    # -----------------------------------------------------------------------
    # 2. Create post_event_reports table
    # -----------------------------------------------------------------------
    op.create_table(
        "post_event_reports",
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
            unique=True,
        ),
        sa.Column(
            "revision_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "actual_attendance",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "objectives_achieved",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "outcomes",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "challenges",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'SUBMITTED'"),
        ),
        sa.Column(
            "submitted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "certified_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "certified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "certification_remarks",
            sa.Text(),
            nullable=True,
        ),
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
            "actual_attendance > 0",
            name="ck_post_event_reports_attendance_positive",
        ),
        sa.CheckConstraint(
            "revision_number >= 1",
            name="ck_post_event_reports_revision_positive",
        ),
    )
    op.create_index(
        "ix_post_event_reports_event_id", "post_event_reports", ["event_id"], unique=True
    )
    op.create_index(
        "ix_post_event_reports_status", "post_event_reports", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_post_event_reports_status", table_name="post_event_reports")
    op.drop_index("ix_post_event_reports_event_id", table_name="post_event_reports")
    op.drop_table("post_event_reports")

    op.drop_column("documents", "geo_source")
    op.drop_column("documents", "geo_longitude")
    op.drop_column("documents", "geo_latitude")
    op.drop_index("ix_documents_event_id", table_name="documents")
    op.drop_column("documents", "event_id")
