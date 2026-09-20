# CampusConnect — Phase 2.2 Implementation Report: Actual Expense Ledger & Finance Verification Foundation

**Status:** COMPLETE & VERIFIED  
**Branch:** `phase2-event-lifecycle`  
**Base Commit:** `a3dd03e` (Phase 2.1 Complete)  
**Date:** September 21, 2026  

---

## 1. Executive Summary

Phase 2.2 establishes the production-grade **Actual Expense Ledger, Bill / Invoice Evidence Engine, and Finance Verification Foundation** for CampusConnect. Building upon the verified Phase 2.1 baseline (Event Execution Lifecycle and Faculty Advisor Post-Event Certification), this phase implements statutory financial record-keeping, strict segregation of duties (SOD), cryptographic bill evidence validation, and non-destructive audit history.

All features strictly adhere to the approved Phase 2.2 Architecture Reconciliation:
- Phase boundary respected: ends strictly at **VERIFIED EXPENSE LEDGER**.
- No Settlement, Cash Advance Reconciliation, Reimbursements, or Utilization Certificates (UCs) are implemented in Phase 2.2 (deferred to Phase 2.3).
- `SETTLED` is strictly NOT an `ActualExpense` status.

---

## 2. Architecture Reconciliation & Decisions

### 2.1 State Machine
The ephemeral `UNDER_REVIEW` state was completely excluded. Finance Officers can inspect submitted claims without altering lifecycle state.

```
                  ┌──────────────┐
                  │    DRAFT     │
                  └──────┬───────┘
                         │ Submit
                         ▼
                  ┌──────────────┐
       ┌──────────┤  SUBMITTED   ├──────────┐
       │          └──────┬───────┘          │
       │ Verify          │ Partial Verify   │ Disallow
       ▼                 ▼                  ▼
┌──────────────┐  ┌──────────────┐   ┌──────────────┐
│   VERIFIED   │  │  PARTIALLY_  │   │  DISALLOWED  │
│  (Terminal)  │  │   VERIFIED   │   │  (Terminal)  │
└──────────────┘  │  (Terminal)  │   └──────────────┘
                  └──────────────┘
                         │
                         │ Query
                         ▼
                  ┌──────────────┐
                  │   QUERIED    │
                  └──────┬───────┘
                         │ Amend & Resubmit
                         ▼
                  ┌──────────────┐
                  │  SUBMITTED   │
                  └──────────────┘
```

- **`VERIFIED`**: Terminal & immutable. Full claimed amount approved (`verified_amount == claimed_amount`).
- **`PARTIALLY_VERIFIED`**: Terminal & immutable. Partial approval (`0 < verified_amount < claimed_amount`). Mandatory Finance justification remarks. Disallowed balance is derived: `disallowed_amount = claimed_amount - verified_amount`.
- **`DISALLOWED`**: Terminal & immutable. Claim rejected in full (`verified_amount == 0.00`). Disallowed amount equals total claimed amount (`disallowed_amount == claimed_amount`). Mandatory Finance justification remarks.
- **`QUERIED`**: Non-terminal. Finance Officer requests clarification or additional evidence. Club Secretary can amend the expense line item and resubmit, returning the expense to `SUBMITTED`. Original and intermediate financial states are fully preserved in `AuditLog`.

### 2.2 Bill Evidence Rules & Document Event Ownership
- **Mandatory Bill Evidence**: Every `ActualExpense` row requires a valid `bill_document_id`.
- **Event Boundary Enforcement**: An expense line item and its supporting bill document MUST belong to the same event (`expense.event_id == document.event_id`). Cross-event bill reuse is strictly rejected with HTTP 400.
- **Same-Event Multi-Line Sharing**: Multiple expense lines within the *same* event may reference the same bill document (e.g., a single vendor invoice covering both Materials and Food).
- **Invoice Number**: Invoice number is optional (for small cash vendors/receipts). If omitted, the bill is accepted but flagged for manual review (`is_flagged_for_review = True`, `review_notes = "Missing invoice number; bill document attached."`).
- **Cryptographic Duplicate Detection**:
  - `Document.file_hash`: SHA-256 hash computed at upload time.
  - Re-uploading an exact duplicate bill document across different events is hard-blocked with HTTP 409 Conflict.
  - Cross-event identical invoice metadata (`vendor_name` + `invoice_number` + `invoice_date`) is rejected with HTTP 409 Conflict.
  - No global SQL unique constraint on invoice metadata, preserving flexibility for intra-club same-event multi-line splits.

### 2.3 Financial Rules & Datatypes
- All monetary amounts use Python `Decimal` and PostgreSQL `NUMERIC(12,2)`.
- Enforced Check Constraints:
  - `claimed_amount > 0.00`
  - `verified_amount >= 0.00`
  - `verified_amount <= claimed_amount`
- `disallowed_amount` is a derived property (`claimed_amount - verified_amount`), never redundantly stored in the database.

### 2.4 Segregation of Duties (SOD) & Preconditions
- **Club Secretary**: Creates, edits, deletes DRAFT expenses; submits claims; amends and resubmits QUERIED claims for their own club.
- **Finance Officer**: Audits SUBMITTED claims; performs VERIFY, PARTIAL_VERIFY, QUERY, or DISALLOW actions.
- **Faculty Advisor**: Certifies event delivery via `PostEventReport`.
- **System Admin**: Barred from verifying, altering, or bypassing Finance verification on expenses (statutory SOD guard; HTTP 403 Forbidden).
- **Execution Preconditions**:
  1. Event must be in `COMPLETED` execution status to record/create actual expenses.
  2. Faculty Advisor must certify event delivery (`post_event_report.status == 'CERTIFIED'`) before Finance Officers can make verification decisions.

---

## 3. Database Schema & Migration

### 3.1 Migration `0003_phase2_2_actual_expenses.py`
- Added column `file_hash VARCHAR(64) NULL` and index `ix_documents_file_hash` to `documents` table.
- Created `actual_expenses` table with:
  - `id UUID PRIMARY KEY`
  - `event_id UUID NOT NULL REFERENCES confirmed_events(id) ON DELETE CASCADE`
  - `budget_line_item_id UUID NULL REFERENCES budget_line_items(id) ON DELETE SET NULL`
  - `category VARCHAR(30) NOT NULL`
  - `description VARCHAR(500) NOT NULL`
  - `vendor_name VARCHAR(255) NOT NULL`
  - `vendor_gstin VARCHAR(15) NULL`
  - `invoice_number VARCHAR(100) NULL`
  - `invoice_date DATE NOT NULL`
  - `claimed_amount NUMERIC(12,2) NOT NULL`
  - `verified_amount NUMERIC(12,2) NULL`
  - `status VARCHAR(30) NOT NULL DEFAULT 'DRAFT'`
  - `bill_document_id UUID NOT NULL REFERENCES documents(id) ON DELETE RESTRICT`
  - `submitted_by UUID NULL REFERENCES users(id) ON DELETE SET NULL`
  - `submitted_at TIMESTAMPTZ NULL`
  - `verified_by UUID NULL REFERENCES users(id) ON DELETE SET NULL`
  - `verified_at TIMESTAMPTZ NULL`
  - `finance_remarks VARCHAR(500) NULL`
  - `query_reason VARCHAR(500) NULL`
  - `is_flagged_for_review BOOLEAN NOT NULL DEFAULT FALSE`
  - `review_notes VARCHAR(255) NULL`
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- Indexes: `ix_actual_expenses_event_id`, `ix_actual_expenses_status`, `ix_actual_expenses_bill_document_id`.
- Table-level Check Constraints:
  - `chk_actual_expense_claimed_positive`: `claimed_amount > 0`
  - `chk_actual_expense_verified_range`: `verified_amount IS NULL OR (verified_amount >= 0 AND verified_amount <= claimed_amount)`

---

## 4. API Endpoints Implemented

| Method | Path | Role / Access | Description |
|---|---|---|---|
| `POST` | `/api/v1/events/{id}/expenses/upload-bill` | Secretary | Uploads bill document with SHA-256 hash calculation |
| `POST` | `/api/v1/events/{id}/expenses` | Secretary | Creates DRAFT actual expense line item |
| `GET` | `/api/v1/events/{id}/expenses` | Authenticated | Lists all actual expenses for the event |
| `GET` | `/api/v1/events/{id}/expenses/summary` | Authenticated | Reconciliation ledger summary (claimed, verified, disallowed) |
| `GET` | `/api/v1/events/{id}/expenses/{exp_id}` | Authenticated | Retrieves single actual expense line item |
| `PATCH` | `/api/v1/events/{id}/expenses/{exp_id}` | Secretary | Updates DRAFT or QUERIED expense (with audit log) |
| `DELETE` | `/api/v1/events/{id}/expenses/{exp_id}` | Secretary | Deletes DRAFT expense |
| `POST` | `/api/v1/events/{id}/expenses/{exp_id}/submit` | Secretary | Submits single expense to Finance queue |
| `POST` | `/api/v1/events/{id}/expenses/submit` | Secretary | Submits all DRAFT expenses to Finance queue |
| `POST` | `/api/v1/events/{id}/expenses/{exp_id}/verify` | Finance Officer | Approves full claim (VERIFIED, terminal) |
| `POST` | `/api/v1/events/{id}/expenses/{exp_id}/partial-verify` | Finance Officer | Partially verifies claim (PARTIALLY_VERIFIED, terminal) |
| `POST` | `/api/v1/events/{id}/expenses/{exp_id}/query` | Finance Officer | Queries claim with reason (QUERIED) |
| `POST` | `/api/v1/events/{id}/expenses/{exp_id}/disallow` | Finance Officer | Disallows claim in full (DISALLOWED, terminal) |

---

## 5. Concurrency Control & Row Locking

All financial state mutations execute within atomic transactions utilizing pessimistic row locking:
- `select(ActualExpense).where(...).with_for_update()`
- Prevents race conditions during simultaneous Secretary amendments and Finance audits.
- Ensures double-auditing or concurrent state conflicts are rejected safely at the database level.

---

## 6. Frontend UI Implementation

### 6.1 Components
- `ExpenseLedgerTab.tsx` (`frontend/src/components/expenses/ExpenseLedgerTab.tsx`):
  - **Ledger Summary Cards**: Real-time display of Sanctioned Budget, Total Claimed, Total Verified, and Total Disallowed spend formatted in Indian Rupee format (`₹`).
  - **Prerequisite Alerts**: Dynamic notices if event execution is not yet COMPLETED, or if Faculty Advisor delivery certification is pending.
  - **SOD Banners**: Clear notice of System Administrator read-only audit status.
  - **Expense Table**: Categorized view with status badges, review flags, vendor/invoice details, claimed vs verified amounts, and direct bill download links.
  - **Bill Upload & Re-use**: Drag & drop bill upload with client validation, plus instant selection of bills already uploaded for the current event.
  - **Club Secretary Workflow**: Add/edit expense modals, single & bulk submit actions, and query amendment banners with resubmit triggers.
  - **Finance Officer Workflow**: Modal-based audit actions (Verify, Partial Verify, Query, Disallow) with validation on partial amounts and mandatory justifications.
- `EventDetailPage.tsx`:
  - Integrated `Expenses & Ledger` tab alongside `Execution & Report`.

---

## 7. Verification & Test Results

### 7.1 Backend Tests
- **Phase 2.1 Baseline**: 302 passed.
- **Phase 2.2 New Tests**: 17 passed (`tests/api/test_actual_expenses.py`).
  1. `test_01_upload_bill_document_happy_path`: Valid PDF bill upload and SHA-256 hash storage.
  2. `test_02_upload_bill_invalid_magic_bytes_rejected`: Rejects spoofed extensions with invalid magic bytes (400).
  3. `test_03_create_draft_expense_happy_path`: Creates DRAFT expense with supporting bill.
  4. `test_04_create_expense_other_club_rejected_403`: Cross-club authorization isolation.
  5. `test_05_finance_officer_cannot_create_expense_403`: SOD check (FO cannot create claims).
  6. `test_06_claimed_amount_must_be_positive`: Validates `claimed_amount > 0`.
  7. `test_07_duplicate_file_hash_across_events_rejected_409`: Hard-blocks cross-event duplicate bill hash.
  8. `test_08_multi_line_bill_sharing_in_same_event_allowed`: Allows multiple line items on one bill within same event.
  9. `test_09_duplicate_metadata_across_events_rejected_409`: Rejects cross-event duplicate vendor/invoice/date.
  10. `test_10_missing_invoice_number_allowed_with_flag`: Accepts missing invoice number with review flag.
  11. `test_11_submit_and_full_verification_flow`: End-to-end submit $ightarrow$ verify and terminal immutability check.
  12. `test_12_partial_verification_flow`: Partial verification with derived disallowed amount.
  13. `test_13_query_and_resubmission_cycle`: Non-destructive query revision and resubmission.
  14. `test_14_disallow_expense_flow`: Full disallowance with verified = 0.
  15. `test_15_ledger_summary_reconciliation`: Reconciliation arithmetic across all categories and statuses.
  16. `test_16_system_admin_cannot_verify_expenses_403`: Statutory SOD guard (Admin blocked from Finance decisions).
  17. `test_17_audit_log_reconstruction_integrity`: Reconstructs complete historical audit trail from `AuditLog`.
- **Total Backend Tests**: **319 passed, 0 failed, 0 errors** (100% pass rate).

### 7.2 Frontend Tests & Build
- **Vitest Unit Tests**: **17 passed, 0 failed** across 6 test suites (`ExpenseLedgerTab.test.tsx` 5/5 passed).
- **ESLint**: 0 errors, 0 warnings.
- **TypeScript**: `tsc -b` clean.
- **Production Build**: `vite build` completed in 3.09s (`dist/` clean).

---

## 8. Known Limitations & Deferred to Phase 2.3

1. **Financial Settlement**: Generating payment disbursement orders, net payable calculation, and post-event fund settlement are intentionally deferred to Phase 2.3.
2. **Cash Advance Reconciliation**: Offsetting verified expenses against approved cash advance disbursements is deferred to Phase 2.3.
3. **Student Reimbursement Workflow**: Bank transfer generation and reimbursement receipts are deferred to Phase 2.3.
4. **Utilization Certificate (UC)**: Statutory UC generation and digital sign-off are deferred to Phase 2.3.
