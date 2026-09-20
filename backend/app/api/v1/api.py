"""
CampusConnect Backend — API v1 Router Aggregator
"""

from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.clubs import router as clubs_router
from app.api.v1.endpoints.dashboard import router as dashboard_router
from app.api.v1.endpoints.documents import router as documents_router
from app.api.v1.endpoints.event_execution import router as event_execution_router
from app.api.v1.endpoints.events import router as events_router
from app.api.v1.endpoints.halls import router as halls_router
from app.api.v1.endpoints.notifications import router as notifications_router
from app.api.v1.endpoints.resources import router as resources_router
from app.api.v1.endpoints.workflows import router as workflows_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(clubs_router, prefix="/clubs", tags=["Clubs"])
api_router.include_router(events_router, prefix="/events", tags=["Events"])
api_router.include_router(documents_router, prefix="/events", tags=["Documents"])
api_router.include_router(resources_router, prefix="/events", tags=["Resources"])
api_router.include_router(halls_router, prefix="/halls", tags=["Halls"])
api_router.include_router(workflows_router, prefix="/workflows", tags=["Workflows"])
api_router.include_router(notifications_router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(event_execution_router, prefix="/events", tags=["Event Execution"])
