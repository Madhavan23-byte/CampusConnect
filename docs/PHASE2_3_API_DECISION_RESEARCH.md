# CAMPUSCONNECT — PHASE 2.3 FINANCIAL SETTLEMENT API ARCHITECTURE & DECISION RECORD

> **Document Type**: Research & Architectural Decision Record (Phase 2.3 REST API Layer)
> **Status**: APPROVED ARCHITECTURE BLUEPRINT (Pre-Implementation)
> **Target Branch**: `phase2-event-lifecycle`
> **Current Commit**: `518f5e3`
> **Baseline Database Migration**: `0004_phase2_3_settlement`
> **Test Baseline**: 371/371 Backend Tests Passing | 17/17 Frontend Tests Passing

---

## 1. Executive Summary

Phase 2.3 implements collegiate Financial Settlement, Cash Advances, and Actual Income. The database layer (Alembic migration `0004_phase2_3_settlement`) and the backend accounting core (`SettlementService`) have been implemented, cascade-hardened, and verified through 52 dedicated service tests (371 backend tests overall).

This document establishes the **authoritative REST API architecture** for Phase 2.3. It specifies:
1. **API Resource Model**: Strict event-nested resource hierarchy (`/events/{event_id}/...`) guaranteeing cross-club isolation and structural alignment with Phase 2.1 and Phase 2.2 endpoints.
2. **Segregation of Duties (SoD) & Role Boundaries**: Rigid role-based guards where Club Secretaries formulate and submit, Finance Officers audit and execute clearing, Principals possess exceptional reopening powers, and System Administrators are barred from all financial operations.
3. **Command-Oriented Endpoints**: Elimination of ambiguous, unsafe `PATCH` mutations on financial ledgers in favor of explicit command endpoints (`/prepare`, `/submit`, `/audit`, `/reopen`, `/payments`).
4. **Idempotency & Concurrency**: Pessimistic database-level row locking (`SELECT FOR UPDATE`), source fingerprint verification, and payload-level deduplication.
5. **Two-Decimal Fixed-Point Financial Precision**: Strict Pydantic `Decimal` serialization eliminating IEEE 754 floating-point errors.
6. **Frontend Integration**: Direct schema contracts tailored for `SettlementTab.tsx` in `EventDetailPage.tsx`.

---

## 2. Current Service Layer Analysis

`SettlementService` in `backend/app/services/settlement_service.py` is the single source of financial truth. The service exposes 19 public methods categorized across five functional domains:

### 2.1 Complete Public Service Method Inventory

| Service Method | Purpose | Authorized Actor | Preconditions | Return Entity | Domain Exceptions |
|---|---|---|---|---|---|
| `request_advance` | Request an operational cash advance prior to event delivery | `CLUB_SECRETARY` | Event must exist, belong to Secretary's club, and have no existing advance (`uq_cash_advances_event_id`). `0 < amount <= sanctioned_grant`. | `CashAdvance` | `NotFoundError`, `ForbiddenError`, `ConflictError`, `BusinessRuleError` |
| `approve_advance` | Approve advance request and establish disbursable ceiling | `FINANCE_OFFICER` | Advance must be in `REQUESTED` state. `0 <= amount_approved <= sanctioned_grant`. | `CashAdvance` | `NotFoundError`, `ForbiddenError`, `InvalidWorkflowTransitionError`, `BusinessRuleError` |
| `reject_advance` | Reject advance request | `FINANCE_OFFICER` | Advance must be in `REQUESTED` state. Rejection reason mandatory. | `CashAdvance` | `NotFoundError`, `ForbiddenError`, `InvalidWorkflowTransitionError`, `BadRequestError` |
| `disburse_advance` | Record institutional cash/transfer disbursal to student organizer | `FINANCE_OFFICER` | Advance must be `APPROVED`. `amount_disbursed == amount_approved` (full disbursement rule). Payment reference mandatory. | `CashAdvance` | `NotFoundError`, `ForbiddenError`, `InvalidWorkflowTransitionError`, `BusinessRuleError`, `BadRequestError` |
| `get_advances_for_event` | Retrieve advance requisition status | Club Secretary, Club Advisor, Finance, Dean, Principal | Event must exist and caller must satisfy event view authorization. | `CashAdvance \| None` | `NotFoundError`, `ForbiddenError` |
| `record_income` | Log external event revenue (sponsorships, stalls, tickets) | `CLUB_SECRETARY` | Event must be in `COMPLETED` status. `amount > 0`. Evidence document must exist, belong to event, and be of type `INCOME_EVIDENCE`. | `ActualIncome` | `NotFoundError`, `ForbiddenError`, `BusinessRuleError`, `BadRequestError` |
| `verify_income` | Finance Officer audit of logged income entry | `FINANCE_OFFICER` | Income entry must be in `RECORDED` status. | `ActualIncome` | `NotFoundError`, `ForbiddenError`, `InvalidWorkflowTransitionError` |
| `reject_income` | Reject logged income entry | `FINANCE_OFFICER` | Income entry must be in `RECORDED` status. Mandatory rejection reason. | `ActualIncome` | `NotFoundError`, `ForbiddenError`, `InvalidWorkflowTransitionError`, `BadRequestError` |
| `get_incomes_for_event` | List all recorded income entries for an event | Club Secretary, Club Advisor, Finance, Dean, Principal | Caller authorized to view event. | `list[ActualIncome]` | `NotFoundError`, `ForbiddenError` |
| `prepare_settlement` | Compute and freeze canonical settlement balance | `CLUB_SECRETARY` | Event must be `COMPLETED` and Post-Event Report `CERTIFIED`. All actual expenses must be resolved (`VERIFIED`, `PARTIALLY_VERIFIED`, `DISALLOWED`). All income resolved (`VERIFIED`, `REJECTED`). Computes SHA-256 fingerprint. | `FinancialSettlement` | `NotFoundError`, `ForbiddenError`, `BusinessRuleError` |
| `submit_settlement` | Submit draft or queried settlement to Finance for audit | `CLUB_SECRETARY` | Settlement must be `DRAFT` or `QUERIED`. Verifies live source fingerprint has not changed since preparation. | `FinancialSettlement` | `NotFoundError`, `ForbiddenError`, `InvalidWorkflowTransitionError`, `SettlementStaleDataError` |
| `audit_settlement` | Finance Officer audit review | `FINANCE_OFFICER` | Settlement must be `UNDER_AUDIT`. Action must be `APPROVE` or `QUERY`. On `APPROVE`, verifies source fingerprint, computes cumulative balance, branches to `SETTLED`, `PENDING_REIMBURSEMENT`, or `PENDING_REFUND`. | `FinancialSettlement` | `NotFoundError`, `ForbiddenError`, `InvalidWorkflowTransitionError`, `SettlementStaleDataError`, `BadRequestError` |
| `record_payment` | Record reimbursement disbursement or refund recovery | `FINANCE_OFFICER` | Settlement in `PENDING_REIMBURSEMENT` or `PENDING_REFUND`. Direction must match balance. Amount must not exceed remaining balance. Valid `SETTLEMENT_PAYMENT_PROOF` document required. Timeless cumulative balance clearing. | `SettlementPayment` | `NotFoundError`, `ForbiddenError`, `InvalidWorkflowTransitionError`, `BusinessRuleError`, `BadRequestError` |
| `reopen_settlement` | Reopen settled account for downward/upward correction | `FINANCE_OFFICER`, `PRINCIPAL` | Settlement must be `SETTLED`. Mandatory reopening reason. Takes immutable snapshot in `settlement_revisions`. Status -> `REOPENED`. | `SettlementRevision` | `NotFoundError`, `ForbiddenError`, `InvalidWorkflowTransitionError`, `BadRequestError` |
| `get_settlement` | Get settlement record by event UUID | Authorized viewer | Caller authorized to view event. | `FinancialSettlement \| None` | `NotFoundError`, `ForbiddenError` |
| `get_settlement_by_id` | Get settlement record by settlement UUID | Authorized viewer | Settlement exists and caller authorized. | `FinancialSettlement` | `NotFoundError`, `ForbiddenError` |
| `get_settlement_payments` | List historical payments for a settlement | Authorized viewer | Settlement exists and caller authorized. Returns payments sorted by creation date. | `list[SettlementPayment]` | `NotFoundError`, `ForbiddenError` |
| `get_settlement_revisions` | List historical revision snapshots | Authorized viewer | Settlement exists and caller authorized. Returns revisions sorted by revision number. | `list[SettlementRevision]` | `NotFoundError`, `ForbiddenError` |
| `get_closure_eligibility` | Evaluates whether event meets institutional financial closure | Authorized viewer | Event exists and caller authorized. Returns boolean status and blocker list. | `dict[str, Any]` | `NotFoundError`, `ForbiddenError` |

---

## 3. Existing CampusConnect API Conventions

Cross-inspection of `backend/app/api/v1/endpoints/` (`events.py`, `expenses.py`, `event_execution.py`, `clubs.py`, `workflows.py`) establishes the following architectural standards:

1. **Router Separation**: Each domain is housed in a dedicated module in `backend/app/api/v1/endpoints/`. All routers are aggregated in `backend/app/api/v1/api.py`.
2. **Dependency Injection**:
   - Database session: `db: Annotated[AsyncSession, Depends(get_db)]`
   - Authentication & User context: `current_user: Annotated[User, Depends(get_current_user)]`
   - HTTP Context: `request: Request` to extract `client.host` and `headers.get("user-agent")`.
3. **Role Guards**:
   - Single role: `Annotated[User, Depends(require_role(UserRole.CLUB_SECRETARY))]`
   - Multi-role: `Annotated[User, Depends(require_any_role(UserRole.FINANCE_OFFICER, UserRole.PRINCIPAL))]`
4. **Command vs. Mutation Semantics**:
   - Resource updates without state transitions: `PATCH /resource/{id}`
   - Explicit workflow/state transitions: `POST /resource/{id}/{action}` (e.g., `/submit`, `/verify`, `/partial-verify`, `/query`, `/disallow`, `/certify`).
5. **Path Parameter Identifiers**: All path entities are strictly validated as `uuid.UUID` parameters.
6. **HTTP Status Codes**:
   - Creation / Initialization: `201 CREATED`
   - Successful command / Retrieval: `200 OK`
   - Successful deletion: `204 NO CONTENT`
   - Business rule / Stale data violations: `422 UNPROCESSABLE ENTITY`
   - State transition conflicts: `409 CONFLICT`
   - Authorization failures: `401 UNAUTHORIZED` / `403 FORBIDDEN`
   - Resource not found: `404 NOT FOUND`

---

## 4. Institutional & External Research

Research into collegiate finance architectures, including public frameworks from UC Berkeley Student Organization Financial Guidelines, St. Olaf Student Activities Cash Advance Policy, and University of Toronto Student Accounting, yields three vital design principles:

1. `[SOURCE FACT]`: In collegiate financial systems, cash advances represent a personal liability charged to the recipient until officially liquidated through verified bills or direct cash deposit receipts.
2. `[SOURCE FACT]`: Settlement workflows require rigid Segregation of Duties: individuals requesting or spending institutional funds cannot approve advances, verify invoices, or execute settlements.
3. `[RESEARCH FINDING]`: Modern financial ERP and settlement APIs avoid generic HTTP `PATCH` endpoints for balance-shifting actions. Instead, they expose explicit "Command Actions" (e.g., `/settle`, `/reconcile`, `/liquidate`, `/reopen`) with mandatory audit payloads to prevent partial or unintended state updates.
4. `[ENGINEERING INFERENCE]`: A settlement endpoint should not force client applications to execute separate round trips to fetch payments and revision histories when viewing an event's financial health.
5. `[CAMPUSCONNECT DECISION]`: The API will provide comprehensive composite responses on `GET /events/{id}/settlement` containing the financial settlement balance, current status, cleared payments ledger, and revision history.

---

## 5. API Resource Model Decision

### Evaluated Alternatives

#### Option A: Top-Level Financial Resources (`/settlements/{id}`, `/advances/{id}`)
- *Pros*: Follows pure REST noun modeling.
- *Cons*: Breaks cross-club event isolation checks; requires clients to discover and store separate settlement UUIDs; diverges from Phase 2.1 and Phase 2.2 conventions.

#### Option B: Event-Nested Resources (`/events/{event_id}/...`)
- *Pros*:
  - Natural 1:0..1 mapping: Each event has at most one cash advance and one financial settlement.
  - Automatic event ownership and club isolation: Authorizes the caller against `events.club_id` immediately from the path parameter.
  - Matches frontend routing: In `frontend/src/pages/EventDetailPage.tsx`, the route is `/events/:id`. Nested endpoints map 1:1 to the tabs.
  - Complete parity with `expenses.py` (`/events/{id}/expenses`) and `event_execution.py` (`/events/{id}/start`).
- *Cons*: Slightly longer URI paths for sub-resource operations.

#### Option C: Hybrid
- *Pros*: Nested collection, top-level item lookup.
- *Cons*: Inconsistent authorization boundaries and redundant routing logic.

### Architectural Decision
`[CAMPUSCONNECT DECISION]`: **Adopt Option B: Event-Nested Resources**.
All Phase 2.3 routes will be anchored under `/api/v1/events/{event_id}/...`. Sub-item actions that require distinct item IDs (such as approving a specific advance or verifying a specific income item) will use nested item paths:
- `/api/v1/events/{event_id}/advances`
- `/api/v1/events/{event_id}/advances/{advance_id}/approve`
- `/api/v1/events/{event_id}/incomes`
- `/api/v1/events/{event_id}/incomes/{income_id}/verify`
- `/api/v1/events/{event_id}/settlement`
- `/api/v1/events/{event_id}/settlement/prepare`
- `/api/v1/events/{event_id}/settlement/submit`
- `/api/v1/events/{event_id}/settlement/audit`
- `/api/v1/events/{event_id}/settlement/payments`
- `/api/v1/events/{event_id}/settlement/reopen`
- `/api/v1/events/{event_id}/settlement/closure-eligibility`

---

## 6. Cash Advance API Design

`[IMPLEMENTATION FACT]`: Cash advances are 1:0..1 per event. An advance cannot exceed the sanctioned institutional grant (`sanctioned_grant`). The service mandates full disbursement (`amount_disbursed == amount_approved`).

### Endpoints Specification

#### 1. Request Cash Advance
- **Method / Path**: `POST /api/v1/events/{event_id}/advances`
- **Authorized Actor**: `CLUB_SECRETARY` (Active club member)
- **Request Body**:
  ```json
  {
    "amount_requested": "15000.00",
    "reason": "Advance booking deposit for audio-visual equipment and guest travel"
  }
  ```
- **Response**: `CashAdvanceResponse` (`201 CREATED`)
- **Errors**: `400` (Negative/zero amount, amount exceeds grant), `403` (Not club secretary, System Admin), `404` (Event not found), `409` (Advance already requested for this event).
- **Service Binding**: `SettlementService.request_advance(db, event_id, amount_requested, reason, actor, ip, ua)`

#### 2. Get Cash Advance Status
- **Method / Path**: `GET /api/v1/events/{event_id}/advances`
- **Authorized Actor**: Club Secretary, Club Advisor, Finance Officer, Union Advisor, Dean, Principal
- **Response**: `CashAdvanceResponse | null` (`200 OK`)
- **Service Binding**: `SettlementService.get_advances_for_event(db, event_id, actor)`

#### 3. Approve Cash Advance
- **Method / Path**: `POST /api/v1/events/{event_id}/advances/{advance_id}/approve`
- **Authorized Actor**: `FINANCE_OFFICER`
- **Request Body**:
  ```json
  {
    "amount_approved": "15000.00",
    "remarks": "Approved as per sanctioned budget grant"
  }
  ```
- **Response**: `CashAdvanceResponse` (`200 OK`)
- **State Transition**: `REQUESTED -> APPROVED`
- **Service Binding**: `SettlementService.approve_advance(db, advance_id, amount_approved, actor, remarks, ip, ua)`

#### 4. Reject Cash Advance
- **Method / Path**: `POST /api/v1/events/{event_id}/advances/{advance_id}/reject`
- **Authorized Actor**: `FINANCE_OFFICER`
- **Request Body**:
  ```json
  {
    "rejection_reason": "Vendor accepts direct college purchase orders; advance not justified"
  }
  ```
- **Response**: `CashAdvanceResponse` (`200 OK`)
- **State Transition**: `REQUESTED -> REJECTED`
- **Service Binding**: `SettlementService.reject_advance(db, advance_id, rejection_reason, actor, ip, ua)`

#### 5. Disburse Cash Advance
- **Method / Path**: `POST /api/v1/events/{event_id}/advances/{advance_id}/disburse`
- **Authorized Actor**: `FINANCE_OFFICER`
- **Request Body**:
  ```json
  {
    "amount_disbursed": "15000.00",
    "payment_reference": "BANK-NEFT-20260924-0012",
    "disbursement_date": "2026-09-24T10:30:00Z",
    "notes": "Transferred to Club Secretary student bank account"
  }
  ```
- **Response**: `CashAdvanceResponse` (`200 OK`)
- **State Transition**: `APPROVED -> DISBURSED`
- **Service Binding**: `SettlementService.disburse_advance(db, advance_id, amount_disbursed, payment_reference, disbursement_date, actor, notes, ip, ua)`

---

## 7. Actual Income API Design

`[IMPLEMENTATION FACT]`: Events can generate self-earned revenue (tickets, sponsorships, donations). Each income entry requires an authentic `INCOME_EVIDENCE` document uploaded for that specific event. Finance Officers audit and either verify or reject income.

### Endpoints Specification

#### 1. Upload Income Evidence Document
- **Method / Path**: `POST /api/v1/events/{event_id}/incomes/upload-evidence`
- **Authorized Actor**: `CLUB_SECRETARY`
- **Content-Type**: `multipart/form-data` (File: `file`)
- **Response**: `DocumentUploadResponse` (`201 CREATED`)
- **Details**: Validates MIME type, stores file via `DocumentService`, assigns `document_type = DocumentType.INCOME_EVIDENCE`, returns `document_id`.

#### 2. Record Actual Income Entry
- **Method / Path**: `POST /api/v1/events/{event_id}/incomes`
- **Authorized Actor**: `CLUB_SECRETARY`
- **Request Body**:
  ```json
  {
    "source_type": "SPONSORSHIP",
    "amount": "25000.00",
    "description": "Title sponsorship from Tech Corp",
    "payer_name": "Tech Corp Pvt Ltd",
    "received_date": "2026-09-20",
    "evidence_document_id": "7b2e95a0-2f9b-4e67-bb89-51d8d3e2a014",
    "reference_number": "TXN-SPON-9941"
  }
  ```
- **Response**: `ActualIncomeResponse` (`201 CREATED`)
- **Service Binding**: `SettlementService.record_income(db, event_id, source_type, amount, description, payer_name, received_date, evidence_document_id, actor, reference_number, ip, ua)`

#### 3. List Actual Income Entries
- **Method / Path**: `GET /api/v1/events/{event_id}/incomes`
- **Authorized Actor**: Authorized Event Viewers
- **Response**: `list[ActualIncomeResponse]` (`200 OK`)
- **Service Binding**: `SettlementService.get_incomes_for_event(db, event_id, actor)`

#### 4. Verify Income Entry
- **Method / Path**: `POST /api/v1/events/{event_id}/incomes/{income_id}/verify`
- **Authorized Actor**: `FINANCE_OFFICER`
- **Request Body**:
  ```json
  {
    "finance_remarks": "Bank statement credit entry verified"
  }
  ```
- **Response**: `ActualIncomeResponse` (`200 OK`)
- **State Transition**: `RECORDED -> VERIFIED`
- **Service Binding**: `SettlementService.verify_income(db, income_id, actor, finance_remarks, ip, ua)`

#### 5. Reject Income Entry
- **Method / Path**: `POST /api/v1/events/{event_id}/incomes/{income_id}/reject`
- **Authorized Actor**: `FINANCE_OFFICER`
- **Request Body**:
  ```json
  {
    "rejection_reason": "Deposit receipt illegible; amount not reflected in institutional bank ledger",
    "finance_remarks": "Please obtain certified bank stamp"
  }
  ```
- **Response**: `ActualIncomeResponse` (`200 OK`)
- **State Transition**: `RECORDED -> REJECTED`
- **Service Binding**: `SettlementService.reject_income(db, income_id, rejection_reason, actor, finance_remarks, ip, ua)`

---

## 8. Settlement Lifecycle & Audit API Design

`[IMPLEMENTATION FACT]`: Financial settlement calculations are deterministic and authoritative.
- Net Deficit: $	ext{NetDeficit} = \max(0, V - I_{	ext{actual}})$
- Entitled Institutional Payout: $P = \min(G_{	ext{sanctioned}}, 	ext{NetDeficit})$
- Authoritative Balance: $B_{	ext{revision}} = (P - A) - (R_{	ext{cleared}} - F_{	ext{cleared}})$
- Stale Data Protection: Evaluates deterministic SHA-256 fingerprint on `submit` and `audit(APPROVE)`.

### Why Generic PATCH is Strictly Prohibited
`[CAMPUSCONNECT DECISION]`: The API will **not** expose a `PATCH /events/{id}/settlement` endpoint. Financial settlements cannot permit partial attribute updates (e.g. updating `institutional_payout` without recalculating `net_deficit` and source fingerprints). Every state modification must occur through an audited command endpoint executing `SettlementService` logic inside a row-locked transaction.

### Endpoints Specification

#### 1. Prepare Settlement
- **Method / Path**: `POST /api/v1/events/{event_id}/settlement/prepare`
- **Authorized Actor**: `CLUB_SECRETARY`
- **Request Body**: None (Empty)
- **Response**: `FinancialSettlementResponse` (`200 OK` or `201 CREATED`)
- **Preconditions**: Event `COMPLETED`, Report `CERTIFIED`, all expenses and incomes resolved.
- **Service Binding**: `SettlementService.prepare_settlement(db, event_id, actor, ip, ua)`

#### 2. Get Settlement Status & Details
- **Method / Path**: `GET /api/v1/events/{event_id}/settlement`
- **Authorized Actor**: Authorized Event Viewers
- **Response**: `FinancialSettlementDetailResponse` (`200 OK`)
- **Details**: Returns settlement snapshot, current balance, embedded payment ledger, and revision history.
- **Service Binding**: `SettlementService.get_settlement(db, event_id, actor)`

#### 3. Submit Settlement for Audit
- **Method / Path**: `POST /api/v1/events/{event_id}/settlement/submit`
- **Authorized Actor**: `CLUB_SECRETARY`
- **Request Body**: None (Empty)
- **Response**: `FinancialSettlementResponse` (`200 OK`)
- **State Transition**: `DRAFT / QUERIED -> UNDER_AUDIT`
- **Error on Mutated Source**: `422 UNPROCESSABLE ENTITY` (`SettlementStaleDataError`) if source records changed after preparation.
- **Service Binding**: `SettlementService.submit_settlement(db, settlement_id, actor, ip, ua)`

#### 4. Audit Settlement (Approve or Query)
- **Method / Path**: `POST /api/v1/events/{event_id}/settlement/audit`
- **Authorized Actor**: `FINANCE_OFFICER`
- **Request Body**:
  ```json
  {
    "action": "APPROVE",
    "remarks": "All original bills and vouchers verified against bank clearing records"
  }
  ```
  *Or for Query:*
  ```json
  {
    "action": "QUERY",
    "query_reason": "Receipt #104 requires GST tax invoice instead of estimate slip",
    "remarks": "Resubmit with formal tax invoice"
  }
  ```
- **Response**: `FinancialSettlementResponse` (`200 OK`)
- **State Transition**:
  - `APPROVE` with $B = 0 \implies 	ext{SETTLED}$
  - `APPROVE` with $B > 0 \implies 	ext{PENDING\_REIMBURSEMENT}$
  - `APPROVE` with $B < 0 \implies 	ext{PENDING\_REFUND}$
  - `QUERY` $\implies 	ext{QUERIED}$
- **Service Binding**: `SettlementService.audit_settlement(db, settlement_id, action, actor, remarks, query_reason, ip, ua)`

#### 5. Reopen Settlement
- **Method / Path**: `POST /api/v1/events/{event_id}/settlement/reopen`
- **Authorized Actor**: `FINANCE_OFFICER` or `PRINCIPAL`
- **Request Body**:
  ```json
  {
    "reopening_reason": "Auditor identified post-settlement GST rebate adjustment"
  }
  ```
- **Response**: `SettlementRevisionResponse` (`200 OK`)
- **State Transition**: `SETTLED -> REOPENED`
- **Service Binding**: `SettlementService.reopen_settlement(db, settlement_id, reopening_reason, actor, ip, ua)`

---

## 9. Settlement Payment & Clearing API Design

`[IMPLEMENTATION FACT]`: Payments are physical, immutable institutional transfers.
- $B > 0$: Finance pays college money to club $\implies$ `REIMBURSEMENT_DISBURSEMENT`.
- $B < 0$: Club refunds overpaid money to college $\implies$ `ADVANCE_REFUND_RECEIPT`.
- Payment must strictly match direction. Overpayment is strictly prevented.
- Valid `SETTLEMENT_PAYMENT_PROOF` document mandatory.

### Endpoints Specification

#### 1. Upload Payment Proof Document
- **Method / Path**: `POST /api/v1/events/{event_id}/settlement/upload-proof`
- **Authorized Actor**: `FINANCE_OFFICER`
- **Content-Type**: `multipart/form-data` (File: `file`)
- **Response**: `DocumentUploadResponse` (`201 CREATED`)
- **Details**: Validates MIME type, stores file, sets `document_type = DocumentType.SETTLEMENT_PAYMENT_PROOF`, returns `document_id`.

#### 2. Record Settlement Payment
- **Method / Path**: `POST /api/v1/events/{event_id}/settlement/payments`
- **Authorized Actor**: `FINANCE_OFFICER`
- **Header**: `X-Idempotency-Key` (Optional/Recommended)
- **Request Body**:
  ```json
  {
    "payment_type": "REIMBURSEMENT_DISBURSEMENT",
    "amount": "4000.00",
    "payment_method": "BANK_TRANSFER_NEFT",
    "transaction_reference": "NEFT-SBI-20260924-88124",
    "transaction_date": "2026-09-24T14:15:00Z",
    "proof_document_id": "8a3d42f1-6c10-4f90-8b12-9c4d5e6f7a8b",
    "notes": "Supplementary reimbursement following revision 2"
  }
  ```
- **Response**: `SettlementPaymentResponse` (`201 CREATED`)
- **Clearing Behavior**: Service updates remaining due. If remaining due reaches ₹0.00, settlement automatically marks `SETTLED`.
- **Service Binding**: `SettlementService.record_payment(...)`

#### 3. List Settlement Payments
- **Method / Path**: `GET /api/v1/events/{event_id}/settlement/payments`
- **Authorized Actor**: Authorized Event Viewers
- **Response**: `list[SettlementPaymentResponse]` (`200 OK`)
- **Service Binding**: `SettlementService.get_settlement_payments(db, settlement_id, actor)`

#### 4. List Settlement Revision Snapshots
- **Method / Path**: `GET /api/v1/events/{event_id}/settlement/revisions`
- **Authorized Actor**: Authorized Event Viewers
- **Response**: `list[SettlementRevisionResponse]` (`200 OK`)
- **Service Binding**: `SettlementService.get_settlement_revisions(db, settlement_id, actor)`

---

## 10. Closure Eligibility API Design

`[IMPLEMENTATION FACT]`: Event closure evaluates six strict criteria:
1. Event status is `COMPLETED`.
2. Post-event report is `CERTIFIED`.
3. Financial settlement exists and is in `SETTLED` status.
4. Zero pending/draft/queried/submitted expenses.
5. Zero unverified/recorded income entries.
6. Zero outstanding balance: $	ext{NetCashTransferred} == P_{	ext{entitled}}$.

### Endpoint Specification
- **Method / Path**: `GET /api/v1/events/{event_id}/settlement/closure-eligibility`
- **Authorized Actor**: Authorized Event Viewers
- **Response**: `ClosureEligibilityResponse` (`200 OK`)
  ```json
  {
    "is_eligible": false,
    "blockers": [
      "Settlement has an outstanding refund balance of ₹4,000.00 due to the college."
    ],
    "settlement_status": "PENDING_REFUND",
    "net_cash_transferred": "10000.00",
    "institutional_payout_entitled": "6000.00",
    "unresolved_expense_count": 0,
    "unverified_income_count": 0
  }
  ```
- **Service Binding**: `SettlementService.get_closure_eligibility(db, event_id, actor)`

---

## 11. Pydantic Schema Design & Precision Handling

`[ENGINEERING INFERENCE]`: Financial APIs must serialize and deserialize money as exact fixed-point strings or `Decimal` objects. Floats must never be used.

### Schema Hierarchy (`backend/app/schemas/financial_settlement.py`)

```python
from decimal import Decimal
from datetime import datetime, date
import uuid
from pydantic import BaseModel, ConfigDict, Field
from app.models.enums import (
    ActualIncomeStatus,
    CashAdvanceStatus,
    IncomeSourceType,
    PaymentMethod,
    SettlementPaymentType,
    SettlementStatus,
    SettlementType,
)

# ---------------------------------------------------------------------------
# Cash Advance Schemas
# ---------------------------------------------------------------------------
class CashAdvanceRequestCreate(BaseModel):
    amount_requested: Decimal = Field(..., gt=Decimal("0.00"), decimal_places=2, max_digits=12)
    reason: str = Field(..., min_length=5, max_length=500)

class CashAdvanceApprove(BaseModel):
    amount_approved: Decimal = Field(..., ge=Decimal("0.00"), decimal_places=2, max_digits=12)
    remarks: str | None = Field(default=None, max_length=500)

class CashAdvanceReject(BaseModel):
    rejection_reason: str = Field(..., min_length=5, max_length=500)

class CashAdvanceDisburse(BaseModel):
    amount_disbursed: Decimal = Field(..., gt=Decimal("0.00"), decimal_places=2, max_digits=12)
    payment_reference: str = Field(..., min_length=2, max_length=100)
    disbursement_date: datetime | None = None
    notes: str | None = Field(default=None, max_length=500)

class CashAdvanceResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    requested_by: uuid.UUID
    amount_requested: Decimal
    amount_approved: Decimal
    amount_disbursed: Decimal
    status: CashAdvanceStatus
    reason: str
    rejection_reason: str | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    disbursed_at: datetime | None
    payment_reference: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

# ---------------------------------------------------------------------------
# Actual Income Schemas
# ---------------------------------------------------------------------------
class ActualIncomeCreate(BaseModel):
    source_type: IncomeSourceType
    amount: Decimal = Field(..., gt=Decimal("0.00"), decimal_places=2, max_digits=12)
    description: str = Field(..., min_length=3, max_length=500)
    payer_name: str = Field(..., min_length=2, max_length=100)
    received_date: date
    evidence_document_id: uuid.UUID
    reference_number: str | None = Field(default=None, max_length=100)

class ActualIncomeVerify(BaseModel):
    finance_remarks: str | None = Field(default=None, max_length=500)

class ActualIncomeReject(BaseModel):
    rejection_reason: str = Field(..., min_length=5, max_length=500)
    finance_remarks: str | None = Field(default=None, max_length=500)

class ActualIncomeResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    source_type: IncomeSourceType
    amount: Decimal
    description: str
    payer_name: str
    received_date: date
    evidence_document_id: uuid.UUID
    status: ActualIncomeStatus
    reference_number: str | None
    verified_by: uuid.UUID | None
    verified_at: datetime | None
    finance_remarks: str | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

# ---------------------------------------------------------------------------
# Settlement Schemas
# ---------------------------------------------------------------------------
class SettlementAuditRequest(BaseModel):
    action: str = Field(..., pattern="^(APPROVE|QUERY)$")
    remarks: str | None = Field(default=None, max_length=1000)
    query_reason: str | None = Field(default=None, max_length=1000)

class SettlementReopenRequest(BaseModel):
    reopening_reason: str = Field(..., min_length=10, max_length=1000)

class SettlementPaymentCreate(BaseModel):
    payment_type: SettlementPaymentType
    amount: Decimal = Field(..., gt=Decimal("0.00"), decimal_places=2, max_digits=12)
    payment_method: PaymentMethod
    transaction_reference: str = Field(..., min_length=3, max_length=100)
    transaction_date: datetime
    proof_document_id: uuid.UUID
    notes: str | None = Field(default=None, max_length=500)

class SettlementPaymentResponse(BaseModel):
    id: uuid.UUID
    settlement_id: uuid.UUID
    payment_type: SettlementPaymentType
    amount: Decimal
    payment_method: PaymentMethod
    transaction_reference: str
    transaction_date: datetime
    proof_document_id: uuid.UUID
    recorded_by: uuid.UUID
    notes: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class SettlementRevisionResponse(BaseModel):
    id: uuid.UUID
    settlement_id: uuid.UUID
    revision_number: int
    snapshot_data: dict
    reopened_by: uuid.UUID
    reopening_reason: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class FinancialSettlementResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    approved_version_id: uuid.UUID
    sanctioned_grant: Decimal
    sanctioned_expenditure: Decimal
    expected_income: Decimal
    total_claimed_expenditure: Decimal
    total_verified_expenditure: Decimal
    total_disallowed_expenditure: Decimal
    total_verified_income: Decimal
    net_deficit: Decimal
    institutional_payout: Decimal
    cash_advance_disbursed: Decimal
    settlement_balance: Decimal
    reimbursement_due: Decimal
    refund_due: Decimal
    settlement_type: SettlementType
    status: SettlementStatus
    prepared_by: uuid.UUID
    submitted_at: datetime | None
    audited_by: uuid.UUID | None
    audited_at: datetime | None
    finance_remarks: str | None
    query_reason: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class FinancialSettlementDetailResponse(FinancialSettlementResponse):
    payments: list[SettlementPaymentResponse] = []
    revisions: list[SettlementRevisionResponse] = []

class ClosureEligibilityResponse(BaseModel):
    is_eligible: bool
    blockers: list[str] = []
    settlement_status: SettlementStatus | None = None
    net_cash_transferred: Decimal = Decimal("0.00")
    institutional_payout_entitled: Decimal = Decimal("0.00")
    unresolved_expense_count: int = 0
    unverified_income_count: int = 0
```

---

## 12. Error Contract & Domain Mapping

`[CAMPUSCONNECT DECISION]`: The API leverages the global FastAPI exception handlers in `app/main.py`. The table below defines how domain exceptions map to client HTTP responses:

| Domain Exception | HTTP Status | Error Response Payload Format | Triggering Condition in Phase 2.3 |
|---|---|---|---|
| `UnauthorizedError` | `401 UNAUTHORIZED` | `{"detail": "Authentication required."}` | Missing, expired, or invalid JWT access token |
| `InsufficientRoleError` | `403 FORBIDDEN` | `{"detail": "Insufficient role permissions."}` | Role not in authorized set (e.g. Secretary attempting Audit) |
| `ResourceOwnershipError` | `403 FORBIDDEN` | `{"detail": "Access denied: Not your club."}` | Calling Secretary does not belong to event's club |
| `ForbiddenError` | `403 FORBIDDEN` | `{"detail": "System Administrators cannot..."}` | System Admin attempting financial operation |
| `NotFoundError` | `404 NOT FOUND` | `{"detail": "Event/Settlement not found."}` | UUID not matching any existing database record |
| `ConflictError` | `409 CONFLICT` | `{"detail": "Advance already exists for event."}` | Unique constraint violation (`uq_cash_advances_event_id`) |
| `InvalidWorkflowTransitionError` | `409 CONFLICT` | `{"detail": "Cannot audit settlement in DRAFT."}` | State transition violation in advance/settlement |
| `SettlementStaleDataError` | `422 UNPROCESSABLE`| `{"detail": "Source data mutated since prep."}` | SHA-256 source fingerprint mismatch |
| `BusinessRuleError` | `422 UNPROCESSABLE`| `{"detail": "Advance exceeds sanctioned grant."}`| Validation invariant or overpayment prevention breach |
| `BadRequestError` | `400 BAD REQUEST` | `{"detail": "Rejection reason is mandatory."}` | Missing mandatory rejection/query reason or empty body |

---

## 13. Idempotency & Transactional Concurrency

`[IMPLEMENTATION FACT]`:
1. **Pessimistic Locking**: `SettlementService` acquires database row locks using `SELECT FOR UPDATE` on:
   - `events` table (in `prepare_settlement`)
   - `cash_advances` table (in `approve_advance`, `disburse_advance`)
   - `financial_settlements` table (in `submit_settlement`, `audit_settlement`, `record_payment`, `reopen_settlement`).
2. **API Layering Role**: The API router delegates transaction management directly to the service layer within the `AsyncSessionLocal` dependency context. The API layer does **not** duplicate locking logic.
3. **HTTP Deduplication**:
   - `X-Idempotency-Key` header: For payment recording and advance requests, if a client includes `X-Idempotency-Key`, the endpoint checks `idempotency_records` table to safely return previous responses on network retries without double-execution.
   - Database Natural Uniqueness: `settlement_payments.transaction_reference` is uniquely indexed; duplicate submission of the same bank reference raises `409 Conflict`.

---

## 14. Audit Logging & Notification Trigger Analysis

`[IMPLEMENTATION FACT]`: The API layer does **not** need to manually call `AuditLog` or `NotificationService`. `SettlementService` handles 100% of audit and notification side-effects atomically inside the database transaction:

| API Command | Underlying Service Method | AuditAction Logged | NotificationType Triggered |
|---|---|---|---|
| `POST /advances` | `request_advance` | `ADVANCE_REQUESTED` | Dispatches to Finance Officers |
| `POST /advances/{id}/approve` | `approve_advance` | `ADVANCE_APPROVED` | `ADVANCE_APPROVED` (To Secretary) |
| `POST /advances/{id}/reject` | `reject_advance` | `ADVANCE_REJECTED` | `ADVANCE_REJECTED` (To Secretary) |
| `POST /advances/{id}/disburse`| `disburse_advance` | `ADVANCE_DISBURSED` | `ADVANCE_DISBURSED` (To Secretary) |
| `POST /incomes` | `record_income` | `INCOME_RECORDED` | Dispatches to Finance Officers |
| `POST /incomes/{id}/verify` | `verify_income` | `INCOME_VERIFIED` | `INCOME_VERIFIED` (To Secretary) |
| `POST /incomes/{id}/reject` | `reject_income` | `INCOME_REJECTED` | `INCOME_REJECTED` (To Secretary) |
| `POST /settlement/prepare` | `prepare_settlement` | `SETTLEMENT_PREPARED` | (None - Draft state) |
| `POST /settlement/submit` | `submit_settlement` | `SETTLEMENT_SUBMITTED` | Dispatches to Finance Officers |
| `POST /settlement/audit (QUERY)`| `audit_settlement` | `SETTLEMENT_QUERIED` | `SETTLEMENT_QUERIED` (To Secretary) |
| `POST /settlement/audit (APPROVE)`| `audit_settlement`| `SETTLEMENT_APPROVED` | `SETTLEMENT_SETTLED` / `REIMBURSEMENT_PENDING` / `REFUND_PENDING` |
| `POST /settlement/payments` | `record_payment` | `SETTLEMENT_PAYMENT_RECORDED` | `SETTLEMENT_SETTLED` (upon final balance clearance) |
| `POST /settlement/reopen` | `reopen_settlement` | `SETTLEMENT_REOPENED` | `SETTLEMENT_REOPENED` (To Secretary & Finance) |

---

## 15. Frontend Data Requirements (`SettlementTab.tsx`)

`[CAMPUSCONNECT DECISION]`: The React frontend component `SettlementTab.tsx` will be integrated into `EventDetailPage.tsx` alongside Overview, Venue, Budget, Documents, Resources, Execution, and Expenses tabs.

### UI Sections & Corresponding API Endpoints:
1. **Settlement Header & Status Card**: `GET /api/v1/events/{id}/settlement`
   - Displays Grant Sanctioned, Total Verified Expenses, Actual Income, Net Deficit, Payout Entitled, Cash Advance, Balance Due, and Settlement Badge (`DRAFT`, `UNDER_AUDIT`, `QUERIED`, `PENDING_REIMBURSEMENT`, `PENDING_REFUND`, `SETTLED`, `REOPENED`).
2. **Cash Advance Section**: `GET /api/v1/events/{id}/advances`
   - Secretary View: "Request Advance" modal (`POST /advances`).
   - Finance View: "Approve" (`POST /approve`), "Reject" (`POST /reject`), "Disburse" (`POST /disburse`) action modals.
3. **Actual Income Ledger**: `GET /api/v1/events/{id}/incomes`
   - Secretary View: "Upload Evidence" + "Record Income" modal (`POST /incomes`).
   - Finance View: "Verify" / "Reject" action buttons.
4. **Settlement Preparation & Audit Bar**:
   - Secretary View: "Compile Settlement" button (`POST /settlement/prepare`), "Submit to Finance" button (`POST /settlement/submit`).
   - Finance View: "Audit Approval" / "Query Settlement" action buttons (`POST /settlement/audit`).
5. **Payment Clearing Ledger**: `GET /api/v1/events/{id}/settlement/payments`
   - Finance View: "Record Payment" button (`POST /settlement/payments`) with proof upload.
   - Displays transaction references, payment types, clearing dates, and downloadable proof links.
6. **Revision & Audit History**: `GET /api/v1/events/{id}/settlement/revisions`
   - Displays timeline of previous revisions, snapshot diffs, and reopening reasons.
   - Finance / Principal View: "Reopen Settlement" modal (`POST /settlement/reopen`).
7. **Closure Readiness Card**: `GET /api/v1/events/{id}/settlement/closure-eligibility`
   - Displays readiness badge and itemized checklist of institutional blockers.

---

## 16. Proposed Endpoint Matrix (Final Endpoint Specification)

`[CAMPUSCONNECT DECISION]`: The Phase 2.3 API layer consists of exactly **20 REST endpoints**:

| # | HTTP Method | Path Pattern | Purpose | Role Authorization |
|---|---|---|---|---|
| 1 | `POST` | `/api/v1/events/{event_id}/advances` | Requisition cash advance | `CLUB_SECRETARY` |
| 2 | `GET` | `/api/v1/events/{event_id}/advances` | View advance requisition | Authorized Viewer |
| 3 | `POST` | `/api/v1/events/{event_id}/advances/{advance_id}/approve` | Approve advance | `FINANCE_OFFICER` |
| 4 | `POST` | `/api/v1/events/{event_id}/advances/{advance_id}/reject` | Reject advance | `FINANCE_OFFICER` |
| 5 | `POST` | `/api/v1/events/{event_id}/advances/{advance_id}/disburse`| Disburse advance | `FINANCE_OFFICER` |
| 6 | `POST` | `/api/v1/events/{event_id}/incomes/upload-evidence` | Upload income receipt/proof | `CLUB_SECRETARY` |
| 7 | `POST` | `/api/v1/events/{event_id}/incomes` | Record external income | `CLUB_SECRETARY` |
| 8 | `GET` | `/api/v1/events/{event_id}/incomes` | List event income entries | Authorized Viewer |
| 9 | `POST` | `/api/v1/events/{event_id}/incomes/{income_id}/verify` | Verify income entry | `FINANCE_OFFICER` |
| 10 | `POST` | `/api/v1/events/{event_id}/incomes/{income_id}/reject` | Reject income entry | `FINANCE_OFFICER` |
| 11 | `POST` | `/api/v1/events/{event_id}/settlement/prepare` | Compile draft settlement | `CLUB_SECRETARY` |
| 12 | `GET` | `/api/v1/events/{event_id}/settlement` | Get settlement detail & ledger | Authorized Viewer |
| 13 | `POST` | `/api/v1/events/{event_id}/settlement/submit` | Submit settlement to Finance | `CLUB_SECRETARY` |
| 14 | `POST` | `/api/v1/events/{event_id}/settlement/audit` | Approve or query settlement | `FINANCE_OFFICER` |
| 15 | `POST` | `/api/v1/events/{event_id}/settlement/reopen` | Reopen settled settlement | `FINANCE_OFFICER`, `PRINCIPAL` |
| 16 | `POST` | `/api/v1/events/{event_id}/settlement/upload-proof` | Upload payment proof voucher | `FINANCE_OFFICER` |
| 17 | `POST` | `/api/v1/events/{event_id}/settlement/payments` | Record disbursement / refund | `FINANCE_OFFICER` |
| 18 | `GET` | `/api/v1/events/{event_id}/settlement/payments` | List historical payments | Authorized Viewer |
| 19 | `GET` | `/api/v1/events/{event_id}/settlement/revisions` | List revision audit snapshots | Authorized Viewer |
| 20 | `GET` | `/api/v1/events/{event_id}/settlement/closure-eligibility` | Check closure readiness | Authorized Viewer |

---

## 17. Security Threat Model & Mitigations

| Threat Description | Attack Vector | Architectural Mitigation in API Design |
|---|---|---|
| **IDOR / Cross-Club Theft** | Attacker calls `/events/{victim_club_id}/settlement/prepare` | Dependency injection validates caller is active Secretary of the specific club owning `event_id`. Non-members receive `403 FORBIDDEN`. |
| **System Admin Financial Bypass** | Administrator calls `/settlement/audit` or `/payments` | Service layer explicitly checks `actor.role == UserRole.SYSTEM_ADMIN` and raises `ForbiddenError` (HTTP 403). System Admin has zero financial write authority. |
| **Secretary Self-Auditing** | Secretary approves own cash advance or audits settlement | Endpoint enforces `require_role(UserRole.FINANCE_OFFICER)`. Secretary accounts fail role dependency check with HTTP 403. |
| **Silent Stale-Data Approval** | Invoice bills modified while Finance Officer has audit screen open | Service computes deterministic record-level SHA-256 source fingerprint. `audit_settlement` raises `422 SettlementStaleDataError`. Recalculation is strictly rejected until re-prepared. |
| **Duplicate Disbursements** | Concurrent payment requests on slow network | `SELECT FOR UPDATE` on settlement row locks the settlement; second request evaluates updated cumulative balance and raises `422 BusinessRuleError` (Overpayment). |
| **Float Precision Theft** | Salami slicing or rounding exploitation in financial math | All amounts deserialized via Pydantic `Decimal` with 2 decimal places. Zero float conversion in API or Service. |
| **Forged Payment Evidence** | Attacker passes UUID of document from another event | `DocumentService` and `SettlementService` enforce `Document.event_id == event.id` and check document type. Foreign document UUID raises `422 BusinessRuleError`. |
| **Unauthorized Reopening** | Secretary or unauthorized reviewer reopens settled account | Endpoint enforces `require_any_role(UserRole.FINANCE_OFFICER, UserRole.PRINCIPAL)`. Mandatory reopening reason enforced. |

---

## 18. API Test Strategy & Test Matrix

An integration test suite `backend/tests/api/test_settlement.py` will be created with minimum 25 integration tests:

| Test Case Identifier | Actor Role | Method / Endpoint | Expected Success Status | Expected Error Scenarios Tested |
|---|---|---|---|---|
| `test_advance_request_secretary` | `CLUB_SECRETARY` | `POST /advances` | `201 CREATED` | `401` Unauthenticated, `403` Wrong Club, `409` Duplicate Advance |
| `test_advance_request_exceeds_grant` | `CLUB_SECRETARY` | `POST /advances` | `422 UNPROCESSABLE` | Amount > Sanctioned Grant |
| `test_advance_admin_blocked` | `SYSTEM_ADMIN` | `POST /advances` | `403 FORBIDDEN` | Admin barred from financial request |
| `test_advance_approve_and_disburse` | `FINANCE_OFFICER` | `POST /approve`, `POST /disburse` | `200 OK` | `403` Secretary cannot approve, `409` State violation |
| `test_income_record_and_verify` | `CLUB_SECRETARY`, `FINANCE_OFFICER` | `POST /incomes`, `POST /verify` | `201 CREATED`, `200 OK` | `422` Missing evidence, `403` Self-verify rejected |
| `test_settlement_prepare_incomplete_event`| `CLUB_SECRETARY`| `POST /settlement/prepare`| `422 UNPROCESSABLE` | Event not completed or unverified bills exist |
| `test_settlement_prepare_success` | `CLUB_SECRETARY` | `POST /settlement/prepare` | `200 OK` | Valid financial snapshots and fingerprint |
| `test_settlement_stale_data_rejection` | `CLUB_SECRETARY` | `POST /settlement/submit` | `422 UNPROCESSABLE` | Bill modified after preparation |
| `test_settlement_audit_query_flow` | `FINANCE_OFFICER` | `POST /settlement/audit` | `200 OK` | Query requires mandatory reason |
| `test_settlement_audit_approve_reimbursement`| `FINANCE_OFFICER`| `POST /settlement/audit` | `200 OK` | Transitions to `PENDING_REIMBURSEMENT` |
| `test_settlement_audit_approve_refund` | `FINANCE_OFFICER` | `POST /settlement/audit` | `200 OK` | Advance > Expenses transitions to `PENDING_REFUND` |
| `test_payment_wrong_direction_rejected`| `FINANCE_OFFICER` | `POST /settlement/payments`| `422 UNPROCESSABLE` | Refund receipt submitted for reimbursement |
| `test_payment_overpayment_rejected` | `FINANCE_OFFICER` | `POST /settlement/payments`| `422 UNPROCESSABLE` | Payment amount > remaining balance |
| `test_payment_clearing_settles_account`| `FINANCE_OFFICER` | `POST /settlement/payments`| `201 CREATED` | Auto-transitions to `SETTLED` on zero balance |
| `test_reopen_settled_creates_revision` | `FINANCE_OFFICER` | `POST /settlement/reopen` | `200 OK` | Revision snapshot captured, state -> `REOPENED` |
| `test_reopen_principal_allowed` | `PRINCIPAL` | `POST /settlement/reopen` | `200 OK` | Principal reopening authorized |
| `test_reopen_secretary_forbidden` | `CLUB_SECRETARY` | `POST /settlement/reopen` | `403 FORBIDDEN` | Secretary cannot reopen settled account |
| `test_closure_eligibility_endpoint` | Authorized User | `GET /closure-eligibility` | `200 OK` | Identifies blockers or verifies readiness |

---

## 19. Open Institutional Decisions & Boundaries

The following two institutional policy questions are explicitly isolated from software code:
1. `[OPEN QUESTION]`: **Default Recovery Enforcement Mechanism**: If a student club has an unliquidated cash advance or an outstanding refund debt following downward revision, what is the institutional enforcement mechanism? (e.g., student advisor payroll deduction vs club budget freezing vs graduation clearance withholding).
   *Current Software Boundary*: CampusConnect marks the settlement `PENDING_REFUND` and blocks event closure. No automatic disciplinary action is executed.
2. `[OPEN QUESTION]`: **Surplus Revenue Ownership**: If an event generates surplus income ($I_{	ext{actual}} > V$), does the college credit the surplus to the club's reserve account or sweep it to central overhead?
   *Current Software Boundary*: CampusConnect offsets event expenses with income ($P = \min(G, \max(0, V - I))$). Any net excess income is reported in the ledger but is never automatically redistributed.

---

## 20. Implementation Order (For Next Phase)

When authorized to begin implementation, work should proceed in the following strict dependency sequence:
1. **Pydantic Schemas**: Create `backend/app/schemas/financial_settlement.py`.
2. **REST Endpoints**: Create `backend/app/api/v1/endpoints/settlement.py` implementing all 20 endpoints.
3. **Router Registration**: Register the router in `backend/app/api/v1/api.py`.
4. **API Integration Tests**: Implement `backend/tests/api/test_settlement.py` (25+ tests).
5. **Full Regression Verification**: Verify all 371+ backend tests pass.
6. **Frontend Integration**: Implement `SettlementTab.tsx` inside `frontend/src/components/settlement/`.
