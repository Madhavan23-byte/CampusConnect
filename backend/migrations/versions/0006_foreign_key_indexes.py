"""Phase 2.5.3 Foreign Key Index Hardening

Adds dedicated btree indexes on high-frequency foreign key columns identified in
the Phase 2.5.3 foreign-key audit:
1. events.hall_id
2. events.approved_version_id
3. event_requests.workflow_instance_id
4. event_requests.submitted_by
5. notifications.event_request_id
6. hall_bookings_confirmed.venue_request_id
7. workflow_instances.template_id
8. workflow_instance_steps.template_step_id

Revision ID: 0006_foreign_key_indexes
Revises: 0005_event_closeout_and_archival
Create Date: 2026-09-29
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0006_foreign_key_indexes"
down_revision: str | None = "0005_event_closeout_and_archival"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = [
    ("ix_events_hall_id", "events", ["hall_id"]),
    ("ix_events_approved_version_id", "events", ["approved_version_id"]),
    ("ix_event_requests_workflow_instance_id", "event_requests", ["workflow_instance_id"]),
    ("ix_event_requests_submitted_by", "event_requests", ["submitted_by"]),
    ("ix_notifications_event_request_id", "notifications", ["event_request_id"]),
    (
        "ix_hall_bookings_confirmed_venue_request_id",
        "hall_bookings_confirmed",
        ["venue_request_id"],
    ),
    ("ix_workflow_instances_template_id", "workflow_instances", ["template_id"]),
    (
        "ix_workflow_instance_steps_template_step_id",
        "workflow_instance_steps",
        ["template_step_id"],
    ),
]


def upgrade() -> None:
    for index_name, table_name, columns in INDEXES:
        op.create_index(index_name, table_name, columns, unique=False)


def downgrade() -> None:
    for index_name, table_name, _ in reversed(INDEXES):
        op.drop_index(index_name, table_name=table_name)
