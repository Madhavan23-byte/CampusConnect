"""
Unit Tests for CampusConnect Security Utilities & Schemas

Verifies:
1. Password hashing with Argon2id (different salts, valid verification)
2. Password verification with correct credentials
3. Password rejection with incorrect credentials
4. Password rejection with empty or malformed hashes
5. JWT access token creation with proper claims (sub, role, email, exp, iat, jti, token_type)
6. JWT decoding and signature verification
7. JWT rejection on expiration (TokenExpiredError)
8. JWT rejection on invalid signature or tampering (InvalidTokenError)
9. JWT rejection on wrong token_type (InvalidTokenError)
10. Secure random token generation and SHA-256 token hashing
11. UserRegisterRequest validation (password complexity, email normalization, name sanitization)
12. UserLoginRequest validation
"""
import uuid
from datetime import timedelta
import pytest
from pydantic import ValidationError

from app.core.exceptions import InvalidTokenError, TokenExpiredError
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_secure_random_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from app.models.enums import UserRole
from app.schemas.auth import (
    TokenPayload,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    validate_password_strength,
)


# ===========================================================================
# Password Hashing & Verification Tests
# ===========================================================================


class TestPasswordSecurity:
    """Test Argon2id password hashing and verification."""

    def test_hash_password_produces_argon2id_format(self):
        password = "SecurePassword123!@#"
        hashed = hash_password(password)
        assert hashed.startswith("$argon2id$")
        assert len(hashed) > 50

    def test_hash_password_generates_unique_salts(self):
        password = "IdenticalPassword123!"
        h1 = hash_password(password)
        h2 = hash_password(password)
        assert h1 != h2, "Each Argon2id hash must contain a unique cryptographic salt"

    def test_verify_password_success(self):
        password = "CorrectHorseBatteryStaple!9"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_failure_incorrect_password(self):
        password = "CorrectPassword!1"
        hashed = hash_password(password)
        assert verify_password("WrongPassword!1", hashed) is False

    def test_verify_password_empty_inputs(self):
        hashed = hash_password("ValidPassword!1")
        assert verify_password("", hashed) is False
        assert verify_password("ValidPassword!1", "") is False
        assert verify_password("", "") is False

    def test_verify_password_malformed_hash(self):
        assert verify_password("Password!1", "not-a-valid-argon2-hash") is False
        assert verify_password("Password!1", "$argon2id$v=19$bad_hash") is False

    def test_hash_password_rejects_empty_string(self):
        with pytest.raises(ValueError, match="Password cannot be empty"):
            hash_password("")

    def test_password_needs_rehash(self):
        hashed = hash_password("Password123!@#")
        # Fresh hash with current settings should not need rehash
        assert password_needs_rehash(hashed) is False
        assert password_needs_rehash("") is True


# ===========================================================================
# JWT Access Token Tests
# ===========================================================================


class TestJWTSecurity:
    """Test JWT access token creation, decoding, and validation."""

    def test_create_and_decode_access_token(self):
        user_id = uuid.uuid4()
        role = UserRole.CLUB_SECRETARY.value
        email = "secretary@college.edu"

        token = create_access_token(
            subject=user_id,
            role=role,
            email=email,
        )
        assert isinstance(token, str)
        assert len(token) > 20

        payload = decode_access_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["role"] == role
        assert payload["email"] == email
        assert payload["token_type"] == "access"
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload
        assert payload["exp"] > payload["iat"]

    def test_token_expiration_rejection(self):
        user_id = uuid.uuid4()
        # Create token that expired 5 minutes ago
        expired_token = create_access_token(
            subject=user_id,
            role=UserRole.FACULTY_ADVISOR.value,
            email="advisor@college.edu",
            expires_delta=timedelta(minutes=-5),
        )
        with pytest.raises(TokenExpiredError) as exc_info:
            decode_access_token(expired_token)
        assert "expired" in str(exc_info.value).lower()

    def test_token_tampering_rejection(self):
        user_id = uuid.uuid4()
        token = create_access_token(
            subject=user_id,
            role=UserRole.PRINCIPAL.value,
            email="principal@college.edu",
        )
        # Tamper with the token string
        tampered_token = token[:-5] + "XXXXX"
        with pytest.raises(InvalidTokenError):
            decode_access_token(tampered_token)

    def test_token_invalid_string_rejection(self):
        with pytest.raises(InvalidTokenError):
            decode_access_token("completely.invalid.token")
        with pytest.raises(InvalidTokenError):
            decode_access_token("")

    def test_token_wrong_type_rejection(self):
        from jose import jwt
        from app.core.config import get_settings
        settings = get_settings()

        # Forge token with token_type="refresh" instead of "access"
        bad_payload = {
            "sub": str(uuid.uuid4()),
            "role": "SYSTEM_ADMIN",
            "email": "admin@college.edu",
            "token_type": "refresh",
            "jti": str(uuid.uuid4()),
            "exp": 9999999999,
        }
        forged_token = jwt.encode(bad_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

        with pytest.raises(InvalidTokenError, match="Invalid token type"):
            decode_access_token(forged_token)

    def test_token_missing_sub_rejection(self):
        from jose import jwt
        from app.core.config import get_settings
        settings = get_settings()

        bad_payload = {
            "role": "SYSTEM_ADMIN",
            "email": "admin@college.edu",
            "token_type": "access",
            "jti": str(uuid.uuid4()),
            "exp": 9999999999,
        }
        forged_token = jwt.encode(bad_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

        with pytest.raises(InvalidTokenError, match="missing subject"):
            decode_access_token(forged_token)


# ===========================================================================
# Cryptographic Token Helper Tests
# ===========================================================================


class TestTokenHelpers:
    """Test secure random token generation and token hashing."""

    def test_generate_secure_random_token(self):
        t1 = generate_secure_random_token()
        t2 = generate_secure_random_token()
        assert t1 != t2
        assert len(t1) >= 40

    def test_hash_token_deterministic(self):
        token = "my_secure_random_token_string"
        h1 = hash_token(token)
        h2 = hash_token(token)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex string

    def test_hash_token_different_inputs(self):
        assert hash_token("token_a") != hash_token("token_b")

    def test_hash_token_empty_rejects(self):
        with pytest.raises(ValueError, match="Token cannot be empty"):
            hash_token("")


# ===========================================================================
# Auth Schema Validation Tests
# ===========================================================================


class TestAuthSchemas:
    """Test Pydantic schemas for registration, login, and tokens."""

    def test_user_register_valid(self):
        req = UserRegisterRequest(
            email="student@college.edu",
            password="StrongPassword123!",
            full_name="John Doe",
            role=UserRole.CLUB_SECRETARY,
            department="Computer Science",
        )
        assert req.email == "student@college.edu"
        assert req.full_name == "John Doe"
        assert req.role == UserRole.CLUB_SECRETARY

    def test_user_register_normalizes_email(self):
        req = UserRegisterRequest(
            email="  STUDENT@COLLEGE.EDU  ",
            password="StrongPassword123!",
            full_name="John Doe",
            role=UserRole.CLUB_SECRETARY,
        )
        assert req.email == "student@college.edu"

    def test_user_register_sanitizes_full_name(self):
        req = UserRegisterRequest(
            email="student@college.edu",
            password="StrongPassword123!",
            full_name="   Jane    Alice   Smith   ",
            role=UserRole.CLUB_SECRETARY,
        )
        assert req.full_name == "Jane Alice Smith"

    def test_password_policy_rejection_no_uppercase(self):
        with pytest.raises(ValidationError, match="uppercase"):
            UserRegisterRequest(
                email="user@college.edu",
                password="password123!",
                full_name="User Name",
                role=UserRole.CLUB_SECRETARY,
            )

    def test_password_policy_rejection_no_lowercase(self):
        with pytest.raises(ValidationError, match="lowercase"):
            UserRegisterRequest(
                email="user@college.edu",
                password="PASSWORD123!",
                full_name="User Name",
                role=UserRole.CLUB_SECRETARY,
            )

    def test_password_policy_rejection_no_digit(self):
        with pytest.raises(ValidationError, match="digit"):
            UserRegisterRequest(
                email="user@college.edu",
                password="PasswordSecret!",
                full_name="User Name",
                role=UserRole.CLUB_SECRETARY,
            )

    def test_password_policy_rejection_no_special_char(self):
        with pytest.raises(ValidationError, match="special character"):
            UserRegisterRequest(
                email="user@college.edu",
                password="Password12345",
                full_name="User Name",
                role=UserRole.CLUB_SECRETARY,
            )

    def test_password_policy_rejection_too_short(self):
        with pytest.raises(ValidationError, match="at least 8 characters"):
            UserRegisterRequest(
                email="user@college.edu",
                password="P1!a",
                full_name="User Name",
                role=UserRole.CLUB_SECRETARY,
            )

    def test_user_login_valid(self):
        login = UserLoginRequest(
            email="User@College.EDU ",
            password="AnyPassword123!",
        )
        assert login.email == "user@college.edu"
        assert login.password == "AnyPassword123!"

    def test_user_login_invalid_email(self):
        with pytest.raises(ValidationError):
            UserLoginRequest(
                email="not-an-email",
                password="password",
            )

    def test_token_response_schema(self):
        res = TokenResponse(
            access_token="fake.jwt.token",
            token_type="bearer",
            expires_in=900,
            refresh_token="opaque_refresh_token_123",
        )
        assert res.access_token == "fake.jwt.token"
        assert res.token_type == "bearer"
        assert res.expires_in == 900
        assert res.refresh_token == "opaque_refresh_token_123"
