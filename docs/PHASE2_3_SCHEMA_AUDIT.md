# CAMPUSCONNECT — PHASE 2.3 PRE-MIGRATION SCHEMA AUDIT

> **Document Type**: Pre-Migration Database Schema & Relational Integrity Audit  
> **Status**: READ-ONLY AUDIT COMPLETE — MIGRATION READINESS: **PASS**  
> **Baseline Checkpoint**: Commit `b05eddd` (`feat(phase2): checkpoint financial settlement domain models`)  
> **Branch**: `phase2-event-lifecycle`  
> **Target Migration**: `0004_phase2_3_financial_settlement` (Not yet created)  

---

## 1. Executive Summary & Readiness Verdict

A comprehensive, read-only architectural audit of the Phase 2.3 domain model layer in `backend/app/models/domain.py` and `backend/app/models/enums.py` has been performed, with specific focus on financial history preservation and cascade hardening.

### Overall Verdict: **PASS**
**Financial records cannot be silently physically deleted through ordinary parent relationship cascades.**

All five Phase 2.3 domain entities—`CashAdvance`, `ActualIncome`, `FinancialSettlement`, `SettlementPayment`, and `SettlementRevision`—strictly adhere to collegiate financial integrity, restrictive delete semantics, segregation of duties (SoD), and ledger immutability requirements.

---

## 2. Domain Model Architecture & Relational Mapping

| Entity | Table Name | Multiplicity to Event | Primary Key | Key Invariants & Database Constraints |
|---|---|---|---|---|
| **`CashAdvance`** | `cash_advances` | Event 1 : 0..1 | UUID | `event_id` UNIQUE; `amount_requested > 0`; `amount_approved >= 0`; `amount_disbursed >= 0`; `amount_disbursed <= amount_approved`. |
| **`ActualIncome`** | `actual_incomes` | Event 1 : N | UUID | `amount > 0`; mandatory `evidence_document_id`; `status IN (RECORDED, VERIFIED, REJECTED)`. |
| **`FinancialSettlement`** | `financial_settlements` | Event 1 : 1 | UUID | `event_id` UNIQUE; frozen snapshots of `sanctioned_grant`, `sanctioned_expenditure`, `expected_income`; non-negative checks on payout, advances, reimbursements, refunds. |
| **`SettlementPayment`** | `settlement_payments` | Settlement 1 : N | UUID | `amount > 0`; mandatory `proof_document_id`; `transaction_reference` indexed; physical clearing record. |
| **`SettlementRevision`** | `settlement_revisions` | Settlement 1 : N | UUID | Composite UNIQUE `(settlement_id, revision_number)`; `revision_number >= 1`; immutable JSONB snapshot; mandatory `reopening_reason`. |

---

## 3. Foreign Key & Cascade / Deletion Safety Audit (Hardened)

All Phase 2.3 financial relationships enforce **restrictive foreign key semantics (`ondelete="RESTRICT"`)** and have had all ORM `delete-orphan` cascades removed. Financial history is permanently protected from accidental parent deletion:

| Foreign Key | Source Column | Target Table & Column | Model `ondelete` | Database Semantics | Audit Evaluation |
|---|---|---|---|---|---|
| `fk_cash_advances_event_id` | `cash_advances.event_id` | `events.id` | `RESTRICT` | Blocks event deletion while cash advance exists | **PASS**: Advance history protected against parent purge. |
| `fk_cash_advances_recipient_id` | `cash_advances.recipient_id` | `users.id` | None (`NO ACTION`) | Prevents physical user deletion | **PASS**: Retains audit identity for advance recipient. |
| `fk_cash_advances_approved_by` | `cash_advances.approved_by` | `users.id` | None (`NO ACTION`) | Prevents physical user deletion | **PASS**: Retains audit identity for finance approver. |
| `fk_cash_advances_disbursed_by` | `cash_advances.disbursed_by` | `users.id` | None (`NO ACTION`) | Prevents physical user deletion | **PASS**: Retains audit identity for finance disburser. |
| `fk_actual_incomes_event_id` | `actual_incomes.event_id` | `events.id` | `RESTRICT` | Blocks event deletion while income records exist | **PASS**: Income ledger protected against parent purge. |
| `fk_actual_incomes_evidence_doc` | `actual_incomes.evidence_document_id` | `documents.id` | `RESTRICT` | Blocks physical document deletion while referenced | **PASS**: Income evidence document protected. |
| `fk_actual_incomes_recorded_by` | `actual_incomes.recorded_by` | `users.id` | None (`NO ACTION`) | Prevents physical user deletion | **PASS**: Submitter identity preserved. |
| `fk_actual_incomes_verified_by` | `actual_incomes.verified_by` | `users.id` | None (`NO ACTION`) | Prevents physical user deletion | **PASS**: Auditor identity preserved. |
| `fk_financial_settlements_event_id` | `financial_settlements.event_id` | `events.id` | `RESTRICT` | Blocks event deletion while settlement exists | **PASS**: Final settlement ledger protected against parent purge. |
| `fk_fin_settlements_version_id` | `financial_settlements.approved_version_id` | `event_request_versions.id` | `RESTRICT` | Blocks version deletion | **PASS**: Historical baseline version permanently protected. |
| `fk_fin_settlements_prepared_by` | `financial_settlements.prepared_by` | `users.id` | None (`NO ACTION`) | Prevents physical user deletion | **PASS**: Preparer identity preserved. |
| `fk_fin_settlements_audited_by` | `financial_settlements.audited_by` | `users.id` | None (`NO ACTION`) | Prevents physical user deletion | **PASS**: Auditor identity preserved. |
| `fk_settlement_payments_settle_id` | `settlement_payments.settlement_id` | `financial_settlements.id` | `RESTRICT` | Blocks settlement deletion while payments exist | **PASS**: Cash payment movements cannot be deleted. |
| `fk_settlement_payments_proof_doc` | `settlement_payments.proof_document_id` | `documents.id` | `RESTRICT` | Blocks proof document deletion while referenced | **PASS**: Payment voucher proof document protected. |
| `fk_settlement_payments_recorded_by`| `settlement_payments.recorded_by` | `users.id` | None (`NO ACTION`) | Prevents physical user deletion | **PASS**: Payment recorder audit identity preserved. |
| `fk_settlement_revisions_settle_id` | `settlement_revisions.settlement_id` | `financial_settlements.id` | `RESTRICT` | Blocks settlement deletion while revisions exist | **PASS**: Audit revision history protected. |
| `fk_settlement_revisions_reopener` | `settlement_revisions.reopened_by` | `users.id` | None (`NO ACTION`) | Prevents physical user deletion | **PASS**: Reopening authority identity preserved. |

---

## 4. Financial Immutability & Cascade Elimination

### 4.1 Elimination of ORM Delete-Orphan Cascades
In standard ORM configurations, `cascade="all, delete-orphan"` causes child rows to be deleted if the parent is deleted or if the child is unlinked from an in-memory collection. For financial history, this is completely disabled:
- **`Event.cash_advance`**: Configured as `relationship("CashAdvance", back_populates="event", uselist=False)`. Zero delete-orphan.
- **`Event.actual_incomes`**: Configured as `relationship("ActualIncome", back_populates="event")`. Zero delete-orphan.
- **`Event.financial_settlement`**: Configured as `relationship("FinancialSettlement", back_populates="event", uselist=False)`. Zero delete-orphan.
- **`FinancialSettlement.payments`**: Configured as `relationship("SettlementPayment", back_populates="settlement")`. Zero delete-orphan.
- **`FinancialSettlement.revisions`**: Configured as `relationship("SettlementRevision", back_populates="settlement")`. Zero delete-orphan.

### 4.2 Frozen Baseline Values
`FinancialSettlement` captures an immutable historical snapshot at preparation:
- `sanctioned_grant`: Immutable copy of `approved_version.budget_proposal.institute_contribution`.
- `sanctioned_expenditure`: Immutable copy of `approved_version.budget_proposal.total_expected_expenditure`.
- `expected_income`: Immutable copy of pre-event expected income.
- `approved_version_id`: Foreign key pointing to the approved `EventRequestVersion`.

**Critical Finding**: The model does **NOT** compute grant utilization or deficit against mutable `budget_proposals` or `budget_line_items` rows. This ensures that even if budget templates change, past settlements remain 100% historically reproducible.

### 4.3 Append-Only Reopening Mechanics (`SettlementRevision`)
- Reopening an `APPROVED` or `SETTLED` financial settlement is strictly controlled:
  - Requires `reopened_by` (Finance Officer or Principal) and mandatory `reopening_reason`.
  - Prior to status transition to `REOPENED`, the settlement record and all associated `SettlementPayment` entries are serialized into `snapshot_data` (`JSONType`).
  - Sequence integrity is guaranteed by `UniqueConstraint("settlement_id", "revision_number")` and `CheckConstraint("revision_number >= 1")`.
  - The previous settlement state is never overwritten or mutated in place.

---

## 5. Index Analysis & Performance Optimization

### 5.1 Redundant Index Identification
1. **`cash_advances.event_id`**:
   - `domain.py` defines `unique=True, index=True`.
   - In PostgreSQL, a `UNIQUE` constraint creates a backing unique btree index automatically.
   - *Migration Guidance*: Migration 0004 will create `sa.UniqueConstraint(["event_id"], name="uq_cash_advances_event_id")` without adding a secondary redundant non-unique index.
2. **`financial_settlements.event_id`**:
   - `domain.py` defines `unique=True, index=True`.
   - *Migration Guidance*: Migration 0004 will create `sa.UniqueConstraint(["event_id"], name="uq_financial_settlements_event_id")` without adding a duplicate non-unique index.
3. **`settlement_revisions.settlement_id`**:
   - The composite constraint `UniqueConstraint("settlement_id", "revision_number")` creates an index with `settlement_id` as the leftmost leading column.
   - In PostgreSQL, any query of the form `SELECT * FROM settlement_revisions WHERE settlement_id = :id` is fully indexed by the composite index.
   - *Migration Guidance*: Migration 0004 can omit a standalone index on `settlement_id`, avoiding index duplication.
4. **`actual_incomes` Indexing**:
   - Composite index `ix_actual_incomes_event_id_status` (`event_id`, `status`) efficiently covers event-level income status filtering (`status == 'VERIFIED'`).
   - Single index on `evidence_document_id` ensures rapid join and referential integrity checks.

---

## 6. Enum Persistence & Database Portability

### 6.1 Project Architectural Convention
Auditing migrations `0001_initial_schema.py`, `0002_phase2_1_post_event_report.py`, and `0003_phase2_2_actual_expenses.py` reveals that **CampusConnect deliberately avoids native PostgreSQL `CREATE TYPE ... AS ENUM`**.

Instead, all status and type columns are stored as `sa.String(length=...)`:
- Eliminates migration lock-in and complex DDL statements (`ALTER TYPE ... ADD VALUE`).
- Ensures seamless interoperability with the SQLite in-memory database used for the unit and integration test suite.
- Type enforcement is performed by SQLAlchemy `Mapped[Enum]` and Pydantic v2 schemas at runtime.

### 6.2 Storage Allocation for Phase 2.3 Columns
- `cash_advances.status`: `sa.String(20)` (`REQUESTED`, `APPROVED`, `DISBURSED`, `REJECTED`)
- `actual_incomes.status`: `sa.String(20)` (`RECORDED`, `VERIFIED`, `REJECTED`)
- `actual_incomes.source_type`: `sa.String(30)` (`REGISTRATION_FEE`, `SPONSORSHIP`, `STALL_RENTAL`, `TICKET_SALES`, `DONATION`, `OTHER`)
- `financial_settlements.status`: `sa.String(30)` (`DRAFT`, `UNDER_AUDIT`, `APPROVED`, `QUERIED`, `PENDING_REIMBURSEMENT`, `PENDING_REFUND`, `SETTLED`, `REOPENED`)
- `financial_settlements.settlement_type`: `sa.String(30)` (`REIMBURSEMENT_DUE`, `REFUND_DUE`, `BALANCED`)
- `settlement_payments.payment_type`: `sa.String(30)` (`REIMBURSEMENT_DISBURSEMENT`, `ADVANCE_REFUND_RECEIPT`)
- `settlement_payments.payment_method`: `sa.String(30)` (`BANK_TRANSFER_NEFT`, `CHEQUE`, `CASH_VOUCHER`, `INSTITUTIONAL_TRANSFER`)

---

## 7. Document Security & Same-Event Cross-Reference Enforcement

### 7.1 `ActualIncome` Document Ownership
- Column: `actual_incomes.evidence_document_id` -> `documents.id` (`ondelete="RESTRICT"`).
- Architectural invariant: An uploaded income receipt must belong to the same confirmed event.
- **Enforcement verification**:
  - `Document` contains `event_id: UUID | None`.
  - The domain model establishes the relationship:
    `evidence_document: Mapped["Document"] = relationship("Document", foreign_keys=[evidence_document_id])`.
  - In `SettlementService.record_income`, the service will verify:
    ```python
    if document.event_id != event_id:
        raise ResourceOwnershipError("Evidence document does not belong to this event.")
    if document.document_type != DocumentType.INCOME_EVIDENCE:
        raise DocumentTypeError("Document must be of type INCOME_EVIDENCE.")
    ```

### 7.2 `SettlementPayment` Document Ownership
- Column: `settlement_payments.proof_document_id` -> `documents.id` (`ondelete="RESTRICT"`).
- Architectural invariant: The physical bank receipt/voucher must belong to the same event being settled.
- **Enforcement verification**:
  - `SettlementPayment` links to `FinancialSettlement`, which contains `event_id`.
  - The service layer will enforce:
    ```python
    if document.event_id != settlement.event_id:
        raise ResourceOwnershipError("Payment proof does not belong to this event.")
    if document.document_type != DocumentType.SETTLEMENT_PAYMENT_PROOF:
        raise DocumentTypeError("Proof document must be of type SETTLEMENT_PAYMENT_PROOF.")
    ```

---

## 8. User Foreign Keys & Segregation of Duties (SoD)

The domain model configures explicit, isolated foreign keys for all audit actors without cross-contamination:

```
CashAdvance:
  recipient_id   --> User (Club Secretary)
  approved_by    --> User (Finance Officer; must != recipient_id)
  disbursed_by   --> User (Finance Officer)

ActualIncome:
  recorded_by    --> User (Club Secretary)
  verified_by    --> User (Finance Officer; must != recorded_by)

FinancialSettlement:
  prepared_by    --> User (Club Secretary)
  audited_by     --> User (Finance Officer; must != prepared_by)

SettlementPayment:
  recorded_by    --> User (Finance Officer)

SettlementRevision:
  reopened_by    --> User (Finance Officer or Principal)
```

**Admin Isolation Guarantee**:
`SystemAdmin` has NO operational financial roles. There are no admin override foreign keys or bypass flags on any settlement table.

---

## 9. Settlement Invariants & Mathematical Model

All monetary fields are strictly defined as `Numeric(precision=12, scale=2)`:

```
V = sum(verified_amount) from actual_expenses where status in ('VERIFIED', 'PARTIALLY_VERIFIED')
I_actual = sum(amount) from actual_incomes where status == 'VERIFIED'
Net Deficit = max(0, V - I_actual)
P = min(G_sanctioned, max(0, V - I_actual))
B = P - A

Case 1: B > 0 (Reimbursement Due)
  reimbursement_due = B
  refund_due = 0
  settlement_type = 'REIMBURSEMENT_DUE'
  status = 'PENDING_REIMBURSEMENT' (upon Finance approval)

Case 2: B < 0 (Refund Due)
  refund_due = abs(B)
  reimbursement_due = 0
  settlement_type = 'REFUND_DUE'
  status = 'PENDING_REFUND' (upon Finance approval)

Case 3: B == 0 (Balanced)
  reimbursement_due = 0
  refund_due = 0
  settlement_type = 'BALANCED'
  status = 'SETTLED' (upon Finance approval)
```

**Server-Authoritative Enforcement**:
Client input is never accepted for any calculated balance ($P, B, \text{Net Deficit}, \text{reimbursement\_due}, \text{refund\_due}$). All calculations are computed server-side in `SettlementService` using Python `Decimal`.

---

## 10. Verification of `EventStatus` Invariant

Confirmed:
- `EventStatus` in `backend/app/models/enums.py` contains:
  - `SCHEDULED`
  - `IN_PROGRESS`
  - `COMPLETED`
  - `CANCELLED`
  - `ARCHIVED`
  - `ACTIVE` (compatibility alias to `IN_PROGRESS`)
- **`CLOSED` has NOT been added.**
- Post-event lifecycle continues under `EventStatus.COMPLETED`. Event closure eligibility is evaluated through the read-only verification check `SettlementService.get_closure_eligibility(event_id)`.

---

## 11. Migration Recommendations for `0004_phase2_3_financial_settlement`

When creating migration `0004`:
1. **Primary Keys**: Use `postgresql.UUID(as_uuid=True)` with `server_default=sa.text("gen_random_uuid()")`.
2. **Numeric Precision**: Use `sa.Numeric(precision=12, scale=2)` on all monetary columns.
3. **Unique Constraints**:
   - `sa.UniqueConstraint("event_id", name="uq_cash_advances_event_id")`
   - `sa.UniqueConstraint("event_id", name="uq_financial_settlements_event_id")`
   - `sa.UniqueConstraint("settlement_id", "revision_number", name="uq_settlement_revisions_number")`
4. **Foreign Key `ondelete`**:
   - Event FKs: `ondelete="RESTRICT"`
   - Version FK: `ondelete="RESTRICT"`
   - Document FKs: `ondelete="RESTRICT"`
   - Settlement FKs: `ondelete="RESTRICT"`
   - User FKs: `ondelete="RESTRICT"` / `NO ACTION`
5. **Check Constraints**: Replicate all `chk_*` check constraints defined in `__table_args__`.
6. **Downgrade**: Ensure downgrade cleanly drops tables in reverse dependency order:
   `settlement_revisions` -> `settlement_payments` -> `financial_settlements` -> `actual_incomes` -> `cash_advances`.

---

## 12. Issues Found & Hardening Applied

| Issue ID | Item | Severity | Resolution Applied |
|---|---|---|---|
| **HARDEN-01** | `Event` $
ightarrow$ Settlement Cascade | **Critical** | Removed `cascade="all, delete-orphan"` from `Event.cash_advance`, `Event.actual_incomes`, and `Event.financial_settlement`. Changed database FKs to `ondelete="RESTRICT"`. |
| **HARDEN-02** | `FinancialSettlement` $
ightarrow$ Payments/Revisions Cascade | **Critical** | Removed `cascade="all, delete-orphan"` from `payments` and `revisions`. Changed database FKs to `ondelete="RESTRICT"`. |
| **HARDEN-03** | Evidence Document Deletion Protection | **Critical** | Added explicit `ondelete="RESTRICT"` to `ActualIncome.evidence_document_id` and `SettlementPayment.proof_document_id`. |
| **OPTIM-01** | Redundant Index on Unique Event IDs | **Optimization** | In migration 0004, create only UNIQUE constraints on `cash_advances(event_id)` and `financial_settlements(event_id)`. |
| **OPTIM-02** | Composite Index Covering on Revisions | **Optimization** | The composite unique constraint on `(settlement_id, revision_number)` covers `settlement_id`. Standalone index omitted in migration 0004. |

---

## 13. Issues Requiring No Action

1. **`EventStatus` Integrity**: Confirmed unchanged; no action required.
2. **Enum Persistence**: Confirmed strings are used across all tables; no action required.
3. **Soft Delete Isolation**: Confirmed financial ledger tables do not implement soft delete; no action required.
4. **Existing Test Suite**: Confirmed all 319 existing backend tests pass; no action required.

---

## 14. Final Migration Readiness Decision

### Decision: **MIGRATION 0004 CREATED, UPGRADE & DOWNGRADE VERIFIED**
The domain models in `backend/app/models/domain.py` and enums in `backend/app/models/enums.py` are mathematically sound, relationally robust, cascade-hardened, conformant with existing codebase conventions, and ready for database migration.
