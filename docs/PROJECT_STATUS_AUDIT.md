# CAMPUSCONNECT — COMPLETE PROJECT STATUS AUDIT

> **Audit Date**: September 24, 2026
> **Status**: Comprehensive, Read-Only, Code-Grounded Project Audit
> **Target Branch**: `phase2-event-lifecycle`
> **Current Commit**: `518f5e3` (`feat(phase2): harden financial settlement and reopening`)
> **Repository Baseline**: `b05eddd` -> `518f5e3` (origin synchronized)
> **Master Reference**: `12b2002` (`feat(day6): notification service, confirmed events, secure docs, dashboard, and complete frontend UI`)

---

## 1. Executive Summary

CampusConnect is a collegiate event governance, approval workflow, and financial settlement platform engineered for multi-role college environments.

This audit provides an authoritative, code-grounded evaluation of the current state of CampusConnect as of September 24, 2026. Every statement, metric, table count, and status in this document is derived strictly from real repository files, database constraints, test execution results, and git history.

### Key High-Level Findings:
1. **Core Lifecycle Progress**: Phases 1, 2.1, and 2.2 are complete full-stack (Database, Domain Models, Service Layer, REST API Endpoints, Frontend UI, and Automated Tests).
2. **Phase 2.3 (Financial Settlement) Status**:
   - **Database & Migration**: COMPLETE (`0004_phase2_3_settlement`, 5 new tables, restrictive foreign keys, monetary check constraints).
   - **Domain Models**: COMPLETE (`CashAdvance`, `ActualIncome`, `FinancialSettlement`, `SettlementPayment`, `SettlementRevision`).
   - **Backend Service Layer**: COMPLETE & HARDENED (`SettlementService` with deterministic SHA-256 source fingerprinting, cumulative reconciliation across revisions, downward recovery branching, and pessimistic row locking).
   - **REST API Layer**: **NOT IMPLEMENTED** (No Pydantic schemas in `backend/app/schemas/financial_settlement.py`, no endpoints in `backend/app/api/v1/endpoints/settlement.py`).
   - **Frontend UI Layer**: **NOT IMPLEMENTED** (No `SettlementTab.tsx` or advance/income UI).
3. **Automated Verification**:
   - Backend Test Suite: **371 / 371 passed** (100% passing across 21 test files).
   - Frontend Test Suite: **17 / 17 passed** (Vitest across 6 component suites).
   - Frontend Production Build: **Passed** (`tsc -b && vite build` transforms 2,005 modules cleanly).
   - Backend Linting: **Clean** on all Phase 2.3 files.
   - Database Migrations: **Clean** at head `0004_phase2_3_settlement`.
4. **First Major Incomplete Lifecycle Stage**: **Phase 2.3 REST API and Frontend UI** (Connecting the hardened `SettlementService` to HTTP clients and the React interface).

---

## 2. Repository Baseline & Git Status

Inspection of git metadata via `git status`, `git branch -a`, `git remote -v`, and `git log`:

- **Active Branch**: `phase2-event-lifecycle`
- **Current Local Commit**: `518f5e3`
- **Remote Origin**: `https://github.com/Madhavan23-byte/CampusConnect.git`
- **Remote Head Tracking**: `origin/phase2-event-lifecycle` is synchronized with local `518f5e3` (0 commits ahead, 0 commits behind).
- **Working Tree State**: **Clean** (`git status --short` returns zero modified or untracked files).
- **Master Branch Status**: Untouched at `12b2002` (`origin/master` synchronized). Branch `phase2-event-lifecycle` is 4 commits ahead of `master`:
  - `a3dd03e`: Phase 2.1 Event completion and post-event certification.
  - `1117541`: Phase 2.2 Actual expense ledger and finance verification.
  - `b05eddd`: Phase 2.3 Domain models and cascade hardening.
  - `518f5e3`: Phase 2.3 Financial settlement and reopening hardening.

---

## 3. High-Level Architecture

CampusConnect is structured as a decoupled multi-tier web application:

1. **Client Tier (`frontend/`)**: Single Page Application built with React 18, TypeScript, Vite, TailwindCSS, React Query, React Router v7, and Zustand.
2. **Gateway / Reverse Proxy Tier (`infrastructure/nginx/`)**: Nginx reverse proxy routing `/api/` traffic to the backend ASGI server and root traffic to frontend static assets.
3. **Application Tier (`backend/app/`)**: FastAPI application running on Python 3.12+ (Uvicorn ASGI), enforcing layered architecture:
   - `api/`: REST routing, dependency injection (`deps.py`), and RBAC parameter extraction.
   - `schemas/`: Pydantic input validation, output serialization, and schema contracts.
   - `services/`: Business logic, domain rules, state machine transitions, and database transactions.
   - `models/`: SQLAlchemy 2.0 ORM domain entities, check constraints, and enum types.
   - `core/`: Configuration (`config.py`), database engines (`database.py`), and cryptography/JWT (`security.py`).
4. **Data Tier (PostgreSQL 16)**: Relational database with PostGIS, `btree_gist`, and `pgcrypto` extensions enforcing physical exclusion constraints, foreign key restrictions, and monetary check constraints.

---

## 4. Technology Stack Audit

Cross-verified from actual dependency manifests and configuration files:

| Layer | Technology | Version | Manifest Source | Role & Notes |
|---|---|---|---|---|
| **Frontend Framework** | React | `18.3.1` | `frontend/package.json` | Component-based UI library |
| **Frontend Language** | TypeScript | `~5.6.2` | `frontend/package.json` | Type-safe JavaScript |
| **Build Tool** | Vite | `5.4.10` | `frontend/package.json` | Bundler & dev server (`tsc -b && vite build`) |
| **Routing** | React Router | `7.18.3` | `frontend/package.json` | Client-side route declarations |
| **State Management** | Zustand | `5.0.15` | `frontend/package.json` | Client session and auth token store |
| **Server State** | TanStack Query | `5.102.8` | `frontend/package.json` | Async API caching and polling |
| **Forms & Validation** | React Hook Form + Zod | `7.88.0` / `3.25.76` | `frontend/package.json` | Client-side input validation |
| **Styling** | TailwindCSS | `3.4.17` | `frontend/package.json` | Utility-first CSS framework |
| **Icons** | Lucide React | `1.45.0` | `frontend/package.json` | UI iconography |
| **Frontend Testing** | Vitest | `2.1.9` | `frontend/package.json` | Unit & component test runner |
| **Backend Framework** | FastAPI | `0.115.0` | `backend/pyproject.toml` | High-performance async ASGI web framework |
| **Server** | Uvicorn | `0.30.6` | `backend/pyproject.toml` | ASGI server |
| **Language** | Python | `>=3.12` (running 3.14.5) | `backend/pyproject.toml` | Core backend runtime |
| **ORM** | SQLAlchemy | `2.0.35` (asyncio) | `backend/pyproject.toml` | Async database abstraction |
| **Database Driver** | asyncpg | `0.29.0` | `backend/pyproject.toml` | Native async PostgreSQL driver |
| **Validation** | Pydantic | `2.9.2` | `backend/pyproject.toml` | Request/response data validation |
| **Settings** | pydantic-settings | `2.5.2` | `backend/pyproject.toml` | Strongly typed environment config |
| **Password Hashing** | Argon2id (`argon2-cffi`)| `23.1.0` | `backend/pyproject.toml` | High-security cryptographic password hashing |
| **Tokens / JWT** | python-jose | `3.3.0` | `backend/pyproject.toml` | HS256 JWT access token generation |
| **File Identification**| python-magic | `0.4.27` | `backend/pyproject.toml` | MIME-type byte inspection |
| **Backend Testing** | Pytest + pytest-asyncio | `8.3.3` / `0.24.0` | `backend/pyproject.toml` | Automated test framework |
| **Linting** | Ruff | `0.6.8` | `backend/pyproject.toml` | Code formatting and lint inspection |
| **Database Engine** | PostgreSQL | `16.15` | Live Database Engine | Primary ACID data store |
| **Database Migrations**| Alembic | `1.13.3` | `backend/pyproject.toml` | Database schema versioning |

---

## 5. Database & Schema Audit

Live query of PostgreSQL and inspection of `backend/app/models/domain.py` and `backend/migrations/versions`:

- **Total Database Tables**: **30 domain tables** (+ 1 `alembic_version` metadata table = 31 total).
- **Total Migrations**: **4 Alembic migrations applied**:
  1. `0001_initial_schema.py`: Initial core tables, indexes, and hall exclusion constraint.
  2. `0002_phase2_1_post_event_report.py`: Post-event reports and evidence documents.
  3. `0003_phase2_2_actual_expenses.py`: Actual expense ledger and document hashes.
  4. `0004_phase2_3_financial_settlement.py`: Cash advances, income, settlements, payments, revisions.
- **Current Migration Head**: `0004_phase2_3_settlement (head)`.

### 5.1 Complete Table Inventory
1. `users`
2. `refresh_tokens`
3. `password_reset_tokens`
4. `email_verification_tokens`
5. `clubs`
6. `club_members`
7. `halls`
8. `hall_bookings_confirmed`
9. `event_requests`
10. `event_request_versions`
11. `venue_requests`
12. `budget_proposals`
13. `budget_line_items`
14. `resource_requests`
15. `workflow_templates`
16. `workflow_template_steps`
17. `workflow_instances`
18. `workflow_instance_steps`
19. `notifications`
20. `documents`
21. `audit_logs`
22. `idempotency_records`
23. `events`
24. `post_event_reports`
25. `actual_expenses`
26. `cash_advances`
27. `actual_incomes`
28. `financial_settlements`
29. `settlement_payments`
30. `settlement_revisions`

### 5.2 Key Database-Level Constraints & Protections
1. **Hall Booking Conflict Exclusion Constraint**:
   ```sql
   excl_hall_bookings_no_overlap: EXCLUDE USING gist (
       hall_id WITH =,
       tstzrange(start_time, end_time, '[)') WITH &&
   ) WHERE (is_active = true);
   ```
   Enforces physical double-booking prevention at the PostgreSQL engine level using GiST index ranges.
2. **Financial Restrictive Foreign Keys (`ondelete="RESTRICT"`)**:
   - `financial_settlements.event_id -> events.id (RESTRICT)`
   - `financial_settlements.approved_version_id -> event_request_versions.id (RESTRICT)`
   - `settlement_payments.settlement_id -> financial_settlements.id (RESTRICT)`
   - `settlement_payments.proof_document_id -> documents.id (RESTRICT)`
   - `settlement_revisions.settlement_id -> financial_settlements.id (RESTRICT)`
   - `actual_expenses.bill_document_id -> documents.id (RESTRICT)`
   - `cash_advances.event_id -> events.id (RESTRICT)`
   - `actual_incomes.evidence_document_id -> documents.id (RESTRICT)`
   Prevents accidental cascade deletion of financial and audit history if parent entities are deleted.
3. **Monetary Non-Negative CHECK Constraints**:
   - `chk_fin_settlements_grant_non_negative`: `sanctioned_grant >= 0.00`
   - `chk_fin_settlements_exp_non_negative`: `sanctioned_expenditure >= 0.00`
   - `chk_fin_settlements_c_exp_non_negative`: `total_claimed_expenditure >= 0.00`
   - `chk_fin_settlements_v_exp_non_negative`: `total_verified_expenditure >= 0.00`
   - `chk_fin_settlements_d_exp_non_negative`: `total_disallowed_expenditure >= 0.00`
   - `chk_fin_settlements_v_inc_non_negative`: `total_verified_income >= 0.00`
   - `chk_fin_settlements_net_deficit_non_negative`: `net_deficit >= 0.00`
   - `chk_fin_settlements_payout_non_negative`: `institutional_payout >= 0.00`
   - `chk_fin_settlements_advance_non_negative`: `cash_advance_disbursed >= 0.00`
   - `chk_fin_settlements_reimb_non_negative`: `reimbursement_due >= 0.00`
   - `chk_fin_settlements_refund_non_negative`: `refund_due >= 0.00`
   - `chk_actual_expenses_claimed_positive`: `claimed_amount > 0.00`
   - `chk_actual_expenses_verified_le_claimed`: `verified_amount <= claimed_amount`
   - `chk_settlement_payments_amount_positive`: `amount > 0.00`
   - `chk_cash_advances_amount_requested_positive`: `amount_requested > 0.00`
   - `chk_actual_incomes_amount_positive`: `amount > 0.00`

---

## 6. Authentication Status

Evaluated against `app/services/auth_service.py`, `app/api/v1/endpoints/auth.py`, and `app/core/security.py`:

| Feature | Implementation Status | Evidence / Implementation Notes |
|---|---|---|
| **User Registration** | **IMPLEMENTED** | `POST /api/v1/auth/register` validates `@college.edu` domain, validates password strength, hashes password with Argon2id. |
| **User Login** | **IMPLEMENTED** | `POST /api/v1/auth/login` verifies Argon2id hash, tracks failed attempts, returns 15-minute JWT access token, and sets HttpOnly refresh cookie. |
| **JWT Access Tokens** | **IMPLEMENTED** | HS256 signed tokens containing `sub` (user UUID), `role`, `email`, and 15-minute expiration (`ACCESS_TOKEN_EXPIRE_MINUTES = 15`). |
| **Refresh Tokens** | **IMPLEMENTED** | 7-day cryptographically secure random token stored in database with SHA-256 hash. Transmitted via HttpOnly, SameSite=Lax cookie (`campusconnect_refresh`). |
| **Refresh Rotation** | **IMPLEMENTED** | Every call to `POST /api/v1/auth/refresh` revokes the used token and issues a new refresh token. |
| **Reuse Detection** | **IMPLEMENTED** | Presenting an already-revoked refresh token revokes all active refresh tokens for that user account and logs an audit security alert. |
| **User Logout** | **IMPLEMENTED** | `POST /api/v1/auth/logout` revokes current refresh token and clears cookie. |
| **Password Hashing** | **IMPLEMENTED** | Argon2id (`time_cost=3`, `memory_cost=65536`, `parallelism=4`). |
| **Account Lockout** | **IMPLEMENTED** | 5 consecutive failed login attempts locks account for 15 minutes (`ACCOUNT_LOCKOUT_MINUTES = 15`). |
| **Enumeration Protection** | **IMPLEMENTED** | Constant-time dummy Argon2id hash computation when email is not found to prevent timing-based user enumeration attacks. |
| **Password Reset** | **DESIGNED ONLY** | Table `password_reset_tokens` exists in DB. However, `POST /auth/forgot-password` and `POST /auth/reset-password` endpoints **are NOT implemented**. |
| **Email Verification** | **DESIGNED ONLY** | Table `email_verification_tokens` exists in DB. However, verification email dispatch and `GET /auth/verify-email` endpoint **are NOT implemented** (users are activated on registration). |
| **Security Headers / CORS** | **IMPLEMENTED** | Configured in `main.py` via CORSMiddleware with strict origin whitelisting (`http://localhost:5173`, `http://localhost:3000`). |

---

## 7. RBAC & Authorization Audit

Evaluated against `app/models/enums.py`, `app/api/deps.py`, and domain services:

### 7.1 Defined Roles (`UserRole`)
1. `SYSTEM_ADMIN`: Platform infrastructure, user management, hall creation. Strictly barred from financial approvals and settlement.
2. `CLUB_SECRETARY`: Club organizer. Creates proposals, submits budgets/venues, manages event execution, submits actual bills, prepares settlements.
3. `FACULTY_ADVISOR`: Club mentor. Endorses club proposals, reviews Stage 1 workflow, certifies post-event delivery.
4. `HALL_INCHARGE`: Venue manager. Reviews Stage 2 workflow, confirms/denies hall availability.
5. `FINANCE_OFFICER`: Financial auditor. Pre-audits proposals (Stage 3), verifies actual bills, audits financial settlements, records disbursements/refunds.
6. `ADVISOR_STUDENTS_UNION`: Student body calendar harmony (Stage 4).
7. `DEAN_STUDENT_AFFAIRS`: Institutional clearance (Stage 5).
8. `PRINCIPAL`: Chief executive authority. Final sanction of proposals (Stage 6), exceptional post-settlement reopening authority.

### 7.2 Authorization Controls & Boundaries
- **Resource Ownership**: Endpoints verify that the calling `CLUB_SECRETARY` is an active member of the club owning the event.
- **Cross-Club Isolation**: A Secretary belonging to Club A cannot view drafts, edit proposals, or submit expenses for Club B.
- **System Admin Boundaries**: System Admins cannot approve workflow steps, disallow expenses, audit settlements, or record payments (enforced with HTTP 403 `InsufficientRoleError`).
- **Pessimistic Concurrency**: Financial transactions lock event and settlement rows using `SELECT FOR UPDATE` to prevent concurrent modification or race conditions.

---

## 8. Club Governance Audit

Evaluated against `app/services/club_service.py`, `app/api/v1/endpoints/clubs.py`, and `app/schemas/club.py`:

- **Endpoints**:
  - `GET /api/v1/clubs`: List active clubs.
  - `POST /api/v1/clubs`: Create new club (Admin only).
  - `GET /api/v1/clubs/{id}`: Club profile and active roster.
  - `PATCH /api/v1/clubs/{id}`: Update club profile.
  - `GET /api/v1/clubs/{id}/members`: List club membership roster.
  - `POST /api/v1/clubs/{id}/members`: Add member to club (Secretary / Faculty Advisor).
  - `PATCH /api/v1/clubs/{id}/members/{user_id}`: Update member role (`SECRETARY`, `TREASURER`, `MEMBER`).
  - `DELETE /api/v1/clubs/{id}/members/{user_id}`: Soft-deactivate member (`is_active = False`).
- **Status**: **COMPLETE** (Backend, API, Tests). Frontend uses clubs within dashboard and create event forms.

---

## 9. Event Proposal Audit

Evaluated against `app/services/event_service.py` and `app/api/v1/endpoints/events.py`:

- **Endpoints**:
  - `POST /api/v1/events`: Create draft event proposal.
  - `GET /api/v1/events`: List proposals filtered by club/status.
  - `GET /api/v1/events/{id}`: Get proposal detail.
  - `PATCH /api/v1/events/{id}`: Update draft proposal.
  - `POST /api/v1/events/{id}/submit`: Submit proposal for institutional workflow review (freezes immutable snapshot in `event_request_versions`).
  - `GET /api/v1/events/{id}/workflow`: Retrieve active approval workflow instance and step progression.
- **Status**: **COMPLETE** (Full stack).

---

## 10. Hall & Venue Management Audit

Evaluated against `app/services/venue_service.py`, `app/api/v1/endpoints/halls.py`, and `app/api/v1/endpoints/events.py`:

- **Rule Verification**:
  - Minimum advance booking notice: **7 days** (`HALL_BOOKING_MIN_ADVANCE_DAYS = 7` in `app/core/config.py`).
  - Enforced in `venue_service.py:273`:
    ```python
    if advance_days < settings.HALL_BOOKING_MIN_ADVANCE_DAYS:
        raise AdvanceBookingViolationError(...)
    ```
- **Physical Double-Booking Prevention**:
  - PostgreSQL exclusion constraint (`excl_hall_bookings_no_overlap`) with GiST index range check `tstzrange(start_time, end_time, '[)')`.
- **Endpoints**:
  - `GET /api/v1/halls`: List all halls.
  - `POST /api/v1/halls`: Create hall (Admin only).
  - `GET /api/v1/halls/{id}`: Hall details.
  - `GET /api/v1/halls/{id}/availability`: Query slot availability.
  - `POST /api/v1/events/{id}/venue`: Request venue for event.
  - `GET /api/v1/events/{id}/venue`: Get venue request.
  - `PATCH /api/v1/events/{id}/venue`: Update venue requirements.
  - `DELETE /api/v1/events/{id}/venue`: Remove venue request.
- **Status**: **COMPLETE** (Full stack).

---

## 11. Budget Audit

Evaluated against `app/services/budget_service.py` and `app/api/v1/endpoints/events.py`:

- **Rules & Invariants**:
  - `Decimal` precision throughout (`Decimal("0.00")`).
  - Total expenditure = Sum of line items.
  - Funding invariant: `expected_income + institute_contribution <= total_expected_expenditure`.
  - Institutional grant cap: `institute_contribution <= 30000.00` (`BUDGET_INSTITUTE_CONTRIBUTION_CAP`).
  - Immutability: Budget is locked once event is submitted; revisions require formal workflow revision request.
- **Endpoints**:
  - `POST /api/v1/events/{id}/budget`: Create event budget.
  - `GET /api/v1/events/{id}/budget`: Retrieve budget and line items.
  - `PATCH /api/v1/events/{id}/budget`: Update expected income / institute contribution.
  - `DELETE /api/v1/events/{id}/budget`: Delete draft budget.
  - `POST /api/v1/events/{id}/budget/items`: Add line item.
  - `PATCH /api/v1/events/{id}/budget/items/{item_id}`: Update line item.
  - `DELETE /api/v1/events/{id}/budget/items/{item_id}`: Delete line item.
  - `POST /api/v1/events/{id}/budget/verify`: Finance Officer direct budget verification.
- **Status**: **COMPLETE** (Full stack).

---

## 12. Approval Workflow Audit

Evaluated against `app/services/workflow_service.py` and `app/api/v1/endpoints/workflows.py`:

- **Sequential 6-Stage Institutional Approval Chain**:
  1. `FACULTY_ADVISOR` (Academic/departmental endorsement).
  2. `HALL_INCHARGE` (Venue availability check; triggers `hall_bookings_confirmed`).
  3. `FINANCE_OFFICER` (Budget cap verification; marks budget `VERIFIED`).
  4. `ADVISOR_STUDENTS_UNION` (Student body calendar harmony).
  5. `DEAN_STUDENT_AFFAIRS` (Institutional administration clearance).
  6. `PRINCIPAL` (Final statutory sanction; creates confirmed `Event`).
- **Interlocks & Invariants**:
  - Sequential pointer: Steps must be processed strictly in order `current_step_order`.
  - Self-approval prevention: User who submitted event cannot approve any step.
  - Mandatory reasons on rejection or revision request.
  - Revision request rewinds workflow to draft, requiring resubmission which creates a new `WorkflowInstance` and marks prior instance `SUPERSEDED`.
- **Endpoints**:
  - `GET /api/v1/workflows/pending`: Personal pending approval queue for current actor.
  - `GET /api/v1/workflows/instance/{instance_id}`: Full workflow history.
  - `POST /api/v1/workflows/steps/{step_id}/approve`: Execute step approval and domain interlocks.
  - `POST /api/v1/workflows/steps/{step_id}/reject`: Reject proposal.
  - `POST /api/v1/workflows/steps/{step_id}/request-revision`: Request changes with mandatory comments.
- **Status**: **COMPLETE** (Full stack).

---

## 13. Notification System Audit

Evaluated against `app/services/notification_service.py` and `app/api/v1/endpoints/notifications.py`:

- **Storage**: Table `notifications` stores notifications per user with type and read timestamp.
- **Triggers**: Automated dispatch upon step assigned, step approved, revision requested, proposal approved, budget queried, report submitted, report certified, expense queried, settlement prepared, and settlement queries.
- **Delivery Model**: Polling-based REST query (TanStack React Query in frontend). No WebSockets or SSE implemented.
- **Endpoints**:
  - `GET /api/v1/notifications`: List notifications for current user.
  - `GET /api/v1/notifications/count`: Unread notification badge count.
  - `PATCH /api/v1/notifications/{id}/read`: Mark notification read.
  - `PATCH /api/v1/notifications/read-all`: Mark all read.
- **Status**: **COMPLETE** (Full stack).

---

## 14. Document Management Audit

Evaluated against `app/services/document_service.py` and `app/api/v1/endpoints/documents.py`:

- **Security Controls**:
  - Magic-byte validation via `python-magic` against allowed MIME types (PDF, JPEG, PNG, DOCX).
  - Maximum upload file size: **10 MB** (`MAX_FILE_SIZE_BYTES = 10485760`).
  - Path containment: Files stored using UUIDs under `UPLOAD_BASE_DIR` (`./uploads`); directory traversal strictly blocked.
  - Access control: Download verifies caller is club secretary, assigned reviewer, or administrator.
  - Cryptographic integrity: Computes and stores SHA-256 `file_hash`.
- **Endpoints**:
  - `POST /api/v1/events/{id}/documents`: Upload document.
  - `GET /api/v1/events/{id}/documents`: List event documents.
  - `GET /api/v1/events/{id}/documents/{doc_id}/download`: Download document.
  - `DELETE /api/v1/events/{id}/documents/{doc_id}`: Soft delete document.
- **Status**: **COMPLETE** (Full stack).

---

## 15. Confirmed Events Audit

Evaluated against `EventService.create_confirmed_event`:

- **Trigger**: Principal approves Step 6 in workflow.
- **Behavior**:
  - Creates row in `events` table with status `EventStatus.SCHEDULED`.
  - Captures frozen `approved_version_id` pointing to `event_request_versions`.
  - Associates confirmed hall booking from `hall_bookings_confirmed`.
  - Idempotent: Subsequent calls return existing event without duplicate insertion.
- **Endpoints**:
  - `GET /api/v1/events/{id}/confirmed`: Retrieve confirmed event record.
- **Status**: **COMPLETE** (Full stack).

---

## 16. Event Execution & Post-Event Report Audit (Phase 2.1)

Evaluated against `app/services/event_execution_service.py` and `app/api/v1/endpoints/event_execution.py`:

- **Lifecycle Distinction**:
  - `Event.status == EventStatus.IN_PROGRESS`: Event has started.
  - `Event.status == EventStatus.COMPLETED`: Event execution has ended.
  - `PostEventReport.status == PostEventReportStatus.CERTIFIED`: Faculty Advisor has endorsed report delivery.
  *(These two concepts are strictly decoupled).*
- **Evidence & Delivery Verification**:
  - Club Secretary submits attendance, objectives achieved, challenges, and photo evidence with GPS coordinates (`geo_lat`, `geo_lng`).
  - Faculty Advisor certifies delivery or requests revisions.
- **Endpoints**:
  - `POST /api/v1/events/{id}/start`: Secretary starts event (`IN_PROGRESS`).
  - `POST /api/v1/events/{id}/admin-start`: Admin emergency override.
  - `POST /api/v1/events/{id}/complete`: Secretary completes event and submits initial post-event report.
  - `GET /api/v1/events/{id}/post-event-report`: Retrieve report details.
  - `PATCH /api/v1/events/{id}/post-event-report`: Update draft report.
  - `POST /api/v1/events/{id}/post-event-report/revise`: Advisor requests changes.
  - `POST /api/v1/events/{id}/post-event-report/resubmit`: Secretary resubmits revised report.
  - `POST /api/v1/events/{id}/post-event-report/certify`: Faculty Advisor certifies report (`CERTIFIED`).
  - `POST /api/v1/events/{id}/evidence`: Upload geotagged photos.
  - `GET /api/v1/events/{id}/evidence`: List photos.
- **Status**: **COMPLETE** (Full stack).

---

## 17. Actual Expenses Ledger Audit (Phase 2.2)

Evaluated against `app/services/expense_service.py` and `app/api/v1/endpoints/expenses.py`:

- **Prerequisites**: Event must be `COMPLETED` and Post-Event Report must be `CERTIFIED` before bills can be submitted for verification.
- **Ledger Invariants**:
  - Mandatory receipt attachment (`EXPENSE_INVOICE` document).
  - SHA-256 duplicate invoice detection across all events.
  - Verification states: `DRAFT`, `SUBMITTED`, `VERIFIED`, `PARTIALLY_VERIFIED`, `QUERIED`, `DISALLOWED`.
  - Disallowed expenses contribute ₹0.00 to verified totals.
  - Verified amount cannot exceed claimed amount (`verified_amount <= claimed_amount`).
- **Endpoints (13 Endpoints)**:
  - `POST /api/v1/events/{id}/expenses`: Create draft expense claim.
  - `GET /api/v1/events/{id}/expenses`: List event expenses.
  - `POST /api/v1/events/{id}/expenses/upload-bill`: Upload receipt document.
  - `POST /api/v1/events/{id}/expenses/submit`: Batch submit expenses.
  - `POST /api/v1/events/{id}/expenses/{expense_id}/submit`: Single submit.
  - `GET /api/v1/events/{id}/expenses/{expense_id}`: Detail.
  - `PATCH /api/v1/events/{id}/expenses/{expense_id}`: Edit draft.
  - `DELETE /api/v1/events/{id}/expenses/{expense_id}`: Delete draft.
  - `GET /api/v1/events/{id}/expenses/summary`: Summary metrics.
  - `POST /api/v1/events/{id}/expenses/{expense_id}/verify`: Finance verify full amount.
  - `POST /api/v1/events/{id}/expenses/{expense_id}/partial-verify`: Finance partial verification.
  - `POST /api/v1/events/{id}/expenses/{expense_id}/query`: Finance query claim.
  - `POST /api/v1/events/{id}/expenses/{expense_id}/disallow`: Finance disallow claim.
- **Status**: **COMPLETE** (Full stack: Backend, API, Frontend `ExpenseLedgerTab.tsx`, Tests).

---

## 18. Financial Settlement Audit (Phase 2.3)

Evaluated against `backend/app/services/settlement_service.py`, `backend/app/models/domain.py`, and `backend/migrations/versions/0004_phase2_3_financial_settlement.py`:

### 18.1 Domain Models & Database (COMPLETE)
All 5 Phase 2.3 tables exist with cascade-hardened restrictive foreign keys (`ondelete="RESTRICT"`) and non-negative check constraints:
1. `cash_advances`: Requisition, approval, and disbursement tracking.
2. `actual_incomes`: External income recording, verification, and evidence.
3. `financial_settlements`: Authoritative settlement state and snapshot records.
4. `settlement_payments`: Immutable disbursement and refund transaction logs.
5. `settlement_revisions`: Snapshot records for reopening audits.

### 18.2 Service Layer Hardening (COMPLETE)
`SettlementService` implements production-grade collegiate financial settlement:
1. **Record-Level Deterministic SHA-256 Source Fingerprint**:
   $$\text{source\_fingerprint} = \text{sha256}(\text{canonical\_json}(\text{payload}))$$
   Fingerprints sorted expenses, incomes, advance status, and `approved_version_id`. Blocks settlement approval if live bills or proposals mutate after settlement preparation (`SettlementStaleDataError`).
2. **Cumulative Reconciliation Formula Across Reopenings**:
   $$\begin{aligned}
   V &= \sum_{\text{VERIFIED}} \text{verified} + \sum_{\text{PARTIALLY\_VERIFIED}} \text{verified} \\
   I_{\text{actual}} &= \sum_{\text{VERIFIED}} \text{income} \\
   \text{NetDeficit} &= \max(0.00, V - I_{\text{actual}}) \\
   P_{\text{entitled}} &= \min(G_{\text{sanctioned}}, \text{NetDeficit}) \\
   R_{\text{cleared}} &= \sum \text{historical } \text{REIMBURSEMENT\_DISBURSEMENT payments} \\
   F_{\text{cleared}} &= \sum \text{historical } \text{ADVANCE\_REFUND\_RECEIPT payments} \\
   \text{NetCashTransferred} &= A + R_{\text{cleared}} - F_{\text{cleared}} \\
   B_{\text{revision}} &= P_{\text{entitled}} - \text{NetCashTransferred} = (P_{\text{entitled}} - A) - (R_{\text{cleared}} - F_{\text{cleared}})
   \end{aligned}$$
3. **Downward Revisions**:
   $B_{\text{revision}} < 0 \implies$ branches to `PENDING_REFUND` (`refund_due = |B|`), cleared by recording `ADVANCE_REFUND_RECEIPT`.
4. **Upward Revisions**:
   $B_{\text{revision}} > 0 \implies$ branches to `PENDING_REIMBURSEMENT`, paying only incremental delta without duplicate payment.
5. **Direction Flips**:
   Properly credits prior refunds when subsequent expenses exceed the advance.
6. **Payment Immutability**:
   Payments are never modified, deleted, or partitioned by timestamps.
7. **Closure Eligibility**:
   `get_closure_eligibility()` verifies all expenses are resolved, all income is verified, and net institutional cash transferred exactly equals entitled payout.

### 18.3 Gaps in Phase 2.3 (API & Frontend)
- **API Schemas**: `backend/app/schemas/financial_settlement.py` **DOES NOT EXIST**.
- **API Endpoints**: `backend/app/api/v1/endpoints/settlement.py` **DOES NOT EXIST**.
- **Frontend UI**: `SettlementTab.tsx` **DOES NOT EXIST**.

---

## 19. Frontend Implementation Audit

Evaluated against `frontend/src/`:

| Page / Component | Route | File Path | Status | Details |
|---|---|---|---|---|
| **Login Page** | `/login` | `src/pages/LoginPage.tsx` | **FUNCTIONAL** | Email/password login with college domain validation and error banners. |
| **Dashboard** | `/dashboard` | `src/pages/DashboardPage.tsx` | **FUNCTIONAL** | Metrics cards, pending approvals, recent events, upcoming calendar. |
| **Event List** | `/events` | `src/pages/EventListPage.tsx` | **FUNCTIONAL** | Filterable table by status, club, academic year; navigation to details. |
| **Create Event** | `/events/new` | `src/pages/CreateEventPage.tsx` | **FUNCTIONAL** | Multi-section form: core metadata, venue selection, budget lines, document upload. |
| **Event Details** | `/events/:id` | `src/pages/EventDetailPage.tsx` | **FUNCTIONAL** | Master container hosting 7 integrated tabs. |
| **- Overview Tab** | (tab) | `src/pages/EventDetailPage.tsx` | **FUNCTIONAL** | Metadata, version info, workflow status indicator. |
| **- Venue Tab** | (tab) | `src/pages/EventDetailPage.tsx` | **FUNCTIONAL** | Venue request, requirements, booking confirmation details. |
| **- Budget Tab** | (tab) | `src/pages/EventDetailPage.tsx` | **FUNCTIONAL** | Budget proposal, breakdown, line items table, cap display. |
| **- Documents Tab** | (tab) | `src/pages/EventDetailPage.tsx` | **FUNCTIONAL** | Upload files, download, delete, status badges. |
| **- Resources Tab** | (tab) | `src/pages/EventDetailPage.tsx` | **FUNCTIONAL** | Equipment requests (chairs, projectors, etc.). |
| **- Execution Tab** | (tab) | `src/pages/EventDetailPage.tsx` | **FUNCTIONAL** | Start event, complete event, post-event report form, advisor certification. |
| **- Expenses Tab** | (tab) | `src/components/expenses/ExpenseLedgerTab.tsx`| **FUNCTIONAL** | Bill upload, ledger table, submit batch, Finance verification buttons. |
| **- Settlement Tab**| (tab) | *None* | **NOT IMPLEMENTED** | No settlement component or tab exists in the frontend. |
| **Pending Queue** | `/workflow/pending` | `src/pages/WorkflowPendingPage.tsx`| **FUNCTIONAL** | Reviewer-specific queue of events awaiting approval. |
| **Workflow Step** | `/workflow/steps/:id` | `src/pages/WorkflowStepPage.tsx` | **FUNCTIONAL** | Step inspection, approve/reject/revision action modals. |
| **Notification Bell**| (navbar) | `src/components/notifications/NotificationBell.tsx`| **FUNCTIONAL** | Header bell with unread badge count and dropdown list. |

---

## 20. Testing & Quality Verification

Live test execution performed during this audit:

### 20.1 Backend Tests (`pytest -q`)
- **Total Test Files**: 21
- **Total Tests Collected**: **371**
- **Test Results**: **371 passed in 75.35s** (0 failed, 0 errors, 0 skipped).
- **Test Category Breakdown**:
  - API Endpoints (`tests/api/`): 261 tests (15 files)
  - Service Layer (`tests/services/`): 52 tests (Settlement Service)
  - Unit Tests (`tests/unit/`): 57 tests (Auth, Security, Relationships, Config)
  - Integration (`tests/integration/`): 1 test (PostgreSQL exclusion constraint)

### 20.2 Frontend Tests (`vitest run`)
- **Total Test Files**: 6
- **Total Tests**: **17**
- **Test Results**: **17 passed in 41.13s** (0 failed).

### 20.3 Code Quality & Linting
- **Frontend ESLint**: `npm run lint` exited code 0 (zero errors, zero warnings).
- **Frontend Build**: `tsc -b && vite build` built cleanly in 4.97s (dist generated).
- **Backend Ruff**: Clean on all Phase 2.3 files.
- **Git Diff Check**: `git diff --check` passed cleanly (zero whitespace errors).

---

## 21. Security & Governance Audit

| Security Domain | Status | Evaluation & Code Evidence |
|---|---|---|
| **Authentication & Tokens** | **PASS** | Argon2id password hashing, constant-time dummy hashing against enumeration, 15-minute HS256 access tokens, 7-day HttpOnly SameSite=Lax refresh cookie with cryptographic rotation and reuse detection. |
| **Authorization & RBAC** | **PASS** | RoleChecker dependency injection in `deps.py`. Distinct roles for all 8 collegiate personas. |
| **System Admin Boundaries** | **PASS** | System Administrators are strictly barred from financial verification, audit, approval, and settlement payments. |
| **Cross-Club Isolation** | **PASS** | Secretary access is strictly checked against active club membership. |
| **Pessimistic Concurrency** | **PASS** | Critical financial paths use `SELECT FOR UPDATE` on settlement, event, advance, and payments. |
| **Source Data Fingerprinting**| **PASS** | Deterministic record-level SHA-256 digest prevents silent stale-data approvals. |
| **Cumulative Ledger Balance** | **PASS** | Timeless cumulative reconciliation prevents overpayment or duplicate disbursements across multiple reopenings. |
| **File Upload Security** | **PASS** | Magic-byte MIME inspection, 10MB file cap, UUID disk filenames, directory traversal containment. |
| **Financial Cascades** | **PASS** | `ON DELETE RESTRICT` on all financial children permanently protects institutional history from parent deletion. |
| **Audit Logging** | **PASS** | 71 distinct `AuditAction` enum types record structured actor, timestamp, previous_state, and new_state in `audit_logs`. |

---

## 22. Documentation Audit

Review of files in `docs/`:

| Document | Type | Evaluation |
|---|---|---|
| `DAY7_BUSINESS_RULES.md` | Historical | Day 7 rules baseline. (Contains early 3-day notice note; code enforces 7 days). |
| `DAY7_SECURITY_AUDIT.md` | Historical | Security audit snapshot from Day 7. |
| `DAY7_SYSTEM_AUDIT.md` | Historical | System audit snapshot from Day 7. |
| `PHASE2_ARCHITECTURE.md` | Current Architecture | Authoritative architectural blueprint for Phase 2. |
| `PHASE2_STATE_MACHINE.md` | Current State Machine | Exact state transitions for events, post-event reports, and expenses. |
| `PHASE2_DECISION_RESEARCH.md` | Research Record | Architectural decision records for Phase 2 lifecycle. |
| `PHASE2_2_DECISION_RESEARCH.md` | Research Record | Research and design for actual expense verification. |
| `PHASE2_2_IMPLEMENTATION_REPORT.md` | Implementation Report | Implementation report for Phase 2.2 expense ledger. |
| `PHASE2_3_DECISION_RESEARCH.md` | Research Record | Research and design for settlement, cash advances, and income. |
| `PHASE2_3_MIGRATION_REPORT.md` | Implementation Report | Migration report for `0004_phase2_3_settlement`. |
| `PHASE2_3_SCHEMA_AUDIT.md` | Pre-Migration Audit | Database schema audit prior to migration 0004. |
| `PHASE2_3_SERVICE_IMPLEMENTATION_REPORT.md` | Implementation Report | Authoritative report on `SettlementService` implementation and hardening. |

### Contradictions Between Documentation & Code:
1. **Hall Booking Advance Days**: Some early research mentioned 3 or 7 days; **Code is authoritative**: `HALL_BOOKING_MIN_ADVANCE_DAYS = 7`.
2. **Event `CLOSED` Status**: Early notes suggested an event status `CLOSED`; **Code is authoritative**: `EventStatus` uses `COMPLETED`; no `CLOSED` status was added.
3. **Monetary Approval Threshold**: An arbitrary ₹1,50,000 threshold for Principal financial approval was discussed in early research; **Code is authoritative**: Standard settlements are audited by Finance Officers; Principal approval is reserved for exceptional reopenings.
4. **Deferred Migration 0005**: Research discussed a `settlement_revision_id` foreign key on payments; **Code is authoritative**: Migration 0005 was explicitly deferred; reconciliation is achieved cumulatively in the service layer.

---

## 23. Git Checkpoint History

```text
* 518f5e3 (HEAD, origin/phase2-event-lifecycle) feat(phase2): harden financial settlement and reopening
* b05eddd feat(phase2): checkpoint financial settlement domain models
* 1117541 feat(phase2): add actual expense ledger and finance verification
* a3dd03e feat(phase2): add event completion and post-event certification
* 12b2002 (origin/master, master) feat(day6): notification service, confirmed events, secure docs, dashboard, and complete frontend UI
* 48578a2 feat(days3-5): club governance, events, venue, budget, approval workflow
* e998199 feat(auth): harden RBAC and test infrastructure
* 9a104ed feat(auth): add role based access control foundation
* 67afd44 feat(auth): complete authentication API and security foundation
```

- **Phase 1 (Days 1–6)**: Merged to `master` at commit `12b2002`.
- **Phase 2.1**: Committed at `a3dd03e` (Event execution & post-event report certification).
- **Phase 2.2**: Committed at `1117541` (Actual expense ledger & bill verification).
- **Phase 2.3 Checkpoint 1**: Committed at `b05eddd` (Domain models, cascade hardening, migration 0004).
- **Phase 2.3 Checkpoint 2 (Current)**: Committed at `518f5e3` (Service hardening, cumulative reconciliation, source fingerprinting, 52 settlement tests).

---

## 24. Overall Module Completion Matrix

| Module | Domain Model | Backend Service | REST API | Frontend UI | Tests | Overall Status |
|---|---|---|---|---|---|---|
| **Authentication & Session** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (68) | **COMPLETE** |
| **User & RBAC Foundation** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (33) | **COMPLETE** |
| **Club Governance** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (36) | **COMPLETE** |
| **Event Proposal Lifecycle** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (14) | **COMPLETE** |
| **Hall & Venue Management** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (19) | **COMPLETE** |
| **Budget Proposal & Items** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (15) | **COMPLETE** |
| **6-Stage Approval Workflow** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (20) | **COMPLETE** |
| **Confirmed Event Creation** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (4) | **COMPLETE** |
| **Document Management** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (23) | **COMPLETE** |
| **Notifications System** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (15) | **COMPLETE** |
| **Dashboard Metrics** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (8) | **COMPLETE** |
| **Phase 2.1 Event Execution** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (21) | **COMPLETE** |
| **Phase 2.2 Expense Ledger** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE (17) | **COMPLETE** |
| **Phase 2.3 Cash Advances** | COMPLETE | COMPLETE | NOT STARTED | NOT STARTED | COMPLETE (incl) | **PARTIAL** |
| **Phase 2.3 Actual Income** | COMPLETE | COMPLETE | NOT STARTED | NOT STARTED | COMPLETE (incl) | **PARTIAL** |
| **Phase 2.3 Financial Settlement**| COMPLETE | COMPLETE | NOT STARTED | NOT STARTED | COMPLETE (52) | **PARTIAL** |
| **Event Final Closure / Archive**| COMPLETE | PARTIAL | NOT STARTED | NOT STARTED | PARTIAL (incl) | **PARTIAL** |

---

## 25. Full Lifecycle Coverage

```text
[1] Club Governance
     ↓ (COMPLETE)
[2] Event Proposal Draft
     ↓ (COMPLETE)
[3] Venue & Hall Request
     ↓ (COMPLETE)
[4] Budget & Institute Contribution
     ↓ (COMPLETE)
[5] Document Attachments
     ↓ (COMPLETE)
[6] Proposal Submission & Snapshot
     ↓ (COMPLETE)
[7] 6-Stage Approval Workflow
     ↓ (COMPLETE)
[8] Principal Sanction
     ↓ (COMPLETE)
[9] Confirmed Event Scheduled
     ↓ (COMPLETE)
[10] Event Execution (IN_PROGRESS)
     ↓ (COMPLETE)
[11] Event Completion (COMPLETED)
     ↓ (COMPLETE)
[12] Post-Event Report & Geotagged Photos
     ↓ (COMPLETE)
[13] Faculty Advisor Certification (CERTIFIED)
     ↓ (COMPLETE)
[14] Actual Expense Ledger & Invoice Bills
     ↓ (COMPLETE)
[15] Finance Bill Verification
     ↓ (COMPLETE)
════════════════════════════════════════════════════════════════════════
[16] Phase 2.3 Financial Settlement & Advances
     ├── Database Schema:     COMPLETE
     ├── Service Engine:      COMPLETE (Hardened)
     ├── REST API Layer:      NOT IMPLEMENTED  ◄── FIRST MAJOR INCOMPLETE STAGE
     └── Frontend UI:         NOT IMPLEMENTED
════════════════════════════════════════════════════════════════════════
     ↓
[17] Reimbursements / Refund Recovery
     ├── Service Engine:      COMPLETE
     ├── API & UI:            NOT IMPLEMENTED
     ↓
[18] Final Event Closure & Archiving
     ├── Service Check:       COMPLETE (get_closure_eligibility)
     ├── Lifecycle Status:    NOT IMPLEMENTED (No CLOSED state or transition)
     └── Archive Action:      NOT IMPLEMENTED
```

---

## 26. What CampusConnect Has Actually Built So Far

CampusConnect has built a robust, collegiate-grade event governance platform that successfully guides student club proposals from initial conception through institutional sanction, physical event delivery, and post-event expenditure verification:

1. **Authentication & Identity**: Multi-persona authentication supporting 8 distinct roles with Argon2id hashing, secure JWT/HttpOnly refresh token rotation, and account lockout protection.
2. **Proposal Lifecycle & Multi-Stage Governance**: Club Secretaries can formulate proposals, request campus halls with PostgreSQL exclusion constraint double-booking protection (enforcing 7-day advance notice), submit itemized budgets (capped at ₹30,000 institute grant), and attach supporting documents.
3. **Rigorous Sequential Approval Workflow**: Proposals traverse a mandatory 6-stage review chain (Faculty Advisor $\to$ Hall In-Charge $\to$ Finance Officer $\to$ Students Union $\to$ Dean $\to$ Principal) with automated interlocks, self-approval prevention, mandatory remarks, and automated notification triggers.
4. **Physical Event Delivery & Certification**: Approved proposals automatically create confirmed `Event` entities. Organizers transition events to `IN_PROGRESS` and `COMPLETED`, uploading geotagged photo evidence and attendance reports that Faculty Advisors formally certify.
5. **Auditable Expense Ledger**: Organizers submit original vendor receipts verified by SHA-256 duplicate detection. Finance Officers audit individual line items (`VERIFIED`, `PARTIALLY_VERIFIED`, `QUERIED`, `DISALLOWED`).
6. **Hardened Financial Settlement Accounting Engine**: The backend service layer provides a mathematically verified cumulative reconciliation engine handling pre-event cash advances, external ticket/sponsorship revenue, verified invoice totals, downward recovery deadlocks, upward supplementary reimbursements, direction flips, and deterministic SHA-256 source fingerprinting to block stale data approvals.

---

## 27. What Is Still Missing

### Critical (Blocks Complete End-to-End User Flow)
1. **Phase 2.3 Pydantic Schemas**: `backend/app/schemas/financial_settlement.py` for advances, income, settlements, payments, and closure.
2. **Phase 2.3 REST Endpoints**: `backend/app/api/v1/endpoints/settlement.py` exposing `SettlementService` functions via HTTP.
3. **Phase 2.3 Router Registration**: Connecting settlement endpoints into `backend/app/api/v1/api.py`.
4. **Phase 2.3 API Integration Tests**: Test suite in `backend/tests/api/test_settlement.py`.
5. **Phase 2.3 Frontend Interface**: `SettlementTab.tsx` inside `EventDetailPage.tsx` providing UI for:
   - Requesting and disbursing cash advances.
   - Recording and verifying external revenues.
   - Preparing, submitting, auditing, and querying settlements.
   - Recording disbursement and refund transactions.
   - Reopening settled accounts and viewing revision history.

### Important (Lifecycle Completeness & Usability)
1. **Event Closure & Archival Transition**: An explicit endpoint and UI flow to transition an event from `COMPLETED` to `ARCHIVED` once `get_closure_eligibility()` passes.
2. **Password Reset Endpoints**: `POST /auth/forgot-password` and `POST /auth/reset-password` (DB tables exist).
3. **Email Verification Endpoints**: Real email delivery and token activation flow.

### Enhancements
1. **Real-time Notifications**: WebSockets or Server-Sent Events (SSE) to replace React Query polling.
2. **PDF Settlement Report Generation**: Exportable institutional settlement vouchers with financial audit breakdown.

### Future / Institutional Confirmation Needed
1. **Institutional Default Recovery Policy**: Statutory mechanism for recovering unreturned cash advances or downwards revision refund deficits (e.g. Faculty Advisor liability vs club budget freeze).
2. **Surplus Revenue Retention Policy**: Statutory ruling on whether surplus event revenue ($I_{\text{actual}} > V$) is retained by the college or credited to the club reserve.

---

## 28. Recommended Next Development Order

Based strictly on code dependencies, lifecycle completeness, and missing layers:

1. **Step 1: Phase 2.3 API Schemas (`backend/app/schemas/financial_settlement.py`)**
   - Create request and response Pydantic models for Cash Advances, Actual Income, Settlement preparation/audit, Payment recording, and Closure check.
2. **Step 2: Phase 2.3 REST API Endpoints (`backend/app/api/v1/endpoints/settlement.py`)**
   - Expose endpoints with dependency-injected RBAC:
     - `POST /events/{id}/advances` (Secretary)
     - `POST /events/{id}/advances/{id}/approve` (Finance)
     - `POST /events/{id}/advances/{id}/disburse` (Finance)
     - `POST /events/{id}/incomes` (Secretary)
     - `POST /events/{id}/incomes/{id}/verify` (Finance)
     - `POST /events/{id}/settlement/prepare` (Secretary)
     - `POST /events/{id}/settlement/submit` (Secretary)
     - `POST /events/{id}/settlement/audit` (Finance)
     - `POST /events/{id}/settlement/payments` (Finance)
     - `POST /events/{id}/settlement/reopen` (Finance / Principal)
     - `GET /events/{id}/settlement` (Authorized viewer)
     - `GET /events/{id}/settlement/closure-eligibility` (Authorized viewer)
3. **Step 3: Register API Router & API Integration Tests**
   - Wire router in `backend/app/api/v1/api.py`.
   - Implement `backend/tests/api/test_settlement.py` verifying full HTTP contract, HTTP 403 barriers for System Admin, and error payloads.
4. **Step 4: Phase 2.3 Frontend UI (`SettlementTab.tsx`)**
   - Build settlement React components in `frontend/src/components/settlement/`.
   - Wire `SettlementTab` into `EventDetailPage.tsx`.
   - Connect TanStack Query hooks and action mutations.
5. **Step 5: Event Closure & Archival Transition**
   - Implement formal archive transition once settlement balance reaches ₹0.00 and closure conditions are met.

---

## 29. Known Limitations & Unresolved Institutional Policies

1. **Deferred Schema Migration 0005**: `settlement_revision_id` foreign key on `SettlementPayment` remains intentionally deferred. The service layer handles revisions timelessly and cumulatively.
2. **Event Status Invariant**: `EventStatus` remains `COMPLETED`. No `CLOSED` status was introduced into the database enum.
3. **Unresolved Recovery Policy**: Marked as `[EVIDENCE INSUFFICIENT — REQUIRES INSTITUTIONAL CONFIRMATION]`: Mechanism for recovering unreturned club refund debts.
4. **Unresolved Surplus Revenue Policy**: Marked as `[EVIDENCE INSUFFICIENT — REQUIRES INSTITUTIONAL CONFIRMATION]`: Ownership of event profit when ticket/sponsorship revenue exceeds total expenditures.

---

## 30. Exact Current Checkpoint

- **Branch**: `phase2-event-lifecycle`
- **Commit**: `518f5e3`
- **Date**: September 24, 2026
- **Status**: Backend hardened; 371/371 tests passing; Ready for Phase 2.3 API implementation.
