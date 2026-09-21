# CAMPUSCONNECT — PHASE 2.3 MIGRATION REPORT
## Migration Revision: `0004_phase2_3_settlement`
**File**: `backend/migrations/versions/0004_phase2_3_financial_settlement.py`  
**Date**: September 21, 2026  
**Status**: UPGRADE, DOWNGRADE, AND RE-UPGRADE VERIFIED — 100% PASSED  

---

## 1. Executive Summary

Alembic migration `0004_phase2_3_settlement` has been successfully implemented and applied to PostgreSQL, establishing the production database schema for Phase 2.3 Financial Settlement, Cash Advances, and Actual Income.

### Verification Highlights:
- **Upgrade Status**: `0003_phase2_2_actual_expenses -> 0004_phase2_3_settlement (head)` applied cleanly.
- **Downgrade Status**: `0004_phase2_3_settlement -> 0003_phase2_2_actual_expenses` verified cleanly, dropping all 5 tables without orphan constraints or indexes.
- **Re-upgrade Status**: Returned to `0004_phase2_3_settlement (head)` and verified.
- **Backend Test Suite**: `319/319 passed` in 84.63s (zero regressions).
- **PostgreSQL Inspection**: Verified all columns, data types, `NUMERIC(12,2)` precision, primary keys, check constraints, foreign key `ON DELETE RESTRICT` semantics, and indexes.

---

## 2. Migration Details & Revisions

- **File Path**: `backend/migrations/versions/0004_phase2_3_financial_settlement.py`
- **Revision Identifier**: `0004_phase2_3_settlement`
  *(Note: Formatted to 24 characters to safely adhere to Alembic's standard `alembic_version.version_num VARCHAR(32)` column constraint without schema truncation).*
- **Down Revision**: `0003_phase2_2_actual_expenses`
- **Branch Labels**: `None`
- **Depends On**: `None`

---

## 3. Tables Created & Schema Specification

### 3.1 Table: `cash_advances`
*Operational Cash Advance requisition, approval, and disbursement tracking (1:0..1 with Event).*

| Column | Type | Nullable | Default / Constraints | Description |
|---|---|---|---|---|
| `id` | `UUID` | NO | `gen_random_uuid()` PK | Primary key |
| `event_id` | `UUID` | NO | FK `events.id` ON DELETE RESTRICT | Associated confirmed event (UNIQUE) |
| `amount_requested` | `NUMERIC(12,2)` | NO | `amount_requested > 0.00` | Requisition amount by Club Secretary |
| `amount_approved` | `NUMERIC(12,2)` | YES | `amount_approved >= 0.00` | Finance Officer approved ceiling |
| `amount_disbursed` | `NUMERIC(12,2)` | NO | `0.00`, non-negative, `<= amount_approved` | Actual physical advance disbursed |
| `status` | `VARCHAR(20)` | NO | `'REQUESTED'` | `REQUESTED`, `APPROVED`, `DISBURSED`, `REJECTED` |
| `recipient_id` | `UUID` | NO | FK `users.id` ON DELETE RESTRICT | Club Secretary recipient |
| `approved_by` | `UUID` | YES | FK `users.id` ON DELETE RESTRICT | Finance Officer approver |
| `disbursed_by` | `UUID` | YES | FK `users.id` ON DELETE RESTRICT | Finance Officer disburser |
| `disbursement_date`| `TIMESTAMPTZ` | YES | None | Physical disbursal timestamp |
| `payment_reference`| `VARCHAR(100)` | YES | None | Cheque / NEFT reference number |
| `notes` | `TEXT` | YES | None | Requisition remarks |
| `rejection_reason` | `TEXT` | YES | None | Reason if rejected by Finance |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Row update timestamp |

**Constraints & Indexes**:
- `uq_cash_advances_event_id`: UNIQUE (`event_id`) — guarantees at most one advance per event.
- `chk_cash_advances_requested_positive`: `CHECK (amount_requested > 0.00)`
- `chk_cash_advances_approved_non_negative`: `CHECK (amount_approved IS NULL OR amount_approved >= 0.00)`
- `chk_cash_advances_disbursed_non_negative`: `CHECK (amount_disbursed >= 0.00)`
- `chk_cash_advances_disbursed_le_approved`: `CHECK (amount_approved IS NULL OR amount_disbursed <= amount_approved)`
- Index: `ix_cash_advances_status` ON (`status`)

---

### 3.2 Table: `actual_incomes`
*Self-generated event revenue ledger (registration fees, sponsorships, stall rentals) (1:N with Event).*

| Column | Type | Nullable | Default / Constraints | Description |
|---|---|---|---|---|
| `id` | `UUID` | NO | `gen_random_uuid()` PK | Primary key |
| `event_id` | `UUID` | NO | FK `events.id` ON DELETE RESTRICT | Parent confirmed event |
| `source_type` | `VARCHAR(30)` | NO | None | Category (`REGISTRATION_FEE`, `SPONSORSHIP`, etc.) |
| `description` | `TEXT` | NO | None | Line item description |
| `payer_name` | `VARCHAR(255)` | NO | None | Payee / Sponsor / Participant source |
| `amount` | `NUMERIC(12,2)` | NO | `amount > 0.00` | Revenue amount received |
| `received_date` | `DATE` | NO | None | Date payment received |
| `reference_number`| `VARCHAR(100)` | YES | None | Receipt / bank credit reference |
| `evidence_document_id` | `UUID` | NO | FK `documents.id` ON DELETE RESTRICT | Mandatory bank slip/voucher document |
| `status` | `VARCHAR(20)` | NO | `'RECORDED'` | `RECORDED`, `VERIFIED`, `REJECTED` |
| `recorded_by` | `UUID` | NO | FK `users.id` ON DELETE RESTRICT | Club Secretary submitter |
| `verified_by` | `UUID` | YES | FK `users.id` ON DELETE RESTRICT | Finance Officer verifier |
| `verified_at` | `TIMESTAMPTZ` | YES | None | Finance verification timestamp |
| `finance_remarks` | `TEXT` | YES | None | Verification notes or rejection justification |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Audit creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Audit update timestamp |

**Constraints & Indexes**:
- `chk_actual_incomes_amount_positive`: `CHECK (amount > 0.00)`
- Index: `ix_actual_incomes_event_id` ON (`event_id`)
- Index: `ix_actual_incomes_status` ON (`status`)
- Index: `ix_actual_incomes_event_id_status` ON (`event_id`, `status`)
- Index: `ix_actual_incomes_evidence_doc` ON (`evidence_document_id`)

---

### 3.3 Table: `financial_settlements`
*Authoritative post-event reconciliation and settlement ledger (1:1 with Event).*

| Column | Type | Nullable | Default / Constraints | Description |
|---|---|---|---|---|
| `id` | `UUID` | NO | `gen_random_uuid()` PK | Primary key |
| `event_id` | `UUID` | NO | FK `events.id` ON DELETE RESTRICT | Event reference (UNIQUE) |
| `approved_version_id` | `UUID` | NO | FK `event_request_versions.id` ON DELETE RESTRICT | Approved baseline version |
| `sanctioned_grant` | `NUMERIC(12,2)` | NO | Non-negative | Frozen approved institutional grant snapshot |
| `sanctioned_expenditure` | `NUMERIC(12,2)` | NO | Non-negative | Frozen approved expenditure ceiling snapshot |
| `expected_income` | `NUMERIC(12,2)` | NO | `0.00` | Frozen expected revenue snapshot |
| `total_claimed_expenditure` | `NUMERIC(12,2)` | NO | `0.00`, non-negative | Sum of claimed expense bills |
| `total_verified_expenditure` | `NUMERIC(12,2)` | NO | `0.00`, non-negative | Total verified expenditure $V$ |
| `total_disallowed_expenditure` | `NUMERIC(12,2)` | NO | `0.00`, non-negative | Total disallowed expenses |
| `total_verified_income` | `NUMERIC(12,2)` | NO | `0.00`, non-negative | Total verified income $I_{actual}$ |
| `net_deficit` | `NUMERIC(12,2)` | NO | `0.00`, non-negative | $\max(0, V - I_{actual})$ |
| `institutional_payout` | `NUMERIC(12,2)` | NO | `0.00`, non-negative | $P = \min(G_{sanctioned}, 	ext{Net Deficit})$ |
| `cash_advance_disbursed` | `NUMERIC(12,2)` | NO | `0.00`, non-negative | Disbursed cash advance $A$ |
| `settlement_balance` | `NUMERIC(12,2)` | NO | `0.00` (can be negative) | $B = P - A$ |
| `reimbursement_due` | `NUMERIC(12,2)` | NO | `0.00`, non-negative | $B > 0 \implies B$, else `0.00` |
| `refund_due` | `NUMERIC(12,2)` | NO | `0.00`, non-negative | $B < 0 \implies \|B\|$, else `0.00` |
| `settlement_type` | `VARCHAR(30)` | NO | None | `REIMBURSEMENT_DUE`, `REFUND_DUE`, `BALANCED` |
| `status` | `VARCHAR(30)` | NO | `'DRAFT'` | `DRAFT`, `UNDER_AUDIT`, `APPROVED`, `SETTLED`, etc. |
| `prepared_by` | `UUID` | NO | FK `users.id` ON DELETE RESTRICT | Club Secretary preparer |
| `submitted_at` | `TIMESTAMPTZ` | YES | None | Secretary submission timestamp |
| `audited_by` | `UUID` | YES | FK `users.id` ON DELETE RESTRICT | Finance Officer auditor |
| `audited_at` | `TIMESTAMPTZ` | YES | None | Finance audit completion timestamp |
| `finance_remarks` | `TEXT` | YES | None | Audit findings / reconciliation notes |
| `query_reason` | `TEXT` | YES | None | Reason if settlement queried back to club |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Preparation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Update timestamp |

**Constraints & Indexes**:
- `uq_financial_settlements_event_id`: UNIQUE (`event_id`) — strictly enforces 1:1 settlement per event.
- Non-negative check constraints on:
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
- Index: `ix_financial_settlements_status` ON (`status`)
- Index: `ix_financial_settlements_approved_version` ON (`approved_version_id`)

---

### 3.4 Table: `settlement_payments`
*Physical cash movement clearing ledger (1:N with FinancialSettlement).*

| Column | Type | Nullable | Default / Constraints | Description |
|---|---|---|---|---|
| `id` | `UUID` | NO | `gen_random_uuid()` PK | Primary key |
| `settlement_id` | `UUID` | NO | FK `financial_settlements.id` ON DELETE RESTRICT | Parent financial settlement |
| `payment_type` | `VARCHAR(30)` | NO | None | `REIMBURSEMENT_DISBURSEMENT`, `ADVANCE_REFUND_RECEIPT` |
| `amount` | `NUMERIC(12,2)` | NO | `amount > 0.00` | Physical payment/receipt amount |
| `payment_method` | `VARCHAR(30)` | NO | None | `BANK_TRANSFER_NEFT`, `CHEQUE`, `CASH_VOUCHER`, etc. |
| `transaction_reference`| `VARCHAR(100)` | NO | None | UTR number / Cheque number / Cash receipt reference |
| `transaction_date` | `TIMESTAMPTZ` | NO | None | Transaction clearance date/time |
| `proof_document_id`| `UUID` | NO | FK `documents.id` ON DELETE RESTRICT | Uploaded clearance voucher/receipt PDF/PNG |
| `recorded_by` | `UUID` | NO | FK `users.id` ON DELETE RESTRICT | Finance Officer recording payment |
| `notes` | `TEXT` | YES | None | Transaction remarks |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Record creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Record update timestamp |

**Constraints & Indexes**:
- `chk_settlement_payments_amount_positive`: `CHECK (amount > 0.00)`
- Index: `ix_settlement_payments_settlement_id` ON (`settlement_id`)
- Index: `ix_settlement_payments_reference` ON (`transaction_reference`)
- Index: `ix_settlement_payments_proof_doc` ON (`proof_document_id`)

---

### 3.5 Table: `settlement_revisions`
*Immutable historical snapshot created prior to reopening an approved/settled settlement (1:N with FinancialSettlement).*

| Column | Type | Nullable | Default / Constraints | Description |
|---|---|---|---|---|
| `id` | `UUID` | NO | `gen_random_uuid()` PK | Primary key |
| `settlement_id` | `UUID` | NO | FK `financial_settlements.id` ON DELETE RESTRICT | Parent financial settlement |
| `revision_number` | `INTEGER` | NO | `revision_number >= 1` | Monotonically increasing revision sequence |
| `snapshot_data` | `JSONB` | NO | None | Full JSON serialization of settlement & payments |
| `reopened_by` | `UUID` | NO | FK `users.id` ON DELETE RESTRICT | Finance Officer or Principal reopening audit |
| `reopening_reason` | `TEXT` | NO | None | Mandatory audit justification for reopening |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Reopening snapshot timestamp |

**Constraints & Indexes**:
- `uq_settlement_revisions_number`: UNIQUE (`settlement_id`, `revision_number`)
- `chk_settlement_revisions_number_positive`: `CHECK (revision_number >= 1)`

---

## 4. Verification Results

### 4.1 Migration Upgrade / Downgrade Lifecycle
```bash
# 1. Upgrade from 0003 to 0004
$ alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade 0003_phase2_2_actual_expenses -> 0004_phase2_3_settlement
Status: SUCCESS (Head at 0004_phase2_3_settlement)

# 2. Downgrade from 0004 to 0003
$ alembic downgrade -1
INFO  [alembic.runtime.migration] Running downgrade 0004_phase2_3_settlement -> 0003_phase2_2_actual_expenses
Status: SUCCESS (Head at 0003_phase2_2_actual_expenses)
Verified: All 5 tables dropped cleanly without orphan constraints.

# 3. Re-upgrade from 0003 to 0004
$ alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade 0003_phase2_2_actual_expenses -> 0004_phase2_3_settlement
Status: SUCCESS (Head at 0004_phase2_3_settlement)
```

### 4.2 Automated Test Suite
```bash
$ pytest -q
319 passed in 84.63s (0:01:24)
Status: 100% PASSED (zero regressions)
```

### 4.3 Ruff Linter
```bash
$ ruff check backend/migrations/versions/0004_phase2_3_financial_settlement.py backend/app/models/domain.py
All checks passed!
```

---

## 5. Known Limitations & Deferred Items

1. **Service Layer Calculations**: The database enforces non-negativity and boundary constraints. The mathematical formulas ($P = \min(G_{sanctioned}, \max(0, V - I_{actual}))$, $B = P - A$, grant utilization, unspent grant surrender) are authoritative service-layer responsibilities implemented in `SettlementService`.
2. **Same-Event Evidence Document Validation**: Enforced at the service layer by verifying `document.event_id == event_id` and document types.
3. **No Automatic Closure**: `Event.status` remains `COMPLETED`. Event closure eligibility is evaluated via service query without mutating the event lifecycle state machine.
