"""
CampusConnect - Dashboard Schemas
"""

import uuid
from typing import Any

from pydantic import BaseModel


class SecretaryDashboardMetrics(BaseModel):
    draft_count: int = 0
    submitted_count: int = 0
    in_review_count: int = 0
    revision_required_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    recent_events: list[dict[str, Any]] = []


class ReviewerDashboardMetrics(BaseModel):
    pending_actions: int = 0
    completed_approvals: int = 0
    recent_workflow_activity: list[dict[str, Any]] = []


class AdminDashboardMetrics(BaseModel):
    system_counts: dict[str, int] = {}
    pending_proposals: int = 0
    active_users: int = 0
    recent_activity: list[dict[str, Any]] = []


class DashboardResponse(BaseModel):
    role: str
    user_id: uuid.UUID
    secretary: SecretaryDashboardMetrics | None = None
    reviewer: ReviewerDashboardMetrics | None = None
    admin: AdminDashboardMetrics | None = None
