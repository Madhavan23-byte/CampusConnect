"""
CampusConnect Backend — Security and Cryptography Utilities

Provides:
- Password hashing and verification using Argon2id
- JWT access token generation and decoding (HMAC-SHA256)
- Secure token generation (for email verification and password reset)
- Token hashing for storage (SHA-256)
- Modular primitives for refresh token rotation

Security principles:
- Argon2id with OWASP-recommended parameters
- Timing-attack safe comparisons where applicable
- JWT claims include exp, iat, jti, sub, role, email, and token_type
- Never store raw tokens (refresh, verification, reset) in plaintext
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.exceptions import InvalidTokenError, TokenExpiredError

# ---------------------------------------------------------------------------
# Argon2id Password Hashing
# ---------------------------------------------------------------------------


def get_password_hasher() -> PasswordHasher:
    """Return configured Argon2id PasswordHasher instance."""
    settings = get_settings()
    return PasswordHasher(
        time_cost=settings.ARGON2_TIME_COST,
        memory_cost=settings.ARGON2_MEMORY_COST,
        parallelism=settings.ARGON2_PARALLELISM,
    )


def hash_password(password: str) -> str:
    """
    Hash a plaintext password using Argon2id.
    Raises ValueError if password is empty.
    """
    if not password:
        raise ValueError("Password cannot be empty")
    hasher = get_password_hasher()
    return hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against an Argon2id hash.
    Returns True if valid, False otherwise.
    Catches verification exceptions to safely return False on invalid/mismatched hashes.
    """
    if not plain_password or not hashed_password:
        return False
    hasher = get_password_hasher()
    try:
        return hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(hashed_password: str) -> bool:
    """Check if the password hash was generated with older Argon2 parameters."""
    if not hashed_password:
        return True
    hasher = get_password_hasher()
    try:
        return hasher.check_needs_rehash(hashed_password)
    except Exception:
        return True


# ---------------------------------------------------------------------------
# JWT Access Token Handling
# ---------------------------------------------------------------------------


def create_access_token(
    subject: str | uuid.UUID,
    role: str,
    email: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    Generate a signed JWT access token.

    Standard Claims:
    - sub: User ID (as string UUID)
    - role: User role string
    - email: User email
    - token_type: "access"
    - jti: Unique token ID (UUID4) for auditing/revocation
    - iat: Issued-at UTC timestamp
    - exp: Expiration UTC timestamp
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": str(role),
        "email": str(email),
        "token_type": "access",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }

    if extra_claims:
        reserved_keys = {"sub", "role", "email", "token_type", "jti", "iat", "exp"}
        for k, v in extra_claims.items():
            if k not in reserved_keys:
                payload[k] = v

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT access token.

    Validates:
    - Cryptographic signature
    - Token expiration
    - token_type == 'access'
    - Presence of 'sub' claim

    Raises:
    - TokenExpiredError: if token has expired
    - InvalidTokenError: if token is malformed, invalid, or wrong type
    """
    if not token or not isinstance(token, str):
        raise InvalidTokenError("Invalid token: token must be a non-empty string")

    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenExpiredError("Access token has expired", detail={"error": str(e)}) from e
    except JWTError as e:
        raise InvalidTokenError("Invalid token or signature", detail={"error": str(e)}) from e

    token_type = payload.get("token_type")
    if token_type != "access":
        raise InvalidTokenError(f"Invalid token type: expected 'access', got '{token_type}'")

    if not payload.get("sub"):
        raise InvalidTokenError("Token missing subject (sub) claim")

    return payload


# ---------------------------------------------------------------------------
# Cryptographic Token Helpers (For Refresh, Email Verification, Reset)
# ---------------------------------------------------------------------------


def generate_secure_random_token(nbytes: int = 32) -> str:
    """Generate a cryptographically secure URL-safe random string."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """
    Compute SHA-256 hash of a token for secure database storage.
    Raw tokens are sent to clients and never stored in plaintext in the database.
    """
    if not token:
        raise ValueError("Token cannot be empty")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
