"""
Alembic env.py — CampusConnect migration environment.
Reads DATABASE_URL from environment variables.
Uses synchronous psycopg2 driver for migrations (async not supported by Alembic).
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure the backend package is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import all models so Alembic can detect schema changes
from app.core.database import Base  # noqa: E402  (must be after sys.path modification)
from app.models import *  # noqa: F401, F403 (import all models to register with metadata)

# Alembic Config object
config = context.config

# Set up logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate
target_metadata = Base.metadata


def get_url() -> str:
    """
    Get synchronous database URL from environment or settings.
    Alembic uses synchronous driver (psycopg or psycopg2).
    """
    from app.core.config import get_settings
    settings = get_settings()
    url = os.environ.get("DATABASE_URL_SYNC")
    if not url:
        raw_url = os.environ.get("DATABASE_URL", settings.DATABASE_URL)
        if "postgresql+asyncpg://" in raw_url:
            try:
                import psycopg  # noqa: F401
                driver = "postgresql+psycopg://"
            except ImportError:
                driver = "postgresql+psycopg2://"
            url = raw_url.replace("postgresql+asyncpg://", driver)
        else:
            url = raw_url
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without connecting)."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect and execute)."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
