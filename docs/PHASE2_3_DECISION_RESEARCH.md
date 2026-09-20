# CampusConnect — Phase 2.3 Decision Research Report
## Financial Settlement, Cash Advance Reconciliation, and Institutional Ledger Closure

> **Focus**: Production-Grade Architecture for Post-Event Financial Settlement, Cash Advance Reconciliation, Actual Income Offsetting, Reimbursement/Refund Workflows, and Event Closure Prerequisites
> **Repository Baseline**: Commit `1117541` (`feat(phase2): add actual expense ledger and finance verification`)
> **Status**: RESEARCH & ARCHITECTURE DECISION ONLY (IMPLEMENTATION STATUS: NOT IMPLEMENTED)
> **Evidence Taxonomy**:
> - `[FACT: INSTITUTIONAL DOCUMENT]`: Formally documented in college circulars, Day 7 governance audits, or pre-existing project charter.
> - `[EXTERNAL RESEARCH]`: Established practice in Indian & global university financial regulations (IITs, NITs, Central Universities, GFR 2017, US/UK student activity governance).
> - `[ENGINEERING INFERENCE]`: Derived from database relational integrity, atomic concurrency, idempotency, or cryptography.
> - `[PROPOSED CAMPUSCONNECT RULE]`: Synthesized business rule proposed for CampusConnect.
> - `[EVIDENCE INSUFFICIENT — REQUIRES INSTITUTIONAL CONFIRMATION]`: Policy ambiguity requiring explicit institutional sign-off.

---

## 1. Executive Summary

CampusConnect Phase 2.2 successfully established the **Verified Expense Ledger** (`ActualExpense`) at commit `1117541`:
```
Event (SCHEDULED)
  ↓ Execution Start
Event (IN_PROGRESS)
  ↓ Execution Conclusion
Event (COMPLETED)
  ↓ Secretary Post-Event Report
PostEventReport (SUBMITTED)
  ↓ Faculty Advisor Delivery Certification
PostEventReport (CERTIFIED)
  ↓ Secretary Records & Submits Claims
ActualExpense (SUBMITTED)
  ↓ Finance Officer Bill Verification
ActualExpense (VERIFIED / PARTIALLY_VERIFIED / DISALLOWED)
  ↓
VERIFIED EXPENSE LEDGER
```

Phase 2.3 addresses the crucial **accounting bridge** between the Verified Expense Ledger and final Event Closure. While Phase 2.2 verified individual vendor invoices against physical delivery, it did not perform macro-financial settlement:
1. It did not reconcile expenditures against the pre-event **Sanctioned Institutional Grant**.
2. It did not account for pre-event **Cash Advances** disbursed to student organizers.
3. It did not capture **Actual Event Revenue** (participant registration fees, sponsorships, ticketing) that institutional accounting rules require to offset college grant liability.
4. It did not determine whether the college owes a **Reimbursement** ($B > 0$) or the club must remit a **Refund** ($B < 0$).
5. It did not prepare the financial ledger data required for the statutory **Utilization Certificate (UC)**.

This research establishes the comprehensive, production-grade architectural specification for Phase 2.3, preserving strict segregation of duties (SOD), cryptographic evidence linkages, and immutable ledger history.

---

## 2. Existing System Inspection (Commit `1117541`)

A thorough inspection of the CampusConnect codebase at stable commit `1117541` reveals the following architectural baseline:

| Component | Current Implementation | Phase 2.3 Relevance |
|---|---|---|
| **`Event` Model** ([`domain.py:924`](file:///E:/Se-Mini-Project/backend/app/models/domain.py#L924)) | Canonical entity in `events` table. Lifecycle status: `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`. Contains `event_request_id` (1:1 with proposal), `club_id`, `hall_id`. Soft-delete enabled. | The root entity for financial settlement. Settlement must be bound 1:1 to a `COMPLETED` event. |
| **`EventRequest` & `Version`** ([`domain.py:461`](file:///E:/Se-Mini-Project/backend/app/models/domain.py#L461)) | Pre-event approval pipeline. Preserves historical proposal versions. Version holds approved `BudgetProposal`. | Authoritative source of original budget proposal. |
| **`BudgetProposal`** ([`domain.py:559`](file:///E:/Se-Mini-Project/backend/app/models/domain.py#L559)) | Pre-event budget estimate: `expected_income`, `institute_contribution`, `total_expected_expenditure`. `Numeric(12,2)`. | `institute_contribution` represents the pre-event requested grant ceiling. Must be snapshotted at settlement time. |
| **`BudgetLineItem`** ([`domain.py:620`](file:///E:/Se-Mini-Project/backend/app/models/domain.py#L620)) | Itemized budget estimates categorized by `BudgetLineItemCategory` (`MATERIALS`, `TRAVEL`, `PRINTING`, `FOOD`, `EQUIPMENT`, `OTHER`). | Baseline for variance analysis ($\text{Verified} - \text{Estimated}$). |
| **`PostEventReport`** ([`domain.py:1120`](file:///E:/Se-Mini-Project/backend/app/models/domain.py#L1120)) | Phase 2.1 execution deliverable. `actual_attendance`, `summary`, `status` (`DRAFT`, `SUBMITTED`, `REVISION_REQUIRED`, `CERTIFIED`), `certified_by` (Faculty Advisor). | **Prerequisite**: Delivery certification by Faculty Advisor is mandatory before financial verification or settlement. |
| **`ActualExpense`** ([`domain.py:1170`](file:///E:/Se-Mini-Project/backend/app/models/domain.py#L1170)) | Phase 2.2 expense ledger: `claimed_amount`, `verified_amount`, `disallowed_amount` (derived), `status` (`DRAFT`, `SUBMITTED`, `VERIFIED`, `PARTIALLY_VERIFIED`, `QUERIED`, `DISALLOWED`). Mandatory bill link (`bill_document_id`). `submitted_by` (NOT NULL). | Source of truth for expenditure total: $V = \sum v_i$. All expenses must be terminal before settlement. |
| **`Document` & `DocumentService`** ([`domain.py:734`](file:///E:/Se-Mini-Project/backend/app/models/domain.py#L734)) | Magic-byte validated file storage, SHA-256 duplicate detection via `file_hash`, strict event ownership (`event_id`). | Will support settlement refund receipts, income deposit proofs, and disbursement vouchers. |
| **`AuditLog`** ([`domain.py:1052`](file:///E:/Se-Mini-Project/backend/app/models/domain.py#L1052)) | Append-only audit table with `actor_id`, `actor_email`, `actor_role`, `action`, `previous_state`, `new_state` JSON snapshots. | Preserves complete history of settlement creation, auditing, revisions, and payment records. |
| **`NotificationService`** | Event-driven notification router for targeted alerts to Secretary, Finance Officer, Advisor, and Principal. | Alerts stakeholders when settlement is generated, audited, approved, or payment pending. |
| **Numeric Conventions** | All monetary columns use PostgreSQL `NUMERIC(12,2)` and Python `Decimal`. | Maintained strictly across all Phase 2.3 settlement calculations to eliminate binary floating-point drift. |

---

## 3. Institutional Reference Findings

Analysis of project artifacts (`DAY7_BUSINESS_RULES.md`, `PHASE2_ARCHITECTURE.md`, `PHASE2_DECISION_RESEARCH.md`) and institutional governance conventions confirms:

1. **Pre-Event Funding Grant Definition**:
   - `[FACT: INSTITUTIONAL DOCUMENT]`: The college budget proposal sheet formally splits expected finance into `institute_contribution` (funds requested from college coffers) and `expected_income` (sponsorships, delegate fees).
   - `[FACT: INSTITUTIONAL DOCUMENT]`: The Principal's signature at Step 6 constitutes the legal sanction of the `institute_contribution` as the maximum institutional financial commitment ($G_{sanctioned}$).
2. **Two-Tier Post-Event Segregation of Duties**:
   - `[FACT: INSTITUTIONAL DOCUMENT]`: The Faculty Advisor must certify actual physical delivery and verify that the event took place as approved before financial claims are paid out.
   - `[FACT: INSTITUTIONAL DOCUMENT]`: The Finance Officer possesses exclusive statutory responsibility for auditing bills, checking GST/vouchers, enforcing tax compliance, and verifying financial amounts.
   - `[FACT: INSTITUTIONAL DOCUMENT]`: Administrative IT personnel (`SYSTEM_ADMIN`) are legally barred from verifying financial claims or authorizing disbursements.
3. **Cash Advance Settlement Mandate**:
   - `[FACT: INSTITUTIONAL DOCUMENT]`: Any cash advance disbursed to a club organizer represents an institutional liability charged against that student/faculty member until formally liquidated with verified original bills.
   - `[FACT: INSTITUTIONAL DOCUMENT]`: Unspent advance money must be refunded to the college cashier/accounts section with an official receipt.
4. **Institutional Documentation Gaps**:
   - `[EVIDENCE INSUFFICIENT — REQUIRES INSTITUTIONAL CONFIRMATION]`: Does the institution enforce a formal percentage cap on pre-event cash advances (e.g., maximum 50% or 80% of sanctioned grant), or is it determined ad-hoc per event?
   - `[EVIDENCE INSUFFICIENT — REQUIRES INSTITUTIONAL CONFIRMATION]`: If an event generates net surplus income ($I_{actual} > V$), does the college retain the surplus in a central student activity fund, or is it credited to the club's rolling reserve ledger?

---

## 4. External University Financial Research

Comparative research into real-world institutional frameworks (IIT Bombay, IIT Madras, National Institutes of Technology, University of Delhi, Government of India General Financial Rules [GFR 2017 Rule 238], and international universities including Princeton, Minnesota, and Brunel) reveals consistent patterns:

### 4.1 Advance Issuance & Liquidation
- **`[EXTERNAL RESEARCH]` (IITs / NITs)**: Cash advances for student events are issued to the designated Faculty Advisor or Club Treasurer only after executive sanction. Advances are treated as temporary personal imprests.
- **`[EXTERNAL RESEARCH]` (GFR 2017 / Central Universities)**: Advances must be liquidated within a strict statutory timeframe (typically **14 to 30 days**) following event completion. Failure to submit bills blocks all future advance requests and financial clearances for that student organization.
- **`[EXTERNAL RESEARCH]` (University Finance Manuals)**: If actual verified expenditure is less than the advance, the unspent cash must be deposited into the university bank account via challan/NEFT before the advance is marked settled.

### 4.2 Revenue Recognition & Self-Generated Income
- **`[EXTERNAL RESEARCH]` (Autonomous Collegiate Norms)**: Universities distinguish between institutional grants (taxpayer or endowment funds) and student-raised revenue (sponsorships, delegate fees, ticket sales).
- **`[EXTERNAL RESEARCH]`**: Institutional grants are "last-dollar" or "deficit-funding" commitments. If a club secures sponsorships or registration fees, these revenues must first offset actual event expenditures. The college grant covers only the **unfunded net deficit**. The college does not disburse grant money for expenses already covered by external sponsors.

### 4.3 Utilization Certificates (UC)
- **`[EXTERNAL RESEARCH]` (GFR Form 12-A / AICTE / DST)**: A Utilization Certificate is a formal statutory document certifying that funds sanctioned were spent strictly for the purposes for which they were sanctioned. A UC requires:
  - Sanctioned grant amount ($G_{sanctioned}$)
  - Actual expenditure incurred ($V$)
  - Revenue/interest earned ($I_{actual}$)
  - Unspent balance refunded ($G_{sanctioned} - P$)
  - Dual certification: Finance Officer (accounts audit) and Head of Institution / Principal (executive sanction).

---

## 5. Reconciling the Approved Accounting Model

The mathematical accounting model established during Phase 2 architecture reconciliation is formally validated as follows:

### 5.1 Mathematical Formulation
Let:
- $G_{sanctioned} \ge 0$: Sanctioned institutional grant (from approved `BudgetProposal.institute_contribution`).
- $E_{sanctioned} \ge 0$: Total approved expenditure ceiling (from `BudgetProposal.total_expected_expenditure`).
- $A \ge 0$: Cash advance actually disbursed by Finance to the club.
- $c_i > 0$: Claimed amount for expense item $i$.
- $v_i \ge 0$: Verified amount for expense item $i$ ($v_i \le c_i$).
- $C = \sum_{i=1}^{n} c_i$: Total claimed expenditure.
- $V = \sum_{i=1}^{n} v_i$: Total verified expenditure.
- $I_{actual} \ge 0$: Total verified event income (sum of verified `ActualIncome` records).

#### Step 1: Net Deficit Calculation
The net expenditure requiring external funding after applying all self-generated event revenue is:
$$\text{Net Deficit} = \max(0, V - I_{actual})$$
- `[PROPOSED CAMPUSCONNECT RULE]`: If $I_{actual} \ge V$, the event was entirely self-funding ($\text{Net Deficit} = 0$).

#### Step 2: Institutional Payout Liability ($P$)
The college's actual financial contribution liability is capped at both the sanctioned grant and the net deficit:
$$P = \min(G_{sanctioned}, \text{Net Deficit})$$
- The college never contributes more than it originally sanctioned ($P \le G_{sanctioned}$).
- The college never contributes more than the actual net deficit ($P \le \text{Net Deficit}$).

#### Step 3: Final Settlement Balance ($B$)
The net cash transfer required to clear the event ledger against the advance already disbursed is:
$$B = P - A$$

#### Step 4: Directional Settlement Interpretation
- **Case 1 ($B > 0$) — Net Reimbursement Payable**:
  - The advance $A$ was insufficient to cover the college's verified liability $P$.
  - **Action**: College Finance disburses reimbursement of amount $B$ to the Club Secretary/Advisor.
  - Settlement enters `PENDING_REIMBURSEMENT`.
- **Case 2 ($B < 0$) — Net Refund Receivable**:
  - The advance $A$ exceeded the college's verified liability $P$.
  - **Action**: The club must remit an unspent advance refund of $|B|$ to the college bank account.
  - Settlement enters `PENDING_REFUND`.
- **Case 3 ($B = 0$) — Balanced Settlement**:
  - The advance $A$ exactly matched the college liability $P$, or both were zero.
  - **Action**: No cash movement required. Ledger transitions directly to `SETTLED`.

#### Step 5: Variance & Utilization Metrics
- **Budget Expenditure Variance**: $\Delta_{budget} = V - E_{sanctioned}$
  - $\Delta_{budget} \le 0$: Under-budget / On-budget.
  - $\Delta_{budget} > 0$: Over-budget expenditure.
- **Grant Utilization Rate**: $\text{Util} = \begin{cases} \left(\frac{P}{G_{sanctioned}}\right) \times 100\% & \text{if } G_{sanctioned} > 0 \\ 100\% & \text{if } G_{sanctioned} = 0 \end{cases}$
- **Unspent / Surrendered Grant**: $U = G_{sanctioned} - P \ge 0$

---

## 6. Sanctioned Grant vs Budget Proposal Snapshotting

### 6.1 The Mutable Proposal Vulnerability
`[ENGINEERING INFERENCE]`: In pre-event phases, `BudgetProposal` can be updated during workflow revisions (`REVISION_REQUIRED`). If a post-event `FinancialSettlement` dynamically reads `BudgetProposal.institute_contribution` via runtime SQL join, any subsequent modification, retro-active script, or proposal amendment would silently mutate historical settlement arithmetic, violating audit immutability.

### 6.2 Mandatory Settlement Snapshotting
`[PROPOSED CAMPUSCONNECT RULE]`: When a `FinancialSettlement` record is created, the system must atomically capture and persist an **immutable financial snapshot**:
1. `sanctioned_grant: Decimal = event.approved_version.budget_proposal.institute_contribution`
2. `sanctioned_expenditure: Decimal = event.approved_version.budget_proposal.total_expected_expenditure`
3. `expected_income: Decimal = event.approved_version.budget_proposal.expected_income`
4. `approved_version_id: UUID = event.approved_version_id`

Once created, `FinancialSettlement` performs all reconciliation exclusively against these snapshotted fields, ensuring permanent determinism.

---

## 7. Cash Advance Model

### 7.1 Architecture Options Evaluated

| Model | Structure | Institutional Fit | Recommended |
|---|---|---|:---:|
| **Option A: No Advance (Reimbursement Only)** | No cash given before event. Students spend own money; college reimburses post-event. | Eliminates advance risk, but imposes unfair financial hardship on students for large events. | NO |
| **Option B: Unconstrained Multiple Advances** | Secretary requests multiple partial advances before and during event. | High operational complexity; excessive cash-handling risks; difficult reconciliation. | NO |
| **Option C: Single Advance per Event (Configurable Cap)** | Exactly one advance record per event (`0.00` to sanctioned ceiling). Formal request, Finance approval, and disbursement tracking. | **Standard Collegiate Practice**: Transparent, clean 1:1 reconciliation, minimal risk. | **YES** |

### 7.2 Approved Advance Lifecycle (`AdvanceStatus`)
`[PROPOSED CAMPUSCONNECT RULE]`:
```
NOT_REQUESTED
  ↓ Secretary Requests
REQUESTED
  ↓ Finance Officer Approves & Disburses
DISBURSED
  ↓ (Or Rejected by Finance)
REJECTED
```
- Advance record fields: `amount_requested`, `amount_approved`, `amount_disbursed`, `disbursement_date`, `disbursement_reference` (NEFT/Cheque/Cash Receipt #), `recipient_user_id`.
- Constraint: Advance cannot be disbursed before `Event.status == SCHEDULED`.
- Constraint: The fundamental architectural safety boundary is `0 <= amount_disbursed <= sanctioned_grant`. CampusConnect does not hard-code an arbitrary institutional percentage (such as 80%). If a ceiling ratio is introduced, it must be configuration-driven and explicitly recognized as a software safeguard rather than unverified institutional policy.

---

## 8. Actual Income Model

### 8.1 Why a First-Class `ActualIncome` Entity is Recommended
`[PROPOSED CAMPUSCONNECT RULE]` & `[ENGINEERING INFERENCE]`:
*Note: While institutional pre-event budgets capture expected income, capturing post-event actual income as a distinct database entity is an architectural proposal and engineering inference to guarantee financial integrity, not an explicit institutional paper-form mandate.* Merely adding an `actual_income NUMERIC(12,2)` field to `FinancialSettlement` is unacceptable in production institutional accounting:
1. **Multiple Income Sources**: A major campus event receives revenue from multiple distinct channels:
   - Delegate registration fees (participant tickets)
   - Title / Corporate sponsorships
   - Food/exhibition stall rentals
   - College merchandise sales
2. **Documentary Evidence Requirement**: Every income claim requires supporting documentation:
   - Bank statement credit entry (PDF/PNG)
   - Sponsorship MOU / Agreement
   - Counterfoil receipt summary signed by Faculty Advisor
3. **Auditability & Verification**: Income must undergo Finance verification. An unverified scalar income field could be fabricated to disguise deficits or misappropriate unspent grants.

### 8.2 `ActualIncome` Domain Model
`[PROPOSED CAMPUSCONNECT RULE]`:
- **Fields**:
  - `id: UUID PRIMARY KEY`
  - `event_id: UUID NOT NULL REFERENCES events(id)`
  - `source_type: IncomeSourceType` (`REGISTRATION_FEE`, `SPONSORSHIP`, `STALL_RENTAL`, `TICKET_SALES`, `DONATION`, `OTHER`)
  - `description: VARCHAR(500) NOT NULL`
  - `payer_name: VARCHAR(255) NOT NULL` (Sponsor company or participant batch)
  - `amount: NUMERIC(12,2) NOT NULL` (Check: `amount > 0.00`)
  - `received_date: DATE NOT NULL`
  - `reference_number: VARCHAR(100) NULL` (Bank UTR / Cash receipt number)
  - `evidence_document_id: UUID NOT NULL REFERENCES documents(id)`
  - `status: IncomeStatus` (`RECORDED`, `VERIFIED`, `REJECTED`)
  - `recorded_by: UUID NOT NULL REFERENCES users(id)`
  - `verified_by: UUID NULL REFERENCES users(id)`
  - `verified_at: TIMESTAMPTZ NULL`
  - `finance_remarks: TEXT NULL`

---

## 9. Expenses vs Income Reconciliation (Edge Cases)

Let $G_{sanctioned} = ₹30,000$, Advance $A = ₹10,000$.

### Case A: Typical Funded Event ($V = ₹25,000$, $I_{actual} = ₹5,000$)
- $\text{Net Deficit} = \max(0, 25000 - 5000) = ₹20,000$
- $P = \min(30000, 20000) = ₹20,000$
- Settlement Balance: $B = P - A = 20000 - 10000 = +₹10,000$
- **Outcome**: College owes club **₹10,000 reimbursement**.

### Case B: Surplus Event ($V = ₹15,000$, $I_{actual} = ₹25,000$)
- $\text{Net Deficit} = \max(0, 15000 - 25000) = ₹0$
- $P = \min(30000, 0) = ₹0$
- Settlement Balance: $B = P - A = 0 - 10000 = -₹10,000$
- **Outcome**: The event generated surplus revenue exceeding verified expenditure ($I_{actual} > V$). Consequently, institutional payout liability is zero ($P = ₹0$). Because cash advance $A = ₹10,000$ was received, the club must **refund the full advance of ₹10,000** to the college ($B = -₹10,000$).
- **Surplus Ownership Policy**: The legal ownership and accounting disposition of the net surplus of ₹10,000 ($I_{actual} - V$) is strictly `[EVIDENCE INSUFFICIENT — REQUIRES INSTITUTIONAL CONFIRMATION]`. CampusConnect calculates and reports that revenue exceeds expenditure, but the implementation must **NOT** automatically distribute, assign, or credit the surplus to any club account.

### Case C: Zero Verified Expenses ($V = ₹0$, $I_{actual} = ₹0$)
- $\text{Net Deficit} = ₹0 \implies P = ₹0$
- $B = 0 - 10000 = -₹10,000$
- **Outcome**: Event incurred no verified expenses. Club must **refund the full ₹10,000 advance**.

### Case D: Income Discovered After Initial Settlement
- `[ENGINEERING INFERENCE]`: If additional sponsorship is credited after settlement is reached, the settlement must be **reopened** (`REOPENED`) or amended via a formal `SettlementRevision`. The recalculated Net Deficit reduces the college payout liability, potentially converting a prior reimbursement into a refund due from the club.

### Case E: Bounced Cheque / Invalidated Income
- If a sponsor cheque bounces, Finance rejects the corresponding `ActualIncome` record. Recalculation increases Net Deficit, and the college reimburses the shortfall up to $G_{sanctioned}$.

---

## 10. Over-Budget Expenditure Policy

### 10.1 The Scenario
Sanctioned expenditure ceiling $E_{sanctioned} = ₹30,000$, Sanctioned grant $G_{sanctioned} = ₹20,000$.
Actual verified expenditure $V = ₹35,000$, Actual income $I_{actual} = ₹5,000$.

### 10.2 Institutional Analysis & Decision
1. **Net Deficit**: $V - I_{actual} = 35000 - 5000 = ₹30,000$.
2. **Statutory Grant Cap**: $P = \min(G_{sanctioned}, \text{Net Deficit}) = \min(20000, 30000) = ₹20,000$.
3. **Over-Budget Excess**:
   $$\text{Excess Expenditure} = V - E_{sanctioned} = 35000 - 30000 = ₹5,000$$
   $$\text{Unfunded Deficit} = \text{Net Deficit} - P = 30000 - 20000 = ₹10,000$$

`[FACT: INSTITUTIONAL DOCUMENT]` & `[EXTERNAL RESEARCH]`:
- Real-world universities **never automatically increase grant payouts** for unapproved over-spending.
- **Default Policy**: The college pays strictly up to $G_{sanctioned}$ ($P = ₹20,000$). The club bears the unfunded balance of ₹10,000 from external sponsorships or student club membership subscriptions.
- **Exception Mechanism**: If the Faculty Advisor submits an **Over-Budget Exception Petition** explaining unforeseen emergencies (e.g. equipment breakdown, police safety requirements), the **Principal** possesses exclusive discretionary authority to sanction a supplementary grant prior to settlement approval.

---

## 11. Disallowed Expenses & Settlement Eligibility

### 11.1 The Ledger Completeness Rule
`[ENGINEERING INFERENCE]`: Financial settlement cannot proceed while any expense claim remains unresolved. Calculating $V$ while claims are in `DRAFT`, `SUBMITTED`, or `QUERIED` introduces unverified or volatile liabilities into the university ledger.

### 11.2 Settlement Eligibility Invariant
A `FinancialSettlement` can ONLY be prepared when **ALL** of the following preconditions are satisfied:
1. `Event.status == COMPLETED`
2. `PostEventReport.status == CERTIFIED` (Faculty Advisor has verified delivery)
3. Total count of `ActualExpense` where `status IN ('DRAFT', 'SUBMITTED', 'QUERIED')` **EQUALS ZERO**.
4. Every `ActualExpense` is in a terminal status:
   - `VERIFIED`: Counted in $V$ at `verified_amount` ($= \text{claimed\_amount}$).
   - `PARTIALLY_VERIFIED`: Counted in $V$ at `verified_amount` ($< \text{claimed\_amount}$). Balance is derived as `disallowed_amount` and excluded from settlement payout.
   - `DISALLOWED`: `verified_amount = 0.00`. Excluded from settlement payout entirely.
5. Every `ActualIncome` record is in a terminal status (`VERIFIED` or `REJECTED`).

---

## 12. Settlement State Machine

### 12.1 State Definitions (`SettlementStatus`)

```
                  ┌──────────────┐
                  │    DRAFT     │
                  └──────┬───────┘
                         │ Submit for Audit
                         ▼
                  ┌──────────────┐
       ┌──────────┤ UNDER_AUDIT  ├──────────┐
       │          └──────┬───────┘          │
       │ Query           │ Approve          │ Reject
       ▼                 ▼                  ▼
┌──────────────┐  ┌──────────────┐   ┌──────────────┐
│   QUERIED    │  │   APPROVED   │   │   REJECTED   │
└──────┬───────┘  └──────┬───────┘   └──────────────┘
       │ Amend           │
       └─────────────────┼──────────────────────────────┐
                         ▼ (If B > 0)                   ▼ (If B < 0)
                  ┌──────────────┐               ┌──────────────┐
                  │   PENDING_   │               │   PENDING_   │
                  │REIMBURSEMENT │               │    REFUND    │
                  └──────┬───────┘               └──────┬───────┘
                         │ Disbursement Confirmed       │ Bank Receipt Confirmed
                         └──────────────┬───────────────┘
                                        ▼ (Or If B == 0)
                                 ┌──────────────┐
                                 │   SETTLED    │
                                 └──────┬───────┘
                                        │ Reopen (Exceptional Audit Override)
                                        ▼
                                 ┌──────────────┐
                                 │   REOPENED   │
                                 └──────────────┘
```

1. **`DRAFT`**: Settlement ledger generated by system / compiled by Secretary.
2. **`UNDER_AUDIT`**: Submitted to Finance Officer for macro-reconciliation of income, advance, and grant caps.
3. **`QUERIED`**: Finance Officer queries macro discrepancies (e.g. missing sponsorship deposit receipt).
4. **`APPROVED`**: Finance Officer approves calculated balances.
5. **`PENDING_REIMBURSEMENT`**: $B > 0$. Settlement waiting for college payment voucher / bank UTR.
6. **`PENDING_REFUND`**: $B < 0$. Settlement waiting for club refund bank deposit challan.
7. **`SETTLED`**: Terminal & immutable. All cash movements verified and cleared.
8. **`REOPENED`**: Exceptional audit reopening by Principal/Finance Officer. Creates an immutable `SettlementRevision` record.

---

## 13. Settlement Responsibility & Segregation of Duties (SOD)

| Responsibility | Actor | Authority & Constraints |
|---|---|---|
| **Compilation & Calculation** | **Automated Engine / Secretary** | System automatically computes $V$, $I_{actual}$, $\text{Net Deficit}$, $P$, and $B$ from verified database rows. Secretary reviews and submits. |
| **Financial Audit & Verification** | **Finance Officer** | Audits income receipts, verifies advance liquidation, verifies over-budget compliance, and approves/queries settlement. |
| **Delivery Oversight** | **Faculty Advisor** | Must have certified event delivery beforehand. Cannot approve financial payouts directly. |
| **Executive Exception Approval** | **Principal** | Approves over-budget supplementary grant exceptions and formal settlement reopening requests. |
| **System Administrator** | **`SYSTEM_ADMIN`** | Strictly barred from approving settlements, entering payments, or overriding financial amounts (HTTP 403). |

---

## 14. Settlement Certification & Final Approval Authority

### 14.1 Comparative Evaluation

| Option | Authority Structure | Pros | Cons | Decision |
|---|---|---|---|:---:|
| **Option A** | Finance Officer Only | Rapid closure | Lacks executive oversight on large funds | Rejected |
| **Option B** | Faculty Advisor + Finance Officer | Two-tier | Advisor already certified delivery; financial ledger is outside advisor's domain | Rejected |
| **Option C** | **Finance Officer Audit + Exception-Driven Principal Approval** | Finance Officer audits all standard settlements. Principal approval is strictly required for defined exceptional cases (over-budget supplementary grants and settlement reopenings). A monetary threshold, if introduced later, must be configurable rather than hard-coded. | **Best Practice**: Fast operational turnaround for standard events with executive protection on exceptions. | **RECOMMENDED** |

---

## 15. Reimbursement vs Refund Representation

`[ENGINEERING INFERENCE]`:
Rather than maintaining two completely disjoint state flows, CampusConnect models the financial position via a single signed decimal:
$$B = P - A$$
- In the UI and API, this balance is explicitly mapped to clear directional semantics:
  - `settlement_balance: Decimal`
  - `reimbursement_due: Decimal = max(0, B)`
  - `refund_due: Decimal = max(0, -B)`
  - `settlement_type: SettlementType` (`REIMBURSEMENT_DUE`, `REFUND_DUE`, `BALANCED`)

This mathematical symmetry ensures zero discrepancy between reimbursement calculations and refund recoveries.

---

## 16. Payment & Disbursement Records

### 16.1 Storage Strategy
`[ENGINEERING INFERENCE]`: In institutional campus environments, an event reimbursement or advance refund may occasionally be cleared in installments (e.g. refund paid in two installments, or reimbursement split between cash voucher and bank transfer).
To prevent schema limitations, payment clearing is modeled as a dedicated entity: **`SettlementPayment`**.

### 16.2 `SettlementPayment` Blueprint
- `id: UUID PRIMARY KEY`
- `settlement_id: UUID NOT NULL REFERENCES financial_settlements(id)`
- `payment_type: SettlementPaymentType` (`REIMBURSEMENT_DISBURSEMENT`, `ADVANCE_REFUND_RECEIPT`)
- `amount: NUMERIC(12,2) NOT NULL`
- `payment_method: PaymentMethod` (`BANK_TRANSFER_NEFT`, `CHEQUE`, `CASH_VOUCHER`, `INSTITUTIONAL_TRANSFER`)
- `transaction_reference: VARCHAR(100) NOT NULL` (Bank UTR / Cash receipt number)
- `transaction_date: DATE NOT NULL`
- `proof_document_id: UUID NOT NULL REFERENCES documents(id)` (Bank slip / voucher scan)
- `recorded_by: UUID NOT NULL REFERENCES users(id)` (Finance Officer)
- `created_at: TIMESTAMPTZ NOT NULL`

---

## 17. Reopening & Revision Semantics

`[ENGINEERING INFERENCE]`:
In auditing, historical records must NEVER be updated in place or overwritten.
When a `SETTLED` event must be reopened (e.g. auditor discovers duplicate vendor invoice, bounced sponsorship cheque):
1. Only a `FINANCE_OFFICER` or `PRINCIPAL` can trigger `reopen_settlement` with mandatory justification (`remarks >= 15 chars`).
2. The current `FinancialSettlement` row is copied into `settlement_revisions` with a sequential `revision_number`.
3. The active settlement status transitions to `REOPENED`.
4. The event status temporarily reverts to `COMPLETED_UNDER_AUDIT`.
5. Once corrections are made, a new settlement approval cycle is executed.

---

## 18. Utilization Certificate (UC) Boundary

### 18.1 Boundary Clarification
- **Phase 2.3 Boundary**: Computes, reconciles, and locks the complete financial dataset required by the UC.
- **Phase 2.4 Boundary**: Generates the formal Government of India GFR 12-A / Autonomous College Utilization Certificate PDF, applies cryptographic watermarks, and orchestrates the digital co-signature workflow between Finance Officer and Principal.

### 18.2 Interface Specification (Data Provided by Phase 2.3 to UC Engine)
```json
{
  "uc_payload": {
    "event_id": "UUID",
    "event_title": "String",
    "club_name": "String",
    "academic_year": "String",
    "sanction_reference": "String",
    "sanctioned_grant": "20000.00",
    "sanctioned_expenditure_ceiling": "30000.00",
    "cash_advance_disbursed": "10000.00",
    "actual_verified_expenditure": "25000.00",
    "actual_verified_income": "5000.00",
    "net_deficit": "20000.00",
    "institutional_payout": "20000.00",
    "settlement_balance": "10000.00",
    "unspent_grant_surrendered": "0.00",
    "grant_utilization_percentage": "100.00",
    "settlement_cleared_at": "2026-09-25T14:30:00Z",
    "finance_officer_id": "UUID",
    "finance_officer_name": "String"
  }
}
```

---

## 19. Event Closure Prerequisites

`[PROPOSED CAMPUSCONNECT RULE]`:
An Event can transition to its terminal operational lifecycle status (`CLOSED`) if and only if:
1. `Event.status == COMPLETED`
2. `PostEventReport.status == CERTIFIED` (Physical delivery confirmed)
3. `ActualExpense` ledger has zero unresolved claims (`DRAFT`, `SUBMITTED`, `QUERIED` == 0)
4. `ActualIncome` ledger has zero unresolved entries (`RECORDED` == 0)
5. `FinancialSettlement.status == SETTLED`
6. `reimbursement_due == 0` AND `refund_due == 0` (All balance payments confirmed via `SettlementPayment`)

---

## 20. Security Threat Model

| Threat / Attack Vector | Vulnerability Exploited | Impact | CampusConnect Protection Architecture |
|---|---|---|---|
| **Settlement Amount Tampering** | Client submits crafted `settlement_balance` or `institutional_payout` | Financial fraud; university overpays | **Server-Side Computation Only**: Client NEVER specifies balances. System calculates all values dynamically from locked DB rows. |
| **Bypassing Unspent Refund** | Secretary marks event settled without remitting unspent cash advance | Direct loss of college funds | `SETTLED` transition is blocked by check: `IF B < 0 AND sum(SettlementPayment) < abs(B) THEN REJECT`. |
| **Fabricated Actual Income** | User creates fake sponsorship income to artificially increase surplus or balance | Audit distortion | Mandatory bank proof document; Finance verification required (`IncomeStatus.VERIFIED`). |
| **Concurrent Double Settlement** | Two users trigger settlement compilation simultaneously | Race condition; duplicate settlement records | Unique SQL constraint on `financial_settlements(event_id)` + `SELECT ... FOR UPDATE` row lock. |
| **Admin Authorization Bypass** | System Administrator approves financial settlement | Violation of statutory SOD | Hardcoded role guard: `IF user.role == SYSTEM_ADMIN THEN RAISE ForbiddenError(403)`. |
| **Reopening without Audit Record** | User quietly alters settled numbers | Loss of financial trace | Append-only `SettlementRevision` table records full state snapshot before any change. |
| **Settlement with Unresolved Claims** | Settlement compiled while queried bill is pending amendment | Inaccurate grant payout | Zero-unresolved invariant check before settlement creation. |

---

## 21. Concurrency & Transaction Design

### 21.1 Pessimistic Row Locking Strategy
All Phase 2.3 financial transitions must execute within explicit database transactions utilizing pessimistic row-level locking:
```python
# 1. Lock confirmed event row
event = await db.scalar(
    select(Event).where(Event.id == event_id).with_for_update()
)

# 2. Lock active settlement row (if updating/auditing)
settlement = await db.scalar(
    select(FinancialSettlement)
    .where(FinancialSettlement.event_id == event.id)
    .with_for_update()
)

# 3. Lock all associated expense items
expenses = (await db.scalars(
    select(ActualExpense)
    .where(ActualExpense.event_id == event.id)
    .with_for_update()
)).all()
```

### 21.2 Idempotent Payment Recording
Recording a reimbursement or refund receipt requires client-supplied idempotency keys:
- Stored in `idempotency_records` table.
- Prevents double-clicking from creating duplicate payment voucher rows.

---

## 22. Database Blueprint (Phase 2.3 Schema Specification)

### 22.1 Proposed Tables

#### 1. `cash_advances`
- `id: UUID PRIMARY KEY`
- `event_id: UUID NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE`
- `amount_requested: NUMERIC(12,2) NOT NULL` (Check: `> 0`)
- `amount_approved: NUMERIC(12,2) NULL`
- `amount_disbursed: NUMERIC(12,2) NOT NULL DEFAULT 0.00`
- `status: VARCHAR(30) NOT NULL DEFAULT 'REQUESTED'` (`REQUESTED`, `APPROVED`, `DISBURSED`, `REJECTED`)
- `disbursed_at: TIMESTAMPTZ NULL`
- `disbursed_by: UUID NULL REFERENCES users(id)`
- `recipient_id: UUID NOT NULL REFERENCES users(id)`
- `payment_reference: VARCHAR(100) NULL`
- `created_at / updated_at: TIMESTAMPTZ`

#### 2. `actual_incomes`
- `id: UUID PRIMARY KEY`
- `event_id: UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE`
- `source_type: VARCHAR(30) NOT NULL`
- `description: VARCHAR(500) NOT NULL`
- `payer_name: VARCHAR(255) NOT NULL`
- `amount: NUMERIC(12,2) NOT NULL` (Check: `> 0`)
- `received_date: DATE NOT NULL`
- `reference_number: VARCHAR(100) NULL`
- `evidence_document_id: UUID NOT NULL REFERENCES documents(id) ON DELETE RESTRICT`
- `status: VARCHAR(30) NOT NULL DEFAULT 'RECORDED'` (`RECORDED`, `VERIFIED`, `REJECTED`)
- `recorded_by: UUID NOT NULL REFERENCES users(id)`
- `verified_by: UUID NULL REFERENCES users(id)`
- `verified_at: TIMESTAMPTZ NULL`
- `finance_remarks: TEXT NULL`
- `created_at / updated_at: TIMESTAMPTZ`

#### 3. `financial_settlements`
- `id: UUID PRIMARY KEY`
- `event_id: UUID NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE`
- `sanctioned_grant: NUMERIC(12,2) NOT NULL` (Immutable snapshot)
- `sanctioned_expenditure: NUMERIC(12,2) NOT NULL` (Immutable snapshot)
- `total_claimed_expenditure: NUMERIC(12,2) NOT NULL`
- `total_verified_expenditure: NUMERIC(12,2) NOT NULL`
- `total_disallowed_expenditure: NUMERIC(12,2) NOT NULL`
- `total_verified_income: NUMERIC(12,2) NOT NULL`
- `net_deficit: NUMERIC(12,2) NOT NULL`
- `institutional_payout: NUMERIC(12,2) NOT NULL`
- `cash_advance_disbursed: NUMERIC(12,2) NOT NULL DEFAULT 0.00`
- `settlement_balance: NUMERIC(12,2) NOT NULL` ($P - A$)
- `reimbursement_due: NUMERIC(12,2) NOT NULL DEFAULT 0.00`
- `refund_due: NUMERIC(12,2) NOT NULL DEFAULT 0.00`
- `status: VARCHAR(30) NOT NULL DEFAULT 'DRAFT'`
- `submitted_by: UUID NOT NULL REFERENCES users(id)`
- `submitted_at: TIMESTAMPTZ NULL`
- `audited_by: UUID NULL REFERENCES users(id)`
- `audited_at: TIMESTAMPTZ NULL`
- `finance_remarks: TEXT NULL`
- `created_at / updated_at: TIMESTAMPTZ`

#### 4. `settlement_payments`
- `id: UUID PRIMARY KEY`
- `settlement_id: UUID NOT NULL REFERENCES financial_settlements(id) ON DELETE CASCADE`
- `payment_type: VARCHAR(30) NOT NULL` (`REIMBURSEMENT_DISBURSEMENT`, `ADVANCE_REFUND_RECEIPT`)
- `amount: NUMERIC(12,2) NOT NULL` (Check: `> 0`)
- `payment_method: VARCHAR(30) NOT NULL`
- `transaction_reference: VARCHAR(100) NOT NULL`
- `transaction_date: DATE NOT NULL`
- `proof_document_id: UUID NOT NULL REFERENCES documents(id) ON DELETE RESTRICT`
- `recorded_by: UUID NOT NULL REFERENCES users(id)`
- `created_at: TIMESTAMPTZ NOT NULL`

#### 5. `settlement_revisions`
- `id: UUID PRIMARY KEY`
- `settlement_id: UUID NOT NULL REFERENCES financial_settlements(id) ON DELETE CASCADE`
- `revision_number: INTEGER NOT NULL`
- `snapshot_data: JSONB NOT NULL` (Full JSON snapshot of settlement, expenses, incomes, and payments)
- `reopened_by: UUID NOT NULL REFERENCES users(id)`
- `reopening_reason: TEXT NOT NULL`
- `created_at: TIMESTAMPTZ NOT NULL`

---

## 23. API Blueprint (Future Phase 2.3 Endpoints)

| Method | Path | Role | Description |
|---|---|---|---|
| `POST` | `/api/v1/events/{id}/advance/request` | Club Secretary | Requests cash advance before event execution |
| `POST` | `/api/v1/events/{id}/advance/disburse` | Finance Officer | Approves and disburses advance with reference |
| `GET` | `/api/v1/events/{id}/advance` | Authenticated | Retrieves event cash advance status |
| `POST` | `/api/v1/events/{id}/income` | Club Secretary | Records actual income entry with evidence document |
| `GET` | `/api/v1/events/{id}/income` | Authenticated | Lists all actual income entries |
| `POST` | `/api/v1/events/{id}/income/{inc_id}/verify` | Finance Officer | Verifies or rejects recorded income entry |
| `POST` | `/api/v1/events/{id}/settlement/prepare` | Secretary / System | Generates draft settlement calculation |
| `POST` | `/api/v1/events/{id}/settlement/submit` | Club Secretary | Submits settlement for Finance Officer audit |
| `GET` | `/api/v1/events/{id}/settlement` | Authenticated | Retrieves current settlement summary & balances |
| `POST` | `/api/v1/events/{id}/settlement/audit` | Finance Officer | Approves or queries settlement |
| `POST` | `/api/v1/events/{id}/settlement/payments` | Finance Officer | Records reimbursement disbursement or refund receipt |
| `POST` | `/api/v1/events/{id}/settlement/reopen` | Finance Officer / Principal | Reopens settled event with audit snapshot |

---

## 24. Frontend Blueprint (EventDetailPage Settlements UX)

The existing `EventDetailPage.tsx` tab navigation will be expanded:
`'overview' | 'venue' | 'budget' | 'documents' | 'resources' | 'execution' | 'expenses' | 'settlement'`

### 24.1 Secretary Interface:
1. **Settlement Balance Card**:
   - Distinct green card for **Reimbursement Due** (`₹...`), or amber card for **Refund Due** (`₹...`).
2. **Income Entry Modal**:
   - File attachment for sponsorship agreement / bank slip.
   - Breakdown of registration fees and ticket sales.
3. **Advance Reconciliation Panel**:
   - Displays advance disbursed vs amount liquidated in verified expenses.
4. **"Submit for Final Settlement" Action**:
   - Enabled only when 100% of expense claims and income entries are resolved.

### 24.2 Finance Officer Interface:
1. **Macro Reconciliation Ledger**:
   - Side-by-side comparison: Sanctioned Grant vs Net Deficit vs Cash Advance.
2. **Audit Action Panel**:
   - "Approve Settlement" button.
   - "Query Discrepancy" modal with mandatory remarks.
3. **Payment Recording Modal**:
   - Enters bank transfer UTR or college cashier receipt number and uploads official challan scan.

---

## 25. Test Strategy Specification

The verification suite for Phase 2.3 must cover the following test matrices:

### 25.1 Accounting Arithmetic Tests
1. `test_settlement_exact_budget_zero_income`: Verified = Grant, Advance = 0 $\implies$ $B = \text{Grant}$.
2. `test_settlement_under_budget_positive_advance`: Verified < Advance $\implies$ $B < 0$ (Refund required).
3. `test_settlement_income_offsets_grant_liability`: $I_{actual} > 0$ reduces Net Deficit and institutional payout.
4. `test_settlement_surplus_income_zero_grant`: $I_{actual} > V \implies P = 0, B = -A$ (Full advance refund).
5. `test_settlement_over_budget_capped_at_grant`: $V > E_{sanctioned} \implies P = G_{sanctioned}$, excess flagged.

### 25.2 Eligibility & Invariant Tests
6. `test_unresolved_draft_expense_blocks_settlement`: HTTP 400 when draft expenses exist.
7. `test_unresolved_queried_expense_blocks_settlement`: HTTP 400 when queried expenses exist.
8. `test_unverified_income_blocks_settlement`: HTTP 400 when unverified income entries exist.
9. `test_uncompleted_event_blocks_settlement`: HTTP 400 if event status is not COMPLETED.
10. `test_uncertified_post_event_report_blocks_settlement`: HTTP 400 if FA certification missing.

### 25.3 Security & Concurrency Tests
11. `test_admin_cannot_approve_settlement`: `SYSTEM_ADMIN` gets HTTP 403.
12. `test_cross_club_settlement_blocked`: Secretary of Club B cannot view or submit Club A's settlement.
13. `test_concurrent_settlement_creation_race_prevented`: Row locking prevents duplicate settlement rows.
14. `test_settled_immutability_guard`: Patching expenses after `SETTLED` status raises 403 Forbidden.
15. `test_reopen_creates_immutable_revision_snapshot`: Verified revision entry created in `settlement_revisions`.

---

## 26. Final Decision Table

| Decision Area | Options Considered | Evidence | Final CampusConnect Decision | Confidence |
|---|---|---|---|:---:|
| **1. Settlement Ownership** | A. Secretary compiles<br>B. System calculates<br>C. Finance creates | `[ENGINEERING INFERENCE]` & `[EXTERNAL RESEARCH]` | **Option B**: System automatically calculates ledger; Secretary submits; Finance audits. | **HIGH** |
| **2. State Machine** | A. 4-state<br>B. 8-state directional | `[PROPOSED CAMPUSCONNECT RULE]` | **Option B**: `DRAFT` $\rightarrow$ `UNDER_AUDIT` $\rightarrow$ `APPROVED` $\rightarrow$ `PENDING_REIMBURSEMENT` / `PENDING_REFUND` $\rightarrow$ `SETTLED` $\rightarrow$ `REOPENED`. | **HIGH** |
| **3. Sanctioned Amount Source** | A. Dynamic proposal join<br>B. Immutable snapshot | `[ENGINEERING INFERENCE]` | **Option B**: Snapshot `institute_contribution` and `total_expected_expenditure` into settlement at instantiation. | **HIGH** |
| **4. Cash Advance Model** | A. No advance<br>B. Multi-advance<br>C. Single advance | `[EXTERNAL RESEARCH]` | **Option C**: Single advance per event with formal request, approval, and disbursement tracking. | **HIGH** |
| **5. Actual Income Model** | A. Single decimal field<br>B. First-class entity | `[PROPOSED CAMPUSCONNECT RULE]` & `[ENGINEERING INFERENCE]` | **Option B**: First-class `ActualIncome` model with categories, evidence document, and Finance verification. | **HIGH** |
| **6. Expense Eligibility** | A. Any status<br>B. All terminal | `[ENGINEERING INFERENCE]` | **Option B**: 100% of expense claims must be in terminal status (`VERIFIED`, `PARTIALLY_VERIFIED`, `DISALLOWED`). | **HIGH** |
| **7. Over-Budget Policy** | A. Auto-pay<br>B. Hard cap<br>C. Hard cap + Principal override | `[EXTERNAL RESEARCH]` & `[FACT: INSTITUTIONAL DOCUMENT]` | **Option C**: Hard cap at $G_{sanctioned}$. Principal discretionary override required for excess grant. | **HIGH** |
| **8. Balance Directionality** | A. Separate entities<br>B. Single signed balance | `[ENGINEERING INFERENCE]` | **Option B**: Single balance $B = P - A$, mapped to `PENDING_REIMBURSEMENT` ($B > 0$) or `PENDING_REFUND` ($B < 0$). | **HIGH** |
| **9. Payment Recording** | A. Single reference string<br>B. `SettlementPayment` entity | `[EXTERNAL RESEARCH]` & `[ENGINEERING INFERENCE]` | **Option B**: `SettlementPayment` entity supporting multiple payment methods and proof documents. | **HIGH** |
| **10. Reopening** | A. In-place edit<br>B. `SettlementRevision` | `[ENGINEERING INFERENCE]` | **Option B**: Append-only `SettlementRevision` snapshot preserves full audit trail. | **HIGH** |
| **11. UC Boundary** | A. Implement now<br>B. Decoupled in Phase 2.4 | `[EXTERNAL RESEARCH]` | **Option B**: Phase 2.3 computes and locks financial data; Phase 2.4 generates certificate PDF and signatures. | **HIGH** |
| **12. Event Closure Prerequisites** | A. Delivery only<br>B. Delivery + Ledger cleared | `[FACT: INSTITUTIONAL DOCUMENT]` | **Option B**: Event closes only after PostEventReport certified AND Settlement status is SETTLED. | **HIGH** |

---

## 27. Open Questions / Institutional Confirmation Required

1. **Advance Disbursal Ceiling**:
   - `[EVIDENCE INSUFFICIENT — REQUIRES INSTITUTIONAL CONFIRMATION]`: Does the college enforce a statutory percentage cap on cash advances, or is advance eligibility determined on a case-by-case basis by the Finance Officer and Principal?
   - *Requirement*: The architectural boundary is `0 <= A <= G_sanctioned`. Any additional percentage constraint must be configuration-driven, never hard-coded, and never misrepresented as an institutional rule.
2. **Surplus Event Revenue Policy**:
   - `[EVIDENCE INSUFFICIENT — REQUIRES INSTITUTIONAL CONFIRMATION]`: When an event generates surplus income ($I_{actual} > V$), does the college credit surplus to the student club, deposit it into a general institutional student activity pool, or retain it for central overhead?
   - *Requirement*: The system must calculate and report that revenue exceeded expenditure, but the software must NEVER automatically distribute, credit, or assign surplus funds without explicit institutional confirmation.

---

## 28. Phase 2.3 Implementation Boundary

The Phase 2.3 implementation scope is strictly bounded:
- **Included in Phase 2.3**:
  1. `CashAdvance` model and disbursement tracking.
  2. `ActualIncome` model, evidence attachment, and Finance audit.
  3. `FinancialSettlement` model with immutable snapshotting and mathematical reconciliation engine.
  4. Directional settlement workflows (`PENDING_REIMBURSEMENT`, `PENDING_REFUND`, `SETTLED`).
  5. `SettlementPayment` recording for disbursement UTRs and refund receipts.
  6. `SettlementRevision` append-only audit tracking.
  7. Frontend Settlement tab and reconciliation dashboard.
- **Strictly Deferred to Future Phases (Phase 2.4+)**:
  1. Utilization Certificate (UC) PDF generation and digital signature workflows (Phase 2.4).
  2. Event Cancellation and Hall Rollback sub-machines (Phase 2.5).
  3. Event Rescheduling sub-machines (Phase 2.5).
  4. Payment Gateway integration (Razorpay / Stripe) (Phase 3).
  5. Direct Public Financial Management System (PFMS) bank API integration (Phase 3).

---

## 29. Implementation Status

**IMPLEMENTATION STATUS: NOT IMPLEMENTED**

- **NO CODE CHANGES MADE**
- **NO DATABASE SCHEMA CHANGES MADE**
- **NO MIGRATIONS CREATED**
- **NO API ENDPOINTS CREATED**
- **NO FRONTEND CHANGES MADE**
- **NO COMMITS CREATED**
- **NO GIT PUSHES PERFORMED**

*Research phase concluded successfully. Awaiting user review and formal architectural approval before beginning Phase 2.3 implementation.*
