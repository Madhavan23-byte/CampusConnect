"""
CampusConnect Backend — Custom Exception Classes
Centralised exception hierarchy. FastAPI exception handlers in main.py
convert these to proper HTTP responses.
"""
from typing import Any


class CampusConnectError(Exception):
    """Base exception for all CampusConnect errors."""

    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


# ---------------------------------------------------------------------------
# HTTP 400
# ---------------------------------------------------------------------------
class BadRequestError(CampusConnectError):
    """Malformed request or invalid input that cannot be expressed via Pydantic."""
    status_code: int = 400


# ---------------------------------------------------------------------------
# HTTP 401
# ---------------------------------------------------------------------------
class UnauthorizedError(CampusConnectError):
    """Request is not authenticated."""
    status_code: int = 401


class InvalidCredentialsError(UnauthorizedError):
    """Wrong email or password."""


class TokenExpiredError(UnauthorizedError):
    """JWT or refresh token has expired."""


class InvalidTokenError(UnauthorizedError):
    """JWT is malformed or tampered."""


class EmailNotVerifiedError(UnauthorizedError):
    """User has not verified their email yet."""


class AccountLockedError(UnauthorizedError):
    """Account is locked due to too many failed login attempts."""


class AccountInactiveError(UnauthorizedError):
    """Account has been deactivated by an administrator."""


# ---------------------------------------------------------------------------
# HTTP 403
# ---------------------------------------------------------------------------
class ForbiddenError(CampusConnectError):
    """Authenticated but not authorised for this action."""
    status_code: int = 403


class InsufficientRoleError(ForbiddenError):
    """User's role does not permit this action."""


class ResourceOwnershipError(ForbiddenError):
    """User is authenticated and has the right role, but does not own this resource."""


class WorkflowStateError(ForbiddenError):
    """Action is not allowed in the current workflow state."""


# ---------------------------------------------------------------------------
# HTTP 404
# ---------------------------------------------------------------------------
class NotFoundError(CampusConnectError):
    """Requested resource not found (or soft-deleted)."""
    status_code: int = 404


# ---------------------------------------------------------------------------
# HTTP 409
# ---------------------------------------------------------------------------
class ConflictError(CampusConnectError):
    """Resource conflict — e.g. hall double-booking, optimistic lock failure."""
    status_code: int = 409


class EmailAlreadyExistsError(ConflictError):
    """An account with this email address already exists."""


class HallConflictError(ConflictError):
    """Hall is already booked for the requested time slot."""


class OptimisticLockError(ConflictError):
    """Record was modified by another session. Client must refetch and retry."""


class DuplicateSubmissionError(ConflictError):
    """Duplicate idempotency key — return cached result."""
    def __init__(self, message: str, cached_response: Any = None) -> None:
        super().__init__(message)
        self.cached_response = cached_response


# ---------------------------------------------------------------------------
# HTTP 422
# ---------------------------------------------------------------------------
class BusinessRuleError(CampusConnectError):
    """Business rule violation that passes schema validation but fails domain logic."""
    status_code: int = 422


class InvalidWorkflowTransitionError(BusinessRuleError):
    """Attempted workflow state transition is not allowed."""


class AdvanceBookingViolationError(BusinessRuleError):
    """Hall booking does not meet the minimum advance notice requirement."""


class BudgetCapExceededError(BusinessRuleError):
    """Institutional contribution requested exceeds policy ceiling."""


# ---------------------------------------------------------------------------
# HTTP 500
# ---------------------------------------------------------------------------
class InternalError(CampusConnectError):
    """Unexpected server-side error."""
    status_code: int = 500
