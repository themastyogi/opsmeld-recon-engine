# Expense Agent — Design Spec for SME Review v1.9

Status: **ALL SIX COUNCIL CONDITIONS CLOSED (2026-09-06).** Infra
decision, `LLMInterpreter` reuse, row-level isolation design, LLM/OCR
cost estimate, D-1/D-2/D-3 (reframed as customer-configurable policy),
and BC-1/BC-7/BC-8/BC-11 (resolved by architecture decision — Purchase
Invoice for GST lines, `OPSMELD_NATIVE` approval, Employee-as-Vendor as
a per-customer option, custom-API fallback if needed) are all closed.
**This clears the pre-build gate — it is not itself a green light to
build the full 40-table schema in one pass.** The council's own
Product Manager finding still holds: start with a thin vertical slice
(one workflow end-to-end) rather than the whole schema at once. This is
the lean, decision-focused version of the design: architecture, scope,
functional requirements, and the open questions that actually need
expert judgment. The full 40-table engineering schema, conversational
workflow walkthroughs, and reporting/dashboard design live in the
companion document `expense-agent-blueprint.md` in this same folder —
reference it only if you need implementation-level detail; it is not
needed to answer the P0/P1 questions below.
Author: Vikas (via Claude design session)
Date: 2026-09-06

## 1. Purpose

Design an AI-assisted expense management capability for Business Central
customers (India-first, globally applicable) that lets employees capture
and submit expenses continuously, handles mixed company-paid/employee-paid
funding, advances, and India statutory compliance (GST ITC, TDS,
payroll/perquisite treatment), and records the final approved accounting
transaction in BC.

This is a design spec, not an implementation plan. No production code is
written against this yet. The goal is correctness feedback from a BC/ERP
expert and an accounting/Indian-compliance domain expert before any build
decision.

## 2. Core Architecture Decision

### 2.0 Inspiration, not replication

This design takes workflow/UX inspiration from how BC (and Concur,
Expensify, Zoho Expense) structure expense capture, approval, and
settlement. **It does not attempt to mirror BC's specific Expense
Report/Expense Line objects, replicate BC's Copilot Expense Agent, or
plug into that module's internals.** The application's own domain model
(§7 in the blueprint) is independent of BC's schema by design (§2.1's
system-of-record boundary already established this — this section makes
the consequence explicit).

The one hard BC dependency this design actually has: **posting a
finished, GST-computed, dimension-tagged transaction into BC's ledgers.**
That's it. That posting can go through BC's long-standing General/Payment
Journal API (stable since BC API v2.0, ~2019, and how most third-party
expense tools already integrate with BC) rather than through the new
2026W1 Expense Report/Line API. That materially changes which BC-N
questions are actually blocking — see the note at the top of §8.

### 2.1 System-of-record boundary

| Data / responsibility | System of record | Notes |
|---|---|---|
| Expense capture and source evidence | Expense system | Receipt/image, extracted fields, employee input |
| OCR / extraction / AI interpretation | Expense system | AI output plus confidence and evidence |
| Policy evaluation | Expense system | Rule evaluation and decision provenance |
| GST / TDS / payroll tax assessment | Expense system | Versioned compliance assessment; final accounting remains in BC |
| Approval workflow state / audit trail | Expense system | Unless deliberately delegated to native BC workflow |
| Operational advance request | Expense system | Request, purpose, approval, expected settlement |
| Accounting advance balance | BC | Prefer native Employee Ledger Entry/application mechanics if confirmed by BC SME |
| Final accounting transaction | BC | Accounting system of record |
| G/L Entry / Employee Ledger Entry / Vendor Ledger Entry | BC | Native posting result |
| Dimensions | BC | Must flow to posted entries |
| Reconciliation state / evidence | Expense system | Links application state back to BC transaction keys |

**Principle:** the Expense capability owns capture, decisioning,
compliance assessment, workflow evidence, and reconciliation state;
Business Central owns the accounting result for approved financial
transactions. The Expense capability should not create a parallel
subledger for amounts BC already owns natively.

This follows the same pattern this repo's own Data Trust module already
uses in production: local records (`DataTrustFinding`) linked back to BC
by key, with BC read via API and never written to directly via table
extension.

### 2.2 Provider abstraction

Rather than hard-coding either "we own everything" or "BC owns
everything," each configurable capability (expense categories, payment
methods, approval policy, GST/ITC rules, dimension mapping, etc.) is
assigned one of three provider modes:

| Provider mode | Meaning | When used |
|---|---|---|
| `MICROSOFT_NATIVE` | Opsmeld stores canonical config and syncs it to BC native setup; BC executes | BC has the native capability and we trust it |
| `OPSMELD_NATIVE` | Opsmeld evaluates and executes; only the resulting accounting data crosses into BC | BC lacks the capability, is unavailable in India, or lacks sufficient API |
| `HYBRID` | Opsmeld owns the canonical policy/evaluation; supported portions project to BC | Native BC capability exists but isn't sufficient alone |

This is a per-capability, per-tenant, per-company selection, not a
global switch. The reason for this layer: it lets a future Microsoft
release (e.g. native India GST support) get adopted by changing a
mapping/provider record, without restructuring the expense, report,
compliance, or audit schema. **This is a real scope decision, not free**
— it's a deliberate choice to build a configuration control plane now
rather than a direct mapping like earlier drafts of this spec had. Full
schema for this is in the blueprint doc (§2.4, §7.3, §7.5).

### 2.3 Channel independence

The same core expense/advance domain model supports app/photo, email,
Teams, Outlook, or future channels — a conversational message (Teams,
Outlook) is unstructured input into a common intake layer that resolves
identity, classifies intent, extracts attributes, validates against
setup/BC reference data, and requires explicit user confirmation before
creating a financial request when interpretation isn't already
deterministic. AI may extract/propose; it may not independently approve,
override policy, or post financial records.

## 3. Scope

In scope:
- Expense capture (as-and-when) and expense report submission (batched)
- Company-paid vs. employee-paid vs. split vs. advance-funded expenses
- Advance request → approval → BC journal creation → BC journal posting
  → advance outstanding → netting → settlement
- Approval workflow (interim/final, delegation, exceptions)
- India GST ITC eligibility, GSTIN/branch matching, TDS assessment,
  payroll/perquisite assessment
- Mapping of final accounting data to BC native objects / APIs
- Application-side operational, compliance, workflow, evidence, and
  reconciliation data model
- Auditability, idempotency, and reconciliation

Out of scope for this doc:
- Actual AL/table/page implementation
- Payroll system integration details (only the handoff point is
  specified)
- Corporate card statement auto-reconciliation logic (dependency, not
  designed here)
- Non-BC ERPs

## 4. Reference: what BC ships natively (2026 Wave 1)

- **Native "Expense Reports" module**: Expense Categories, two Posting
  Groups, Expense Reports (header) + Expense Lines, itemization,
  participants, mileage, per diem. Payment Methods carry a Reimbursement
  Type: `Employee Paid`, `Company Paid/Credit Card`, `Cash Advance`.
  Approval → Employee Ledger Entries + Expense Ledger Entries → G/L →
  reimbursement run.
- **Expense Agent** (Copilot layer, public preview May 2026, US-English
  only at launch): submission via Outlook/Teams/M365 Copilot Chat/web
  app, OCR + auto-categorization + itemization, continuous policy
  validation, interim + final approval.
- Neither the release notes nor Microsoft Learn pages reviewed mention
  India localization (GST/TDS) hooks for this module as of this writing
  — treat India compliance fields as a gap to be confirmed, not assumed
  present (see BC-1).
- As of the release-plan documentation reviewed on 2026-09-06, Expense
  Agent public preview geography lists the US and then Australia, New
  Zealand, and UK; India is not listed. A later search that same day
  (aggregated results summarizing Microsoft's "Copilot and agents
  country/region availability" page — see source below) reported more
  specifically that "environments in the UK, India, and Australia are
  excluded from an initial rollout and will receive updates at a later
  date." **Confidence note, per BC-expert review**: this second claim
  comes from an aggregated search summary, not a direct fetch of
  Microsoft's own page (blocked by network egress in this environment)
  — treat it as higher-confidence than "not listed" but not
  primary-source-verified. Either way, don't plan around Indian
  Expense-Agent-UI availability without checking the live page yourself
  before it matters.

**Update, per second BC-expert re-review (attempted to close this
exact gap, still open)**: a direct `WebFetch` to `learn.microsoft.com`
was blocked by network egress in that review's environment too —
independently corroborating that this limitation is real, not an
excuse, across two separate review sessions. A further aggregated
search surfaced two claims that don't fully reconcile: (a) "public
preview is available in English and the US only, but following with
these countries/regions in July 2026" — a general regional-expansion
date for Expense Agent; and (b) a narrower claim that "UK, India, and
Australia [are] excluded from the GPT-5.3-chat model update for
agents," which is about a specific *model-version* rollout, not
necessarily Expense-Agent-*feature* availability itself. **These two
aggregated, non-primary-source snippets can't be reconciled from search
alone.** If (a) is accurate and applies to the feature (not just the
model), Wave 1/India access could arrive well before this design
reaches build — which would change the "optional native-path
exploration" calculus in §8. **Recommended next step**: someone with
actual BC admin-center/tenant portal access should check the live
"Feature availability by country/region" page directly — that's the
primary source neither this review nor the prior one could reach.

Sources: Microsoft Dynamics 365 Blog (Expense Agent, Apr 2026); Microsoft
Learn — Expense Management Overview, Expense Agent Overview, Set Up
Expense Categories and Rules, Release Plan 2026W1, Copilot and agents
country/region availability and supported languages (accessed via
aggregated search, not direct fetch — direct fetch attempted twice,
blocked both times).

## 4A. Verified: this codebase has no BC write path today

Confirmed by direct code inspection (`MCP/core/bc_mcp_client.py`), not
inference: `_execute_bc_rest` (line 277) and `_execute_bc_rest_url`
(line 321) are the only two methods that call BC's REST API directly,
and both build their `urllib.request.Request` without a `method=`
argument — which defaults to GET. There is a POST in this file (line
214), but it targets the MCP JSON-RPC server itself, not BC's REST
surface. **There is no POST/PATCH against BC anywhere in this codebase
today** — not "read-only by convention," but no write method exists at
all.

Practical consequence: FR-49–FR-55 (posting, idempotency, retry
reconciliation) are greenfield engineering for this codebase, not an
extension of an existing capability. Scope/estimate accordingly.

## 5. Actors

- **Employee** — captures/submits expenses, requests advances
- **Approver (manager)** — interim/final approval, exception review
- **Finance/AP** — posting, advance aging review, GST/TDS review
- **Payroll** — perquisite/taxable-benefit handling (handoff only)
- **Delegate** — submits/approves on behalf of another user
- **Expense Agent (system)** — OCR, categorization, policy validation,
  duplicate/fraud checks
- **Compliance/Rule owner** — maintains rule versions and approves rule
  changes

## 6. Functional Requirements

### 6.1 Capture (continuous)
- FR-1: Employee can submit a single expense at any time via
  app/photo/email-forward, independent of any report.
- FR-2: System extracts vendor, date, amount, currency, tax breakup
  (where present), and proposes a category; employee/approver can
  override.
- FR-3: Captured-but-unsubmitted expenses are visible in a running
  "pending" list per employee.
- FR-4: Each captured expense has a lifecycle independent of the report
  lifecycle: Captured, Processing, Needs Review, Ready, Attached,
  Submitted, Rejected, Archived.
- FR-5: Source evidence is retained and linked to the expense.

### 6.2 Report submission (batched)
- FR-6: Employee can bundle any subset of pending expenses into an
  Expense Report and submit for approval at any time (ad hoc).
- FR-7: Configurable submission nudges: trip-end based, monthly cutoff
  based, pending-value-threshold based, and financial-year-end ITC sweep
  reminder.
- FR-8: Nudges are reminders, never hard blocks on ad hoc submission
  unless a separate explicit policy rule is configured.
- FR-9: A report may contain lines with different funding/settlement
  types in any combination.
- FR-9A–FR-9F: All configurable capabilities have a canonical Opsmeld
  representation and a provider mode (§2.2); rules/policies are
  versioned and immutable once used by a decision; setup sync to BC is
  idempotent and reconcilable.

### 6.3 Funding and settlement model

Do not use one field to represent both how an expense was funded and how
it will be settled:

| Funding Source | Settlement Method / Result |
|---|---|
| Employee | Employee Reimbursement |
| Corporate Card | Card Settlement |
| Company Paid | No Settlement |
| Employee Advance | Employee Recovery |

- FR-10: Every expense allocation/line records one Funding Source and
  one expected Settlement Method.
- FR-11: A single source invoice can be itemized into multiple
  lines/allocations with different funding sources.
- FR-12: Employee Advance allocations must reference a specific Advance
  Request / accounting advance reference.
- FR-13: On advance settlement: Report total > usable advance →
  reimburse difference; Report total < usable advance → recover
  difference; Equal → close with no payment either direction.
- FR-14: Under-spent advance recovery must support an installment
  schedule where payroll deduction is used (Payment of Wages Act
  constraint); a one-shot deduction must not be assumed.

### 6.4 Advance requests
- FR-15: Employee can raise an Advance Request before or independent of
  an expense report.
- FR-16: Approved advances generate a BC Payment Journal
  instruction/reference but are **not automatically posted by Opsmeld**
  — Finance reviews and posts the journal through normal process. Once
  BC confirms the journal is posted, Opsmeld treats the advance as
  `OUTSTANDING`. Opsmeld does not independently verify cash was
  physically received unless a future payment integration is enabled.
- FR-17: One or more Expense Reports can settle a single Advance Request
  (partial settlement supported).
- FR-18: The application must not create a duplicate advance subledger
  if BC Employee Ledger Entry/application mechanics can represent the
  accounting balance. **Confirm with BC SME before build (BC-7).**
- FR-19: System flags advances beyond a configurable age, anchored to
  trip/project expected settlement date; recommended default review
  bands are 15/30/45 days (tightened from generic AP aging norms).
- FR-20: New Advance Request may be blocked if an employee has an
  overdue unsettled advance beyond a configurable threshold.

### 6.5 Approval
- FR-21: Approval matrix configurable by category, amount, department,
  employee grade/band, and organisational hierarchy, aligned to DOFA.
- FR-22: Approval routing is versioned so historical decisions can be
  explained against the policy in force at the time.
- FR-23: Approver can approve/reject at line level (interim) without
  blocking the rest of the report.
- FR-24: Final approval closes the business approval lifecycle;
  successful accounting posting is a separate state.
- FR-25: Delegation supported (approver nominates delegate; submit
  on-behalf-of).
- FR-26: Out-of-policy lines are flagged, not auto-rejected by default,
  and routed to an explicit exception-approval step with a mandatory
  reason code.
- FR-27: DOFA must support an explicit named override authority above
  the top monetary slab.

### 6.6 Duplicate / fraud signals
- FR-28: Duplicate detection supports exact and near-duplicate signals;
  receipt-image hash is one signal, not the sole algorithm.
- FR-29: Signals may include vendor, amount, date, currency,
  invoice/reference number, image hash, OCR similarity, employee, and
  organisation-wide matches.
- FR-30: Result is a risk assessment with evidence and confidence, not
  only a binary flag.

### 6.7 India compliance
- FR-31: Capture vendor GSTIN and tax breakup (CGST/SGST/IGST) per line.
- FR-32: Separate tax calculation, invoice validity, and ITC
  eligibility as distinct decisions.
- FR-33: Each taxable line carries an ITC eligibility decision (Yes, No,
  Blocked, Review) plus reason code, rule-set/version, and provenance.
- FR-34: Sec 17(5) blocked-credit defaults allow a controlled override
  path for statutory carve-outs; overrides require reason and reviewer
  evidence.
- FR-35: Receipt-less self-declared lines default to ITC No (no tax
  invoice exists); the receipt threshold is internal-control policy, not
  a statutory minimum.
- FR-36: Resolve the relevant company GSTIN by matching expense
  location/branch against vendor/place-of-supply, subject to BC SME
  confirmation of the Location pattern (BC-4).
- FR-37: TDS assessment supports applicability, section, threshold,
  rate/amount where determinable, and review status — not a boolean.
- FR-38: Policy rule redirects employee-mediated vendor cash payments
  above a configured threshold to AP instead of employee reimbursement.
- FR-39: Payroll tax treatment distinguishes actual business-expense
  reimbursement (never a perquisite) from taxable allowance/perquisite
  treatment, and is regime-aware per employee.
- FR-40: Compliance rules are versioned; historical decisions retain
  the rule-set version and input/decision evidence used at the time.

### 6.8 Mapping and accounting dimensions
- FR-41: Mapping configured per tenant + BC company by semantic business
  concept — no concept may depend on a hard-coded Global Dimension 1/2
  assumption.
- FR-42: Cost Center/Department mappings identify the actual BC
  Dimension Code the customer uses and the valid Dimension Values.
- FR-43: Project mapping supports Dimension-only, Job-only, and Both
  modes, maintained independently.
- FR-44: Employee mapping assignments are effective-dated and support
  multiple eligible projects/jobs simultaneously, plus an optional
  default.
- FR-45: Mapping resolution precedence: explicit selection → contextual
  default → employee default → company default → ambiguity requires
  review (never silently guessed).
- FR-46: Each allocation persists an immutable resolved mapping snapshot
  before posting.
- FR-47: Project/job mapping supports allocating one expense across
  multiple projects/jobs.
- FR-48: Invalid or missing required mappings block posting and create
  an auditable exception.

### 6.9 Posting and settlement
- FR-49: Approved reports transition to Ready to Post; approval alone
  does not imply posting success.
- FR-50: Posting uses supported BC API/journal mechanisms confirmed by
  BC SME (BC-11).
- FR-51: Every externally initiated posting action requires a durable
  idempotency key.
- FR-52: Retry logic first establishes whether the intended transaction
  already posted before creating another.
- FR-53: Final approved financial transactions post to BC so G/L /
  Employee Ledger / Vendor Ledger Entries are the accounting system of
  record.
- FR-54: Dimensions relevant to the expense flow to the posted entries.
- FR-55: Reimbursement/recovery instructions are batchable.

### 6.10 Audit and reconciliation
- FR-56: Every material decision has provenance: who/what, when, which
  rule/policy version, input snapshot, override or not.
- FR-57: Every posting attempt is auditable by idempotency key,
  request/response status, BC company/tenant, resulting BC references.
- FR-58: Periodic reconciliation between operational state and BC
  accounting state creates a finding on divergence. **Exception, per
  BC-expert review**: if the BC-7 advance fallback is used (advance
  tracked application-side, only net settlement posted via Journal),
  the original advance's BC Employee Ledger Entry stays permanently
  Open/unapplied from BC's own perspective — this is an **expected
  structural divergence**, not an anomaly, and reconciliation must
  recognize it as such rather than flagging it every cycle.
- FR-59: Corrections after posting use reversal/adjustment workflows,
  never mutation of historical evidence.
- FR-60: Compliance evidence retained outside BC remains linkable to the
  final BC transaction.

## 7. Accounting Treatment Matrix

**Updated 2026-09-06 per §8's BC architecture decisions** — the posting
mechanism column is no longer conceptual; it's a decision. GST-bearing
lines route through Purchase Invoice; non-tax lines may use Journal;
either way Finance reviews and posts in BC (FR-16's unposted-draft
principle applies to both document types).

| Scenario | Expense funding | Employee settlement | Posting mechanism | Expected BC accounting result |
|---|---|---|---|---|
| Employee-paid expense, GST-bearing | Employee | Reimbursement | **Purchase Invoice** (Employee-as-Vendor if that mapping is used) | Purchase Invoice with GST detail + Vendor/Employee Ledger Entry for reimbursement |
| Employee-paid expense, no GST detail needed | Employee | Reimbursement | General/Payment Journal | Expense + employee payable/reimbursement |
| Company-paid expense | Company | None | Purchase Invoice (if GST-bearing) or Journal | Expense accounting without employee reimbursement |
| Corporate-card expense | Corporate Card | Card settlement | Purchase Invoice or Journal, matched to card statement | Expense + card/vendor settlement path |
| Advance-funded expense | Employee Advance | Advance application | Journal (disbursement) + Purchase Invoice/Journal (settlement) | Expense + application against employee advance (native Employee Ledger, Employee-as-Vendor's Vendor Ledger, or app-side tracking — per BC-7's per-customer choice) |
| Expense > advance | Employee Advance + employee | Reimburse difference | Same as above | Apply advance + employee payable for difference |
| Expense < advance | Employee Advance | Recover difference | Same as above | Apply expense against advance + employee recovery |
| Split invoice | Mixed | Mixed | Itemized across Purchase Invoice lines and/or Journal lines by allocation | Itemized accounting/settlement by allocation |
| TDS-required vendor payment | Employee-mediated | AP/TDS path where threshold met | Purchase Invoice (this is what routing to AP means concretely) | Route to supported AP/vendor tax process |

## 8. BC Architecture Decisions (formerly "Open Questions for BC Expert")

**Reframed and largely closed 2026-09-06** by direct architecture
decisions (real BC-consulting judgment, not a sandbox test) rather than
left as open questions pending external validation. Per §2.0
("inspiration, not replication"), this design was already not going to
plug into BC's new 2026W1 Expense Report/Expense Line module — these
decisions go further and pick specific, well-established BC document
types for posting instead.

### BC-1 — CLOSED: post GST-bearing lines via Purchase Invoice, not Journal

**Decision**: expense lines that carry GST/tax detail post to BC as a
**Purchase Invoice**, not a General/Payment Journal line. This resolves
the entire "does the Journal API expose India GST fields" question by
not depending on Journal for tax-bearing lines at all — Purchase
documents are core, guaranteed BC functionality that runs through the
full GST/Tax engine (Tax Area, GST Group Code, HSN/SAC, GST Posting
Setup), unlike the newer Expense Report/Line objects or generic Journal
lines. Non-tax-bearing lines (e.g., a pure company-paid line with no ITC
relevance) may still use the simpler Journal path — see the updated
Accounting Treatment Matrix (§7). GST/ITC *computation* remains
`OPSMELD_NATIVE` as before; this decision is about *where the computed
result lands* in BC, not who computes it.

### BC-7 — Architecturally addressed, genuinely tricky, stays a
per-customer implementation choice

**Decision direction**: support an **Employee-as-Vendor** mapping mode
alongside native BC Employee, since modeling expense-claiming employees
as Vendor records (to use BC's mature Vendor Ledger Entry + Application
functionality, rather than the newer and less certain Employee Ledger
Entry API surface) is a real, common pattern in BC T&E implementations.
Combined with BC-1's decision, this becomes elegant: a Purchase
Invoice's Buy-from Vendor is the employee-modeled-as-vendor, GST fields
land correctly on the Purchase Line, and settlement application uses
Vendor Ledger's well-documented Application mechanics instead of the
uncertain `employeeLedgerEntries` API. **This stays flagged as the
tricky one**, not fully closed, because: not every customer models
employees as vendors; switching between native-Employee and
Employee-as-Vendor per customer needs careful mapping design (§10.5's
mapping table gets a new representation option); and using Vendor for
employees carries its own risks (mixing genuine trade vendors with
employee-vendors in reporting/aging, TDS implications on vendor
payments) that need a real decision **per customer at implementation
time**, not a single global answer. The advance-tracked-application-side
fallback (net settlement journal line) remains available for customers
where neither native Employee application nor Employee-as-Vendor fits.

### BC-11 — Reframed as non-blocking, resolved at development time with a known fallback

**Decision**: don't pre-validate a specific API against a specific BC
version before build starts. Try Purchase Invoice (BC-1) and Journal
APIs first — both are long-standing, well-documented v2.0 endpoints. If
either proves insufficient for a specific field/scenario, **Opsmeld can
build a custom AL Custom API page** to expose exactly what's needed —
a legitimate, low-risk fallback specifically because Opsmeld is itself a
BC consulting/development firm, not a third party dependent on
Microsoft's roadmap. This removes BC-11 as a pre-build blocker entirely;
it becomes normal implementation-time engineering, with a known escape
hatch if the standard APIs don't cover a case.

### BC-8 — CLOSED: approval/DOFA workflow is fully `OPSMELD_NATIVE`

**Decision**: the approval/DOFA engine (§6.5) does not depend on native
BC Approval Workflow capability at all — it's built and owned entirely
in Opsmeld. No BC-side validation needed.

### Net effect on condition 1

These four decisions close BC-1 and BC-8 outright, and turn BC-11 and
BC-7 from "needs a BC SME sandbox session before build" into
"implementation-time engineering with an identified fallback (BC-11)"
and "a per-customer mapping choice made during implementation, not a
single global unknown (BC-7)." **No BC-N item remains as a genuine
pre-build blocker.** See §13's updated condition 1 status.

**Posting review discipline unchanged**: per FR-16's existing principle,
whichever document type is used — Journal or Purchase Invoice — Opsmeld
creates it unposted; Finance reviews and posts it in BC. This isn't
weakened by adding Purchase Invoice as a posting path; it now applies to
both.

Costing-method awareness (FIFO/Standard/Average) does not apply to this
domain — employee expense/reimbursement has no inventory costing
dimension — confirmed by BC-expert review, no action needed.

**Remaining BC-N items (not gating a build decision)**
- BC-2: Can the mapping layer discover/resolve the actual BC Dimension
  Code used for Cost Center and Department in each customer/company?
  What API validates allowed Dimension Values?
- BC-3: Should billable/rebillable expenses use Job No./Job Task when
  Jobs is licensed?
- BC-4: Confirm BC Location with GST Registration No. as the appropriate
  branch-GSTIN resolution mechanism.
- BC-5/BC-6: If extensions are needed, what's the supported extension
  pattern for Expense Line/Report that stays safe across Expense Agent
  writes/upgrades?
- BC-9: Confirm Participants semantics and whether usable independently
  of the Copilot Expense Agent.
- BC-10: Any India-localization roadmap that would materially change
  this design?

## 9. Open Questions for Domain Expert

**Reframed 2026-09-06 — D-1/D-2/D-3 are out of scope for Opsmeld to
decide, and closed as build blockers.** These are each customer's
Finance team's own policy decisions, not something Opsmeld's design or
internal Finance/Compliance should pre-answer with one global value —
different customers legitimately choose differently (one company
recovers under-spent advances via payroll deduction, another via direct
repayment; one company's DOFA authorizes ITC overrides at Controller
level, another at CFO level only). The system's job is to **support**
each of these as configurable policy, not to enforce Opsmeld's own
answer:

- D-1 (advance recovery mechanism) → FR-14 already requires the system
  support an installment schedule (Payment of Wages Act constraint on
  *how* recovery can happen structurally), while *which* mechanism
  (payroll deduction / direct repayment / carry-forward) a given
  customer uses is configured per tenant, not fixed by Opsmeld.
- D-2 (perquisite tax treatment) → FR-39 already requires the system
  distinguish reimbursement from allowance/perquisite and be
  regime-aware per employee; the customer's payroll/tax team supplies
  the applicable limits and regime data, not Opsmeld.
- D-3 (GST blocked-credit override authority) → FR-27 and FR-34 already
  require a configurable named override authority and a reason-coded
  override path; *who* holds that authority is each customer's DOFA,
  configured at onboarding, not an Opsmeld default.

No further Opsmeld-side sign-off needed on these three. What Opsmeld
*does* still own: shipping sensible starting defaults/templates (a
default DOFA template, a default Sec 17(5) blocked-credit list) as a
convenience — but the authoritative answer for any deployment is
customer-configured, never Opsmeld's internal decision.

**Priority P0 (remaining)**
- D-4: Typical receipt-less internal-control thresholds by
  company/sector — confirm these are policy norms, not statutory minima.
- D-7: Threshold/routing policy for employee-mediated vendor payments
  that should go to AP for TDS handling instead of reimbursement.

**Priority P1**
- D-5: Advance-aging policy anchored to trip/project expected
  settlement date; validate 15/30/45-day review bands.
- D-6: DOFA structure — category, department, grade/band, amount, and
  named override authority.
- D-8: Monthly GST operational submission cutoff plus financial-year-end
  ITC sweep timing (Sec 16(4) time-bar) — the system should support both
  the operational cutoff and the statutory time-bar.

## 10. Risks

- **R1** — Native BC capability may reduce custom scope if BC supports
  enough natively; some application tables become mapping/audit layers
  rather than primary workflow stores.
- **R2** — Native BC capability may be insufficient; if Expense Report
  APIs can't accept the required data, posting may need a journal-based
  route — must not be hidden behind assumptions. Confirmed: this
  codebase has no BC write path today (§4A) — plan the posting layer as
  new engineering effort from day one, not as extending an existing
  write capability, regardless of how BC-11 resolves.
- **R3** — Duplicate accounting risk: any retryable BC call without
  durable idempotency/reconciliation can create duplicate postings.
- **R4** — Compliance rule drift: GST/TDS/payroll decisions without
  versioned rules and input snapshots become hard to defend historically.
- **R5** — Two-system disagreement: if compliance results live outside
  BC while tax filing reads BC directly, a formal reconciliation/
  exception mechanism is required — don't declare either system
  universally "legal truth" without Finance/Tax sign-off.
- **R6** — Employee advance duplication: don't build an application-side
  monetary advance ledger until BC confirms native Employee Ledger
  Entry/application mechanics can't cover it.

## 11. Build Decision Gate

**Updated 2026-09-06 — BC-11/BC-7/BC-1/BC-8 closed via architecture
decision (§8), not left as pre-build unknowns:**

- BC-11: **Closed.** Post via Purchase Invoice (GST-bearing) or Journal
  (non-GST); if either standard API proves insufficient for a specific
  field, build a custom AL API page — Opsmeld's own delivery capability
  as a BC dev shop. No external validation needed before build.
- BC-7: **Architecturally addressed, resolved per-customer at
  implementation time.** Support native Employee, Employee-as-Vendor,
  or app-side tracking with net Journal settlement, chosen per
  customer's actual BC configuration — not a single global answer to
  pin down before build starts.
- BC-1: **Closed.** GST-bearing lines post via Purchase Invoice, which
  runs through BC's full GST/Tax engine — the "does Journal expose GST
  fields" question is moot because Journal isn't used for those lines.
  GST/ITC computation remains `OPSMELD_NATIVE`.
- BC-8: **Closed.** Approval/DOFA is fully `OPSMELD_NATIVE`; no
  dependency on native BC Workflow.
- Mapping ownership: the semantic-to-BC mapping model, validation
  source, and whether project mapping uses Dimension, Job/Job Task, or
  both — **now also includes the Employee-as-Vendor mapping option**
  per BC-7 (see blueprint §10.5/§7.12).
- Tax ownership: **closed** — compliance assessment (ITC eligibility,
  TDS) stays application-owned (`OPSMELD_NATIVE`); the computed tax
  amount lands in BC via Purchase Invoice per BC-1.
- Accounting ownership: confirmed — BC remains the source of truth for
  final posted financial amounts and ledger balances, posted via
  Purchase Invoice or Journal per scenario, always Finance-reviewed
  before posting (FR-16).

**No item in this gate remains a genuine pre-build blocker.**
Remaining implementation design derives from the decisions above; the
per-customer choices (Employee-as-Vendor vs. native Employee vs.
app-side tracking) are implementation-time configuration, not open
architecture questions.

## 12. Companion document

The full engineering blueprint — 40-table schema, provider/setup table
definitions, two end-to-end conversational reference workflows (advance
request and expense submission via Teams/Outlook), reporting/dashboard
design, API contract catalogue, idempotency/state-machine contracts, and
build gates — is in `expense-agent-blueprint.md` in this folder. It's
the internal build reference once the P0 questions above are answered;
it isn't needed to review this document.

## 13. Council Go/No-Go Review (2026-09-06)

**Verdict: Approve with conditions — scoped to continuing the
design/validation phase. Not approved to start the 40-table schema build
or write production code.** Full review convened all twelve advisory
personas plus CEO synthesis; investigation phase read both design docs
in full and cross-checked claims against the live repo rather than
trusting the docs' own assertions.

### New finding from this review (not previously in either doc)

This repo's actual persistence layer today is JSON files
(`open(path, "w")` in `data_trust.py`/`config.py`) — no ORM, no
Postgres/MySQL driver, no web framework (`server.py` runs on stdlib
`http.server`). The blueprint's 40-table relational schema with UUID
PKs, effective-dated versioning, and idempotent posting (FR-51/52) and
reconciliation (FR-58) assumes infrastructure — a real RDBMS, migrations,
likely a real web framework — that doesn't exist in this codebase yet.
Three roles (Product Manager, Solution Architect, Tech Expert) converged
on this independently. **This is the actual source of build-scope risk,
more than any BC limitation** — resolve it (pick a DB + framework) before
schema is treated as final.

### Six conditions before build starts

1. **CLOSED 2026-09-06 — see §8.** BC-1, BC-8, and BC-11 resolved by
   architecture decision (Purchase Invoice for GST-bearing lines,
   `OPSMELD_NATIVE` approval, custom-API fallback if standard APIs prove
   insufficient) rather than left pending a BC SME sandbox session.
   BC-7 (advance/employee ledger modeling) is architecturally addressed
   with a genuine per-customer choice (native Employee, Employee-as-
   Vendor, or app-side tracking) rather than a single unresolved global
   question. No BC-N item remains a pre-build blocker. What's left is
   normal implementation-time engineering: build against Purchase
   Invoice/Journal APIs, validate each customer's actual configuration
   during onboarding, and use the custom-API fallback if a specific
   field is genuinely unavailable.
2. **CLOSED 2026-09-06 — reframed as out of scope, not deferred.** D-1,
   D-2, D-3 are each customer's own Finance-team policy decisions, not
   an Opsmeld build blocker — see §9. The system already requires
   configurable support for all three (FR-14, FR-27, FR-34, FR-39); no
   Opsmeld-internal Finance/Compliance sign-off is needed on a specific
   global answer, because there isn't meant to be one.
3. **Infrastructure decision — CLOSED 2026-09-06.** The Expense Agent
   will be a **new standalone repository**, not a module inside
   opsmeld-recon-engine, on **Python/FastAPI + PostgreSQL**. Rationale:
   this repo's architecture (JSON files, stdlib `http.server`, read-only
   reconciliation conventions) is a scale/risk mismatch for a
   write-capable, financially-sensitive, always-on system (matches the
   Solution Architect/Tech Expert finding in §13 below) — a separate
   deployable keeps blast radius and release cadence independent.
   PostgreSQL gives real transactions (needed for FR-51/52) and
   row-level security (feeds condition 4 below) rather than a
   `tenant_id` column alone. **What's reused isn't the repo — it's two
   patterns, copied/adapted, not imported as a dependency**:
   `MCP/core/bc_mcp_client.py`'s MSAL auth/token/company-discovery logic,
   and `MCP/modules/data_trust_engine/llm_interpreter.py`'s
   provider-failover + cost-tracking pattern (extended for vision/OCR
   calls) — this also closes condition 6 below.
4. **CLOSED 2026-09-06 — full design in blueprint §19.** Two-layer
   model: an app-layer authorization gate ported from
   `MCP/core/authorization.py`'s six-gate shape (Session → Org →
   Subscription → Permission → Company ACL → BC probe — correcting an
   earlier citation of `data_trust_engine/authorization.py`, which is
   Data Trust's narrower company-discovery variant, not the general
   engine this design generalizes from), plus **new** PostgreSQL
   Row-Level Security enforcing `tenant_id`/`bc_company_id` at the
   database level — impossible with JSON files, which is why this
   waited on the infra decision (condition 3). Verification test stated
   explicitly: an app-role DB connection scoped to tenant A running
   `SELECT * FROM expense` with no `WHERE` clause must return zero rows
   for tenant B, regardless of query shape.
5. **CLOSED 2026-09-06 — full model in blueprint §20.** Reuses
   `LLMInterpreter`'s cost-tracking formula extended to vision/OCR,
   using current Claude Haiku 4.5/Sonnet 5 pricing (verified via the
   `claude-api` skill) and an image-tokenization formula (verified via
   web search). Estimate: **~$1–2/month for a 50-employee tenant to
   ~$18–25/month for 1,000 employees** — a minor cost line at any
   realistic scale. Stated plainly: infrastructure/engineering cost is
   the real driver here, not per-call LLM pricing.
6. **CLOSED 2026-09-06 — see condition 3.** OCR/extraction and the
   conversational-intake AI layer reuse `LLMInterpreter`'s
   provider-failover and cost-tracking pattern, copied/adapted into the
   new standalone repo rather than imported as a dependency on this one.
   Still open: OCR (receipt image → structured fields) is a materially
   different task from the tool-use classification `llm_interpreter.py`
   currently does — vision-capable model calls at receipt volume need
   their own cost/latency line (feeds condition 5, still open).

### What was validated as sound (not just unchallenged)

- The system-of-record boundary (§2.1) and provider-mode abstraction
  (§2.2) are the right shape — explicitly refuses to duplicate BC's
  ledger (FR-18, R6).
- The AI/deterministic boundary (§2.3, "AI may extract/propose; it may
  not independently approve, override policy, or post financial
  records") matches how Data Trust actually behaves in production today
  — findings are read-only, human-reviewed, never auto-acted.
- The India compliance reasoning (§6.7 — Sec 17(5) override path with
  evidence, receipt-less ITC-No default as policy not statute, Payment
  of Wages Act awareness for advance recovery) reflects real Indian SME
  operational reality, not generic SaaS assumptions.
- Reusing the "local record linked to BC by key, BC read via API, never
  written via table extension" pattern from Data Trust is correct reuse,
  not reinvention.

### Biggest risk named by the CEO synthesis

Scope creep from "approve the design direction" into "approve full
build" without conditions 1–3 closing first.

**Update (2026-09-06, superseded by architecture decisions in §8):**
BC-1, BC-8, and BC-11 are now closed by direct decision — Purchase
Invoice for GST-bearing lines, `OPSMELD_NATIVE` approval, a custom-API
fallback if a standard API proves insufficient — rather than pending a
BC SME sandbox session. BC-7 is architecturally addressed as a
per-customer implementation choice (native Employee /
Employee-as-Vendor / app-side tracking), not a single open question.
**No BC-N item remains a pre-build blocker.** Condition 1 of the
six-condition gate is now closed (§13); **all six conditions are
closed**. What's left is standard implementation-time engineering:
build against the decided posting paths, and validate each customer's
actual BC configuration during onboarding rather than pre-validating
one hypothetical tenant.

## Change Log

| Version | Change |
|---|---|
| v0.1 | Initial functional design and brainstorm. |
| v0.2 | Added internal review corrections (advance ledger reuse, funding vs. settlement split, FY-end ITC sweep, Sec 17(5) override, receipt-less ITC default, installment recovery, named override authority, TDS-to-AP redirect) and the non-BC storage architecture option (§2.1 here), following this repo's existing Data Trust pattern. |
| v1.0 | Split from the consolidated v0.9 draft into this lean SME-review document plus the full `expense-agent-blueprint.md`. Provider abstraction (§2.2) kept in scope per explicit decision. No FR/BC-N/D-N content dropped — only re-scoped for reviewer audience. |
| v1.1 | Folded in BC-expert review: added §4A verified finding (no BC write path exists in this codebase today — confirmed by reading `bc_mcp_client.py`), sharpened BC-11 (confirm documented write-API stability, not sandbox behavior; plan Journal API as day-1 path), BC-7 (ask specifically about Employee Ledger Entry *application* API access, historically read-only), and BC-1 (treat OPSMELD_NATIVE for GST as the probable outcome, not a coin flip). Updated R2 accordingly. |
| v1.2 | Full council Go/No-Go review (§13): approved for design/validation phase only, not for build. New finding — this repo's persistence layer today is JSON files, no DB/framework, which the 40-table schema assumes but doesn't name as a prerequisite. Six conditions set before schema/code work: BC SME sandbox answers (BC-1/7/8/11), Finance/Compliance sign-off (D-1/2/3), infra decision, enforced multi-tenant isolation (not just a column), per-tenant LLM/OCR cost estimate, explicit reuse of `LLMInterpreter` for OCR/extraction. |
| v1.3 | Added §2.0 ("inspiration, not replication") clarifying this design doesn't need to mirror BC's native Expense Report module — the only hard BC dependency is posting via BC's long-standing General/Payment Journal API. Split BC-11/BC-7/BC-1 in §8 into a default path (testable on any existing BC access, no Wave 1/India-inclusion needed) and an optional native-path exploration (needs Wave 1, and Expense Agent Copilot UI confirmed excluded from India in the current rollout). Updated §11's Build Decision Gate and §13's next-step guidance accordingly — resolves the "I don't have Wave 1 access" blocker by removing the dependency on it. |
| v1.4 | Closed council conditions 3 and 6 (§13): infrastructure decision made — new standalone repository (not a module in opsmeld-recon-engine), Python/FastAPI + PostgreSQL. Reuses two proven patterns from this repo (`bc_mcp_client.py`'s MSAL auth, `llm_interpreter.py`'s provider-failover/cost-tracking), copied/adapted rather than imported as a dependency. Remaining open conditions: 1 (BC default-path testing), 2 (Finance/Compliance sign-off), 4 (row-level isolation design), 5 (LLM/OCR cost estimate, now sharper since OCR is confirmed a distinct cost line from the reused pattern). |
| v1.5 | Second BC-expert re-review of v1.3's reframing, folded in: (1) BC-1's "nothing to test" was overclaimed — restored a real, testable-today question about whether the Journal API exposes India GST-specific fields (GST Group Code/HSN-SAC/Jurisdiction Type), which decides who owns GST-return prep (this tool vs. BC); (2) softened "confirmed excluded from India" to "reported as excluded" with an explicit confidence note (aggregated search, not primary-source-verified) and reconciled §4's two differently-worded availability claims; (3) reworded the FR-18 citation on BC-7's fallback from "existing fallback" to "consistent with FR-18's intent" (FR-18 doesn't literally specify the net-journal-line mechanic); (4) added a named residual risk to BC-7's default path and FR-58: the fallback leaves BC's own Employee Ledger Entry for the original advance permanently Open/unapplied — reconciliation must treat this as expected structural divergence, not an anomaly. |
| v1.6 | Third BC-expert pass, attempting to close the §4 confidence gap directly: a second `WebFetch` to `learn.microsoft.com` was independently blocked (same limitation, different review session — corroborates it's real). Aggregated search surfaced two India-availability claims that don't fully reconcile: a general "July 2026" regional-expansion date for Expense Agent vs. a narrower claim about a specific GPT-5.3-chat *model-version* rollout excluding India/UK/Australia (not necessarily the feature itself). Documented both in §4 rather than picking one, and added the concrete recommendation: someone with actual BC admin-center/tenant portal access should check the live "Feature availability by country/region" page directly — the primary source no search-based review could reach. If the July 2026 date is accurate and feature-wide, it would change §8's "optional native-path exploration" timing. |
| v1.7 | Closed council conditions 4 and 5 (§13) — full designs in blueprint §19/§20. Row-level isolation: app-layer gate ported from `MCP/core/authorization.py`'s six-gate shape (corrected a prior citation of `data_trust_engine/authorization.py`, which is Data Trust's narrower company-discovery variant) plus new PostgreSQL Row-Level Security enforcing tenant/company isolation at the DB level, with a concrete verification test. Cost estimate: current Claude Haiku 4.5/Sonnet 5 pricing (verified via the `claude-api` skill) and an image-tokenization formula (verified via web search) yield ~$1–25/month per tenant across 50–1,000 employees — stated plainly as a minor cost line, not the real cost driver. 4 of 6 conditions now closed; the remaining 2 (BC SME sandbox, Finance/Compliance sign-off) cannot be closed by further design work. |
| v1.8 | Reframed and closed condition 2 (§13, §9): D-1/D-2/D-3 (advance recovery mechanism, perquisite tax treatment, GST override authority) are each customer's own Finance-team policy decision, not an Opsmeld build blocker — the system already requires configurable support for all three (FR-14, FR-27, FR-34, FR-39). No Opsmeld-internal Finance/Compliance sign-off needed on a specific global answer, since there isn't meant to be one; Opsmeld ships sensible defaults/templates, customers configure the authoritative values. 5 of 6 conditions now closed — only condition 1 (BC SME sandbox testing) remains, and it cannot be closed by further design work. |
| v1.9 | Closed condition 1 (§8, §11, §13) via direct BC architecture decisions rather than pending sandbox validation: BC-1 (GST-bearing lines post via Purchase Invoice, not Journal — sidesteps the "does Journal expose GST fields" question entirely), BC-8 (approval/DOFA fully `OPSMELD_NATIVE`), BC-11 (Purchase Invoice/Journal APIs first, custom AL API page as a known fallback since Opsmeld is itself a BC dev shop). BC-7 (advance/employee ledger) architecturally addressed with a genuine per-customer choice — native Employee, Employee-as-Vendor (leverages BC's mature Vendor Ledger Application instead of the less-certain Employee Ledger API), or app-side tracking — rather than a single global unknown. Updated the Accounting Treatment Matrix (§7) with the posting-mechanism column. **All six council conditions now closed** — this clears the pre-build gate, though the council's own guidance to start with a thin vertical slice rather than the full schema still holds. |
