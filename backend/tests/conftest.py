"""
CampusConnect — Pytest Configuration and Fixtures
Shared test infrastructure for unit and API tests.
"""
import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Use an in-memory SQLite for tests to avoid requiring PostgreSQL
# Note: For tests involving PostgreSQL-specific features (EXCLUDE constraints),
# use a real PostgreSQL test database by setting TEST_DATABASE_URL env var.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///:memory:",
)

# Override settings for test environment
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("ENV", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("ALLOWED_EMAIL_DOMAIN", "college.edu")
os.environ.setdefault("EMAIL_PROVIDER", "development")

from app.core.config import get_settings  # noqa: E402
get_settings.cache_clear()

from app.core.database import Base, engine as app_engine, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create an async test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False} if "sqlite" in TEST_DATABASE_URL else {},
        poolclass=StaticPool if "sqlite" in TEST_DATABASE_URL else None,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a test database session that rolls back after each test."""
    async_session = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP test client with overridden DB dependency."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
async def reset_app_engine_pool_per_test():
    """
    Cleanly dispose the global application engine pool after each test.

    Root Cause of asyncpg 'Connection._cancel' warning:
    When health checks or startup lifespan ping the database, the global QueuePool
    retains asyncpg connection objects. Because pytest-asyncio creates a separate
    asyncio event loop for each test function, an existing connection from the pool
    is borrowed across a different event loop in subsequent tests, causing asyncpg to
    abort and fail to await Connection._cancel during loop teardown.

    Disposing the engine inside the same event loop that created the connection
    guarantees all connections are closed cleanly before the event loop shuts down.
    """
    yield
    await app_engine.dispose()
