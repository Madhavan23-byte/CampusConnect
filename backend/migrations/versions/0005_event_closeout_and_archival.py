"""Phase 2.4 Event Closeout and Archival Schema

Creates event_closures and event_closure_revisions tables with cascade-hardened
restrictive foreign keys, unique certification constraints, and revision tracking.

Revision ID: 0005_event_closeout_and_archival
Revises: 0004_phase2_3_settlement
Create Date: 2026-09-27
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_event_closeout_and_archival"
down_revision: str | None = "0004_phase2_3_settlement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_enum_values_if_native(conn, enum_name: str, values: list[str]) -> None:
    """Safely append enum values if native PostgreSQL enum type exists."""
    has_type = conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :typname AND typtype = 'e'"),
        {"typname": enum_name},
    ).scalar()
    if has_type:
        for val in values:
            check_sql = (
                "SELECT 1 FROM pg_enum "
                "WHERE enumtypid = :typname::regtype AND enumlabel = :label"
            )
            has_val = conn.execute(
                sa.text(check_sql),
                {"typname": enum_name, "label": val},
            ).scalar()
            if not has_val:
                conn.execute(sa.text(f"ALTER TYPE {enum_name} ADD VALUE '{val}'"))


def upgrade() -> None:
    conn = op.get_bind()

    # -----------------------------------------------------------------------
    # 1. Update native ENUM types if present in PostgreSQL catalog
    # -----------------------------------------------------------------------
    if conn.dialect.name == "postgresql":
        _add_enum_values_if_native(
            conn, "eventstatus", ["CLOSURE_REQUESTED", "CLOSED"]
        )
        _add_enum_values_if_native(
            conn,
            "auditaction",
            [
                "CLOSURE_REQUESTED",
                "CLOSURE_REJECTED",
                "EVENT_CLOSED",
                "EVENT_REOPEN_REQUESTED",
                "EVENT_REOPENED",
                "EVENT_ARCHIVED",
            ],
        )
        _add_enum_values_if_native(
            conn,
            "notificationtype",
            [
                "EVENT_CLOSURE_REQUESTED",
                "EVENT_CLOSED",
                "EVENT_CLOSURE_REJECTED",
                "EVENT_REOPENED",
            ],
        )

    # -----------------------------------------------------------------------
    # 2. Create event_closures table
    # -----------------------------------------------------------------------
    op.create_table(
        "event_closures",
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
            "settlement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("financial_settlements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "post_event_report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("post_event_reports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "certified_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "certified_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "closure_notes",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "venue_cleared",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "certificate_manifest_hash",
            sa.String(length=64),
            nullable=False,
        ),
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
        sa.UniqueConstraint("event_id", name="uq_event_closures_event_id"),
        sa.UniqueConstraint("settlement_id", name="uq_event_closures_settlement_id"),
    )
    op.create_index(
        "ix_event_closures_certified_at", "event_closures", ["certified_at"]
    )
    op.create_index(
        "ix_event_closures_post_event_report_id",
        "event_closures",
        ["post_event_report_id"],
    )

    # -----------------------------------------------------------------------
    # 3. Create event_closure_revisions table
    # -----------------------------------------------------------------------
    op.create_table(
        "event_closure_revisions",
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
            "closure_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_closures.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "revision_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "reopened_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reopened_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "reopening_reason",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "snapshot_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "event_id", "revision_number", name="uq_event_closure_revisions_number"
        ),
        sa.CheckConstraint(
            "revision_number >= 1",
            name="chk_event_closure_revisions_number_positive",
        ),
    )
    op.create_index(
        "ix_event_closure_revisions_event_id",
        "event_closure_revisions",
        ["event_id"],
    )
    op.create_index(
        "ix_event_closure_revisions_closure_id",
        "event_closure_revisions",
        ["closure_id"],
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("event_closure_revisions")
    op.drop_table("event_closures")
