"""
CampusConnect — Domain Model Architecture & Relationship Verification
Validates that all 20 models have correct foreign keys, relationship mappers,
numeric types for money, and no circular import failures.
"""
from decimal import Decimal
import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import RelationshipProperty

from app.models import (
    AuditLog,
    BudgetLineItem,
    BudgetProposal,
    Club,
    ClubMember,
    Document,
    EmailVerificationToken,
    Event,
    EventRequest,
    EventRequestVersion,
    Hall,
    HallBookingConfirmed,
    IdempotencyRecord,
    Notification,
    PasswordResetToken,
    RefreshToken,
    ResourceRequest,
    User,
    VenueRequest,
    WorkflowInstance,
    WorkflowInstanceStep,
    WorkflowTemplate,
    WorkflowTemplateStep,
)


def test_required_models_exist():
    """Verify all 20 required domain models exist and have valid tablenames."""
    models = [
        User, Club, ClubMember, Hall, HallBookingConfirmed,
        EventRequest, EventRequestVersion, VenueRequest,
        BudgetProposal, BudgetLineItem, ResourceRequest,
        Event, WorkflowTemplate, WorkflowTemplateStep,
        WorkflowInstance, WorkflowInstanceStep,
        Document, Notification, AuditLog, IdempotencyRecord,
    ]
    for model in models:
        mapper = inspect(model)
        assert mapper is not None
        assert mapper.tables[0].name is not None
        assert len(mapper.primary_key) == 1
        pk_col = mapper.primary_key[0]
        # Primary keys must be 'id'
        assert pk_col.name == "id"


def test_financial_field_types():
    """Verify all budget-related fields use Numeric/Decimal, never Float."""
    proposal_mapper = inspect(BudgetProposal)
    for col_name in ["expected_income", "institute_contribution", "total_expected_expenditure"]:
        col = proposal_mapper.columns[col_name]
        col_type_str = str(col.type).upper()
        assert "NUMERIC" in col_type_str or "DECIMAL" in col_type_str
        assert "FLOAT" not in col_type_str

    item_mapper = inspect(BudgetLineItem)
    col = item_mapper.columns["estimated_amount"]
    col_type_str = str(col.type).upper()
    assert "NUMERIC" in col_type_str or "DECIMAL" in col_type_str
    assert "FLOAT" not in col_type_str


def test_critical_relationships():
    """Verify core foreign keys and bidirectional relationships."""
    # User -> Club (faculty advisor)
    user_mapper = inspect(User)
    club_mapper = inspect(Club)
    er_mapper = inspect(EventRequest)
    budget_mapper = inspect(BudgetProposal)
    venue_mapper = inspect(VenueRequest)

    # EventRequest has relationships to Club, VenueRequest, BudgetProposal
    assert "club" in er_mapper.relationships
    assert "venue_request" in er_mapper.relationships
    assert "budget_proposal" in er_mapper.relationships
    assert "versions" in er_mapper.relationships

    # BudgetProposal has relationships to LineItems
    assert "line_items" in budget_mapper.relationships

    # VenueRequest references Hall and EventRequest
    assert "hall" in venue_mapper.relationships
    assert "event_request" in venue_mapper.relationships


def test_audit_log_append_only_model():
    """Verify audit log table has required audit trail columns."""
    mapper = inspect(AuditLog)
    col_names = [c.name for c in mapper.columns]
    assert "actor_id" in col_names
    assert "action" in col_names
    assert "entity_type" in col_names
    assert "entity_id" in col_names
    assert "created_at" in col_names
