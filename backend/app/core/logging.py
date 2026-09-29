"""
CampusConnect Backend — Structured Production Logging & Observability
Features:
- Thread-safe & async ContextVar request ID propagation
- Sanitization & validation of incoming X-Request-ID headers
- Structured JSON logging in production / machine-readable environments
- Human-friendly formatted logging in development & test
- Recursive redaction of sensitive credentials, tokens, cookies, and secrets
"""

import json
import logging
import re
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings

settings = get_settings()

# ContextVar for async request-id propagation across coroutines
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# Safe regex pattern for incoming X-Request-ID header (alphanumeric, dash, underscore, 1-64 chars)
_SAFE_REQUEST_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def is_safe_request_id(rid: str | None) -> bool:
    """Validate client-supplied request ID against strict safety pattern."""
    if not rid or not isinstance(rid, str):
        return False
    return bool(_SAFE_REQUEST_ID_REGEX.match(rid.strip()))


def get_request_id() -> str | None:
    """Retrieve current request ID from async context."""
    return request_id_ctx.get()


def set_request_id(request_id: str) -> Token:
    """Bind a request ID to the current async context."""
    return request_id_ctx.set(request_id)


def reset_request_id(token: Token) -> None:
    """Reset the request ID ContextVar using the token returned by set_request_id."""
    request_id_ctx.reset(token)


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
        "cookie",
        "set-cookie",
        "credit_card",
        "cvv",
    }
)


def _redact(data: Any) -> Any:
    """Recursively redact sensitive keys from a dict/list/string before logging."""
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if str(k).lower() in _SENSITIVE_FIELDS:
                result[k] = "[REDACTED]"
            else:
                result[k] = _redact(v)
        return result
    if isinstance(data, (list, tuple)):
        return [_redact(item) for item in data]
    return data


class StructuredLogFormatter(logging.Formatter):
    """
    Production-ready JSON log formatter.
    Outputs single-line JSON with standard fields:
    timestamp (ISO8601 UTC), level, logger, message, request_id, and any extra attributes.
    """

    _RESERVED_ATTRS = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        req_id = get_request_id() or getattr(record, "request_id", None) or None

        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": req_id,
        }

        extras: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in self._RESERVED_ATTRS and key != "request_id":
                extras[key] = value

        if extras:
            log_entry["extra"] = _redact(extras)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class StandardTextFormatter(logging.Formatter):
    """Development/test text formatter with request_id tag."""

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id") or not record.request_id:
            record.request_id = get_request_id() or "-"
        return super().format(record)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger configured for the current application environment."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        use_json = (
            getattr(settings, "LOG_FORMAT", "auto") == "json"
            or (getattr(settings, "LOG_FORMAT", "auto") == "auto" and settings.ENV == "production")
        )
        if use_json:
            handler.setFormatter(StructuredLogFormatter())
        else:
            fmt = "%(asctime)s | %(levelname)-8s | [%(request_id)s] %(name)s | %(message)s"
            handler.setFormatter(StandardTextFormatter(fmt))
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    return logger
