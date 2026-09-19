"""
CampusConnect Backend — Workflow API Endpoints

Provides institutional review and approval workflow operations:
- Inspection of pending institutional action queues
- Detailed inspection of specific workflow instances
- Transactional step approval with domain interlocks
- Rejection with mandatory justification
- Revision requests with mandatory reviewer feedback
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.domain import User
from app.schemas.workflow import (
    WorkflowInstanceResponse,
    WorkflowPendingItemResponse,
    WorkflowStepApproveRequest,
    WorkflowStepRejectRequest,
    WorkflowStepResponse,
    WorkflowStepRevisionRequest,
)
from app.services.workflow_service import WorkflowService, to_step_response

router = APIRouter()


@router.get(
    "/pending",
    response_model=list[WorkflowPendingItemResponse],
    summary="Get pending workflow queue",
    description=(
        "Retrieve proposals currently awaiting institutional action from the calling reviewer."
    ),
)
async def get_pending_queue(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0, description="Items to skip"),
    limit: int = Query(default=50, ge=1, le=100, description="Max items to return"),
) -> list[WorkflowPendingItemResponse]:
    return await WorkflowService.get_pending_queue(
        db=db, actor=current_user, skip=skip, limit=limit
    )


@router.get(
    "/instance/{instance_id}",
    response_model=WorkflowInstanceResponse,
    summary="Get workflow instance details",
    description=(
        "Inspect a complete workflow instance including all historical and pending step decisions."
    ),
)
async def get_workflow_instance(
    instance_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowInstanceResponse:
    return await WorkflowService.get_workflow_instance(db=db, instance_id=instance_id)


@router.post(
    "/steps/{step_id}/approve",
    response_model=WorkflowStepResponse,
    summary="Approve workflow step",
    description=(
        "Approve current sequential step, trigger domain interlocks, and advance workflow pointer."
    ),
)
async def approve_workflow_step(
    step_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    approve_in: WorkflowStepApproveRequest | None = None,
) -> WorkflowStepResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    comments = approve_in.comments if approve_in else None

    step = await WorkflowService.approve_step(
        db=db,
        step_id=step_id,
        actor=current_user,
        comments=comments,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_step_response(step)


@router.post(
    "/steps/{step_id}/reject",
    response_model=WorkflowStepResponse,
    summary="Reject workflow step",
    description=(
        "Reject proposal with mandatory justification. "
        "Terminates workflow and transitions proposal to REJECTED."
    ),
)
async def reject_workflow_step(
    step_id: uuid.UUID,
    reject_in: WorkflowStepRejectRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowStepResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    step = await WorkflowService.reject_step(
        db=db,
        step_id=step_id,
        actor=current_user,
        comments=reject_in.comments,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_step_response(step)


@router.post(
    "/steps/{step_id}/request-revision",
    response_model=WorkflowStepResponse,
    summary="Request proposal revision",
    description=(
        "Request modifications with mandatory instructions. "
        "Transitions proposal to REVISION_REQUIRED for secretary editing."
    ),
)
async def request_workflow_step_revision(
    step_id: uuid.UUID,
    revision_in: WorkflowStepRevisionRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowStepResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    step = await WorkflowService.request_revision(
        db=db,
        step_id=step_id,
        actor=current_user,
        comments=revision_in.comments,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return to_step_response(step)
