# CampusConnect — Phase 2 Decision Research Report

> **Focus**: Deep-Dive Comparative Research on Post-Event Governance & Financial Settlement  
> **Repository Baseline**: Commit `12b2002`  
> **Source Discipline Standard**: Fact vs External Research vs Engineering Inference vs Proposed CampusConnect Rule

---

## 1. Context & Problem Statement

At commit `12b2002`, CampusConnect's lifecycle terminates at:
```
Event Proposal -> Venue -> Budget -> 6-Level Approval -> Principal Sanction -> Confirmed Event (SCHEDULED)
```
In real-world colleges, an approved event initiates a critical operational phase:
- Hall physical handover and logistics mobilization
- Event execution and participant turnout recording
- Post-event reporting with photographic evidence
- Financial accounting, bill verification, and reconciliation against sanctioned funds
- Official institutional closure

To construct Phase 2 without architectural debt or policy invalidation, three pivotal institutional governance decisions must be formally researched, analyzed, and presented for user decision.

---

## 2. Decision 1: Financial Settlement Authority

### The Decision Question
Who possesses the authority to review submitted vendor invoices, verify actual expenditures, compute variance against the sanctioned grant, and formally execute financial settlement?

### Architectural Alternatives

| Option | Architecture Model | Pros | Cons |
| :--- | :--- | :--- | :--- |
| **A. Finance Officer Only** | Single-tier audit: Finance Officer verifies all bills and marks settlement complete. | Fast turnaround; direct accounting control. | Bypasses academic mentor who witnessed physical event execution; risk of approving fictitious bills. |
| **B. Faculty Advisor + Finance Officer (Co-Signature)** | Two-tier model: Faculty Advisor first certifies that goods/services were physically delivered, then Finance Officer conducts financial/tax audit. | **Highest Segregation of Duties (SOD)**; eliminates ghost vouchers; aligns with collegiate norms. | Requires two distinct sign-offs; potential delay if faculty is slow to certify. |
| **C. Central Accounts / Internal Auditor** | Centralized college accounting section independent of student governance. | Comprehensive financial rigor. | Heavyweight for small club events (₹2,000–₹10,000); excessive bureaucracy. |
| **D. Stage-Dependent Tiered Authority** | For spend < ₹5,000: Finance Officer only. For spend >= ₹5,000: Faculty Advisor endorsement + Finance Officer clearance. | Pragmatic throughput; risk-proportional scrutiny. | More complex state machine logic and edge cases. |

### Institutional & External Research Findings
- `[FACT: INSTITUTIONAL DOCS]`: On college budget application forms, the Faculty Advisor is the designated guarantor of the student club's operational integrity, while the Accounts / Finance department holds sole custody of institutional bank disbursements.
- `[EXTERNAL RESEARCH]`: In premier Indian technical institutes (IIT Madras, IIT Bombay, NIT Trichy), post-event financial settlement requires the Faculty In-Charge to verify that the event took place and goods were received (Good Received Note / Physical Verification), followed by Accounts Section audit for GST-compliant vouchers.
- `[EXTERNAL RESEARCH]`: The Government of India General Financial Rules (GFR Rule 238) dictates that a Utilization Certificate (UC) for grants must be signed by both the executive authority administering the grant and the financial officer verifying the accounts.
- `[ENGINEERING INFERENCE]`: A pure "Finance Officer Only" model creates a severe security threat: a corrupt or compromised secretary could submit fraudulent receipts for an event that never occurred or bought unapproved equipment, which a finance officer sitting in an admin office cannot physically cross-check without the Faculty Advisor's verification.

### Recommendation for Decision 1
> **RECOMMENDED: OPTION B (Two-Tier Model: Faculty Advisor Certification -> Finance Officer Audit)**  
> 1. Club Secretary uploads post-event report, photo evidence, and itemized bills.  
> 2. Faculty Advisor reviews and executes `CERTIFY_DELIVERY` (certifying event execution and valid expenditures).  
> 3. Finance Officer reviews vouchers, verifies GST/PAN and arithmetic, deducts disallowed expenses, and executes `FINANCIAL_SETTLEMENT`.  
> *Status: Recommended for user sign-off. If college accounting has unique delegation rules: "Evidence insufficient — requires institutional confirmation."*

---

## 3. Decision 2: Funding Mechanism

### The Decision Question
What financial funding model should CampusConnect support for sanctioned college grants?

### Architectural Alternatives

| Option | Financial Model | Operational Workflow | Risk Profile |
| :--- | :--- | :--- | :--- |
| **A. Pure Post-Event Reimbursement** | Club/Secretary incurs all expenses upfront from club fund or personal cash; college reimburses approved expenses post-settlement against original bills. | 1. Sanction grant. 2. Execute event. 3. Submit bills. 4. Disburse reimbursement. | Low risk to college; severe financial hardship on student secretaries who cannot advance ₹15,000 out-of-pocket. |
| **B. Pre-Event Cash Advance** | College disburses 100% of sanctioned grant in advance; secretary submits bills later. | 1. Sanction grant. 2. Disburse full advance. 3. Execute event. 4. Submit bills & refund surplus. | High institutional risk; difficult recovery of unspent advance or disputed bills from graduating students. |
| **C. Hybrid Model (Advance + Settlement Reconciliation)** | College disburses a configurable advance (e.g. 50%–75% of sanctioned grant) or full reimbursement based on event scale; settlement reconciles balance. | 1. Sanction grant. 2. Disburse optional advance. 3. Submit actual bills. 4. System computes variance. 5. If Spend > Advance: disburse balance. If Spend < Advance: student refunds surplus. | **Optimal Real-World Balance**: Relieves student cash strain while limiting college exposure. |

### Financial Variance & Balance Mathematics
In the Hybrid Model, financial settlement is strictly governed by the following equations:
```
Net Payable = MIN(Sanctioned Grant, Verified Actual Spend)
Balance Due = Net Payable - Cash Advance Received

If Balance Due > 0:
    College owes Club a REIMBURSEMENT DISBURSEMENT of Balance Due.
If Balance Due < 0:
    Club owes College a SURPLUS REFUND of |Balance Due|.
If Balance Due == 0:
    Accounts are EXACTLY BALANCED.
```

### Overspending Governance Rule
- `[FACT: INSTITUTIONAL DOCS]`: Sanctioned amounts approved by the Principal represent hard statutory upper bounds.
- `[PROPOSED RULE]`: Any actual expenditure incurred beyond the sanctioned institutional contribution is classified as **Unauthorized Overspend** and must be absorbed entirely by club membership collections or external sponsorships. The college will never disburse reimbursement exceeding `sanctioned_amount`.

### Recommendation for Decision 2
> **RECOMMENDED: OPTION C (Hybrid Model with Configurable Advance & Strict Balance Settlement)**  
> 1. Support an optional `cash_advance_disbursed` record (default: ₹0.00 for reimbursement-only, or up to sanctioned amount upon finance clearance).  
> 2. System automatically reconciles: `Verified Expenses vs Advance = Balance`.  
> 3. Settlement cannot transition to `CLOSED` until any negative balance (unspent advance) has a recorded bank refund reference number.  
> *Status: Recommended for user sign-off.*

---

## 4. Decision 3: Event Cancellation Authority

### The Decision Question
Who holds the authority to cancel a confirmed and scheduled event, and what are the cascading resource and financial side-effects?

### Architectural Alternatives

| Option | Authority Model | Operational Rules | Limitations |
| :--- | :--- | :--- | :--- |
| **A. Club Secretary Unilateral** | Secretary can click "Cancel Event" at any time prior to event execution. | Immediate hall release; low friction. | Moral hazard: Secretary could cancel hours before an event after halls have been prepared and dignitaries invited. |
| **B. Secretary Initiates + Faculty Advisor Approves** | Secretary submits cancellation request with justification; Faculty Advisor confirms. | Ensures academic oversight before cancellation. | Does not address hall administration or advance financial recovery. |
| **C. Institutional Authority (Dean / Principal Only)** | Only Dean of Student Affairs or Principal can cancel a scheduled event. | Complete administrative control. | Bottleneck: High latency for emergency cancellations (e.g. severe weather, speaker illness). |
| **D. Stage-Dependent Lifecycle Authority** | **Pre-Sanction (DRAFT / IN_REVIEW)**: Secretary can withdraw unilaterally.<br>**Post-Sanction (SCHEDULED, No Advance)**: Secretary requests, Faculty Advisor + Hall In-Charge approve to release venue.<br>**Post-Sanction (Advance Disbursed)**: Dean / Principal + Finance Officer must cancel and audit fund recovery. | **Context-Aware Governance**: Matches risk and operational impact at each stage. | Requires multi-state cancellation sub-machine. |

### Cascading Side-Effects of Cancellation
When a confirmed event is cancelled, CampusConnect must execute the following atomic operations:
1. **Hall Release**: Delete or soft-deactivate `hall_bookings_confirmed` row, instantly restoring venue availability in the public calendar.
2. **Notification Dispatch**: Emit high-priority alerts to Hall In-Charge, Principal, Dean, and Registered Participants.
3. **Financial Lock**: If cash advance was disbursed, lock event into `CANCELLED_PENDING_REFUND` until Finance Officer logs return of the full advance amount.
4. **Audit Trail**: Record canceller ID, cancellation category (`WEATHER`, `SPEAKER_UNAVAILABLE`, `STUDENT_EMERGENCY`, `ADMINISTRATIVE_ORDER`), and detailed remarks.

### Recommendation for Decision 3
> **RECOMMENDED: OPTION D (Stage-Dependent Authority with Atomic Hall Release & Advance Lock)**  
> - Pre-Approval: Secretary can withdraw proposal anytime.  
> - Post-Approval (SCHEDULED): Cancellation request submitted by Secretary, confirmed by Faculty Advisor (and Finance Officer if cash advance was issued).  
> - Emergency Override: Principal or Dean can cancel unilaterally with immediate effect.  
> *Status: Recommended for user sign-off.*

---

## 5. Comparative Decision Summary

| Decision Area | Evaluated Options | Recommended Architecture | Open Institutional Question |
| :--- | :--- | :--- | :--- |
| **1. Settlement Authority** | A. Finance Only<br>B. Advisor + Finance<br>C. Central Accounts<br>D. Tiered | **Option B: Two-Tier (Advisor Certifies Delivery -> Finance Audits Bills)** | Does the college require physical bill submission to Accounts in addition to digital scans? |
| **2. Funding Mechanism** | A. Reimbursement<br>B. Cash Advance<br>C. Hybrid | **Option C: Hybrid (Reimbursement default, Advance with automated variance & refund tracking)** | What is the maximum cash advance percentage allowed prior to event date? |
| **3. Cancellation Authority**| A. Secretary<br>B. Secretary + Advisor<br>C. Dean/Principal<br>D. Stage-Dependent | **Option D: Stage-Dependent (Secretary withdraws pre-approval; Advisor/Finance co-signs post-approval; Dean override)** | Can Hall In-Charge revoke hall allocation unilaterally in case of emergency maintenance? |

---

## 6. Phase 3 / Future Scope Boundary (Do Not Implement in Phase 2)

The following capabilities are strictly deferred to Phase 3:
1. Automated OCR scanning of physical receipts (Tesseract / Cloud Vision).
2. Direct integration with college bank gateway / PFMS (Public Financial Management System).
3. Student ticket sales and payment gateway integration (Razorpay / Stripe).
4. Multi-campus cross-institutional federation.
