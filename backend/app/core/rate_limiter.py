"""
CampusConnect Backend - In-Memory Sliding-Window Rate Limiter
Provides rate-limiting for high-risk endpoints (e.g. login brute-force mitigation).
Enforces:
- Sliding-window tracking per client key/IP
- Thread-safe timestamp purging and recording
- HTTP 429 RateLimitExceededError with Retry-After header
- Clean reset interface for test isolation
"""
import time
from collections import defaultdict
from threading import Lock

from fastapi import Request

from app.core.config import get_settings
from app.core.exceptions import RateLimitExceededError


class InMemoryRateLimiter:
    """
    Thread-safe in-memory sliding-window rate limiter.
    Stores timestamps of requests per client key.
    Automatically purges expired records to prevent memory leaks.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._records: dict[str, list[float]] = defaultdict(list)

    def check_rate_limit(
        self, key: str, max_requests: int, window_seconds: int
    ) -> tuple[bool, int]:
        """
        Check whether an action is allowed for the given key.

        Returns:
            (is_allowed: bool, retry_after_seconds: int)
        """
        now = time.time()
        window_start = now - window_seconds

        with self._lock:
            # Filter out timestamps older than the sliding window
            timestamps = [t for t in self._records[key] if t > window_start]
            self._records[key] = timestamps

            if len(timestamps) >= max_requests:
                # Calculate retry-after based on oldest timestamp in window
                oldest = timestamps[0]
                retry_after = max(1, int(oldest + window_seconds - now))
                return False, retry_after

            self._records[key].append(now)
            return True, 0

    def reset(self, key: str | None = None) -> None:
        """Reset records for a specific key or all keys (useful for test isolation)."""
        with self._lock:
            if key is not None:
                self._records.pop(key, None)
            else:
                self._records.clear()


# Global singleton instance for login rate limiting
login_limiter = InMemoryRateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP address, respecting X-Forwarded-For if behind a reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def check_login_rate_limit(request: Request) -> None:
    """
    FastAPI dependency that enforces rate limiting on the login endpoint.
    Keyed by client IP address using configured RATE_LIMIT_LOGIN_PER_MINUTE.
    """
    settings = get_settings()
    ip = get_client_ip(request)
    limit = settings.RATE_LIMIT_LOGIN_PER_MINUTE
    window = 60

    allowed, retry_after = login_limiter.check_rate_limit(
        key=f"login:{ip}",
        max_requests=limit,
        window_seconds=window,
    )
    if not allowed:
        raise RateLimitExceededError(
            message=f"Too many login attempts. Please try again in {retry_after} seconds.",
            retry_after=retry_after,
        )
