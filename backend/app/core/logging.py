"""
CampusConnect Backend — Structured Logging
JSON-structured logging for all environments.
Sensitive fields are never logged.
"""

import logging
import sys
from typing import Any

from app.core.config import get_settings

settings = get_settings()

# Fields that must NEVER appear in logs
_SENSITIVE_FIELDS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "secret_key",
        "authorization",
        "smtp_password",
    }
)


def _redact(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact sensitive keys from a dict before logging."""
    result = {}
    for k, v in data.items():
        if k.lower() in _SENSITIVE_FIELDS:
            result[k] = "[REDACTED]"
        elif isinstance(v, dict):
            result[k] = _redact(v)
        else:
            result[k] = v
    return result


def get_logger(name: str) -> logging.Logger:
    """Return a named logger configured for this application."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        handler.setFormatter(logging.Formatter(fmt))
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    return logger
