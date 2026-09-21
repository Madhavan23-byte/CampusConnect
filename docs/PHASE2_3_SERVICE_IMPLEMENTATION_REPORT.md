# CampusConnect — Phase 2.3 Financial Settlement Service Implementation Report

> **Component**: `SettlementService` (Authoritative Accounting Engine, Cash Advance, Actual Income, Settlement Lifecycle, Payment Clearance, Reopening & Closure Eligibility)  
> **Repository Baseline**: Checkpoint `b05eddd` (Branch `phase2-event-lifecycle`)  
> **Database State**: Migration `0004_phase2_3_settlement` applied at `head`  
> **Service Layer File**: `backend/app/services/settlement_service.py`  
> **Test Suite**: `backend/tests/services/test_settlement_service.py`  
> **Status**: Service Layer Fully Implemented and Verified (356/356 backend tests passing; Ruff clean; 0 git commits/pushes)

---

## 1. Implementation Scope

Phase 2.3 establishes the authoritative financial reconciliation layer between the verified vendor expense ledger (`ActualExpense`) and eventual institutional event closure.

This implementation covers exclusively the **backend service and business logic layer**:
1. Authoritative Accounting Engine (`Decimal`-only arithmetic and server-side calculation).
2. Cash Advance Requisition, Approval, and Full Disbursement tracking (`CashAdvance`).
3. Actual Event Revenue Ledger and Evidence Verification (`ActualIncome`).
4. Financial Settlement Preparation, Ledger Completeness Invariant Gates, and Locking (`FinancialSettlement`).
5. Live Source Stale-Data Protection Engine (`SettlementStaleDataError`).
6. Finance Officer Audit and Query Workflow (`UNDER_AUDIT`, `QUERIED`, `APPROVED`).
7. Settlement Clearing Payments and Overpayment Guard (`SettlementPayment`).
8. Controlled Settlement Reopening with Immutable Revision Snapshots (`SettlementRevision`).
9. Read-Only Institutional Closure Eligibility Evaluation (`get_closure_eligibility`).

*Exclusions (per strict project instructions)*:
- No REST API endpoints or routers created.
- No Pydantic API schemas created.
- No frontend components or API client calls modified.
- `EventStatus` remains `COMPLETED` (`CLOSED` status was NOT added).
- No git commits or pushes performed.

---

## 2. Existing Architecture Reused

The `SettlementService` integrates directly with established CampusConnect core patterns:
- **Async SQLAlchemy ORM**: `AsyncSession` with explicit transactions, `selectinload` for eager fetching, and `with_for_update()` row-level pessimistic locking.
- **Cascade Hardening**: Reuses the non-cascading, restricted FK architecture established in Phase 2.3 schema hardening (`ondelete="RESTRICT"`).
- **Domain Exceptions**: Subclasses `BusinessRuleError`, `WorkflowStateError`, `ConflictError`, `ForbiddenError`, and `NotFoundError` from `app.core.exceptions`.
- **Audit System**: Participates in the active transaction by appending `AuditLog` records with prior/new state JSON dictionaries.
- **Notification System**: Dispatches transactional in-app notifications via `NotificationService.create_notification`.
- **RBAC & SOD**: Strictly enforces `UserRole` (`CLUB_SECRETARY`, `FINANCE_OFFICER`, `PRINCIPAL`, `SYSTEM_ADMIN`) and club membership (`ClubMemberRole.SECRETARY`) without introducing secondary permission mechanisms.

---

## 3. Authoritative Accounting Engine

All monetary calculations use Python `Decimal` exclusively. Floating-point arithmetic and int-based cent conversions are strictly prohibited.

### 3.1 Locked Formulas
Given:
- $G$: Sanctioned Institutional Grant (immutable snapshot from approved `EventRequestVersion`)
- $V$: Total Verified Expenditure
- $I_{\text{actual}}$: Total Verified Actual Income
- $A$: Actually Disbursed Cash Advance

$$\begin{aligned}
V &= \sum_{\text{VERIFIED}} \text{verified\_amount} + \sum_{\text{PARTIALLY\_VERIFIED}} \text{verified\_amount} + \sum_{\text{DISALLOWED}} 0.00 \\
I_{\text{actual}} &= \sum_{\text{VERIFIED}} \text{amount} \quad (\text{RECORDED and REJECTED contribute 0.00}) \\
\text{NetDeficit} &= \max(0.00, V - I_{\text{actual}}) \\
P &= \min(G, \text{NetDeficit}) \quad (\text{Institutional payout cannot exceed sanctioned grant}) \\
B &= P - A \quad (\text{Settlement balance})
\end{aligned}$$

### 3.2 Directional Interpretation
- **$B > 0$ (`REIMBURSEMENT_DUE`)**: College owes money to club.
  $$\text{reimbursement\_due} = B, \quad \text{refund\_due} = 0.00$$
- **$B < 0$ (`REFUND_DUE`)**: Club owes unspent cash advance back to college.
  $$\text{reimbursement\_due} = 0.00, \quad \text{refund\_due} = |B|$$
- **$B = 0$ (`BALANCED`)**: Zero net balance.
  $$\text{reimbursement\_due} = 0.00, \quad \text{refund\_due} = 0.00$$

### 3.3 Verified Canonical Cases
- **Case 1**: $G = 30000, V = 40000, I = 0, A = 20000 \implies P = 30000, B = 10000 \implies \text{REIMBURSEMENT\_DUE} = 10000$.
- **Case 2**: $G = 30000, V = 20000, I = 0, A = 25000 \implies P = 20000, B = -5000 \implies \text{REFUND\_DUE} = 5000$.
- **Case 3**: $G = 30000, V = 20000, I = 5000, A = 15000 \implies P = 15000, B = 0 \implies \text{BALANCED}$.
- **Case 4**: Claimed = 10000, Verified = 6000 $\implies V$ contribution = 6000 (NOT 10000), Disallowed = 4000.

---

## 4. Cash Advance Lifecycle

### 4.1 State Machine
```
REQUESTED (by Secretary)
   ├── APPROVED (by Finance Officer: 0 < amount_approved <= G)
   │      └── DISBURSED (by Finance Officer: amount_disbursed == amount_approved)
   └── REJECTED (by Finance Officer: mandatory rejection_reason)
```

### 4.2 Invariants Enforced
1. **Single Advance per Event**: `CashAdvance.event_id` is unique (`1:0..1`).
2. **Sanctioned Ceiling**: `amount_approved <= sanctioned_grant`.
3. **No Partial Disbursement**: The current state machine does not have `PARTIALLY_DISBURSED`. Therefore, `amount_disbursed == amount_approved` is strictly enforced.
4. **Terminal Protection**: Once `DISBURSED`, an advance cannot be mutated or cancelled.

---

## 5. Actual Income Lifecycle

### 5.1 State Machine
```
RECORDED (by Secretary with DocumentType.INCOME_EVIDENCE)
   ├── VERIFIED (by Finance Officer: contributes to I_actual)
   └── REJECTED (by Finance Officer: mandatory reason, excluded from I_actual)
```

### 5.2 Invariants Enforced
1. **Mandatory Evidence Document**: Must be active, of type `INCOME_EVIDENCE`, and strictly belong to the event (`doc.event_id == event.id`). Cross-event reuse triggers `BadRequestError`.
2. **Segregation of Duties**: The Secretary who recorded the income cannot verify or reject it. System Admin is strictly barred from verifying.
3. **Unresolved Gate**: Settlements cannot be compiled while any income entry remains in `RECORDED` status.

---

## 6. Settlement Preparation & Validation Gates

Preparation (`prepare_settlement`) executes within an explicit transaction with `SELECT ... FOR UPDATE` row locking on the `Event`:
1. **Event State Gate**: `Event.status == EventStatus.COMPLETED`.
2. **Delivery Certification Gate**: `PostEventReport.status == PostEventReportStatus.CERTIFIED`.
3. **Ledger Completeness Gate**:
   - Zero `DRAFT`, `SUBMITTED`, or `QUERIED` expenses. Every expense must be `VERIFIED`, `PARTIALLY_VERIFIED`, or `DISALLOWED`.
   - Zero `RECORDED` income entries. Every income entry must be `VERIFIED` or `REJECTED`.
4. **Advance Gate**: Advance must be resolved (`DISBURSED`, `REJECTED`, or non-existent). Pending advances block settlement.
5. **Snapshot Immutability**: Extracts and freezes `sanctioned_grant`, `sanctioned_expenditure`, and `expected_income` from `EventRequestVersion.snapshot`.
6. **Uniqueness Safety**: `financial_settlements.event_id` database uniqueness is caught and translated to a domain `ConflictError`.

---

## 7. Stale-Data Protection Engine

To eliminate the vulnerability where underlying financial records are altered after a settlement is prepared:
1. `_verify_live_source_consistency`:
   - Queries live database rows for current verified expenses, verified income, disbursed advance, and sanctioned grant.
   - Compares live totals against the snapshotted values in `FinancialSettlement`.
2. **Enforcement Points**:
   - `submit_settlement`: Rejects submission with `SettlementStaleDataError` if source data mutated.
   - `audit_settlement`: Rejects Finance approval/query with `SettlementStaleDataError` if source data mutated.
3. **Remediation**: The preparer must call `prepare_settlement` again to recompile the draft with updated figures.

---

## 8. Finance Audit Workflow

### 8.1 State Transitions
```
UNDER_AUDIT
   ├── QUERY (requires query_reason) ──> QUERIED ──> (Secretary amends & resubmits) ──> UNDER_AUDIT
   └── APPROVE
         ├── If B == 0: ──> SETTLED (direct terminal settlement)
         ├── If B > 0:  ──> PENDING_REIMBURSEMENT
         └── If B < 0:  ──> PENDING_REFUND
```

### 8.2 Authority & Constraints
- Only active `FINANCE_OFFICER` can audit.
- `SYSTEM_ADMIN` is explicitly barred (`ForbiddenError`).
- No arbitrary thresholds (e.g. ₹50,000) are hard-coded.

---

## 9. Payment Lifecycle & Clearance

### 9.1 Directional Rules
- `PENDING_REIMBURSEMENT` allows ONLY `SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT`.
- `PENDING_REFUND` allows ONLY `SettlementPaymentType.ADVANCE_REFUND_RECEIPT`.
- `BALANCED` settlements reject payment attempts (`BusinessRuleError`). Zero-value fake payments are never created.

### 9.2 Overpayment & Clearance
- Calculates remaining balance due: $\text{remaining} = \text{target} - \sum \text{cleared payments}$.
- Rejects payments where $\text{amount} > \text{remaining}$ (`BusinessRuleError`).
- When $\sum \text{cleared} \ge \text{target}$, settlement status automatically transitions to `SETTLED`.

---

## 10. Controlled Settlement Reopening

### 10.1 Workflow
- Permitted actors: `FINANCE_OFFICER` or `PRINCIPAL`.
- Current status must be `SETTLED`.
- Reopening requires mandatory non-empty `reopening_reason`.
- Copies full prior settlement state (all calculation fields and serialized payments) into `SettlementRevision`.
- Increments `revision_number` sequentially.
- Transitions settlement status to `REOPENED`.

### 10.2 Event Lifecycle Safety
- **Event status remains `COMPLETED`**. It is NOT reverted to `SCHEDULED` or `IN_PROGRESS`.
- Historical revisions and previous payments are permanently preserved in append-only tables.

---

## 11. Read-Only Closure Eligibility

`get_closure_eligibility(event_id, actor)` evaluates the canonical institutional preconditions without mutating any database state:

| Blocker Code | Precondition Checked |
|---|---|
| `EVENT_NOT_COMPLETED` | `event.status == EventStatus.COMPLETED` |
| `POST_EVENT_REPORT_NOT_CERTIFIED` | `PostEventReport.status == PostEventReportStatus.CERTIFIED` |
| `UNRESOLVED_EXPENSES` | Zero `ActualExpense` in `DRAFT`, `SUBMITTED`, `QUERIED` |
| `UNVERIFIED_INCOME` | Zero `ActualIncome` in `RECORDED` |
| `ADVANCE_UNRESOLVED` | Advance is not in `REQUESTED` or `APPROVED` |
| `SETTLEMENT_MISSING` | `FinancialSettlement` exists |
| `SETTLEMENT_NOT_SETTLED` | `FinancialSettlement.status == SettlementStatus.SETTLED` |
| `PAYMENT_OUTSTANDING` | All balance payments cleared (reimbursement or refund cleared $\ge$ due) |

Result structure:
```json
{
  "eligible": true,
  "blockers": [],
  "event_id": "uuid-str",
  "settlement_id": "uuid-str"
}
```

---

## 12. Segregation of Duties (SOD) Matrix

| Operation | Club Secretary | Finance Officer | Faculty Advisor | Principal | System Admin |
|---|:---:|:---:|:---:|:---:|:---:|
| Request Advance | **ALLOW** (Own club) | DENY | DENY | DENY | **BARRED** (403) |
| Approve / Reject Advance | DENY | **ALLOW** | DENY | DENY | **BARRED** (403) |
| Disburse Advance | DENY | **ALLOW** | DENY | DENY | **BARRED** (403) |
| Record Actual Income | **ALLOW** (Own club) | DENY | DENY | DENY | **BARRED** (403) |
| Verify / Reject Income | **BARRED** (Self-verify) | **ALLOW** | DENY | DENY | **BARRED** (403) |
| Prepare Settlement | **ALLOW** (Own club) | DENY | DENY | DENY | **BARRED** (403) |
| Submit Settlement | **ALLOW** (Own club) | DENY | DENY | DENY | **BARRED** (403) |
| Query Settlement | DENY | **ALLOW** | DENY | DENY | **BARRED** (403) |
| Approve Settlement | DENY | **ALLOW** | DENY | DENY | **BARRED** (403) |
| Record Payment | DENY | **ALLOW** | DENY | DENY | **BARRED** (403) |
| Reopen Settlement | DENY | **ALLOW** | DENY | **ALLOW** | **BARRED** (403) |
| Closure Eligibility | **ALLOW** (Read own) | **ALLOW** (Read) | **ALLOW** (Read own) | **ALLOW** (Read) | **ALLOW** (Read) |

---

## 13. Concurrency Strategy

- **Pessimistic Row Locking**:
  - `prepare_settlement`: Locks `Event` row (`SELECT ... FOR UPDATE`).
  - `approve_advance`, `disburse_advance`: Locks `CashAdvance` row.
  - `verify_income`, `reject_income`: Locks `ActualIncome` row.
  - `submit_settlement`, `audit_settlement`, `record_payment`, `reopen_settlement`: Locks `FinancialSettlement` row.
- **Database Boundary Invariants**:
  - `uq_financial_settlements_event_id`: Ensures at most 1 settlement per event.
  - `chk_cash_advances_disbursed_le_approved`: Enforces disbursement constraint at SQL engine level.
  - `chk_settlement_payments_amount_positive`: Enforces positive money values.

---

## 14. Audit Logging & In-App Notifications

### 14.1 Audit Actions Logged
- `ADVANCE_REQUESTED`, `ADVANCE_APPROVED`, `ADVANCE_REJECTED`, `ADVANCE_DISBURSED`
- `INCOME_RECORDED`, `INCOME_VERIFIED`, `INCOME_REJECTED`
- `SETTLEMENT_PREPARED`, `SETTLEMENT_SUBMITTED`, `SETTLEMENT_QUERIED`, `SETTLEMENT_APPROVED`, `SETTLEMENT_PAYMENT_RECORDED`, `SETTLEMENT_SETTLED`, `SETTLEMENT_REOPENED`

Each entry captures: `actor_id`, `actor_email`, `actor_role`, `action`, `entity_type`, `entity_id`, `previous_state`, `new_state`, `ip_address`, and `user_agent`.

### 14.2 Notifications Triggered
- `ADVANCE_APPROVED`, `ADVANCE_REJECTED`, `ADVANCE_DISBURSED` to Club Secretary.
- `INCOME_VERIFIED`, `INCOME_REJECTED` to Club Secretary.
- `SETTLEMENT_QUERIED`, `SETTLEMENT_REIMBURSEMENT_PENDING`, `SETTLEMENT_REFUND_PENDING`, `SETTLEMENT_SETTLED`, `SETTLEMENT_REOPENED` to Club Secretary.

---

## 15. Automated Verification Results

### 15.1 Unit & Integration Test Results
Command:
```powershell
& "E:\Se-Mini-Projectackend\.venv\Scripts\python.exe" -m pytest backend/tests/services/test_settlement_service.py -v
```
Output:
```
============================= test session starts =============================
collected 37 items

backend	ests\services	est_settlement_service.py::test_accounting_case_1 PASSED
backend	ests\services	est_settlement_service.py::test_accounting_case_2 PASSED
backend	ests\services	est_settlement_service.py::test_accounting_case_3 PASSED
backend	ests\services	est_settlement_service.py::test_accounting_case_4_partial_expense PASSED
backend	ests\services	est_settlement_service.py::test_accounting_surplus_income_exceeds_expenditure PASSED
backend	ests\services	est_settlement_service.py::test_accounting_decimal_precision PASSED
backend	ests\services	est_settlement_service.py::test_unresolved_draft_expense_blocks_settlement PASSED
backend	ests\services	est_settlement_service.py::test_unresolved_submitted_expense_blocks_settlement PASSED
backend	ests\services	est_settlement_service.py::test_unresolved_queried_expense_blocks_settlement PASSED
backend	ests\services	est_settlement_service.py::test_disallowed_expense_excluded_from_verified_total PASSED
backend	ests\services	est_settlement_service.py::test_unverified_recorded_income_blocks_settlement PASSED
backend	ests\services	est_settlement_service.py::test_income_secretary_cannot_self_verify PASSED
backend	ests\services	est_settlement_service.py::test_income_system_admin_cannot_verify PASSED
backend	ests\services	est_settlement_service.py::test_income_cross_event_evidence_rejected PASSED
backend	ests\services	est_settlement_service.py::test_income_invalid_document_type_rejected PASSED
backend	ests\services	est_settlement_service.py::test_income_reject_flow PASSED
backend	ests\services	est_settlement_service.py::test_advance_full_lifecycle PASSED
backend	ests\services	est_settlement_service.py::test_advance_approval_exceeding_grant_rejected PASSED
backend	ests\services	est_settlement_service.py::test_advance_partial_disbursement_rejected PASSED
backend	ests\services	est_settlement_service.py::test_advance_duplicate_request_rejected PASSED
backend	ests\services	est_settlement_service.py::test_advance_system_admin_blocked PASSED
backend	ests\services	est_settlement_service.py::test_settlement_submission_and_query_flow PASSED
backend	ests\services	est_settlement_service.py::test_stale_data_detection_on_audit_approval PASSED
backend	ests\services	est_settlement_service.py::test_duplicate_settlement_creation_prevented PASSED
backend	ests\services	est_settlement_service.py::test_payment_recording_and_clearing_reimbursement PASSED
backend	ests\services	est_settlement_service.py::test_payment_wrong_direction_rejected PASSED
backend	ests\services	est_settlement_service.py::test_payment_balanced_settlement_rejects_payments PASSED
backend	ests\services	est_settlement_service.py::test_reopen_settled_settlement_creates_revision PASSED
backend	ests\services	est_settlement_service.py::test_reopen_non_settled_rejected PASSED
backend	ests\services	est_settlement_service.py::test_reopen_role_guards PASSED
backend	ests\services	est_settlement_service.py::test_closure_eligibility_all_conditions_met PASSED
backend	ests\services	est_settlement_service.py::test_closure_eligibility_blockers PASSED
backend	ests\services	est_settlement_service.py::test_cross_club_isolation PASSED
backend	ests\services	est_settlement_service.py::test_system_admin_strictly_barred_from_financial_actions PASSED
backend	ests\services	est_settlement_service.py::test_audit_logs_recorded_for_all_transitions PASSED
backend	ests\services	est_settlement_service.py::test_concurrency_duplicate_settlement_creation PASSED
backend	ests\services	est_settlement_service.py::test_concurrency_payment_overpayment_prevention PASSED

============================== 37 passed in 1.19s ==============================
```

### 15.2 Backend Regression Test Suite
Command:
```powershell
& "E:\Se-Mini-Projectackend\.venv\Scripts\python.exe" -m pytest -q
```
Output:
```
356 passed in 87.92s (0:01:27)
```
- Baseline tests: 319 passed
- Phase 2.3 service tests: 37 passed
- Total: 356 passed, 0 failures, 0 errors.

### 15.3 Ruff Linter
Command:
```powershell
& "E:\Se-Mini-Projectackend\.venv\Scripts\python.exe" -m ruff check backend/app/services/settlement_service.py backend/tests/services/test_settlement_service.py
```
Output:
```
All checks passed!
```

---

## 16. Security Review Summary

1. **Server-Authoritative Arithmetic**: Clients never supply computed balances. $V, I, NetDeficit, P, B$, reimbursement, and refund figures are calculated exclusively server-side from locked database rows.
2. **System Administrator Restrictions**: `SYSTEM_ADMIN` is hard-blocked with HTTP 403 across all financial approvals, verifications, disbursements, and payment recordings.
3. **Cross-Event Document Protection**: Documents used for income evidence or settlement payment proofs must match the event ID (`doc.event_id == event.id`).
4. **Anti-Overpayment Guard**: Settlement payments are locked and checked against the remaining due balance.
5. **Historical Immutability**: Settled calculations cannot be quietly edited in place. Reopening creates an immutable `SettlementRevision` snapshot.
6. **No Unwarranted State Mutations**: Event status remains `COMPLETED`. `CLOSED` status was not added.

---

## 18. Known Limitations & Deferred Work

1. **Deferred REST Endpoints**: API routers (`POST /events/{id}/settlement`, `POST /events/{id}/advances`, etc.) will be created in the subsequent Phase 2.3 API task.
2. **Deferred Pydantic Schemas**: Request/response schemas for settlements, advances, and income are deferred to the API task.
3. **Deferred Frontend UI**: The React `SettlementTab.tsx` and settlement dashboard will be implemented after API verification.
4. **Partial Advance Disbursement**: Partial disbursement is deferred until an institutional requirement is formally established.
5. **Principal Monetary Threshold**: No arbitrary ₹50,000 threshold was implemented; standard settlements are audited by Finance Officers, and Principal approval is reserved for exceptional reopenings.


---

## 17. Phase 2.3 Financial Integrity Hardening

Following a strict read-only audit and financial accounting research, Phase 2.3 `SettlementService` has been hardened against record-level stale data mutation and downward post-settlement reopening deadlocks.

### 17.1 Original Stale-Data Weakness
The initial implementation of `_verify_live_source_consistency` compared four aggregate totals:
- `sanctioned_grant`
- `total_verified_expenditure`
- `total_verified_income`
- `cash_advance_disbursed`

This left significant audit blind spots:
1. **Equal-Sum Expense Replacement**: Replacing a verified invoice with another of identical amount was undetected.
2. **Status Substitution**: Disallowing one claim and verifying another compensating claim preserved total expenditure.
3. **Income Swaps**: Replacing one verified income record with another of identical value preserved total income.
4. **Proposal Version Swaps**: Amending `EventRequestVersion` while keeping the grant ceiling unchanged preserved the grant total.

### 17.2 Deterministic Record-Level SHA-256 Fingerprint Design
Stale-data verification now generates a deterministic cryptographic digest (`source_fingerprint`) across the canonical source dataset:
- `approved_version_id`: Event request approved version UUID.
- `sanctioned_grant`: String formatted to two decimal places.
- `expenses`: Deterministically sorted list of `(id, status, claimed_amount, verified_amount)`.
- `incomes`: Deterministically sorted list of `(id, status, amount)`.
- `advance`: Canonical `(id, status, amount_approved, amount_disbursed)` tuple.

**Mechanism**:
$$\text{source\_fingerprint} = \text{sha256}(\text{canonical\_json}(\text{payload}))$$
1. Calculated during `prepare_settlement()` and stored in `AuditAction.SETTLEMENT_PREPARED` metadata as well as transient instance state.
2. Evaluated at `submit_settlement()` and `audit_settlement(action='APPROVE')`.
3. If live source records differ in any record ID, amount, status, or version ID, the service raises `SettlementStaleDataError`. Silent recalculation is strictly prohibited.

### 17.3 Original Reopening Defect & Downward Deadlock
Previously, settlement balance was computed purely as $B = P - A$, ignoring previous settlement disbursements. When a settlement was reopened downward after full reimbursement (e.g. $P$ dropped from ₹10,000 to ₹6,000 after ₹10,000 was paid):
1. $B$ remained $+₹6,000$ (`REIMBURSEMENT_DUE`), erroneously indicating college owed money.
2. `record_payment` evaluated $\text{remaining\_due} = 6,000 - 10,000 = -₹4,000$, causing any payment attempt to fail overpayment checks and freezing the settlement in `PENDING_REIMBURSEMENT`.
3. The system could not accept an incoming recovery refund or return to `SETTLED`.

### 17.4 Authoritative Cumulative Reconciliation Formula
The authoritative balance formula now incorporates the complete historical cash flow vector across all immutable prior payments:

$$\begin{aligned}
V &= \sum_{\text{VERIFIED}} \text{verified\_amount} + \sum_{\text{PARTIALLY\_VERIFIED}} \text{verified\_amount} \\
I_{\text{actual}} &= \sum_{\text{VERIFIED}} \text{amount} \\
\text{NetDeficit} &= \max(0.00, V - I_{\text{actual}}) \\
P_{\text{entitled}} &= \min(G, \text{NetDeficit}) \\
R_{\text{cleared}} &= \sum \text{historical } \text{REIMBURSEMENT\_DISBURSEMENT payments} \\
F_{\text{cleared}} &= \sum \text{historical } \text{ADVANCE\_REFUND\_RECEIPT payments} \\
\text{NetCashTransferred} &= A + R_{\text{cleared}} - F_{\text{cleared}} \\
B_{\text{revision}} &= P_{\text{entitled}} - \text{NetCashTransferred} = (P_{\text{entitled}} - A) - (R_{\text{cleared}} - F_{\text{cleared}})
\end{aligned}$$

### 17.5 Directional Behavior Across Lifecycle Scenarios
- **Downward Revision ($B_{\text{revision}} < 0$)**:
  - `settlement_type = SettlementType.REFUND_DUE`
  - `refund_due = |B_{\text{revision}}|`, `reimbursement_due = 0.00`
  - Transitions to `PENDING_REFUND` (Overpayment Recovery).
  - Cleared by recording `SettlementPaymentType.ADVANCE_REFUND_RECEIPT`.
- **Upward Revision ($B_{\text{revision}} > 0$)**:
  - `settlement_type = SettlementType.REIMBURSEMENT_DUE`
  - `reimbursement_due = B_{\text{revision}}`, `refund_due = 0.00`
  - Transitions to `PENDING_REIMBURSEMENT` (Supplementary Reimbursement).
  - Cleared by recording `SettlementPaymentType.REIMBURSEMENT_DISBURSEMENT`.
- **Direction Flip with Prior Refund**:
  - Advance ₹25,000, Initial Expense ₹20,000 $\implies$ Refund ₹5,000 paid. Net transferred = ₹20,000.
  - Expense increases to ₹30,000 $\implies B = 30,000 - 20,000 = +₹10,000$.
  - Correctly credits the historical refund and issues supplementary reimbursement for the full ₹10,000 delta.
- **Multiple Successive Reopenings**:
  - Maintained across revisions: Rev 1 (₹10,000 paid), Rev 2 (₹4,000 refunded), Rev 3 (₹2,000 supplementary paid).
  - Cumulative net cash out = $10,000 - 4,000 + 2,000 = ₹8,000 == P_{\text{entitled}}$.

### 17.6 Historical Payment Immutability
- No timestamps (`payment.created_at`) are used to partition payment obligations.
- `SettlementPayment` records are strictly append-only and protected by `ON DELETE RESTRICT`.
- Target and remaining calculations evaluate cumulative sums, guaranteeing zero duplicate disbursements and zero duplicate refunds.

### 17.7 Test Suite Expansion (371/371 Passing)
15 new targeted regression tests were added to `backend/tests/services/test_settlement_service.py` (totaling 52 settlement service tests; 371 across the full backend suite):
1. `test_stale_data_fails_on_expense_replacement_with_identical_total`
2. `test_stale_data_fails_on_expense_status_substitution`
3. `test_stale_data_fails_on_income_replacement_with_identical_total`
4. `test_stale_data_fails_on_approved_version_swap`
5. `test_reopen_downward_revision_transitions_to_pending_refund`
6. `test_reopen_downward_revision_clears_via_refund`
7. `test_reopen_upward_revision_creates_supplementary_reimbursement`
8. `test_reopen_downward_revision_with_partial_prior_payment`
9. `test_reopen_direction_flip_credits_prior_refund`
10. `test_multiple_successive_reopenings_preserve_cumulative_balance`
11. `test_historical_payments_are_immutable_across_reopen`
12. `test_no_duplicate_reimbursement_after_reopen`
13. `test_no_duplicate_refund_after_reopen`
14. `test_closure_blocked_while_reopened_revision_has_outstanding_balance`
15. `test_fingerprint_detects_approved_version_change_with_same_grant`

### 17.8 Explicit Scope & Governance Boundaries
1. **Deferred Schema Hardening**:
   - Migration 0005 is explicitly deferred.
   - `settlement_revision_id` foreign key on `SettlementPayment` is deferred.
   - Implementation is 100% service-layer authoritative within migration 0004.
2. **Event Lifecycle Stability**:
   - `EventStatus` remains `COMPLETED`. No `CLOSED` status was added.
3. **Unresolved Institutional Policies**:
   - `[EVIDENCE INSUFFICIENT — REQUIRES INSTITUTIONAL CONFIRMATION]`: Statutory club overpayment default recovery policy (e.g. salary deduction of Advisor vs budget freeze vs graduation clearance withholding).
   - `[EVIDENCE INSUFFICIENT — REQUIRES INSTITUTIONAL CONFIRMATION]`: Event surplus revenue ownership ($I_{\text{actual}} > V$).
