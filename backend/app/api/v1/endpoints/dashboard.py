"""
CampusConnect - Dashboard Endpoints
GET /api/v1/dashboard
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.domain import User
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> DashboardResponse:
    """Return aggregated, role-aware workflow and system metrics."""
    return await DashboardService.get_dashboard(db=db, actor=current_user)
