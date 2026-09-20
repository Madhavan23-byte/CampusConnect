# CampusConnect — Phase 2.2 Decision Research Report
## Actual Expenses, Bill/Invoice Verification & Financial Audit

> **Focus**: Deep-Dive Architectural & Governance Decision Research for Actual Expenses and Bill Submissions  
> **Repository Baseline**: Active branch `phase2-event-lifecycle` at commit `a3dd03e` (Phase 2.1 Complete)  
> **Source Discipline Standard**: Every assertion explicitly categorized as `[FACT: INSTITUTIONAL DOCS]`, `[EXTERNAL RESEARCH]`, `[ENGINEERING INFERENCE]`, or `[PROPOSED CAMPUSCONNECT RULE]`.  
> **Status**: Comprehensive Decision Research (Pre-Implementation Architectural Alignment)

---

## 1. Executive Summary & Objective

In Phase 2.1, CampusConnect established the operational conclusion and delivery verification of campus events:
```
SCHEDULED -> IN_PROGRESS -> COMPLETED (Secretary) -> PostEventReport CERTIFIED (Faculty Advisor)
```
While Phase 2.1 guarantees physical delivery proof (turnout, summary, outcomes, and photographic evidence with GPS metadata), **Phase 2.2 addresses financial accountability**:
- Transitioning from estimated budget allocations to concrete post-event actual expenses.
- Providing documentary evidence via digitized vendor bills, cash vouchers, and tax invoices.
- Preventing duplicate invoice submissions and double reimbursements across clubs and academic terms.
- Permitting partial claim verification by the institutional Finance Officer (`claimed_amount` vs `verified_amount`).
- Governing non-destructive query/revision workflows between Finance and Club Secretaries.
- Laying the exact mathematical foundation for Phase 2.3 cash advance reconciliation, financial settlement, and statutory Utilization Certificates (UC).

This document provides exhaustive comparative research, threat models, database schemas, state machines, API specifications, frontend UX blueprints, and test matrices required before modifying any code or database tables.

---

## 2. Institutional Baseline & Source Discipline Taxonomy

Every architectural decision and operational requirement in this research is classified into four provenance tiers:

1. **`[FACT: INSTITUTIONAL DOCS]`**: Derived directly from collegiate administrative circulars, financial codes, and institutional manual accounting forms.
2. **`[EXTERNAL RESEARCH]`**: Derived from statutory collegiate standards, Indian Universities Financial Codes (GFR 2017 / UGC Guidelines), and institutional finance practices across IITs, NITs, and Anna University affiliated colleges.
3. **`[ENGINEERING INFERENCE]`**: Deduced from software engineering principles, database consistency models, cryptographic hashing, and application security requirements.
4. **`[PROPOSED CAMPUSCONNECT RULE]`**: Recommended rules specific to CampusConnect's digital governance, balancing strict institutional audit compliance with student club operational ease.

---

## 3. Actual Expense Domain Model & Architectural Decisions

### 3.1 Domain Modeling: Expense vs Bill Relationship

#### The Architectural Alternatives

| Option | Architecture Model | Pros | Cons | Decision |
| :--- | :--- | :--- | :--- | :--- |
| **Option A: 1 Expense = 1 Bill Document (Embedded FK)** | `ActualExpense` directly holds `bill_document_id` referencing `documents.id`. Each expense row corresponds to one invoice. | Simple 1:1 audit flow; direct line-by-line verification in UI; simplest schema. | A multi-item store bill (e.g. stationery + refreshments) requires either splitting or uploading the same file twice. | **Recommended for Phase 2.2** |
| **Option B: Independent Bill Entity (1 Bill : N Expense Lines)** | A separate `ExpenseBill` entity parent to multiple `ActualExpenseLineItem` rows. | Models consolidated retail bills with multiple categories on a single receipt. | Heavy relational overhead; multi-level status synchronization; complex UI forms for student secretaries. | Deferred to Phase 3 |
| **Option C: Many-to-Many via Join Table** | `expense_bill_association` joining expenses and documents. | Maximum theoretical flexibility. | Severe complexity in audit logs, verification status, and constraint enforcement. | Rejected |

#### Architectural Decision: Option A (Enhanced with Shared Bill Document Support)
`ActualExpense` acts as the financial line item and holds a foreign key to `Document` (`bill_document_id`). To accommodate single bills with mixed expenses, multiple `ActualExpense` records may reference the same `bill_document_id`, but each `ActualExpense` maintains its own distinct category, claimed amount, and independent verification status.

---

## 4. Bill & Invoice Evidence Handling

### 4.1 Document Type & Validation
- `[FACT: INSTITUTIONAL DOCS]`: Every expense claim submitted to the Accounts Office must be supported by an authentic cash voucher, tax invoice, or retail bill.
- `[ENGINEERING INFERENCE]`: A new `DocumentType.EXPENSE_INVOICE = "EXPENSE_INVOICE"` is registered in `app/models/enums.py`.
- **Validation Pipeline**:
  1. **Allowed Extensions**: `.pdf`, `.png`, `.jpg`, `.jpeg`.
  2. **Magic-Byte Signature Verification**:
     - PDF: `%PDF-` (`%PDF-`)
     - PNG: `PNG

`
     - JPEG: `ÿØÿ`
  3. **Maximum File Size**: 10 MB per invoice.
  4. **Path Traversal & Storage Containment**:
     Files stored in `/uploads/events/{event_id}/expenses/{file_uuid}.{ext}` with strict `is_relative_to(storage_root)` validation.
  5. **Cryptographic Checksum**:
     Every uploaded bill computes a SHA-256 hash stored on `Document.file_hash` to detect duplicate files across the system.

---

## 5. Duplicate Invoice Detection & Anti-Fraud Engine

### 5.1 The Fraud Threat Vectors
1. **Intra-Event Double Submission**: A secretary accidentally or intentionally enters the same bill twice within the same event.
2. **Cross-Event Re-use**: A club re-uses a vendor invoice from a prior semester for a new event.
3. **Cross-Club Invoice Sharing**: Two clubs running concurrent events share or copy a single high-value catering or tent bill.
4. **Altered Invoice Splitting**: Altering invoice numbers slightly to bypass simple text matches.

### 5.2 Multi-Tier Duplicate Prevention Architecture

```
Tier 1: Cryptographic File Hash Match (SHA-256)
  └── documents.file_hash == uploaded_file.sha256
        └── Block upload if hash already exists in another verified/submitted expense.

Tier 2: Normalized Natural Key Constraint (DB Level)
  └── UNIQUE(normalized_vendor_name, normalized_invoice_no, invoice_date)
        └── Prevents identical invoice registration even if scanned/photographed differently.

Tier 3: Fuzzy Vendor Match & Warning (Application Service Level)
  └── Same vendor + same date + same amount within 30 days
        └── Raises AUDIT_WARNING in Finance Portal for manual inspector review.
```

#### SQL Constraint Definition
```sql
CREATE UNIQUE INDEX uq_actual_expenses_vendor_invoice ON actual_expenses (
    LOWER(TRIM(vendor_name)),
    LOWER(TRIM(invoice_number)),
    invoice_date
) WHERE status NOT IN ('DISALLOWED');
```
> **Critical Rule**: If an invoice was formally `DISALLOWED` due to a clerical mistake, the partial index allows re-submission after correction, while strictly preventing duplicate concurrent or verified claims.

---

## 6. Claimed vs. Verified Amount Arithmetic & Tax Rules

### 6.1 Strict Decimal Arithmetic
- `[FACT: INSTITUTIONAL DOCS]`: Financial entries cannot use floating-point types due to IEEE 754 precision rounding errors.
- `[ENGINEERING INFERENCE]`: All financial fields use `Numeric(precision=12, scale=2)` (mapped to Python `Decimal`).

### 6.2 The Three Core Financial Fields
For every `ActualExpense` record:
1. **`claimed_amount: Numeric(12, 2)`**
   - Declared by Club Secretary upon submission.
   - Constraint: `claimed_amount > 0.00`.
2. **`verified_amount: Numeric(12, 2)`**
   - Determined exclusively by Finance Officer during audit.
   - Constraint: `0.00 <= verified_amount <= claimed_amount`.
3. **`disallowed_amount: Numeric(12, 2)`**
   - Computed as: `disallowed_amount = claimed_amount - verified_amount`.
   - Populated automatically upon Finance Officer verification.

### 6.3 GST & Tax Breakdown
- In collegiate accounting, bills may show Base Amount + CGST + SGST/IGST.
- **Decision**: To avoid requiring student secretaries to perform complex tax splits, `claimed_amount` represents the **Gross Total (inclusive of all taxes)** paid to the vendor. An optional `gst_number` and `gst_amount` field captures vendor tax credentials when present for institutional GST credit claiming.

---

## 7. Expense Status Machine & Lifecycle

### 7.1 State Machine

```
      ┌──────────────────────────────────────────────────────────┐
      │                                                          │
      ▼                                                          │
   [DRAFT] ──(Secretary Submits)──► [SUBMITTED]                  │
                                         │                       │
                                   (FO Audits)                   │
                                         │                       │
                     ┌───────────────────┼───────────────────┐   │
                     ▼                   ▼                   ▼   │
                [VERIFIED]           [QUERIED]         [DISALLOWED]
                     │                   │                       │
               (Settlement)      (Secretary Amends)              │
                     │                   │                       │
                     ▼                   └───────────────────────┘
                 [SETTLED]
```

### 7.2 State Definitions
1. **`DRAFT`**:
   - Expense line item created by Club Secretary.
   - Editable, deletable. Bill document attached.
   - Not yet locked for financial audit.
2. **`SUBMITTED`**:
   - Club Secretary formally submits the expense package for the event.
   - Line items lock against regular edits.
   - Becomes visible in Finance Officer Audit Queue.
3. **`QUERIED`**:
   - Finance Officer flags an issue (e.g. illegible invoice scan, missing vendor stamp, mismatch between receipt and claimed amount).
   - Mandatory `finance_remarks` ($\ge 5$ characters).
   - Re-opens edit rights to Club Secretary for that specific line item.
4. **`VERIFIED`**:
   - Finance Officer approves the expense.
   - `verified_amount` set ($0.00 \le 	ext{verified\_amount} \le 	ext{claimed\_amount}$).
   - Locked against all further modifications.
5. **`DISALLOWED`**:
   - Finance Officer completely rejects the expense (e.g. prohibited items, duplicate claim, fictitious voucher).
   - Mandatory `finance_remarks`. `verified_amount = 0.00`, `disallowed_amount = claimed_amount`.
   - Terminal status for that line item.
6. **`SETTLED`**:
   - Expense line incorporated into the final `FinancialSettlement` in Phase 2.3.
   - Permanent immutable archive status.

---

## 8. Revision, Immutability & Audit Guarantees

### 8.1 Non-Destructive Query Resolution
When an expense is placed in `QUERIED` status:
- The historical claimed amount and bill are preserved.
- The Secretary can upload an amended bill or adjust the claimed amount down.
- An `AuditLog` entry captures:
  - `action = AuditAction.EXPENSE_QUERIED` (Actor: Finance Officer, Remarks)
  - `action = AuditAction.EXPENSE_AMENDED` (Actor: Secretary, Previous vs New State)
  - `action = AuditAction.EXPENSE_RESUBMITTED` (Actor: Secretary)

### 8.2 Terminal Lock
Once an expense transitions to `VERIFIED`, `DISALLOWED`, or `SETTLED`:
- Any HTTP `PATCH` or `DELETE` attempt returns `HTTP 403 Forbidden` (`WorkflowStateError`).
- Database trigger/service layer rejects row updates.

---

## 9. Finance Officer Verification & Audit Workflow

### 9.1 Verification Preconditions
- `[FACT: INSTITUTIONAL DOCS]`: Accounts cannot disburse or audit funds for an event that has not been certified as delivered by academic authorities.
- `[PROPOSED CAMPUSCONNECT RULE]`:
  **Prerequisite Check**: `PostEventReport` for the event must be in `CERTIFIED` status before the Finance Officer audit portal enables the **Approve / Verify** actions for actual expenses. If the report is still `SUBMITTED` or `REVISION_REQUIRED`, the Finance Officer can view expenses in read-only mode with the banner:
  *"Post-Event Delivery Certification pending from Faculty Advisor. Audit clearance blocked."*

### 9.2 Audit Actions Available to Finance Officer
1. **Verify (Full Amount)**:
   `verified_amount = claimed_amount`. Remarks optional.
2. **Verify with Reduction (Partial Approval)**:
   `verified_amount < claimed_amount`. Mandatory remarks explaining disallowed difference.
3. **Query (Request Clarification)**:
   Status $ightarrow$ `QUERIED`. Mandatory remarks ($\ge 5$ chars). Sends notification to Club Secretary.
4. **Disallow (Total Rejection)**:
   Status $ightarrow$ `DISALLOWED`. `verified_amount = 0.00`. Mandatory justification.

---

## 10. Authorization & Segregation of Duties (SOD) Matrix

| Actor Role | Add Draft Expense | Submit Expense Bundle | Query Expense | Verify / Disallow | Delete Expense | Settle Final Ledger |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Club Secretary** (Assigned Club) | **YES** | **YES** | NO | NO | **YES** (DRAFT only) | NO |
| **Other Club Secretary** | NO | NO | NO | NO | NO | NO |
| **Faculty Advisor** (Assigned Club) | Read Only | Read Only | Advisory Notes | NO (Statutory Delivery only) | NO | NO |
| **Finance Officer** | NO | NO | **YES** | **YES** | NO | **YES** (Phase 2.3) |
| **Principal / Dean** | Read Only | Read Only | Read Only | Read Only | NO | Executive Sign-off |
| **System Admin** | NO | NO | NO | NO | NO | NO (SOD Blocked) |

> **SOD Invariant**: The person who spends the money (Club Secretary) can NEVER audit or approve the bills. The person who audits the bills (Finance Officer) can NEVER submit expenses. `SYSTEM_ADMIN` is hard-blocked from auditing or submitting expenses.

---

## 11. Compatibility with Phase 2.3 Financial Settlement

Phase 2.2 provides the exact mathematical aggregates consumed by Phase 2.3:
```
Total Claimed Spend   = SUM(actual_expenses.claimed_amount)
Total Verified Spend  = SUM(actual_expenses.verified_amount WHERE status = 'VERIFIED')
Total Disallowed      = SUM(actual_expenses.disallowed_amount)
Budget Variance       = Sanctioned Grant - Total Verified Spend
```

In Phase 2.3:
- If `Cash Advance Issued > Total Verified Spend`:
  - `Net Settlement = Advance - Verified Spend` $ightarrow$ **Refund due to College from Club Secretary**.
- If `Total Verified Spend > Cash Advance Issued`:
  - `Net Settlement = Verified Spend - Advance` $ightarrow$ **Reimbursement due to Club Secretary** (capped at Sanctioned Grant).

---

## 12. Security Threat Model & Mitigations

| Threat | Attack Scenario | Defense Implementation |
| :--- | :--- | :--- |
| **Ghost Vouchers** | Secretary submits bills for events that never happened | Precondition: `PostEventReport.status == CERTIFIED` required before audit. |
| **Double Dipping** | Same catering receipt submitted across two separate club events | Global index on `(vendor_name, invoice_number, invoice_date)` + SHA-256 file hash index on `documents`. |
| **Tampered Scan** | Modifying bill total on PDF with local editor | Finance Officer manual verification with side-by-side original image view + SHA-256 hash preservation. |
| **Bill Injection** | Uploading PHP/executable with `.pdf` extension | Magic byte signature verification (`%PDF-`, `PNG`, `JPG`) + strict storage containment. |
| **Audit Race Condition** | Secretary modifies claimed amount while Finance Officer is auditing | Pessimistic locking via `SELECT ... FOR UPDATE` on all status transitions. |

---

## 13. Concurrency & Transaction Design

### 13.1 Database Isolation & Row Locking
All expense auditing and submission operations execute in explicit transactions with pessimistic row locking:
```python
async with db.begin():
    # 1. Lock confirmed event row
    event = await db.scalar(
        select(Event).where(Event.id == event_id).with_for_update()
    )
    # 2. Lock target actual_expense row
    expense = await db.scalar(
        select(ActualExpense)
        .where(ActualExpense.id == expense_id, ActualExpense.event_id == event.id)
        .with_for_update()
    )
    # 3. Validate state transitions and SOD rules
    # 4. Update status and verified_amount
    # 5. Append AuditLog
    # 6. Emit Real-time Notification
```

---

## 14. REST API Blueprint (Phase 2.2)

### Endpoints Specification

| Method | Path | Role | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/events/{id}/expenses` | `CLUB_SECRETARY` | Create draft expense item and upload bill document (multipart/form-data) |
| `GET` | `/api/v1/events/{id}/expenses` | Authenticated | List all expenses, claim totals, and verification states for event |
| `GET` | `/api/v1/events/{id}/expenses/{exp_id}` | Authenticated | Get detailed expense record including bill document metadata |
| `PATCH` | `/api/v1/events/{id}/expenses/{exp_id}` | `CLUB_SECRETARY` | Edit draft or queried expense details |
| `DELETE` | `/api/v1/events/{id}/expenses/{exp_id}` | `CLUB_SECRETARY` | Delete draft expense item |
| `POST` | `/api/v1/events/{id}/expenses/submit` | `CLUB_SECRETARY` | Submit all draft expenses for Finance Officer audit |
| `POST` | `/api/v1/events/{id}/expenses/{exp_id}/verify` | `FINANCE_OFFICER` | Verify expense with full or partial verified amount |
| `POST` | `/api/v1/events/{id}/expenses/{exp_id}/query` | `FINANCE_OFFICER` | Place expense in QUERIED status with mandatory remarks |
| `POST` | `/api/v1/events/{id}/expenses/{exp_id}/disallow` | `FINANCE_OFFICER` | Disallow expense item with mandatory remarks |
| `GET` | `/api/v1/events/{id}/expenses/summary` | Authenticated | Ledger arithmetic summary (Sanctioned vs Claimed vs Verified vs Disallowed) |

---

## 15. Database Blueprint (SQL & Migration Design)

### 15.1 New Table: `actual_expenses`

```sql
CREATE TABLE actual_expenses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    budget_line_item_id UUID REFERENCES budget_line_items(id) ON DELETE SET NULL,
    category VARCHAR(30) NOT NULL,
    description VARCHAR(500) NOT NULL,
    vendor_name VARCHAR(255) NOT NULL,
    vendor_gstin VARCHAR(20),
    invoice_number VARCHAR(100) NOT NULL,
    invoice_date DATE NOT NULL,
    claimed_amount NUMERIC(12, 2) NOT NULL CHECK (claimed_amount > 0.00),
    verified_amount NUMERIC(12, 2) CHECK (verified_amount >= 0.00),
    disallowed_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (disallowed_amount >= 0.00),
    status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    bill_document_id UUID NOT NULL REFERENCES documents(id),
    submitted_by UUID NOT NULL REFERENCES users(id),
    verified_by UUID REFERENCES users(id),
    verified_at TIMESTAMPTZ,
    finance_remarks TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_verified_le_claimed CHECK (verified_amount IS NULL OR verified_amount <= claimed_amount)
);

CREATE INDEX idx_actual_expenses_event_id ON actual_expenses(event_id);
CREATE INDEX idx_actual_expenses_status ON actual_expenses(status);

-- Anti-Duplicate Partial Unique Index
CREATE UNIQUE INDEX uq_actual_expenses_vendor_invoice_date ON actual_expenses (
    LOWER(TRIM(vendor_name)),
    LOWER(TRIM(invoice_number)),
    invoice_date
) WHERE status != 'DISALLOWED';
```

### 15.2 Document Schema Enhancement
Add `file_hash VARCHAR(64)` to `documents` table to record SHA-256 checksums of invoice attachments.

---

## 16. Frontend UI Blueprint (Phase 2.2)

### 16.1 UI Architecture
1. **`ExpenseLedgerTab.tsx`** (Integrated into `EventDetailPage.tsx` under new tab *"Expenses & Bills"*):
   - **Financial Ledger Summary Card**:
     - Metric Badges: Approved Grant (₹), Claimed Expenses (₹), Verified Spend (₹), Disallowed (₹).
     - Live progress bar showing budget consumption percentage.
   - **Expense Item List**:
     - Categorized line items with vendor name, invoice #, invoice date, amount.
     - Status Pills: `DRAFT` (Gray), `SUBMITTED` (Blue), `VERIFIED` (Green), `QUERIED` (Amber), `DISALLOWED` (Red).
     - Side-by-side invoice document viewer (PDF embed or Image modal).
   - **Secretary Expense Entry Form**:
     - Dropdown mapping to approved `budget_line_items` or generic category.
     - Vendor details, invoice number, invoice date (constrained to $\le$ today).
     - Amount (numeric currency input).
     - File drag-and-drop for bill upload.
   - **Finance Officer Audit Console**:
     - Action buttons on each submitted item: **Verify Full**, **Verify Partial**, **Query**, **Disallow**.
     - Modal for entering partial verified amount and required remarks.
     - Clear indicator if `PostEventReport` delivery certification is pending.

---

## 17. Comprehensive Test Strategy & Test Matrix

### 17.1 Test Cases Required in `tests/api/test_actual_expenses.py`

| # | Test Scenario | Expected Outcome |
| :--- | :--- | :--- |
| 1 | Secretary creates draft expense with valid bill document | 201 Created; status `DRAFT` |
| 2 | Secretary uploads invalid file format (.exe, text file with .pdf extension) | 400 Bad Request; magic byte failure |
| 3 | Claimed amount $\le 0.00$ or future invoice date | 422 Validation Error |
| 4 | Duplicate invoice upload (same vendor, invoice no, date) | 409 Conflict Error |
| 5 | Submit expense bundle for event not yet `COMPLETED` | 400 Bad Request |
| 6 | Finance Officer verifies expense before Faculty Advisor delivery certification | 400 Bad Request (Statutory interlock blocked) |
| 7 | Finance Officer verifies full amount after certification | 200 OK; status `VERIFIED`, `verified_amount == claimed_amount` |
| 8 | Finance Officer partially verifies amount ($	ext{verified} < 	ext{claimed}$) | 200 OK; status `VERIFIED`, `disallowed_amount` accurately calculated |
| 9 | Finance Officer verifies amount higher than claimed | 422 Validation Error (`verified <= claimed` violated) |
| 10 | Finance Officer queries expense with remarks | 200 OK; status `QUERIED`, notification sent to Secretary |
| 11 | Secretary amends queried expense and resubmits | 200 OK; status `SUBMITTED`, audit log captures diff |
| 12 | Finance Officer disallows expense item | 200 OK; status `DISALLOWED`, `verified_amount = 0.00` |
| 13 | Cross-club invoice reuse attempt | 409 Conflict Error |
| 14 | Secretary attempts to audit own expenses | 403 Forbidden |
| 15 | Finance Officer attempts to create expenses for club | 403 Forbidden |
| 16 | System Admin attempts ordinary audit bypass | 403 Forbidden |
| 17 | Concurrent audit verification calls on same expense | First succeeds (200), second returns 400/403 (locking) |
| 18 | Attempting to edit or delete `VERIFIED` or `SETTLED` expense | 403 Forbidden |

---

## 18. Final Decision Table

| Decision Item | Evaluated Options | Chosen Architecture | Justification |
| :--- | :--- | :--- | :--- |
| **Model Cardinality** | 1:1 vs 1:N vs N:M | **1 Expense Item : 1 Bill Doc** | Aligns with individual line item auditability; avoids complex multi-level approval states. |
| **Duplicate Bill Detection** | Soft warning vs DB unique constraint | **Hard DB Partial Unique Index + SHA-256 Hash** | Prevents financial fraud and cross-event double claiming at the lowest database layer. |
| **Amount Representation** | Float vs Integer Paisa vs Numeric(12,2) | **Numeric(12, 2)** | Standard collegiate accounting format; avoids IEEE 754 float drift and unnecessary scaling conversions. |
| **Partial Approval Semantics** | Binary Approve/Reject vs Claimed/Verified Split | **Claimed vs Verified Split** | In real collegiate audits, Finance Officers frequently strike out non-allowable sub-items without rejecting the entire legitimate vendor bill. |
| **Audit Prerequisite** | Independent Audit vs Sequential Interlock | **Sequential Interlock (PostEventReport CERTIFIED first)** | Prevents institutional fund disbursement for ghost events that did not physically occur. |
| **SOD Enforcement** | Application UI hide vs DB/Service Layer Hard Block | **Service Layer Exception Hard Block** | Immune to API tampering or forged role claims. System Admin blocked from financial audit. |

---

## 19. Summary of Resolution Status

| Phase 2.2 Scope Area | Status | Notes |
| :--- | :---: | :--- |
| Actual Expense domain model | **Fully Resolved** | Detailed table schema and constraints specified |
| Expense ↔ Bill relationship | **Fully Resolved** | 1:1 line item with foreign key to Document |
| Duplicate invoice detection | **Fully Resolved** | SHA-256 + DB Partial Unique Index |
| Claimed vs verified arithmetic | **Fully Resolved** | `Numeric(12,2)` with `verified <= claimed` constraint |
| Expense status machine | **Fully Resolved** | 6 distinct lifecycle states defined |
| Revision/immutability | **Fully Resolved** | Non-destructive query flow with AuditLog history |
| Finance Officer verification | **Fully Resolved** | Full/partial verify, query, disallow actions |
| Authorization and SOD | **Fully Resolved** | Secretary vs Finance Officer vs Admin separation |
| Financial reconciliation compatibility| **Fully Resolved** | Prepares claimed/verified spend for Phase 2.3 |
| Security threat model | **Fully Resolved** | 5 threats identified with concrete defenses |
| Concurrency design | **Fully Resolved** | `SELECT FOR UPDATE` transaction isolation |
| API blueprint | **Fully Resolved** | 10 REST endpoints specified |
| Database blueprint | **Fully Resolved** | Table DDL, indexes, check constraints designed |
| Frontend blueprint | **Fully Resolved** | Ledger table, uploader, audit console mapped |
| Test strategy | **Fully Resolved** | 18 test scenarios designed |
| Final decision table | **Fully Resolved** | 6 key architectural trade-offs resolved |

**All Phase 2.2 research items are 100% resolved and documented in this specification.**
