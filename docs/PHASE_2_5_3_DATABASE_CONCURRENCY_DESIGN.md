# CAMPUSCONNECT — PHASE 2.5.3 DATABASE & CONCURRENCY HARDENING DESIGN

=============================================================================
CRITICAL NOTICE: BUSINESS FEATURE SCOPE IS STRICTLY FROZEN.
THIS PHASE IS TARGETED DATABASE AND CONCURRENCY HARDENING:
1. GAP-04: DRAFT OPTIMISTIC CONCURRENCY CONTROL (OCC) FOR EVENT REQUESTS
2. GAP-05: POSTGRESQL FOREIGN KEY INDEX AUDIT & MIGRATION 0006
3. TRANSACTION BOUNDARY AUDIT (get_db VS SERVICE EXPLICIT COMMITS)
=============================================================================

## 1. Research Findings

### A. Optimistic Concurrency Control (OCC) for Collaborative Drafts
- **Martin Fowler, Patterns of Enterprise Application Architecture (PofEAA - Optimistic Offline Lock)**:
  - In web applications where multiple users or browser sessions can edit the same draft resource, preventing the "lost update" anomaly requires detecting concurrent conflicts before applying mutations.
  - Unlike pessimistic locking at the HTTP session level (which holds database connections or locks across stateless HTTP roundtrips and degrades availability), Optimistic Concurrency Control maintains an integer `version_lock` on the record.
  - When the client initiates an update, it submits its known `expected_version`. The server verifies that the current database version matches `expected_version`.
  - If the database version has advanced beyond `expected_version` (indicating another user or tab saved changes in the interim), the mutation is aborted, and the server returns **HTTP 409 Conflict** with an informative error payload.
  - When the versions match, the server applies the delta, atomically increments `version_lock = version_lock + 1`, records an audit entry, and commits the transaction.
- **PostgreSQL Row-Level Concurrency (`SELECT ... FOR UPDATE`)**:
  - In PostgreSQL MVCC, an in-flight transaction verifying `event.version_lock == expected_version` and updating `version_lock` could still suffer race conditions under `READ COMMITTED` isolation if two concurrent requests evaluate the version simultaneously before writing.
  - By combining optimistic version checking with a row-level latch (`SELECT ... FOR UPDATE`), the transaction serializes concurrent update requests on the exact row ID. The first request reads version $N$, updates to $N+1$, and commits. The second request blocks on `FOR UPDATE` until the first transaction completes, re-reads the updated row at version $N+1$, detects the version mismatch ($N+1 \neq N$), and immediately raises HTTP 409 without overwriting.

### B. PostgreSQL Foreign Key Indexing & Query Planner Analysis
- **PostgreSQL Official Documentation (Chapter 5: Data Definition - Foreign Keys)**:
  - PostgreSQL automatically creates a B-Tree index on primary key and unique constraint columns. However, **PostgreSQL does NOT automatically create indexes on foreign key columns**.
  - Lack of foreign key indexing incurs two severe performance penalties:
    1. **Reverse Joins and Filtering**: Queries performing `JOIN` operations from the parent table to the child table, or filtering child records by parent ID, must execute a sequential table scan (`Seq Scan`) if no index exists on the foreign key column.
    2. **Parent Row Deletion / Updates (Locking & Cascade Scans)**: When a row in the referenced parent table is deleted or its primary key updated, PostgreSQL must scan the referencing child table to verify that no referencing foreign keys violate the constraint (or to execute `ON DELETE CASCADE/SET NULL/RESTRICT`). Without an index on the foreign key, PostgreSQL must perform a sequential scan on the referencing table, frequently taking share locks that severely degrade concurrency.
- **Write Amplification & Cardinality Trade-Offs**:
  - Blindly indexing all foreign key columns in an enterprise schema creates severe downsides: write amplification, increased Write-Ahead Log (WAL) volume, buffer pool churn, and table bloat during inserts and updates.
  - Every candidate foreign key must be evaluated individually against:
    * Query frequency and workload filter patterns.
    * Join frequency in application domain services and reporting.
    * Deletion semantics (e.g. `users` records in CampusConnect are soft-deactivated and never hard-deleted in production; thus reverse FK deletion locks against `users` do not occur).
    * Column cardinality and lifecycle characteristics (e.g. transient short-lived auth tokens queried by cryptographic token hashes).

### C. SQLAlchemy 2.0 AsyncSession Transaction Boundaries & Unit-of-Work
- **SQLAlchemy 2.0 Official Documentation (Session Basics & Managing Transactions)**:
  - An `AsyncSession` represents a Unit of Work. By default, it operates in transactional mode (`autocommit=False`).
  - In web architectures using FastAPI, dependencies such as `get_db()` yield a session inside a `try/except/finally` context.
  - A common architectural tension arises when service methods explicitly execute `await db.commit()`, while `get_db()` also executes `await session.commit()` upon successful exit.
  - Potential failure modes to evaluate:
    1. *Premature commits*: Committing half of a multi-table workflow before all operations and audit logs are written.
    2. *Broken rollbacks*: An exception occurring midway after a partial commit, leaving corrupted orphan state.
    3. *Lock release*: Row-level locks (`FOR UPDATE`) are released immediately when `commit()` is called, exposing subsequent uncommitted operations to race conditions.
  - Proving safety: If each domain service method strictly encapsulates its complete business operation, audit logging, and notifications within a single atomic commit at the end of the method, and rolls back on any exception, then transaction integrity is preserved without needing a destabilizing architectural overhaul.

---

## 2. GAP-04: Draft Optimistic Concurrency Control

### A. Audit of EventRequest Mutation Flows
We audited all locations across CampusConnect where `EventRequest` records are modified:
1. `EventService.create_draft`: Initializes a new request at `version_lock = 1`.
2. `EventService.update_draft`: Modifies fields on existing drafts. **Previously lacked `expected_version` validation, allowing concurrent editors to overwrite changes.**
3. `EventService.submit_proposal`: Locks draft via `with_for_update()`, validates completeness, transitions to `SUBMITTED`, increments `version_lock`, and creates an immutable `EventRequestVersion` (snapshot version 1).
4. `EventService.cancel_event`: Transitions approved events to `CANCELLED`, releases venue reservations, and increments `version_lock`.

### B. State Machine Analysis
- **Immutable States**: Once submitted (`SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, `REJECTED`, `CANCELLED`, `COMPLETED`), proposals cannot be edited via `update_draft`. Lifecycles are protected by strict workflow state machine checks.
- **Editable States**: Proposals can only be modified via `update_draft` when in `DRAFT` or `REVISION_REQUIRED` state.
- **Concurrency Risk Target**: The concurrency risk is exclusively present during the drafting and revision phases when multiple club committee members or advisors access the same proposal draft.

### C. Implementation Details

#### 1. Schema Enhancement (`backend/app/schemas/event.py`)
`EventRequestUpdate` was extended with an optional `expected_version` parameter:
```python
class EventRequestUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=500)
    description: str | None = None
    event_type: EventType | None = None
    expected_attendees: int | None = Field(default=None, gt=0)
    expected_version: int | None = Field(
        default=None,
        ge=0,
        description="Optimistic concurrency control: expected version_lock before applying update",
    )
```

#### 2. Service-Layer Atomic Validation (`backend/app/services/event_service.py`)
In `EventService.update_draft`:
1. Row-level latch acquisition:
   ```python
   stmt = (
       select(EventRequest)
       .where(EventRequest.id == event_id)
       .with_for_update()
   )
   event = await db.scalar(stmt)
   ```
2. Optimistic version check:
   ```python
   if (
       event_in.expected_version is not None
       and event.version_lock != event_in.expected_version
   ):
       raise OptimisticLockError(
           f"Event proposal draft has been modified concurrently. "
           f"Expected version {event_in.expected_version}, but current version is "
           f"{event.version_lock}. "
           "Please refetch the latest draft and reapply your changes."
       )
   ```
3. Lifecycle guard:
   ```python
   if event.status not in (EventRequestStatus.DRAFT, EventRequestStatus.REVISION_REQUIRED):
       raise WorkflowStateError(...)
   ```
4. Atomic increment and commit:
   ```python
   event.version_lock += 1
   # apply delta mutations...
   await self.db.commit()
   await self.db.refresh(event)
   ```

#### 3. Frontend TypeScript Contract Synchronization (`frontend/src/types/index.ts`)
Updated `EventRequest` to expose `version_lock: number` and updated `EventRequestUpdate` to accept `expected_version?: number`. This maintains complete contract compatibility without breaking any existing client call sites.

---

## 3. GAP-05: Foreign Key Index Audit & Migration 0006

### A. Complete Foreign Key Inventory
A live PostgreSQL audit of the database identified **84 Foreign Key constraints**.
- **48 FKs** were already indexed via dedicated B-Trees or unique composite constraints (including migrations 0001 through 0005).
- **36 FKs** were flagged by initial scans as missing a dedicated single-column B-Tree index.

### B. High-Frequency Relational Indexes Created (Migration 0006)
Out of the 36 unindexed candidates, exactly **8 foreign key columns** are high-frequency relational join keys, filtering columns, or cascade targets that technically warrant dedicated B-Tree indexes:

| Table | Column | Index Name | Technical Justification |
| :--- | :--- | :--- | :--- |
| `events` | `hall_id` | `ix_events_hall_id` | Venue schedule lookups, hall utilization queries, avoids table lock on hall modification |
| `events` | `approved_version_id` | `ix_events_approved_version_id` | Joins event records to their immutable approved proposal version snapshot |
| `event_requests` | `workflow_instance_id` | `ix_event_requests_workflow_instance_id` | Bidirectional workflow lookup from request to active workflow instance |
| `event_requests` | `submitted_by` | `ix_event_requests_submitted_by` | Applicant dashboard filtering ("My Proposals"), user activity tracking |
| `notifications` | `event_request_id` | `ix_notifications_event_request_id` | Notification queries by event request, cascading cleanup |
| `hall_bookings_confirmed` | `venue_request_id` | `ix_hall_bookings_confirmed_venue_request_id` | Venue allocation auditing, booking-to-request traceability |
| `workflow_instances` | `template_id` | `ix_workflow_instances_template_id` | Workflow engine template usage reporting and lifecycle lookups |
| `workflow_instance_steps` | `template_step_id` | `ix_workflow_instance_steps_template_step_id` | Workflow step definition joins, SLA validation |

*(Note: Prior migrations 0004 and 0005 already created indexes for `financial_settlements.approved_version_id` as `ix_financial_settlements_approved_version` and `event_closures.post_event_report_id` as `ix_event_closures_post_event_report_id`.)*

### C. Deliberately Unindexed Foreign Keys (28 Columns)
The remaining **28 unindexed foreign key columns** were evaluated and deliberately left unindexed with technical justifications:

1. **Actor / Audit Attribution Columns (25 FKs to `users.id`)**:
   - `actual_expenses.submitted_by`
   - `actual_expenses.verified_by`
   - `actual_incomes.recorded_by`
   - `actual_incomes.verified_by`
   - `budget_proposals.finance_verified_by`
   - `cash_advances.approved_by`
   - `cash_advances.disbursed_by`
   - `cash_advances.recipient_id`
   - `clubs.created_by`
   - `documents.uploaded_by`
   - `event_closure_revisions.reopened_by`
   - `event_closures.certified_by`
   - `event_closures.requested_by`
   - `event_request_versions.submitted_by`
   - `events.cancelled_by`
   - `financial_settlements.audited_by`
   - `financial_settlements.prepared_by`
   - `post_event_reports.certified_by`
   - `post_event_reports.submitted_by`
   - `resource_requests.managed_by`
   - `settlement_payments.recorded_by`
   - `settlement_revisions.reopened_by`
   - `venue_requests.reviewed_by`
   - `workflow_template_steps.assigned_user_id`
   - `workflow_templates.created_by`

   *Technical Justification*:
   - Read patterns: These tables are never queried with filters like `WHERE certified_by = :user_id` or `WHERE verified_by = :user_id`. Queries always access records by primary entity ID (`id`, `event_id`, or `settlement_id`), loading the actor UUID as an informational attribute.
   - Deletion semantics: In CampusConnect, `User` records are NEVER hard-deleted in production (`is_active = False` soft deactivation). Therefore, PostgreSQL never performs reverse cascade/restrict scans against these tables.
   - Write amplification: Adding 25 redundant indexes would penalize write throughput, inflate index memory footprints, and bloat WAL logs without providing any measurable read performance advantage.

2. **Transient Token & Idempotency Store Columns (3 FKs to `users.id`)**:
   - `email_verification_tokens.user_id`
   - `password_reset_tokens.user_id`
   - `idempotency_records.user_id`

   *Technical Justification*:
   - Read patterns: Lookups on these tables are executed exclusively on high-entropy unique tokens (`token_hash` or `idempotency_key`), which already possess dedicated unique B-Tree indexes.
   - Table volume: These tables have short TTLs and undergo frequent insert-delete churn. Indexing `user_id` would add index maintenance overhead on every token generation and cleanup cycle.

### D. Migration 0006 Architecture
Migration `0006_foreign_key_indexes.py` (`revises: 0005_event_closeout_and_archival`) cleanly creates the 8 high-value indexes in `upgrade()` and drops them in `downgrade()`. The migration lifecycle was verified via `alembic upgrade head` $\rightarrow$ `alembic downgrade -1` $\rightarrow$ `alembic upgrade head`, ensuring a single linear migration head.

---

## 4. Transaction Boundary Audit

### A. Architectural Inspection
We audited the interaction between FastAPI's dependency injection (`get_db()`) and service-layer transaction handling:
- `get_db()` implementation:
  ```python
  async def get_db() -> AsyncGenerator[AsyncSession, None]:
      async with AsyncSessionLocal() as session:
          try:
              yield session
              await session.commit()
          except Exception:
              await session.rollback()
              raise
          finally:
              await session.close()
  ```
- Service methods across all modules (`EventService`, `WorkflowService`, `SettlementService`, `FinancialService`, `CloseoutService`) follow a strict Unit of Work pattern:
  1. Retrieve entities and acquire row locks (`with_for_update()`).
  2. Validate state transitions, invariants, and authorization.
  3. Mutate domain state and generate audit logs and notification records.
  4. Execute a single `await self.db.commit()`.
  5. On any exception, execute `await self.db.rollback()` and re-raise.

### B. Hazard Analysis
1. **Partial Commits**: No service method executes intermediate commits during multi-step business transactions. In mutations involving multiple entities (e.g. approving a budget proposal and creating cash advance snapshots, or closing an event and finalizing financial settlements), all entities, audit logs, and notifications are staged in memory and persisted in a single commit.
2. **Premature Commits**: `get_db()` only executes `await session.commit()` after the endpoint handler returns. It never executes prior to or during service execution.
3. **Broken Rollback**: If an exception occurs at any point during service execution, the service catches it, calls `rollback()`, and re-raises. If an unhandled exception escapes to `get_db()`, `get_db()` catches it, executes `await session.rollback()`, and re-raises. No uncommitted or partial state is ever committed.
4. **Lock Release**: Row locks are held until `commit()` completes. Since the commit occurs at the conclusion of all mutations, locks are held for the exact duration required.
5. **Session Teardown**: In SQLAlchemy 2.0, calling `session.commit()` on a session where all changes have already been committed is a harmless no-op.

### C. Architectural Conclusion
The existing transaction boundary pattern is **robust, atomic, and safe** for CampusConnect's architecture. Blindly altering `get_db()` or removing auto-commit would destabilize endpoints that rely on standard generator semantics. No sweeping refactor is warranted or permitted under the scope freeze.

---

## 5. Security & Data Integrity Protections

- **RBAC & IDOR Boundaries**: Optimistic locking checks are executed strictly *after* role authorization and club ownership validation. Stale version submissions from unauthorized actors or cross-club attackers are rejected with HTTP 403 / 404 before reaching optimistic concurrency checks.
- **Workflow Integrity**: Proposals in non-draft states (`SUBMITTED`, `APPROVED`, etc.) are immutable to draft updates; attempts to update version locks on non-draft proposals are rejected with HTTP 400 WorkflowStateError.
