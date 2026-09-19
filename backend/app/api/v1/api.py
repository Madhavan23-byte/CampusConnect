"""
CampusConnect Backend — API v1 Router Aggregator
"""
from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.clubs import router as clubs_router
from app.api.v1.endpoints.events import router as events_router
from app.api.v1.endpoints.halls import router as halls_router
from app.api.v1.endpoints.workflows import router as workflows_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(clubs_router, prefix="/clubs", tags=["Clubs"])
api_router.include_router(events_router, prefix="/events", tags=["Events"])
api_router.include_router(halls_router, prefix="/halls", tags=["Halls"])
api_router.include_router(workflows_router, prefix="/workflows", tags=["Workflows"])
