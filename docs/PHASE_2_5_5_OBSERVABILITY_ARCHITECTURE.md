# CampusConnect — Phase 2.5.5 Observability Architecture & Implementation

## 1. Overview & Purpose
Phase 2.5.5 implements a minimal, zero-external-dependency, production-grade observability architecture for CampusConnect. It equips the backend and frontend with request-tracing, structured logging, safe exception handling, and health/readiness/liveness probes without introducing unnecessary third-party services or infrastructure complexity.

---

## 2. Architectural Components

### A. Request Correlation & Context Propagation (`X-Request-ID`)
- **Safety & Sanitization**: Incoming `X-Request-ID` headers are validated against a strict regex (`^[a-zA-Z0-9_\-]{1,64}$`). Any invalid, malformed, or excessively long headers are safely replaced with a newly generated UUIDv4.
- **Async Isolation**: Utilizes Python's standard `contextvars.ContextVar` (`request_id_ctx`) to propagate correlation IDs across coroutines, tasks, and log records seamlessly.
- **Propagation**:
  - Attached to `request.state.request_id`
  - Injected into response header `X-Request-ID`
  - Injected into log records automatically via `logging.Filter` / `StandardTextFormatter` / `StructuredLogFormatter`
  - Returned in unexpected 500 error bodies for incident triage.

### B. Structured Production Logging & Redaction
- **Formatters**:
  - `StructuredLogFormatter`: Active in production or when `LOG_FORMAT="json"`. Formats logs as single-line JSON objects containing `timestamp` (ISO8601 UTC), `level`, `logger`, `message`, `request_id`, and redacted `extra` attributes.
  - `StandardTextFormatter`: Active in development and testing (`%(asctime)s | %(levelname)-8s | [%(request_id)s] %(name)s | %(message)s`).
- **Data Protection & Zero-Leakage Guarantee**:
  - Recursive key redaction (`_redact`) sanitizes sensitive keys before emitting logs.
  - Sensitive keys include: `password`, `password_hash`, `token`, `access_token`, `refresh_token`, `secret`, `secret_key`, `authorization`, `smtp_password`, `cookie`, `set-cookie`, `credit_card`, `cvv`.
  - HTTP access log captures `method`, `path`, `status_code`, `duration_ms`, and `client_ip` without request/response payload leakage.

### C. Exception Handling & Security
- **Error Contract Preservation**: Domain exceptions continue to map to standard status codes (401, 403, 404, 409, 422, 429).
- **Internal 500 Protection**: Unhandled exceptions and `CampusConnectError` log with full exception stack traces internally with `[request_id=<id>]`, but return sanitized responses:
  ```json
  {
    "error": "internal_error",
    "message": "An unexpected error occurred.",
    "request_id": "5386371b-0867-4084-9a90-c5262a832b00"
  }
  ```
  No stack traces, PostgreSQL connection strings, database usernames, or query details are ever exposed to API consumers.

### D. Health, Readiness & Liveness Probes
- **`/api/v1/health`** (Composite Health): Pings PostgreSQL (`SELECT 1`). Returns 200 OK or 503 Service Unavailable without exposing DB connection parameters. Maintained for Docker Compose health check compatibility.
- **`/api/v1/health/ready`** (Readiness Probe): Verifies database readiness before routing traffic. Returns 200 if ready, 503 if not ready.
- **`/api/v1/health/live`** (Liveness Probe): Verifies the FastAPI event loop is responsive. Returns 200 independently of external dependencies to avoid cascading container restarts during transient network drops.

### E. Frontend Observability
- In `frontend/src/lib/apiClient.ts`, Axios response interceptors extract `X-Request-ID` or `data.request_id` from error responses and attach it to the caught error (`(error as any).requestId`).
- Enables frontend users and administrators to report specific request IDs for production debugging.

---

## 3. Verification & Test Coverage
The observability suite in `backend/tests/api/test_observability.py` covers:
1. `TestRequestIdMechanics`:
   - Validates regex sanitization of safe IDs (`valid-request-id-123_abc`).
   - Rejection and safe UUID replacement for malicious injection attempts (`\r\n`, `<script>`, SQL injection strings).
   - Header propagation on requests and responses.
   - Timing header `X-Process-Time-Ms` accuracy.
2. `TestStructuredLoggingAndRedaction`:
   - Verifies recursive redaction across top-level and nested dictionaries and lists.
   - Verifies `StructuredLogFormatter` produces parseable single-line JSON with all required fields.
3. `TestUnhandledExceptionSafety`:
   - Simulates unhandled exception in an endpoint.
   - Verifies HTTP 500 status code, presence of `request_id`, and zero leakage of connection strings or tracebacks.
4. `TestHealthAndProbes`:
   - Verifies `GET /api/v1/health/live` returns 200 alive.
   - Verifies `GET /api/v1/health/ready` returns 200 when database is healthy.
   - Verifies `GET /api/v1/health/ready` returns 503 when database is unreachable without exposing secrets.

**Regression Status**:
- Backend suite: 576/576 passed
- Frontend suite: 87/87 passed
- Playwright E2E suite: 17/17 passed
