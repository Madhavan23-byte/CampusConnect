# CampusConnect — Day 7 Institutional Business Rules Specification

> **Focus**: Codified Business Rules, Precedents, and Operational Logic  
> **Repository Baseline**: Commit `12b2002`  
> **Source Discipline Standard**: Every assertion explicitly categorized into Fact, Research, Inference, or Proposed Rule.

---

## 1. Source Discipline Taxonomy

To prevent arbitrary rule invention, every governance rule in this document is labeled with its factual origin:
1. **[FACT: INSTITUTIONAL DOCS]**: Verified directly from institutional paper forms, workflow records, or domain guidelines of the college.
2. **[EXTERNAL RESEARCH]**: Derived from established university policies (IITs, NITs, Central Universities, Anna University, collegiate governance frameworks).
3. **[ENGINEERING INFERENCE]**: Derived from sound software engineering, database integrity, and cybersecurity requirements.
4. **[PROPOSED RULE]**: Recommended business rule for CampusConnect pending explicit institutional confirmation.

---

## 2. Club Governance & Membership Rules

1. **Club Roster & Roles**:
   - `[FACT: INSTITUTIONAL DOCS]`: Every recognized college club operates under one designated Faculty Advisor and one or more student office-bearers, primarily the Club Secretary.
   - `[ENGINEERING INFERENCE]`: A user cannot act as Club Secretary for multiple conflicting clubs unless formally assigned. Proposal creation is restricted strictly to active club members with the `CLUB_SECRETARY` role.
2. **Faculty Advisor Stewardship**:
   - `[FACT: INSTITUTIONAL DOCS]`: A club proposal cannot bypass its designated Faculty Advisor. The Faculty Advisor represents Step 1 in the approval pipeline.
   - `[PROPOSED RULE]`: If a Faculty Advisor is on leave, interim endorsement can only be delegated by the Dean of Student Affairs or System Administrator.

---

## 3. Venue & Hall Booking Rules

1. **Advance Booking Notice**:
   - `[FACT: INSTITUTIONAL DOCS]`: Hall bookings must be submitted in advance to prevent operational disruption and permit maintenance checks.
   - `[PROPOSED RULE]`: `HALL_BOOKING_MIN_ADVANCE_DAYS = 3`. Venue requests scheduled with less than 3 days of advance notice are automatically rejected with `AdvanceBookingViolationError`.
2. **Single Venue per Proposal**:
   - `[ENGINEERING INFERENCE]`: An event request is permitted exactly one active venue request (`venue_requests.event_request_id` is unique). If multiple halls are required for large symposiums, separate sub-proposals or multi-hall extensions must be formally chartered.
3. **Hard Conflict Exclusion**:
   - `[FACT: INSTITUTIONAL DOCS]`: Two clubs cannot be allotted the same hall during identical time slots under any circumstances.
   - `[ENGINEERING INFERENCE]`: Enforced via PostgreSQL `EXCLUDE USING gist (hall_id WITH =, booking_slot WITH &&)` upon Principal approval.

---

## 4. Budget & Financial Governance Rules

1. **Institutional Contribution Cap**:
   - `[FACT: INSTITUTIONAL DOCS]`: The college provides partial financial assistance (institutional grant) up to a ceiling; clubs must source the balance through registrations, sponsorships, or parent department funds.
   - `[PROPOSED RULE]`: `BUDGET_INSTITUTE_CONTRIBUTION_CAP = 15,000.00`. Any proposal requesting institutional grant funding exceeding ₹15,000.00 is blocked during budget validation.
2. **Server-Side Arithmetic Verification**:
   - `[ENGINEERING INFERENCE]`: Total expected expenditure is recalculated strictly as `SUM(line_items.amount)`. Client-supplied totals are rejected if inconsistent.
   - `[ENGINEERING INFERENCE]`: `expected_income + institute_contribution <= total_expected_expenditure`. Clubs cannot claim grants exceeding total budgeted spend.
3. **Line Item Granularity**:
   - `[FACT: INSTITUTIONAL DOCS]`: Lump-sum budgets are not accepted. Budget submissions must itemize printing, mementos, refreshments, guest honorariums, and technical equipment.
   - `[ENGINEERING INFERENCE]`: Every line item requires a positive unit price (`> 0`) and quantity (`>= 1`).

---

## 5. Multi-Level Approval Chain Rules

1. **Sequential 6-Stage Progression**:
   - `[FACT: INSTITUTIONAL DOCS]`: The college clearance hierarchy strictly follows:
     - **Step 1: Faculty Advisor** — Academic feasibility & departmental concurrence.
     - **Step 2: Hall In-Charge** — Venue physical availability & logistics suitability.
     - **Step 3: Finance Officer** — Budget sanction & funding ceiling verification.
     - **Step 4: Advisor Students Union** — Inter-club calendar coordination & student welfare.
     - **Step 5: Dean Student Affairs** — Institutional policy & disciplinary compliance.
     - **Step 6: Principal** — Final executive sanction.
   - `[ENGINEERING INFERENCE]`: Approver at Step N cannot act until Step N-1 has reached `APPROVED` status.
2. **Conflict of Interest & Self-Approval**:
   - `[ENGINEERING INFERENCE]`: A Club Secretary who also holds an academic or reviewer role is strictly blocked from approving their own event proposal.
3. **Reviewer Action Semantics**:
   - `[ENGINEERING INFERENCE]`:
     - **Approve**: Advances workflow to Step N+1 (or final sanction at Step 6). Remarks optional.
     - **Request Revision**: Reverts proposal to `REVISION_REQUIRED`. Restores edit rights to Club Secretary. Mandatory remarks (`>= 5 characters`).
     - **Reject**: Terminates workflow permanently (`REJECTED`). Proposal cannot be edited or resubmitted. Mandatory remarks (`>= 5 characters`).
4. **Statutory Non-Bypassability**:
   - `[FACT: INSTITUTIONAL DOCS]`: Administrative staff or IT personnel cannot sign off on behalf of the Principal or Finance Officer.
   - `[ENGINEERING INFERENCE]`: `SYSTEM_ADMIN` is hard-blocked from approving or rejecting Steps 2 through 6.

---

## 6. Document & Media Governance Rules

1. **Allowed MIME Types & Extensions**:
   - `[FACT: INSTITUTIONAL DOCS]`: Event documentation comprises official circulars, brochures, speaker profiles, and budget estimations.
   - `[ENGINEERING INFERENCE]`: Permitted extensions: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.docx`.
   - `[ENGINEERING INFERENCE]`: Maximum upload size: 10 MB per file.
2. **Magic-Byte Cryptographic Inspection**:
   - `[ENGINEERING INFERENCE]`: Files must pass signature verification (`%PDF-`, `\x89PNG`, `\xff\xd8\xff`, `PK\x03\x04`). Renamed scripts or executables are rejected with `HTTP 400 UnsupportedMediaType`.
3. **Storage Isolation**:
   - `[ENGINEERING INFERENCE]`: Files are saved with UUID filenames under directory `/data/uploads/{event_id}/`. Directory traversal (`../`) is verified impossible via `Path.resolve().is_relative_to()`.

---

## 7. Confirmed Event & Immutability Rules

1. **Post-Sanction Immutability**:
   - `[FACT: INSTITUTIONAL DOCS]`: Once the Principal signs the approval sheet, event dates, hall allocations, and sanctioned funds cannot be altered informally.
   - `[ENGINEERING INFERENCE]`: Upon Step 6 approval, the proposal is locked permanently in `APPROVED` status, and an official `Event` record is instantiated in `SCHEDULED` status.
2. **Audit Logging Guarantee**:
   - `[FACT: INSTITUTIONAL DOCS]`: Administrative reviews require immutable historical records of all approvals and rejections.
   - `[ENGINEERING INFERENCE]`: All state changes write to an append-only `AuditLog` table containing actor ID, IP address, timestamp, and before/after metadata snapshots.

---

## 8. Summary of Evidence Status

| Governance Domain | Status | Institutional Confirmation Needed |
| :--- | :---: | :--- |
| **Pre-Event 6-Stage Approval** | Fully Documented & Verified | No — Matches historical institutional practices |
| **Hall GiST Exclusion Policy** | Fully Documented & Verified | No — Absolute institutional requirement |
| **Budget Grant Ceiling (₹15,000)** | Verified in Code | Requires periodic review by College Finance Committee |
| **Post-Event Settlement Authority** | Gap Identified | **YES — Subject of Day 7 Decision 1** |
| **Funding Mechanism (Advance/Reimburse)**| Gap Identified | **YES — Subject of Day 7 Decision 2** |
| **Approved Event Cancellation Authority**| Gap Identified | **YES — Subject of Day 7 Decision 3** |
