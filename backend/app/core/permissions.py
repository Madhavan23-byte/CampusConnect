"""
CampusConnect — Permission Definitions and Institutional Role Mapping

Defines granular institutional operations and explicitly maps them to authorized
UserRole members. In Phase 1, CampusConnect enforces role-based access where roles
represent specific institutional responsibilities without implicit hierarchical
inheritance (e.g. Principal does not implicitly possess Club Secretary or Finance
actions).
"""

import enum
from collections.abc import Mapping

from app.models.enums import UserRole


class Permission(str, enum.Enum):
    """Granular system and business permissions."""

    # Club Governance
    CLUB_CREATE = "club:create"
    CLUB_UPDATE = "club:update"
    CLUB_MANAGE_MEMBERS = "club:manage_members"
    CLUB_VIEW_ANY = "club:view_any"

    # Event Proposals
    EVENT_PROPOSE = "event:propose"
    EVENT_EDIT_DRAFT = "event:edit_draft"
    EVENT_CANCEL = "event:cancel"
    EVENT_VIEW_ALL = "event:view_all"

    # Approval Chain Steps (Institutional Responsibilities)
    APPROVAL_FACULTY_REVIEW = "approval:faculty_review"
    APPROVAL_HALL_REVIEW = "approval:hall_review"
    APPROVAL_UNION_REVIEW = "approval:union_review"
    APPROVAL_DEAN_REVIEW = "approval:dean_review"
    APPROVAL_PRINCIPAL_REVIEW = "approval:principal_review"
    APPROVAL_FINANCE_REVIEW = "approval:finance_review"

    # Venue / Hall Management
    HALL_CREATE = "hall:create"
    HALL_UPDATE = "hall:update"
    HALL_OVERRIDE_BOOKING = "hall:override_booking"

    # Finance & Settlement
    BUDGET_APPROVE = "budget:approve"
    FINANCIAL_SETTLEMENT = "financial:settlement"

    # System Administration
    SYSTEM_CONFIG = "system:config"
    USER_MANAGE = "user:manage"
    AUDIT_LOG_VIEW = "audit_log:view"


# Explicit mapping from institutional permission to authorized roles.
# NOTE: Roles are explicit. An administrator or executive only has access
# if explicitly included in the set.
ROLE_PERMISSIONS: Mapping[Permission, frozenset[UserRole]] = {
    # Clubs
    Permission.CLUB_CREATE: frozenset({UserRole.SYSTEM_ADMIN}),
    Permission.CLUB_UPDATE: frozenset({UserRole.CLUB_SECRETARY, UserRole.SYSTEM_ADMIN}),
    Permission.CLUB_MANAGE_MEMBERS: frozenset({UserRole.CLUB_SECRETARY, UserRole.SYSTEM_ADMIN}),
    Permission.CLUB_VIEW_ANY: frozenset(UserRole),  # All authenticated roles can view
    # Events
    Permission.EVENT_PROPOSE: frozenset({UserRole.CLUB_SECRETARY}),
    Permission.EVENT_EDIT_DRAFT: frozenset({UserRole.CLUB_SECRETARY}),
    Permission.EVENT_CANCEL: frozenset({UserRole.CLUB_SECRETARY, UserRole.SYSTEM_ADMIN}),
    Permission.EVENT_VIEW_ALL: frozenset(UserRole),
    # Approval chain steps
    Permission.APPROVAL_FACULTY_REVIEW: frozenset({UserRole.FACULTY_ADVISOR}),
    Permission.APPROVAL_HALL_REVIEW: frozenset({UserRole.HALL_INCHARGE}),
    Permission.APPROVAL_UNION_REVIEW: frozenset({UserRole.ADVISOR_STUDENTS_UNION}),
    Permission.APPROVAL_DEAN_REVIEW: frozenset({UserRole.DEAN_STUDENT_AFFAIRS}),
    Permission.APPROVAL_PRINCIPAL_REVIEW: frozenset({UserRole.PRINCIPAL}),
    Permission.APPROVAL_FINANCE_REVIEW: frozenset({UserRole.FINANCE_OFFICER}),
    # Halls
    Permission.HALL_CREATE: frozenset({UserRole.SYSTEM_ADMIN}),
    Permission.HALL_UPDATE: frozenset({UserRole.HALL_INCHARGE, UserRole.SYSTEM_ADMIN}),
    Permission.HALL_OVERRIDE_BOOKING: frozenset({UserRole.HALL_INCHARGE, UserRole.PRINCIPAL}),
    # Finance
    Permission.BUDGET_APPROVE: frozenset({UserRole.FINANCE_OFFICER, UserRole.PRINCIPAL}),
    Permission.FINANCIAL_SETTLEMENT: frozenset({UserRole.FINANCE_OFFICER}),
    # System
    Permission.SYSTEM_CONFIG: frozenset({UserRole.SYSTEM_ADMIN}),
    Permission.USER_MANAGE: frozenset({UserRole.SYSTEM_ADMIN}),
    Permission.AUDIT_LOG_VIEW: frozenset(
        {
            UserRole.SYSTEM_ADMIN,
            UserRole.PRINCIPAL,
            UserRole.DEAN_STUDENT_AFFAIRS,
        }
    ),
}
