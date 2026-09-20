"""
CampusConnect Backend — FastAPI Application Entry Point

Centralised exception handlers ensure no stack traces reach clients.
All CampusConnect custom exceptions map to structured JSON responses.
"""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.core.exceptions import (
    AccountInactiveError,
    AccountLockedError,
    AdvanceBookingViolationError,
    BadRequestError,
    BusinessRuleError,
    CampusConnectError,
    ConflictError,
    EmailNotVerifiedError,
    ForbiddenError,
    HallConflictError,
    InsufficientRoleError,
    InternalError,
    InvalidCredentialsError,
    InvalidTokenError,
    InvalidWorkflowTransitionError,
    NotFoundError,
    OptimisticLockError,
    ResourceOwnershipError,
    TokenExpiredError,
    UnauthorizedError,
    WorkflowStateError,
)
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: startup and shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info(
        "CampusConnect starting up | env=%s | version=%s",
        settings.ENV,
        settings.APP_VERSION,
    )
    # Verify database connectivity on startup
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection verified successfully.")
    except Exception as exc:
        logger.error("Database connection failed on startup: %s", exc)
        # Don't crash — let health endpoint report unhealthy state

    yield

    logger.info("CampusConnect shutting down.")
    await engine.dispose()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Secure college club and event governance platform.",
        docs_url="/api/v1/docs" if settings.ENV != "production" else None,
        redoc_url="/api/v1/redoc" if settings.ENV != "production" else None,
        openapi_url="/api/v1/openapi.json" if settings.ENV != "production" else None,
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # ------------------------------------------------------------------
    # Request timing middleware
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
        return response

    # ------------------------------------------------------------------
    # Security headers middleware
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response

    # ------------------------------------------------------------------
    # Exception handlers — convert domain exceptions to HTTP responses
    # ------------------------------------------------------------------

    @app.exception_handler(InvalidCredentialsError)
    @app.exception_handler(TokenExpiredError)
    @app.exception_handler(InvalidTokenError)
    @app.exception_handler(EmailNotVerifiedError)
    @app.exception_handler(AccountLockedError)
    @app.exception_handler(AccountInactiveError)
    @app.exception_handler(UnauthorizedError)
    async def unauthorized_handler(request: Request, exc: UnauthorizedError):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "unauthorized", "message": exc.message},
        )

    @app.exception_handler(InsufficientRoleError)
    @app.exception_handler(ResourceOwnershipError)
    @app.exception_handler(WorkflowStateError)
    @app.exception_handler(ForbiddenError)
    async def forbidden_handler(request: Request, exc: ForbiddenError):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "forbidden", "message": exc.message},
        )

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "not_found", "message": exc.message},
        )

    @app.exception_handler(HallConflictError)
    @app.exception_handler(OptimisticLockError)
    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": "conflict", "message": exc.message},
        )

    @app.exception_handler(InvalidWorkflowTransitionError)
    @app.exception_handler(AdvanceBookingViolationError)
    @app.exception_handler(BusinessRuleError)
    async def business_rule_handler(request: Request, exc: BusinessRuleError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "business_rule_violation", "message": exc.message},
        )

    @app.exception_handler(BadRequestError)
    async def bad_request_handler(request: Request, exc: BadRequestError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "bad_request", "message": exc.message},
        )

    @app.exception_handler(InternalError)
    @app.exception_handler(CampusConnectError)
    async def internal_error_handler(request: Request, exc: CampusConnectError):
        logger.error("Unhandled CampusConnectError: %s", exc.message, exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "internal_error", "message": "An unexpected error occurred."},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", str(exc), exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "internal_error", "message": "An unexpected error occurred."},
        )

    # ------------------------------------------------------------------
    # Register routers
    # ------------------------------------------------------------------
    from app.api.v1.api import api_router
    from app.modules.health import router as health_router

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(api_router, prefix="/api/v1")

    # Additional routers will be registered here as modules are implemented:
    # from app.modules.auth.router import router as auth_router
    # app.include_router(auth_router, prefix="/api/v1")
    # ... etc.

    return app


app = create_app()
