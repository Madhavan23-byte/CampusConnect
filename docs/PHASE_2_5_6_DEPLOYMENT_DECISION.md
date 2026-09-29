# CampusConnect — Production Deployment Architecture & Verification Decision

## 1. Overview
This document specifies the production deployment architecture chosen for CampusConnect, the technical evaluation behind the decision, the security hardening implemented, and the real-world verification performed.

---

## 2. Architecture Comparison & Evaluation

| Evaluation Criteria | Option A: Multi-Container Docker + Nginx Gateway (Chosen) | Option B: Cloud PaaS (Cloud Run / ECS + S3 + Cloud SQL) | Option C: Static Host (Vercel) + Remote API |
| :--- | :--- | :--- | :--- |
| **Data Sovereignty & Cost** | **Zero vendor lock-in**, fixed predictable host cost. Suitable for colleges. | High variable cloud cost, egress fees, managed DB minimum charges. | Fragmented vendor bills, cross-origin domain boundaries. |
| **HttpOnly Cookie Handling** | **Same-origin routing** (`/` and `/api/`). Zero third-party cookie blocking. | Separate subdomains require complex cookie domains / SameSite=None. | Requires public CORS exposure, third-party cookie vulnerability. |
| **PostgreSQL & Alembic** | Direct PostgreSQL 16 container or native server with full migration automation. | Cloud SQL requires IAM proxy or VPC connectors. | Requires external managed database service. |
| **Storage & Documents** | Persistent named volume `/app/uploads` matching `StorageService` design. | Requires complete rewrite of `DocumentService` to AWS S3 / GCS. | Local uploads not persistent across serverless invocations. |
| **Simplicity & Maintainability**| Self-contained `docker-compose.prod.yml`, single-command bringup. | Complex cloud IAM, secret managers, VPC peering. | Multi-dashboard operations. |

### Decision
**Option A: Production Multi-Container Docker Stack with Nginx Gateway (and Native Local HTTPS Runtime)** was selected as the optimal architecture for CampusConnect.
- **Why**: Eliminates CORS friction by unifying frontend and backend under a single reverse-proxy origin. Preserves HttpOnly, Secure, SameSite=Lax refresh cookies. Keeps document uploads on high-performance persistent volumes without requiring external cloud object store dependencies.

---

## 3. Production Hardening Implementation

1. **Reverse Proxy & TLS Termination**:
   - Configuration: `infrastructure/nginx/nginx.conf`
   - TLS v1.2 / TLS v1.3 only, modern high-security cipher suites.
   - HSTS header: `Strict-Transport-Security: max-age=31536000; includeSubDomains`.
   - Security headers: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`.
   - Nginx rate-limiting zone: `10 req/min` burst `5` on `/api/v1/auth/login` to prevent brute-force attacks.
   - Request ID propagation: Injects `$request_id` into `X-Request-ID` proxy header.

2. **Frontend Production Build**:
   - Multi-stage `frontend/Dockerfile` (`node:20-alpine` build -> `nginx:1.27-alpine` runtime).
   - Zero Vite development server in production. Static assets served with `Cache-Control: public, immutable` (1 year).
   - SPA fallback: `try_files $uri $uri/ /index.html` preserves client-side routing.

3. **Backend Production Configuration**:
   - Runs as non-root user `appuser` (UID 1001).
   - Structured JSON logging (`LOG_FORMAT=json`) with contextvar request correlation and automatic secret redaction.
   - Healthcheck: Native Python probe checking `/api/v1/health` with 503 fallback on DB outage.
   - Database connection pooling: `pool_size=20`, `max_overflow=10`.

4. **Environment & Secrets**:
   - Template provided in `.env.production.example`.
   - No hardcoded secrets. `JWT_SECRET_KEY` and `REFRESH_TOKEN_SECRET` must be 32-byte cryptographic random hex keys.
   - `COOKIE_SECURE=true` enforced in production mode.

---

## 4. Real-World Production Verification

The production runtime was started over HTTPS (`https://127.0.0.1:8443`) and verified via `backend/scripts/verify_production_smoke.py`:
- [x] **Frontend Delivery**: Production SPA root delivered (`HTTP 200`, 473 bytes, verified title and asset bundles).
- [x] **Security Headers**: HSTS, X-Frame-Options, X-Content-Type-Options verified.
- [x] **Health Check**: `/api/v1/health` returns `200 OK` (PostgreSQL `status: ok`).
- [x] **Readiness Probe**: `/api/v1/health/ready` returns `200 OK` (`status: ready`).
- [x] **Liveness Probe**: `/api/v1/health/live` returns `200 OK` (`status: alive`).
- [x] **Authentication**: `e2e.admin@college.edu` authenticated; issued JWT access token.
- [x] **Secure HttpOnly Cookie**: `campusconnect_refresh` verified with `Secure=True`, `HttpOnly=True`, `SameSite=Lax`, `Path=/api/v1/auth`.
- [x] **Authenticated API Access**: `/api/v1/auth/me` retrieved user profile and role (`SYSTEM_ADMIN`).
- [x] **Session Renewal**: `/api/v1/auth/refresh` exchanged cookie for rotated token.
- [x] **Logout**: `/api/v1/auth/logout` invalidated session and cleared refresh cookie.
- [x] **Structured Logging**: All production requests logged in machine-readable JSON format.

**Status**: **VERIFIED**
