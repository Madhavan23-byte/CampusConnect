"""Initial database schema — CampusConnect Phase 1

Creates all core tables, indexes, constraints, and the critical
PostgreSQL EXCLUDE USING gist constraint for hall booking conflict prevention.

Revision ID: 0001
Revises: (none)
Create Date: 2026-09-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # Enable required PostgreSQL extensions
    # -----------------------------------------------------------------------
    # btree_gist is required for the hall booking exclusion constraint
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # For gen_random_uuid() if needed

    # -----------------------------------------------------------------------
    # users
    # -----------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("designation", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("char_length(email) > 0", name="ck_users_email_not_empty"),
        sa.CheckConstraint("char_length(full_name) > 0", name="ck_users_full_name_not_empty"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])

    # -----------------------------------------------------------------------
    # refresh_tokens
    # -----------------------------------------------------------------------
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    # -----------------------------------------------------------------------
    # password_reset_tokens
    # -----------------------------------------------------------------------
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(512), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # -----------------------------------------------------------------------
    # email_verification_tokens
    # -----------------------------------------------------------------------
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(512), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # -----------------------------------------------------------------------
    # clubs
    # -----------------------------------------------------------------------
    op.create_table(
        "clubs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "faculty_advisor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("academic_year", sa.String(10), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_clubs_name", "clubs", ["name"], unique=True)
    op.create_index("ix_clubs_slug", "clubs", ["slug"], unique=True)
    op.create_index("ix_clubs_faculty_advisor_id", "clubs", ["faculty_advisor_id"])

    # -----------------------------------------------------------------------
    # club_members
    # -----------------------------------------------------------------------
    op.create_table(
        "club_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "club_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("member_role", sa.String(20), nullable=False, server_default="MEMBER"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("club_id", "user_id", name="uq_club_members_club_user"),
    )
    op.create_index("ix_club_members_club_id", "club_members", ["club_id"])
    op.create_index("ix_club_members_user_id", "club_members", ["user_id"])

    # -----------------------------------------------------------------------
    # halls
    # -----------------------------------------------------------------------
    op.create_table(
        "halls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column(
            "available_facilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint("capacity > 0", name="ck_halls_capacity_positive"),
    )
    op.create_index("ix_halls_name", "halls", ["name"], unique=True)

    # -----------------------------------------------------------------------
    # workflow_templates (must exist before event_requests because of FK)
    # -----------------------------------------------------------------------
    op.create_table(
        "workflow_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_type", sa.String(30), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # -----------------------------------------------------------------------
    # workflow_template_steps
    # -----------------------------------------------------------------------
    op.create_table(
        "workflow_template_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(255), nullable=False),
        sa.Column("required_role", sa.String(50), nullable=False),
        sa.Column(
            "assigned_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("is_optional", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "template_id", "step_order", name="uq_workflow_template_steps_template_order"
        ),
        sa.CheckConstraint(
            "step_order > 0", name="ck_workflow_template_steps_order_positive"
        ),
    )
    op.create_index(
        "ix_workflow_template_steps_template_id", "workflow_template_steps", ["template_id"]
    )

    # -----------------------------------------------------------------------
    # workflow_instances (before event_requests because of circular FK)
    # We create the table here but the FK from event_requests → workflow_instances
    # is added as a separate ALTER after event_requests is created.
    # -----------------------------------------------------------------------
    op.create_table(
        "workflow_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_templates.id"),
            nullable=False,
        ),
        # event_request_id FK added after event_requests table is created
        sa.Column("event_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_step_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="IN_PROGRESS"),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_workflow_instances_event_request_id", "workflow_instances", ["event_request_id"]
    )
    op.create_index("ix_workflow_instances_status", "workflow_instances", ["status"])

    # -----------------------------------------------------------------------
    # event_requests
    # -----------------------------------------------------------------------
    op.create_table(
        "event_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "club_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clubs.id"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("expected_attendees", sa.Integer(), nullable=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chief_guest_name", sa.String(255), nullable=True),
        sa.Column("chief_guest_designation", sa.String(255), nullable=True),
        sa.Column("chief_guest_institution", sa.String(255), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version_lock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("academic_year", sa.String(10), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column(
            "workflow_instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_instances.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expected_attendees IS NULL OR expected_attendees > 0",
            name="ck_event_requests_attendees_positive",
        ),
    )
    op.create_index("ix_event_requests_club_id", "event_requests", ["club_id"])
    op.create_index("ix_event_requests_status", "event_requests", ["status"])
    op.create_index(
        "ix_event_requests_status_club", "event_requests", ["status", "club_id"]
    )
    op.create_index(
        "ix_event_requests_academic_year_status",
        "event_requests",
        ["academic_year", "status"],
    )
    op.create_index(
        "ix_event_requests_idempotency_key",
        "event_requests",
        ["idempotency_key"],
        unique=True,
    )

    # Now add the FK from workflow_instances → event_requests (resolve circular dependency)
    op.create_foreign_key(
        "fk_workflow_instances_event_request_id",
        "workflow_instances",
        "event_requests",
        ["event_request_id"],
        ["id"],
    )

    # -----------------------------------------------------------------------
    # event_request_versions
    # -----------------------------------------------------------------------
    op.create_table(
        "event_request_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
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
            server_default=sa.text("NOW()"),
        ),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "event_request_id",
            "version_number",
            name="uq_event_request_versions_request_version",
        ),
    )
    op.create_index(
        "ix_event_request_versions_request_id",
        "event_request_versions",
        ["event_request_id"],
    )

    # -----------------------------------------------------------------------
    # venue_requests
    # -----------------------------------------------------------------------
    op.create_table(
        "venue_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "hall_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("halls.id"),
            nullable=False,
        ),
        sa.Column("requested_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_audience", sa.Integer(), nullable=True),
        sa.Column("requires_stage", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("requires_audio", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("requires_lcd", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("requires_ac", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "requires_projector", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("additional_requirements", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column(
            "reviewed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "end_time > start_time", name="ck_venue_requests_end_after_start"
        ),
    )
    op.create_index(
        "ix_venue_requests_hall_date", "venue_requests", ["hall_id", "requested_date"]
    )

    # -----------------------------------------------------------------------
    # hall_bookings_confirmed
    # CRITICAL: EXCLUDE USING gist prevents overlapping bookings at DB level
    # -----------------------------------------------------------------------
    op.create_table(
        "hall_bookings_confirmed",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "hall_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("halls.id"),
            nullable=False,
        ),
        sa.Column(
            "event_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "venue_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("venue_requests.id"),
            nullable=False,
        ),
        sa.Column("booking_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "end_time > start_time", name="ck_hall_bookings_end_after_start"
        ),
    )
    op.create_index(
        "ix_hall_bookings_hall_date",
        "hall_bookings_confirmed",
        ["hall_id", "booking_date"],
    )

    # CRITICAL: The exclusion constraint that prevents overlapping hall bookings.
    # Uses btree_gist extension (enabled above).
    # tstzrange(start_time, end_time, '[)') = half-open interval: [start, end)
    # This means adjacent bookings (one ends at 12:00, next starts at 12:00) are allowed.
    # WHERE is_active = true means cancelled bookings don't block new ones.
    op.execute("""
        ALTER TABLE hall_bookings_confirmed
        ADD CONSTRAINT excl_hall_bookings_no_overlap
        EXCLUDE USING gist (
            hall_id WITH =,
            tstzrange(start_time, end_time, '[)') WITH &&
        )
        WHERE (is_active = true)
    """)

    # -----------------------------------------------------------------------
    # budget_proposals
    # -----------------------------------------------------------------------
    op.create_table(
        "budget_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "expected_income",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column(
            "institute_contribution",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column(
            "total_expected_expenditure",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("finance_status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column(
            "finance_verified_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("finance_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finance_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "expected_income >= 0", name="ck_budget_proposals_income_non_negative"
        ),
        sa.CheckConstraint(
            "institute_contribution >= 0",
            name="ck_budget_proposals_contribution_non_negative",
        ),
        sa.CheckConstraint(
            "total_expected_expenditure >= 0",
            name="ck_budget_proposals_expenditure_non_negative",
        ),
    )

    # -----------------------------------------------------------------------
    # budget_line_items
    # -----------------------------------------------------------------------
    op.create_table(
        "budget_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "budget_proposal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("budget_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("estimated_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "estimated_amount >= 0", name="ck_budget_line_items_amount_non_negative"
        ),
    )
    op.create_index(
        "ix_budget_line_items_proposal_id",
        "budget_line_items",
        ["budget_proposal_id"],
    )

    # -----------------------------------------------------------------------
    # resource_requests
    # -----------------------------------------------------------------------
    op.create_table(
        "resource_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(30), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column(
            "managed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "quantity > 0", name="ck_resource_requests_quantity_positive"
        ),
    )
    op.create_index(
        "ix_resource_requests_event_request_id",
        "resource_requests",
        ["event_request_id"],
    )

    # -----------------------------------------------------------------------
    # documents
    # -----------------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(30), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("stored_filename", sa.String(100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "file_size_bytes > 0", name="ck_documents_file_size_positive"
        ),
    )
    op.create_index(
        "ix_documents_event_request_id", "documents", ["event_request_id"]
    )
    op.create_index(
        "ix_documents_stored_filename", "documents", ["stored_filename"], unique=True
    )

    # -----------------------------------------------------------------------
    # workflow_instance_steps
    # -----------------------------------------------------------------------
    op.create_table(
        "workflow_instance_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_template_steps.id"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(255), nullable=False),
        sa.Column(
            "assigned_to",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("action_taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("version_reviewed", sa.Integer(), nullable=True),
        sa.Column(
            "step_version_lock", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "instance_id",
            "step_order",
            name="uq_workflow_instance_steps_instance_order",
        ),
    )
    op.create_index(
        "ix_workflow_instance_steps_instance_id",
        "workflow_instance_steps",
        ["instance_id"],
    )
    op.create_index(
        "ix_workflow_instance_steps_assigned_status",
        "workflow_instance_steps",
        ["assigned_to", "status"],
    )

    # -----------------------------------------------------------------------
    # events (confirmed, created from approved event_requests)
    # -----------------------------------------------------------------------
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_requests.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "approved_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_request_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "club_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clubs.id"),
            nullable=False,
        ),
        sa.Column(
            "hall_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("halls.id"),
            nullable=True,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_attendees", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="SCHEDULED"),
        sa.Column("academic_year", sa.String(10), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column(
            "cancelled_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_events_club_id_status", "events", ["club_id", "status"])
    op.create_index(
        "ix_events_academic_year_status", "events", ["academic_year", "status"]
    )
    op.create_index("ix_events_event_date", "events", ["event_date"])

    # -----------------------------------------------------------------------
    # notifications
    # -----------------------------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "recipient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_notifications_recipient_is_read",
        "notifications",
        ["recipient_id", "is_read"],
    )
    op.create_index(
        "ix_notifications_created_at", "notifications", ["created_at"]
    )

    # -----------------------------------------------------------------------
    # audit_logs (append-only — no UPDATE/DELETE should be granted on this table)
    # -----------------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_email", sa.String(255), nullable=True),
        sa.Column("actor_role", sa.String(50), nullable=True),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=True),
        sa.Column(
            "previous_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "new_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index(
        "ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"]
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # -----------------------------------------------------------------------
    # idempotency_records
    # -----------------------------------------------------------------------
    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("endpoint", sa.String(500), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column(
            "response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_idempotency_records_key", "idempotency_records", ["idempotency_key"], unique=True
    )
    op.create_index(
        "ix_idempotency_records_expires_at", "idempotency_records", ["expires_at"]
    )

    # -----------------------------------------------------------------------
    # Triggers: auto-update updated_at on row changes
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql'
    """)

    for table_name in [
        "users", "clubs", "club_members", "halls",
        "event_requests", "venue_requests", "budget_proposals",
        "budget_line_items", "resource_requests", "documents",
        "workflow_templates", "workflow_template_steps",
        "workflow_instances", "workflow_instance_steps", "events",
        "hall_bookings_confirmed",
    ]:
        op.execute(f"""
            CREATE TRIGGER trg_{table_name}_updated_at
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
        """)


def downgrade() -> None:
    # Drop in reverse dependency order
    tables = [
        "idempotency_records",
        "audit_logs",
        "notifications",
        "events",
        "workflow_instance_steps",
        "workflow_instances",
        "documents",
        "resource_requests",
        "budget_line_items",
        "budget_proposals",
        "hall_bookings_confirmed",
        "venue_requests",
        "event_request_versions",
        "event_requests",
        "workflow_template_steps",
        "workflow_templates",
        "club_members",
        "clubs",
        "halls",
        "email_verification_tokens",
        "password_reset_tokens",
        "refresh_tokens",
        "users",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
