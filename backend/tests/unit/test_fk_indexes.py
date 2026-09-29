"""
Unit tests for Foreign Key Index definitions and metadata consistency (Phase 2.5.3 GAP-05).
"""

from app.models.domain import (
    Event,
    EventRequest,
    HallBookingConfirmed,
    Notification,
    WorkflowInstance,
    WorkflowInstanceStep,
)


def _get_indexed_column_names(model) -> set[str]:
    table = model.__table__
    indexed_cols = set()
    for index in table.indexes:
        for col in index.columns:
            indexed_cols.add(col.name)
    return indexed_cols


class TestForeignKeyIndexes:
    """Verifies that high-frequency foreign key columns are indexed in SQLAlchemy metadata."""

    def test_events_fk_indexes(self):
        indexed = _get_indexed_column_names(Event)
        assert "hall_id" in indexed, "Event.hall_id must be indexed"
        assert "approved_version_id" in indexed, "Event.approved_version_id must be indexed"
        assert "club_id" in indexed, "Event.club_id must be indexed"

    def test_event_requests_fk_indexes(self):
        indexed = _get_indexed_column_names(EventRequest)
        assert "workflow_instance_id" in indexed, (
            "EventRequest.workflow_instance_id must be indexed"
        )
        assert "submitted_by" in indexed, "EventRequest.submitted_by must be indexed"
        assert "club_id" in indexed, "EventRequest.club_id must be indexed"

    def test_notifications_fk_indexes(self):
        indexed = _get_indexed_column_names(Notification)
        assert "event_request_id" in indexed, "Notification.event_request_id must be indexed"
        assert "recipient_id" in indexed, "Notification.recipient_id must be indexed"

    def test_hall_bookings_confirmed_fk_indexes(self):
        indexed = _get_indexed_column_names(HallBookingConfirmed)
        assert "venue_request_id" in indexed, (
            "HallBookingConfirmed.venue_request_id must be indexed"
        )
        assert "hall_id" in indexed, "HallBookingConfirmed.hall_id must be indexed"

    def test_workflow_instances_fk_indexes(self):
        indexed = _get_indexed_column_names(WorkflowInstance)
        assert "template_id" in indexed, "WorkflowInstance.template_id must be indexed"
        assert "event_request_id" in indexed, "WorkflowInstance.event_request_id must be indexed"

    def test_workflow_instance_steps_fk_indexes(self):
        indexed = _get_indexed_column_names(WorkflowInstanceStep)
        assert "template_step_id" in indexed, (
            "WorkflowInstanceStep.template_step_id must be indexed"
        )
        assert "instance_id" in indexed, "WorkflowInstanceStep.instance_id must be indexed"
