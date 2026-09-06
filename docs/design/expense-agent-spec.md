# Expense Agent — Design Spec v0.2

Status: DRAFT — reviewed once internally (BC Expert + Domain Expert
personas); pending external SME review before any build decision.
Author: Vikas (via Claude design session)
Date: 2026-09-06

## 1. Purpose

Design an AI-assisted expense management capability for Business Central
customers (India-first, globally applicable) that lets employees capture and
submit expenses continuously, handles mixed company-paid/employee-paid
funding, advances, and India statutory compliance (GST ITC, TDS,
perquisite), and posts cleanly into BC's ledgers.

This is a **design spec**, not an implementation plan. No code is written
against this yet. Goal of this document is to get correctness feedback from
a BC/ERP expert and an accounting/Indian-compliance domain expert before any
build decision.

## 2. Scope

In scope:
- Expense capture (as-and-when) and expense report submission (batched)
- Company-paid vs. employee-paid vs. split vs. advance-funded expenses
- Advance request → disbursement → netting → settlement
- Approval workflow (interim/final, delegation, exceptions)
- India GST ITC eligibility, GSTIN/branch matching, TDS flag, perquisite flag
- Mapping of new data to BC objects: native tables, Dimensions, or new
  custom (AL extension) tables

Out of scope (for this doc):
- Actual AL/table/page implementation
- Payroll system integration details (only the handoff point is specified)
- Corporate card statement auto-reconciliation logic (noted as a dependency,
  not designed here)
- Non-BC ERPs

## 3. Reference: what BC ships natively (2026 Wave 1)

- **Native "Expense Reports" module**: Expense Categories, two Posting
  Groups, Expense Reports (header) + Expense Lines, itemization,
  participants, mileage, per diem. Payment Methods carry a Reimbursement
  Type: `Employee Paid`, `Company Paid/Credit Card`, `Cash Advance`.
  Approval → Employee Ledger Entries + Expense Ledger Entries → G/L →
  reimbursement run.
- **Expense Agent** (Copilot layer, public preview May 2026, US-English
  only at launch): submission via Outlook/Teams/M365 Copilot Chat/web app,
  OCR + auto-categorization + itemization, continuous policy validation,
  interim + final approval.
- Neither the release notes nor Microsoft Learn pages reviewed mention
  India localization (GST/TDS) hooks for this module as of this writing —
  **treat India compliance fields as a gap to be confirmed, not assumed
  present.** (See open question BC-1.)

Sources: Microsoft Dynamics 365 Blog (Expense Agent, Apr 2026); Microsoft
Learn — Expense Management Overview, Expense Agent Overview, Set Up Expense
Categories and Rules, Release Plan 2026W1 (Manage employee expenses using
expense reports; Manage expenses using Expense Agent).

## 4. Actors

- **Employee** — captures/submits expenses, requests advances
- **Approver (manager)** — interim/final approval, exception review
- **Finance/AP** — posting, advance aging review, GST/TDS review
- **Payroll** — perquisite/taxable-benefit handling (handoff only)
- **Delegate** — submits/approves on behalf of another user
- **Expense Agent (system)** — OCR, categorization, policy validation,
  duplicate/fraud checks

## 5. Functional requirements

### 5.1 Capture (continuous)
- FR-1: Employee can submit a single expense at any time via
  app/photo/email-forward, independent of any report.
- FR-2: System extracts vendor, date, amount, tax breakup (where present)
  and proposes a category; employee/approver can override.
- FR-3: Captured-but-unsubmitted expenses are visible in a running
  "pending" list per employee.

### 5.2 Report submission (batched)
- FR-4: Employee can bundle any subset of pending expenses into an
  Expense Report and submit for approval at any time (ad hoc).
- FR-5: System supports configurable submission nudges: trip-end based,
  monthly-cutoff based (aligned to GST filing cutoff), and
  pending-value-threshold based. Nudges are reminders, never hard blocks
  on ad hoc submission (FR-4 always available).
- FR-6: A report may contain lines with different reimbursement types
  (see 5.3) in any combination.

### 5.3 Funding / reimbursement type (line-level attribute)
- FR-7: Every expense line carries one Reimbursement Type: `Employee Paid`,
  `Company Paid`, or `Advance Offset`.
- FR-8: A single source invoice can be itemized into multiple lines with
  different Reimbursement Types (e.g., hotel bill: business nights =
  Company Paid, personal extension = Employee Paid).
- FR-9: `Advance Offset` lines net against a specific Advance Request
  (5.4); only the balance (if any) is reimbursed or recovered.

### 5.4 Advance requests
- FR-10: Employee can raise an Advance Request (amount, purpose, linked
  trip/project, expected settlement date) before or independent of any
  expense report.
- FR-11: Approved advances are disbursed and tracked as outstanding
  against the employee until settled.
- FR-12: One or more Expense Reports can be submitted against a single
  Advance Request (partial settlement supported).
- FR-13: On settlement: Report total > Advance → reimburse difference.
  Report total < Advance → recover difference (repayment or payroll
  deduction — recovery *mechanism* is a domain-expert decision, D-1).
  Equal → close advance, no payment either direction.
- FR-14: System flags advances outstanding beyond a configurable age
  (e.g., 30/60/90 days) for finance follow-up.
- FR-15: New Advance Request is blocked if employee has an overdue
  unsettled advance beyond a configurable threshold (policy-configurable,
  can be disabled).

### 5.5 Approval
- FR-16: Approval matrix is configurable by role/grade/department/category/
  amount, intended to mirror the company's existing Delegation of
  Financial Authority (DOFA) document rather than a single global rule.
- FR-17: Approver can approve/reject at line level (interim) without
  blocking the rest of the report; final approval closes the report.
- FR-18: Delegation: an approver can nominate a delegate (leave coverage);
  a user can submit on behalf of another (assistant-for-executive).
- FR-19: Out-of-policy lines (over limit, missing receipt above
  threshold, duplicate suspicion, weekend/holiday date) are flagged, not
  auto-rejected, and routed to an explicit exception-approval step with a
  mandatory reason code.
- FR-20: Duplicate detection compares vendor+amount+date+receipt-image
  hash across the employee's history (and optionally org-wide, to catch
  the same bill submitted by two people).

### 5.6 India compliance
- FR-21: Capture vendor GSTIN and tax breakup (CGST/SGST/IGST) per line
  where applicable.
- FR-22: Each line carries an ITC Eligible flag (Yes/No/Blocked) with a
  reason code for blocked credit (Sec 17(5) CGST Act categories — e.g.,
  employee food & beverages, outdoor catering, non-mandated employee
  insurance) — default per category, employee/finance can review.
- FR-23: Resolve the correct company GSTIN for a claim by matching the
  expense's location/branch (see §7 — proposal: reuse BC Location master)
  against the vendor/place-of-supply state.
- FR-24: Flag lines where a TDS obligation may arise from an employee-
  mediated payment (e.g., professional fees paid in cash by employee)
  for finance review before reimbursement.
- FR-25: Flag lines/categories that exceed statutory tax-exempt
  reimbursement limits (conveyance, telephone/internet, LTA, medical) for
  payroll perquisite handling; do not silently treat as a clean
  non-taxable reimbursement.
- FR-26: Support receipt-less self-declaration below a configurable
  per-instance and monthly-aggregate threshold.

### 5.7 Posting
- FR-27: Approved reports generate Employee Ledger Entries / G/L Entries
  (and Vendor Ledger Entries where a corporate-card statement match
  applies) consistent with native BC posting behavior.
- FR-28: Dimensions relevant to the line (cost center, department,
  project/job, billable customer, trip) flow to the posted entries.
- FR-29: Reimbursement payments are batchable into a payment run
  (bank transfer or payroll-carried).

## 6. State machine

```
[Draft line] --bundle--> [Draft report] --submit--> [Pending approval]
   --interim review--> (exceptions flagged/resolved)
   --final approval--> [Approved] --advance netting--> [Posted]
   --payment run--> [Reimbursed | Recovered]

Rejected report --resubmit (versioned)--> [Draft report]

[Advance Request] --approve--> [Disbursed/Outstanding]
   --report(s) settle against it--> [Partially settled | Closed]
   --aging threshold exceeded--> [Flagged for finance]
```

## 7. Mapping new data to Business Central objects

This is the question this doc most needs BC-expert eyes on. Proposed
default split — **confirm or correct each row**:

| Need | Proposed BC mechanism | Why | Confirm? |
|---|---|---|---|
| Cost center | Global Dimension 1 (or existing shortcut dim) | Standard analytical tag, needs to flow to G/L/Employee Ledger like any journal | BC-2 |
| Department | Global Dimension 2 / shortcut dimension | Same as above | BC-2 |
| Project/Job | Dimension, or actual `Job No.` if Jobs module is in use | If billable-to-customer is needed, Jobs module may be the correct object, not just a dimension | BC-3 |
| Billable customer (rebill) | Dimension, or Job's Bill-to Customer if Jobs module used | Same as above | BC-3 |
| Trip/batch reference | Dimension value (e.g., "Trip: MUM-2609") | Lightweight cross-report grouping for reporting/reminders | — |
| Branch / which company GSTIN applies | **Existing BC `Location` master** (India localization already carries GST Registration No. per Location) | Avoids inventing new master data; reuses a table that already exists and is already GST-aware in most IN-localized installs | BC-4 |
| GSTIN of vendor, HSN/SAC, tax breakup, ITC eligibility + reason | New fields — likely a **table extension on Expense Line** (not a dimension; this is structured compliance data with its own validation, not an analytical tag) | Dimensions aren't the right fit for data with lifecycle/validation rules (reason codes, computed eligibility) | BC-1, BC-5 |
| TDS flag/section, perquisite flag | Table extension on Expense Line | Same reasoning | BC-1, BC-6 |
| Advance Request (header + status + aging) | **New table** — no clear native equivalent found; "Cash Advance" in the native module appears to be a *payment method classification on a line*, not a trackable advance-with-aging object | Needs an outstanding-balance-per-employee view that a payment-method tag alone doesn't give | BC-7 |
| Duplicate hash / OCR confidence / exception reason code | Table extension on Expense Line, or a companion table | Operational/audit metadata, not reporting-dimension data | — |
| Approval matrix (role/grade/category/amount → approver) | Reuse BC's native Workflow + Approval User Setup **if it supports this granularity**; else a new configuration table | Don't build a custom approval engine if native Workflow already covers it — needs BC-expert confirmation | BC-8 |
| Participants (shared bill) | Native — release notes say the 2026W1 module already has a Participants concept | Reuse, don't rebuild | BC-9 (confirm it's usable pre-agent / matches our participant model) |

### General principle being proposed
- **Dimensions** = cross-cutting analytical tags with no independent
  lifecycle (cost center, department, project, trip, billable customer).
  They should flow automatically to ledger entries the way any BC
  dimension does.
- **Table extensions on existing BC tables** (Expense Line, Expense
  Report) = compliance/data fields that belong to that specific record
  and need validation (GSTIN, ITC flag, TDS flag).
- **New custom tables** = only where no native object plausibly covers
  the need after checking (Advance Request/aging is the clearest
  candidate; approval matrix is a "maybe," pending BC-8).

This keeps the design close to standard BC extensibility patterns (AL
table/page extensions + dimensions) rather than introducing a parallel
custom data model, which should make it easier to upgrade-safe across BC
releases and easier for a BC consultant to support later.

### 7.1 Alternative: keep enrichment/workflow data outside BC entirely

This repo's own Data Trust capability already establishes a working
precedent for this, and it should be treated as the default rather than
the AL-table-extension approach above, pending BC-11 below:

- `DataTrustFinding` (`MCP/modules/data_trust_engine/models.py:48-68`)
  stores locally-owned records (JSON-backed, no SQL/ORM in this repo
  today — see `requirements.txt`) carrying workflow state BC has no
  concept of (Open/Under Review/Confirmed/False Positive/Ignored), linked
  back to BC via `StructuredEvidence` (`entity_table`, `record_id`,
  `field_name`) and synthetic keys such as `IC-ILE-{ile_id}`
  (`acquisition.py:333`) tied to a BC ledger entry number.
- `DataAcquirer` (`acquisition.py:104-267`) is strictly read-only against
  BC's OData v2.0 endpoints — no AL extension, no per-tenant app install.

Applying the same pattern here:

- **Own tables (linked to BC by key, not posted into BC's schema)**: OCR
  extraction + confidence, duplicate-detection hashes, GSTIN/HSN/tax
  breakup working data, ITC-eligibility computation + reason code, TDS
  flag, perquisite flag, Advance Request lifecycle + aging, the
  DOFA/approval-matrix configuration, approval workflow audit trail,
  policy-exception reason codes.
- **Must still post into BC** (not a design choice — Companies Act books
  of account and any GST-return prep that reads BC directly require it):
  the final approved financial transaction — G/L Entry / Employee Ledger
  Entry / Vendor Ledger Entry — and the Dimensions on it.
- Post the clean, approved result via BC's standard journal/ledger API
  surface (the same class of API this repo's staged/unposted draft
  documents already use), rather than writing into Expense Line/Report
  via a table extension. If achievable, this removes the need for **any**
  AL extension, and with it the upgrade-collision risk in BC-5/BC-6.
- "Maintain" = a periodic pull-based reconciliation between our own state
  (e.g., Advance Request outstanding balance) and BC's actual ledger
  entries, using the same acquisition/findings-diff pattern Data Trust
  already runs — to catch drift if a BC record is edited or corrected
  outside this workflow after posting.
- Trade-off to make explicitly with whoever owns GST filing: if their
  return-prep process queries BC directly rather than through this
  engine, ITC-eligibility/TDS flags kept only in our tables won't be
  visible there. Given this product's positioning as the
  reconciliation/compliance layer over BC, the default assumption is that
  this tool is the source of truth for compliance flags and BC is the
  source of truth for posted amounts — but confirm this is acceptable
  before committing to it.

## 8. Open questions for BC Expert

- **BC-1**: Does the native Expense Line table already run through BC's
  GST/Tax engine (Tax Area/Tax Group as on Purchase Lines), or does it
  post without tax breakup today? This determines whether GST fields are
  a genuine gap or already present.
- **BC-2**: Confirm whether reusing Global Dimensions 1/2 for cost
  center/department is safe, or whether customers' existing dimension
  usage (many IN-localized installs already use Global Dim 1/2 for other
  purposes) means we should default to unused shortcut dimensions
  instead.
- **BC-3**: Should billable/rebillable expenses ride on the Jobs module
  (Job No./Job Task) rather than a plain dimension, when Jobs is
  licensed?
- **BC-4**: Confirm `Location` (with GST Registration No.) is in fact the
  right/only native object for branch-GSTIN resolution, and that it's
  populated in typical IN-localized installs (not just available but
  unused).
- **BC-5/BC-6**: Best-practice pattern for extending Expense Line via
  table extension without breaking the native Expense Agent's own
  writes/upgrades to that table.
- **BC-7**: Is there really no native "Cash Advance" ledger/aging object,
  or did we miss one? (Payment Method Reimbursement Type = `Cash Advance`
  looks like a line classification, not an outstanding-balance tracker.)
- **BC-8**: What granularity does native Approval Workflow / Approval
  User Setup actually support — can it express "category X + grade Y +
  amount > Z → approver role W," or does it only do amount-based limits?
- **BC-9**: Confirm what the native Participants feature captures today
  (names only, or business purpose too) and whether it's usable
  independent of the Copilot Expense Agent (i.e., in India before that
  agent is available there).
- **BC-10**: Any known India-localization roadmap for this module we
  should wait on rather than build ourselves?
- **BC-11**: Does BC 2026W1's native Expense Report/Expense Line expose a
  write-capable API (so we could post clean, pre-validated data and let
  BC's own engine generate the ledger entries), or would posting have to
  go directly through the standard General/Payment Journal API instead,
  bypassing Expense Report/Line entirely? This decides whether the
  Section 7.1 "no AL extension" approach is viable as described, or needs
  adjustment.

## 9. Open questions for Domain Expert (accounting / Indian compliance)

- **D-1**: Preferred recovery mechanism when an employee under-spends an
  advance — payroll deduction, direct repayment, or carry-forward against
  next advance? Does this vary by advance type (travel vs. project
  imprest)?
- **D-2**: Current statutory tax-exempt limits to encode for conveyance,
  telephone/internet, LTA (including block-year rules), and medical
  reimbursement — and how often these need review (Finance Act changes).
- **D-3**: Should the Sec 17(5) blocked-credit default list be
  configurable per company, or should some companies be allowed to
  voluntarily claim and reverse instead of blocking upfront?
- **D-4**: Typical receipt-less self-declaration thresholds (per instance
  and monthly aggregate) seen in practice — is ₹200–500/instance a
  reasonable default?
- **D-5**: What advance-aging thresholds (30/60/90 days) and audit
  sampling rate are typical for a company this size/sector?
- **D-6**: Does a DOFA (Delegation of Financial Authority) document
  typically key approval limits off category, grade, department, or some
  combination — need a representative example structure to validate
  FR-16.
- **D-7**: For TDS-on-behalf-of-vendor scenarios via employee
  reimbursement (FR-24), how commonly does this actually arise in
  practice, and is flag-for-review sufficient or does it need to block
  reimbursement until resolved?
- **D-8**: GSTR-2B/3B filing cutoff timing to calibrate the monthly
  submission nudge (FR-5) — confirm the practical "must be submitted by"
  date finance actually needs, not just the statutory filing date.

## 10. Assumptions / risks

- Assumes the company already licenses BC's Expense Management module
  (2026 Wave 1) as the posting backbone; this design layers on top of it
  rather than replacing it.
- Assumes India localization for GST/TDS may need to be extended
  independently of when/whether the Copilot Expense Agent reaches India
  (per search results, only US at May 2026 preview, UK from July 2026 —
  no India date found).
- Risk: if BC-7 finds a native advance-tracking object we missed, the
  proposed new Advance Request table becomes redundant duplication —
  must confirm before building.
- Risk: if BC-8 finds native Approval Workflow can't express
  category+grade matrices, the approval engine becomes a larger custom
  build than currently scoped.

## 11. Internal review notes (BC Expert + Domain Expert personas, v0.1 → v0.2)

These are corrections from a first internal review pass. They should be
validated by real BC/domain SMEs, not treated as settled — but they change
the design enough to record before anyone reads v0.1 in isolation.

**BC — likely wrong assumption in Section 7/BC-7:** Employee Ledger
Entries already support Open/Closed status, Remaining Amount, and
Application (same mechanics as Customer/Vendor Ledger Entries) — this
predates 2026W1. An advance can plausibly be posted as a Payment Journal
line (Account Type = Employee) and later applied against the Employee
Ledger Entry the settling Expense Report generates. **Before building a
new Advance Request ledger table, verify whether native application/aging
on Employee Ledger Entry already covers FR-11/FR-13/FR-14** — if so, only
a thin request/approval UI is needed on top, not a parallel ledger.

**BC — BC-4 upgraded from "confirm" to "reasonably confident":**
GST Registration No. on Location is an established BC India-localization
pattern, not just a guess.

**BC — BC-8 narrowed:** native Workflow conditions plus Approval User
Setup limits plus the existing employee/manager hierarchy plausibly cover
category+amount branching without a custom engine. The real gap is a
grade/band concept independent of reporting-line hierarchy, which needs a
small lookup, not a full custom approval engine. Re-scope BC-8 to ask
specifically whether one Workflow can condition on Category AND Amount
together.

**Domain — FR-25 conflates two different legal concepts.** "Reimbursement
of actual expense" (e.g., telephone bill, actual official-duty conveyance)
is not a perquisite at all when backed by a bill — no exemption limit
applies because it was never income. A fixed "allowance" (e.g., conveyance
allowance) is taxable salary, exempt only up to a Sec 10(14) statutory cap.
Separately, "medical reimbursement" as its own exempt category is largely
obsolete since FY 2018-19 (folded into the ₹50,000 standard deduction), and
most such exemptions don't apply at all if the employee is on the **new
tax regime** (the default since FY 2023-24). **Action: split FR-25 into
reimbursement-of-actual-expense vs. allowance, and make exemption logic
regime-aware per employee**, rather than one shared "tax-free limit"
concept.

**Domain — FR-13 needs a legal constraint added.** Recovering an
under-spent advance via payroll isn't a free design choice — Payment of
Wages Act, 1936 (Sec 7(2)(f) and deduction caps) generally requires
installment-based recovery of advances from wages, not a single lump-sum
deduction. **Action: FR-13 should support an installment schedule, not
just one-shot recovery.**

**Domain — FR-22 needs an explicit override path.** Sec 17(5) blocked
credits have a carve-out: ITC becomes eligible where a service is
government-notified as obligatory for the employer to provide under law
(e.g., certain statutory insurance). Keep the default-block behavior but
make sure the reason-code mechanism allows this override, not a hard rule.

**Domain — FR-26 should link to FR-22.** A receipt-less self-declared line
has no invoice, therefore ITC eligibility should default to **No**
automatically, not be evaluated separately. Also, D-4's ₹200–500/instance
range is an internal-control norm, not a statutory minimum — state that
explicitly so it isn't mistaken for a compliance requirement later.

**Domain — D-5 default is too loose.** 30/60/90-day advance aging is
borrowed from AP/vendor aging norms and understates the cash-leakage risk
of employee advances, which are usually tied to a known trip/project
end-date. Recommend a tighter default such as 15/30/45 days
(still policy-configurable).

**Domain — D-7 should be a hard policy cap, not just a flag.** TDS-on-
behalf-of-vendor via employee reimbursement is expensive to unwind after
the fact (gross-up, Sec 201 interest exposure on short deduction).
**Action: add a policy rule redirecting single-vendor cash payments above
a threshold to AP instead of employee reimbursement**, in addition to the
existing flag-for-review behavior.

**Domain — D-8 is missing the deadline that actually matters.** The
monthly GST-filing-cutoff nudge (FR-5) is good hygiene but not the
compliance-critical deadline. **Sec 16(4) CGST Act time-bars an ITC claim
by 30th November of the following financial year** (or the annual return
date, if earlier) — missing it loses the credit permanently, not just
delays it. **Action: add a financial-year-end sweep reminder** alongside
the monthly nudge.

**Domain — D-6 confirmed**, with one addition: real DOFA documents
typically also name a specific override authority above the top monetary
slab, not just "escalate to next role up." FR-16 should allow for a named
override authority, not only a role-based chain.
