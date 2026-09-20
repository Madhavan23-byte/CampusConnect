"""
CampusConnect — Health Check Endpoint
Returns application status and database connectivity.
No authentication required — used by Docker health checks and monitoring.
"""

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.core.logging import get_logger

router = APIRouter(tags=["Health"])
settings = get_settings()
logger = get_logger(__name__)


@router.get("/health", summary="Application health check")
async def health_check():
    """
    Returns the operational status of the CampusConnect backend.

    Checks:
    - Application is running
    - Database is reachable
    - Configuration is loaded

    Used by:
    - Docker Compose health checks
    - Load balancer health probes
    - Deployment smoke tests
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

    overall_status = "ok" if db_status == "ok" else "degraded"

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
