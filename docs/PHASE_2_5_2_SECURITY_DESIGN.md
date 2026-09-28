# CAMPUSCONNECT — PHASE 2.5.2 SECURITY HARDENING DESIGN

=============================================================================
CRITICAL NOTICE: BUSINESS FEATURE SCOPE IS STRICTLY FROZEN.
THIS PHASE IS TARGETED SECURITY HARDENING:
1. GAP-02: ACTIVE AUTHENTICATION RATE LIMITING
2. GAP-10: ROUTER & SERVICE AUTHORIZATION STANDARDIZATION
3. PRODUCTION SECURITY HEADERS (HSTS, CSP, PERMISSIONS-POLICY)
=============================================================================

## 1. Research Findings

### A. Authentication Rate Limiting
- **OWASP Authentication Cheat Sheet & ASVS 4.0.3 (V2.2.1, V2.2.2)**:
  - Authentication endpoints (especially `/api/v1/auth/login`) must be protected by rate limiting to defeat automated credential stuffing, brute-force password guessing, and CPU exhaustion attacks caused by compute-heavy password hashing algorithms (Argon2id).
  - Rate limiting must track requests primarily by source IP address and enforce thresholds over a defined sliding or fixed window (e.g. 10 requests per minute).
  - When the threshold is exceeded, the server MUST return HTTP 429 (Too Many Requests) along with a `Retry-After: <seconds>` header.
  - The response payload must be generic and uniform (e.g. `{"error": "rate_limited", "message": "Too many login attempts. Please try again later."}`) to prevent email/account enumeration.
- **NIST SP 800-63B Section 5.2.2**:
  - Rate limiting operates at the network/HTTP transport layer to prevent rapid automated guessing, while account lockout operates at the identity layer to protect specific accounts against targeted, distributed attacks. Both controls must operate concurrently without interfering with each other.

### B. Authorization Architecture
- **OWASP ASVS 4.0.3 (V4.1 Access Control)**:
  - Access control must be enforced server-side and authoritative.
  - Principle of Defense-in-Depth: Coarse-grained Role-Based Access Control (RBAC) should be evaluated declaratively at the router edge to reject unauthorized personas immediately before processing request bodies or database operations.
  - Fine-grained Resource Ownership & Statutory Constraints: Must be enforced in the domain service layer (e.g. checking whether a Club Secretary belongs to the specific host club, preventing submitter self-approval in workflows, and barring System Administrators from financial payouts).
- **FastAPI Dependency Patterns**:
  - Reusable dependencies (`require_role`, `require_any_role`, `require_permission`) inspect the cryptographically verified user identity from the database session and enforce role checks before executing endpoint handler logic.

### C. Security Headers
- **OWASP Secure Headers Project & MDN Web Security**:
  - **Strict-Transport-Security (HSTS)**: Instructs browsers to communicate exclusively over HTTPS (`max-age=31536000; includeSubDomains`).
    * *CRITICAL CAVEAT*: HSTS must ONLY be sent when the connection is secure (HTTPS or `X-Forwarded-Proto: https` in production/staging environments). Sending HSTS over local plaintext HTTP (`http://localhost`) can break local developer workflows.
  - **Content-Security-Policy (CSP)**: Mitigates Cross-Site Scripting (XSS) and data injection.
    * *Vite / React SPA Compatibility*: CampusConnect's frontend uses Vite with React and imports Google Fonts (`https://fonts.googleapis.com` and `https://fonts.gstatic.com`), as well as `blob:` URLs for client-side evidence image previews.
    * *Policy*: `default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`.
  - **Permissions-Policy**: Explicitly disables browser hardware capabilities not used by the application (`camera=(), microphone=(), geolocation=(), payment=(), usb=()`).
  - **X-Content-Type-Options**: `nosniff` (prevents MIME type sniffing).
  - **X-Frame-Options**: `DENY` (prevents clickjacking via iframes).
  - **Referrer-Policy**: `strict-origin-when-cross-origin` (protects sensitive path/query leakage).

---

## 2. Existing Security Controls in CampusConnect

1. **Password Security**:
   - Argon2id with 64 MB memory cost, 3 time iterations, 4 parallel lanes, 16-byte cryptographically secure random salt.
   - Constant-time dummy verification on nonexistent users to neutralize timing side-channels.
2. **Account Lockout**:
   - Tracks `user.failed_login_attempts`. When count reaches `settings.MAX_LOGIN_ATTEMPTS` (5), `user.locked_until` locks the account for 15 minutes.
3. **Session & Token Management**:
   - Short-lived JWT access tokens (15 minutes).
   - Opaque refresh tokens stored as SHA-256 hashes in PostgreSQL; transmitted strictly via `HttpOnly`, `SameSite=Lax`, secure cookies.
   - Single-use refresh token rotation; reuse detection revokes all user sessions.
4. **Existing Security Headers**:
   - `main.py` middleware injects `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and `X-XSS-Protection: 1; mode=block`.

---

## 3. Identified Gaps

1. **GAP-02**: `RATE_LIMIT_LOGIN_PER_MINUTE = 10` is defined in `backend/app/core/config.py` but is unreferenced anywhere in code. The `/api/v1/auth/login` endpoint has zero rate limiting, allowing rapid automated brute-force password guessing and Argon2id CPU exhaustion.
2. **GAP-10**: Authorization is inconsistent across API routers:
   - `closeout.py`, `settlement.py`, `events.py`, and `clubs.py` enforce declarative role/permission checks at the router edge.
   - `expenses.py` and `event_execution.py` used generic `get_current_user` dependencies, relying solely on service-layer checks.
3. **Security Headers**: Missing `Strict-Transport-Security` (conditional on HTTPS), `Content-Security-Policy`, and `Permissions-Policy`.

---

## 4. Rate-Limiting Design (GAP-02)

### Architecture
- **In-Memory Sliding-Window Limiter**:
  - Implemented in `backend/app/core/rate_limiter.py`.
  - A thread-safe, sliding-window request tracker keyed by client IP address.
  - Avoids external dependencies (no Redis required for single-node modular monolith).
  - Memory-safe: Automatically purges expired request timestamps so memory does not leak.
  - Test-friendly: Supports programmatically resetting IP state or configuring test limits without real-time sleep delays.
- **FastAPI Integration**:
  - Reusable dependency `check_login_rate_limit(request: Request)`.
  - Injected directly into `POST /api/v1/auth/login`.
- **Response Contract**:
  - Status code: `429 Too Many Requests`.
  - Headers: `Retry-After: <seconds>`.
  - Body: `{"error": "rate_limited", "message": "Too many login attempts. Please try again in X seconds."}`.
- **Synergy with Account Lockout**:
  - Rate limiting throttles the network layer (max 10 requests / min per IP).
  - Account lockout locks the database user identity after 5 consecutive failed passwords.

---

## 5. Authorization Standardization Strategy (GAP-10)

### 2-Tier Defense-in-Depth Model
1. **Tier 1 — Router Edge (Coarse-Grained RBAC)**:
   - Declarative FastAPI dependencies (`require_role`, `require_any_role`, `require_permission`).
   - Rejects unauthenticated callers (`401 Unauthorized`) and wrong personas (`403 Forbidden`) before invoking database or business transactions.
2. **Tier 2 — Domain Service Layer (Fine-Grained Ownership & Statutory Rules)**:
   - Resource ownership: Verifies that a `CLUB_SECRETARY` belongs to the specific club hosting the event.
   - Anti-self-approval: Submitter cannot approve their own proposal.
   - Statutory bounds: `SYSTEM_ADMIN` is strictly forbidden from approving financial settlements or advances.
   - State machine guards: Events must be in proper status (`DRAFT`, `SCHEDULED`, `COMPLETED`, etc.).

### Router Adjustments
- **`expenses.py`**:
  - Secretary endpoints (`upload-bill`, `create`, `update`, `delete`, `submit`): Standardize to `require_role(UserRole.CLUB_SECRETARY)`.
  - Finance Officer endpoints (`verify`, `partial-verify`, `query`, `disallow`): Standardize to `require_role(UserRole.FINANCE_OFFICER)`.
- **`event_execution.py`**:
  - Secretary execution (`start`, `complete`, `post-event-report` edit/resubmit, `evidence` upload): Standardize to `require_role(UserRole.CLUB_SECRETARY)`.
  - Faculty Advisor certification (`post-event-report/certify`, `post-event-report/revise`): Standardize to `require_role(UserRole.FACULTY_ADVISOR)`.
  - Admin emergency start: Remains `require_role(UserRole.SYSTEM_ADMIN)`.
- **`resources.py`**:
  - Declare `require_permission(Permission.EVENT_EDIT_DRAFT)` on mutation routes (`create_resource_request`, `delete_resource_request`).

---

## 6. Security-Header Strategy

Update `add_security_headers` middleware in `backend/app/main.py`:
1. **HSTS**:
   - Injected if request is HTTPS (`request.url.scheme == "https"` or `request.headers.get("x-forwarded-proto") == "https"`) OR if `settings.ENV == "production"`.
   - Value: `max-age=31536000; includeSubDomains`.
2. **CSP**:
   - `default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`.
3. **Permissions-Policy**:
   - `camera=(), microphone=(), geolocation=(), payment=(), usb=()`.
4. **Preserve Existing**:
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY`
   - `Referrer-Policy: strict-origin-when-cross-origin`

---

## 7. Development vs. Production Behavior

- **HSTS**: Suppressed on local plaintext HTTP (`http://127.0.0.1`, `http://localhost`) during development to prevent local browser SSL redirection loops. Active when served over TLS or in production mode.
- **Rate Limiting**: Configured to 10 req/min by default. In tests, the rate limiter can be programmatically tested or reset using helper methods.

---

## 8. Test Strategy

1. **Rate Limiting Tests** (`backend/tests/api/test_rate_limiting.py`):
   - Allowed login attempts within limit succeed or fail with 401.
   - Limit exceeded triggers HTTP 429 with `Retry-After` header.
   - Response body does not leak credentials or account existence.
   - Legitimate login succeeds after rate limit window reset.
   - Inactive account / lockout behaves correctly in conjunction with rate limiting.
2. **Authorization Hardening Tests** (`backend/tests/api/test_authorization_hardening.py`):
   - Unauthorized roles calling newly guarded routes get HTTP 403.
   - Unauthenticated requests get HTTP 401.
   - Cross-club IDOR checks remain enforced by service layer.
   - System Admin financial restrictions remain intact.
3. **Security Headers Tests** (`backend/tests/api/test_security_headers.py`):
   - Verifies presence of `Content-Security-Policy`, `Permissions-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`.
   - Verifies HSTS injection when HTTPS / production simulated.

---

## 9. Rollback Considerations

- Zero database schema changes (no Alembic migrations required).
- Pure application code and middleware enhancement.
- Can be rolled back via git restore without database downtime or data loss.
