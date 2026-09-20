# CampusConnect Schemas
from app.schemas.auth import (
    TokenPayload,
    TokenResponse,
    UserAuthResponse,
    UserLoginRequest,
    UserRegisterRequest,
)
from app.schemas.club import (
    ClubCreate,
    ClubMemberAdd,
    ClubMemberResponse,
    ClubMemberUpdate,
    ClubResponse,
    ClubUpdate,
)
from app.schemas.event import (
    EventRequestCreate,
    EventRequestResponse,
    EventRequestSubmit,
    EventRequestUpdate,
)

__all__ = [
    "TokenPayload",
    "TokenResponse",
    "UserAuthResponse",
    "UserLoginRequest",
    "UserRegisterRequest",
    "ClubCreate",
    "ClubUpdate",
    "ClubResponse",
    "ClubMemberAdd",
    "ClubMemberUpdate",
    "ClubMemberResponse",
    "EventRequestCreate",
    "EventRequestUpdate",
    "EventRequestSubmit",
    "EventRequestResponse",
]
from app.schemas.budget import (
    BudgetLineItemCreate,
    BudgetLineItemResponse,
    BudgetLineItemUpdate,
    BudgetProposalCreate,
    BudgetProposalResponse,
    BudgetProposalUpdate,
    FinanceVerificationRequest,
)
from app.schemas.venue import (
    HallAvailabilityResponse,
    HallCreate,
    HallResponse,
    VenueRequestCreate,
    VenueRequestResponse,
    VenueRequestUpdate,
)
from app.schemas.workflow import (
    WorkflowInstanceResponse,
    WorkflowPendingItemResponse,
    WorkflowStepApproveRequest,
    WorkflowStepRejectRequest,
    WorkflowStepResponse,
    WorkflowStepRevisionRequest,
)
