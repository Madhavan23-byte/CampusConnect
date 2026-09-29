"""
CampusConnect — Health, Readiness & Liveness Probes
Provides standardized endpoints for container orchestrators and monitoring:
- GET /health: Composite health check (application + database)
- GET /health/ready: Readiness probe (verifies database readiness before routing traffic)
- GET /health/live: Liveness probe (verifies application process is responsive)
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.core.logging import get_logger

router = APIRouter(tags=["Health"])
settings = get_settings()
logger = get_logger(__name__)


@router.get("/health", summary="Application composite health check")
async def health_check(response: Response):
    """
    Returns the operational status of the CampusConnect backend and database.
    Used by Docker Compose health checks and load balancers.
    Returns 200 OK or 503 Service Unavailable (without leaking credentials).
    """
    db_status = "ok"
    db_error = None

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = "error"
        db_error = "Database unreachable"
        logger.warning("Health check: database unreachable — %s", str(exc))

    if db_status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        overall_status = "unhealthy"
    else:
        overall_status = "ok"

    return {
        "status": overall_status,
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENV,
        "timestamp": datetime.now(UTC).isoformat(),
        "checks": {
            "database": {
                "status": db_status,
                **({"error": db_error} if db_error else {}),
            }
        },
    }


@router.get("/health/ready", summary="Readiness probe")
async def readiness_probe(response: Response):
    """
    Verifies that the backend is ready to accept user traffic (database is reachable).
    Returns 200 if ready, 503 if not ready.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "app": settings.APP_NAME,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except Exception as exc:
        logger.warning("Readiness probe failed: %s", str(exc))
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "error": "Database unreachable",
            "timestamp": datetime.now(UTC).isoformat(),
        }


@router.get("/health/live", summary="Liveness probe")
async def liveness_probe():
    """
    Verifies that the application event loop is alive and running.
    Does not depend on external services to prevent cascading container restarts.
    """
    return {
        "status": "alive",
        "app": settings.APP_NAME,
        "timestamp": datetime.now(UTC).isoformat(),
    }
