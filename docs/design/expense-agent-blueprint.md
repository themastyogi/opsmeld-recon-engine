# Expense Agent — Engineering Blueprint v1.8

Status: **APPROVED FOR DESIGN/VALIDATION PHASE ONLY — NOT APPROVED FOR
BUILD.** Full council Go/No-Go review completed 2026-09-06 — see the
"Council Go/No-Go Review" section for the CEO synthesis and conditions.
**5 of 6 conditions closed as of v1.8** (infra decision, `LLMInterpreter`
reuse, row-level isolation design, LLM/OCR cost estimate, and D-1/D-2/D-3
reframed as customer-configurable policy rather than an Opsmeld build
blocker — §19/§20, §12). **1 remains open and cannot be closed by
further design work**: BC SME sandbox answers to BC-11/7/1/8 (§11) need
a real person with live BC tenant access. Structurally consolidated
from the v0.9 blueprint candidate; numbering collisions and misplaced
sections have been corrected (see "Structural corrections" below). v1.1
folded in BC-expert review findings (§4A, §11, §16) — same content as
`expense-agent-spec.md`, kept in sync. This is the detailed build
reference; for the document intended for BC-expert and domain-expert
review, see `expense-agent-spec.md` in this folder.
Author: Vikas (via Claude design session)
Date: 2026-09-06

## Structural corrections applied in this pass

The v0.9 draft was assembled by appending sections across many revisions
and accumulated numbering defects. This version fixes them without
changing any FR/BC/D identifier (those are stable IDs, not section
numbers) or any substantive content:

- Two sections were both numbered "10" (State Machines, then BC Mapping)
  → the second is now **10.5 BC Mapping**.
- Two sections were both numbered "14" (Posting and Reconciliation
  Contract, then Engineering Blueprint Contract) → the second is now
  **Section 18**.
- Two sections were both numbered "15" (Accounting Treatment Matrix,
  then Change Log) → the second was renumbered to Section 19 in this
  pass, then to **Section 21** when v1.7 inserted two new sections
  (Row-Level Tenant Isolation Design, LLM/OCR Cost Model) ahead of it.
- Section 7.4's subsections reused **7.3.1–7.3.6**, colliding with the
  earlier 7.3.1–7.3.5 under Configuration Control Plane → renumbered to
  **7.4.1–7.4.6**.
- Sections 7.5 and 7.6 were missing (jumped from 7.4 to "7.7A") → the
  setup/provider table cluster is now **7.5.1–7.5.7**, and the
  conversational-intake table cluster is now **7.6**.
- Section 7.7 was used twice (once for the conversational-intake
  cluster, once for `tenant`) → resolved by the 7.5/7.6 renumbering
  above; `tenant` remains 7.7 and the rest of the table catalogue
  (7.8–7.33) is unchanged.
- **10E (Reference Workflow 2)** and **10F (Reporting)** were stranded
  after Appendix A/B → moved to their narrative position, immediately
  after 10D and before Section 11.

Everything else — every FR, every BC-N/D-N question, every table
definition, every workflow step — is unchanged from the v0.9 content.

## 1. Purpose

Design an AI-assisted expense management capability for Business Central
customers (India-first, globally applicable) that lets employees capture
and submit expenses continuously, handles mixed company-paid/employee-paid
funding, advances, and India statutory compliance (GST ITC, TDS,
payroll/perquisite treatment), and records the final approved accounting
transaction in BC.

This document is the single source blueprint for the Expense capability.
It is intentionally implementation-oriented at the contract level (domain
model, persistence, APIs/events, provider adapters, synchronization,
security, reliability and reporting) while leaving low-level code/framework
choices to implementation. No production code is written against this yet.
The goal is to obtain correctness feedback from a BC/ERP expert and an
accounting/Indian-compliance domain expert before implementation.

## 2. Core Architecture Decision

### 2.0 Inspiration, not replication

This design takes workflow/UX inspiration from how BC (and Concur,
Expensify, Zoho Expense) structure expense capture, approval, and
settlement. **It does not attempt to mirror BC's specific Expense
Report/Expense Line objects, replicate BC's Copilot Expense Agent, or
plug into that module's internals.** The application's own domain model
(§7) is independent of BC's schema by design.

The one hard BC dependency this design actually has: **posting a
finished, GST-computed, dimension-tagged transaction into BC's ledgers.**
That posting can go through BC's long-standing General/Payment Journal
API (stable since BC API v2.0, ~2019, and how most third-party expense
tools already integrate with BC) rather than through the new 2026W1
Expense Report/Line API. That materially changes which BC-N questions
in §11 are actually blocking — see the reframing note there.

### 2.1 System-of-record boundary

The Expense capability and Business Central have different ownership
boundaries:

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

### 2.2 Architectural principle

The Expense capability owns capture, decisioning, compliance assessment,
workflow evidence, and reconciliation state; Business Central owns the
accounting result for approved financial transactions.

The Expense capability should not create a parallel subledger for amounts
that BC already owns natively.

### 2.3 Channel independence

Expense Agent is one possible user/ingestion channel, not the domain model
itself. The same core expense model should support app/photo, email,
Teams, Outlook, or future channels.

### 2.3A Conversational intake principle

Teams and Outlook messages are treated as unstructured inputs into a
common conversational intake layer. The layer must:

- authenticate/resolve the sender to an Opsmeld employee;
- classify intent (for example ADVANCE_REQUEST);
- extract canonical business attributes;
- validate against canonical setup plus synchronized BC reference data;
- ask for missing information when required;
- obtain explicit user confirmation before creating a financial request
  when the interpretation is not already sufficiently deterministic; and
- create the same domain transaction regardless of originating channel.

The original message and extraction evidence are retained for
auditability.

### 2.4 Configuration ownership and provider abstraction

Recommendation: Opsmeld should own the canonical Expense configuration
model even when Business Central already has an equivalent setup object.

The application must not model Microsoft setup objects as the primary
domain contract. Instead, Opsmeld maintains a stable, semantic
configuration model and a provider/mapping layer determines how that
configuration is executed for a particular customer/company.

Each configurable capability has a provider mode:

| Provider mode | Meaning | When used |
|---|---|---|
| `MICROSOFT_NATIVE` | Opsmeld stores the canonical configuration and synchronizes/maps it to BC native setup; BC executes the capability | BC has the required native capability and we trust it for that function |
| `OPSMELD_NATIVE` | Opsmeld evaluates and executes the capability; only the resulting accounting data crosses into BC | BC lacks the capability, is unavailable in India, or does not expose sufficient API/control |
| `HYBRID` | Opsmeld owns the canonical policy and evaluation; supported portions are projected to BC while Opsmeld retains the authoritative policy/evidence | Native BC capability exists but is not sufficient for the product requirement |

This is a provider selection, not a schema fork. Microsoft adoption in a
future BC release should therefore change configuration/mapping/provider
records rather than force a redesign of the core Expense schema.

### 2.5 Canonical configuration principle

All customer-facing setup, rules and policies required by the Expense
capability must be representable in the Opsmeld database, even if an
equivalent BC setup currently exists. The same canonical setup can then be
projected to BC where supported.

The application therefore becomes the configuration control plane, while
BC remains the accounting execution plane.

Examples:

```
Opsmeld Expense Category: HOTEL
        |
        +---- Microsoft provider → BC Expense Category HOTEL
        |
        +---- Opsmeld provider   → Opsmeld rule/category evaluation

Opsmeld Approval Policy DOFA-2026-v3
        |
        +---- Microsoft provider → native BC approval workflow where supported
        |
        +---- Opsmeld provider   → Opsmeld Approval Engine

Opsmeld Cost Center concept
        |
        +---- Mapping → BC Dimension Code COSTCENTER
```

A capability can move from `OPSMELD_NATIVE` to `MICROSOFT_NATIVE` later
without changing expense/report/compliance tables. Only the provider and
mapping/synchronization configuration changes.

```
                     +----------------+
                     | Mobile / App   |
                     +--------+-------+
                              |
+---------------+             |       +----------------+
| Email/Outlook |-------------+-------| Teams / Agent  |
+---------------+                     +--------+-------+
                                               |
                                               v
                                   +-----------------------+
                                   | Common Expense Model  |
                                   +-----------+-----------+
                                               |
                           +-------------------+-------------------+
                           |                   |                   |
                           v                   v                   v
                    Policy Engine      Compliance Engine     Approval Engine
                           |                   |                   |
                           +-------------------+-------------------+
                                               |
                                               v
                                  +--------------------------+
                                  | BC Posting / Accounting  |
                                  +--------------------------+
                                               |
                                               v
                                  G/L / Employee / Vendor
                                       Ledger Entries
```

## 3. Scope

In scope:
- Expense capture (as-and-when) and expense report submission (batched)
- Company-paid vs. employee-paid vs. split vs. advance-funded expenses
- Advance request → approval → BC journal creation → BC journal posting →
  advance outstanding → netting → settlement
- Approval workflow (interim/final, delegation, exceptions)
- India GST ITC eligibility, GSTIN/branch matching, TDS assessment,
  payroll/perquisite assessment
- Mapping of final accounting data to BC native objects / APIs
- Application-side operational, compliance, workflow, evidence, and
  reconciliation data model
- Auditability, idempotency, and reconciliation

Out of scope for this doc:
- Actual AL/table/page implementation
- Payroll system integration details (only the handoff point is specified)
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
  only at launch): submission via Outlook/Teams/M365 Copilot Chat/web app,
  OCR + auto-categorization + itemization, continuous policy validation,
  interim + final approval.
- Neither the release notes nor Microsoft Learn pages reviewed mention
  India localization (GST/TDS) hooks for this module as of this writing —
  treat India compliance fields as a gap to be confirmed, not assumed
  present. (See open question BC-1.)
- As of the current Microsoft release-plan documentation reviewed on
  2026-09-06, Expense Agent public preview geography lists the US and
  then Australia, New Zealand, and UK; India is not listed in that
  availability note. A later search that same day (aggregated results
  summarizing Microsoft's "Copilot and agents country/region
  availability" page) reported more specifically that "environments in
  the UK, India, and Australia are excluded from an initial rollout and
  will receive updates at a later date." **Confidence note, per
  BC-expert re-review**: this second claim comes from an aggregated
  search summary, not a direct fetch of Microsoft's own page (blocked by
  network egress in this environment) — treat it as higher-confidence
  than "not listed" but not primary-source-verified. Don't plan around
  Indian Expense-Agent-UI availability without checking the live page
  yourself before it matters.

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
exploration" calculus in §11. **Recommended next step**: someone with
actual BC admin-center/tenant portal access should check the live
"Feature availability by country/region" page directly — that's the
primary source neither this review nor the prior one could reach.

Sources: Microsoft Dynamics 365 Blog (Expense Agent, Apr 2026); Microsoft
Learn — Expense Management Overview, Expense Agent Overview, Set Up
Expense Categories and Rules, Release Plan 2026W1 (Manage employee
expenses using expense reports; Manage expenses using Expense Agent),
Copilot and agents country/region availability and supported languages
(accessed via aggregated search, not direct fetch — direct fetch
attempted twice, blocked both times).

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
extension of an existing capability. Scope/estimate accordingly, and see
§18.7 (BC integration contract) — the adapter described there has no
prior art in this repo to build on.

## 5. Actors

- **Employee** — captures/submits expenses, requests advances
- **Approver (manager)** — interim/final approval, exception review
- **Finance/AP** — posting, advance aging review, GST/TDS review
- **Payroll** — perquisite/taxable-benefit handling (handoff only)
- **Delegate** — submits/approves on behalf of another user
- **Expense Agent (system)** — OCR, categorization, policy validation,
  duplicate/fraud checks
- **Compliance/Rule owner** — maintains rule versions and approves rule
  changes (can be Finance in smaller organisations)

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
- FR-5: Source evidence is retained and linked to the expense, including
  the original receipt/image and extracted/normalized values.

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

### 6.2A Configuration control plane
- FR-9A: All configurable Expense capabilities used by the product must
  have a canonical representation in the Opsmeld database, regardless of
  whether BC has an equivalent native setup.
- FR-9B: Each setup capability is assigned a provider mode:
  `MICROSOFT_NATIVE`, `OPSMELD_NATIVE`, or `HYBRID`.
- FR-9C: Microsoft-specific objects must be represented through provider
  mappings/adapters, not embedded as the core domain schema.
- FR-9D: When a native BC capability becomes available or materially
  improves, migration to that provider must be achievable by
  configuration and synchronization without restructuring historical
  Expense data.
- FR-9E: Rules and policies are versioned, effective-dated, auditable,
  and immutable once used by a submitted/posting decision.
- FR-9F: Setup synchronization to BC must be idempotent, detectable, and
  reconcilable; a failed synchronization must not partially change the
  canonical Opsmeld configuration.

### 6.3 Funding and settlement model

Do not use one field to represent both how an expense was funded and how
it will be settled.

| Funding Source | Settlement Method / Result |
|---|---|
| Employee | Employee Reimbursement |
| Corporate Card | Card Settlement |
| Company Paid | No Settlement |
| Employee Advance | Employee Recovery |

- FR-10: Every expense allocation/line records one Funding Source and one
  expected Settlement Method.
- FR-11: A single source invoice can be itemized into multiple
  lines/allocations with different funding sources.
- FR-12: Employee Advance allocations must reference a specific Advance
  Request / accounting advance reference.
- FR-13: On advance settlement: Report total > usable advance → reimburse
  difference; Report total < usable advance → recover difference; Equal →
  close with no payment either direction.
- FR-14: Under-spent advance recovery must support an installment
  schedule where payroll deduction is used; a one-shot deduction must not
  be assumed.

### 6.4 Advance requests
- FR-15: Employee can raise an Advance Request (amount, purpose, linked
  trip/project, expected settlement date) before or independent of an
  expense report.
- FR-16: Approved advances generate a BC Payment Journal
  instruction/reference but are not automatically posted by Opsmeld. The
  accountant reviews and posts the BC journal through the normal finance
  process. Once BC confirms the journal is posted, Opsmeld treats the
  advance as `OUTSTANDING` for settlement purposes. Opsmeld does not
  independently verify that cash was physically received by the employee
  unless a future payment integration is explicitly enabled.
- FR-17: One or more Expense Reports can settle a single Advance Request
  (partial settlement supported).
- FR-18: The application must not create a duplicate advance subledger if
  BC Employee Ledger Entry/application mechanics can represent the
  accounting balance. Confirm with BC SME before build.
- FR-19: System flags advances beyond a configurable age, using
  trip/project expected settlement date as the primary policy anchor;
  recommended default review bands are 15/30/45 days but remain
  configurable.
- FR-20: New Advance Request may be blocked if an employee has an
  overdue unsettled advance beyond a configurable threshold; policy can
  disable the block.

### 6.5 Approval
- FR-21: Approval matrix is configurable by relevant policy dimensions
  such as category, amount, department, employee grade/band, and
  organisational hierarchy, aligned to the company's DOFA.
- FR-22: Approval routing must be versioned so historical approval
  decisions can be explained against the policy in force at the time.
- FR-23: Approver can approve/reject at line level (interim) without
  blocking the rest of the report, subject to report policy.
- FR-24: Final approval closes the business approval lifecycle;
  successful accounting posting is a separate state.
- FR-25: Delegation: approver can nominate a delegate; a user can submit
  on behalf of another.
- FR-26: Out-of-policy lines (over limit, missing receipt above
  threshold, duplicate suspicion, weekend/holiday date) are flagged, not
  auto-rejected by default, and routed to an explicit exception-approval
  step with a mandatory reason code.
- FR-27: DOFA must support an explicit named override authority above
  the top monetary slab where required.

### 6.6 Duplicate / fraud signals
- FR-28: Duplicate detection must support exact and near-duplicate
  signals; receipt-image hash is one signal, not the sole algorithm.
- FR-29: Signals may include vendor, amount, date, currency,
  invoice/reference number, image hash, OCR similarity, employee, and
  organisation-wide matches where permitted.
- FR-30: Result is represented as a risk assessment with evidence and
  confidence, not only a binary duplicate flag.

### 6.7 India compliance
- FR-31: Capture vendor GSTIN and tax breakup (CGST/SGST/IGST) per line
  where applicable.
- FR-32: Separate tax calculation, invoice validity, and ITC eligibility.
- FR-33: Each taxable line carries an ITC eligibility decision (Yes, No,
  Blocked, Review) plus reason code, rule-set/version, and decision
  provenance.
- FR-34: Sec 17(5) blocked-credit defaults must allow a controlled
  override path for applicable statutory carve-outs; overrides require
  reason and reviewer evidence.
- FR-35: Receipt-less self-declared lines default to ITC No because
  there is no tax invoice; the receipt threshold is an internal-control
  policy, not a statutory minimum.
- FR-36: Resolve the relevant company GSTIN for a claim by matching the
  expense location/branch against vendor/place-of-supply information,
  subject to BC SME confirmation of the Location pattern.
- FR-37: TDS assessment must support applicability, section, threshold
  assessment, rate/amount where determinable, and review status rather
  than a boolean only.
- FR-38: Add a policy rule that can redirect employee-mediated vendor
  cash payments above a configured threshold to AP instead of employee
  reimbursement, in addition to any review flag.
- FR-39: Payroll tax treatment must distinguish actual business-expense
  reimbursement from taxable allowance/perquisite treatment and must be
  regime-aware per employee where relevant.
- FR-40: Compliance rules must be versioned. Historical decisions retain
  the rule-set version and input/decision evidence used at the time.

### 6.8 Mapping and accounting dimensions
- FR-41: Mapping is configured per tenant + BC company by semantic
  business concept; no concept may depend on a hard-coded Global
  Dimension 1/2 assumption.
- FR-42: Cost Center and Department mappings must identify the actual BC
  Dimension Code selected by the customer and the valid BC Dimension
  Values.
- FR-43: Project mapping must support Dimension-only, Job-only, and Both
  modes. In Both mode, dimension and Job/Job Task targets are maintained
  independently.
- FR-44: Employee mapping assignments are effective-dated and support
  multiple eligible projects/jobs simultaneously, plus an optional
  default assignment.
- FR-45: Mapping resolution must support explicit transaction selection,
  contextual defaults, employee defaults, and company defaults in a
  defined precedence order. Ambiguity must require review.
- FR-46: Each expense allocation must persist an immutable resolved
  mapping snapshot before posting.
- FR-47: Project/job mapping must support allocation of one expense
  across multiple projects/jobs.
- FR-48: Invalid or missing required mappings must block posting and
  create an auditable exception.

### 6.9 Posting and settlement
- FR-49: Approved reports transition to Ready to Post; approval alone
  does not imply posting success.
- FR-50: Posting must use supported BC API/journal mechanisms confirmed
  by BC SME.
- FR-51: Every externally initiated posting action requires a durable
  idempotency key.
- FR-52: Retry logic must first establish whether the intended
  transaction already posted before creating another financial
  transaction.
- FR-53: Post final approved financial transactions to BC so that G/L /
  Employee Ledger / Vendor Ledger Entries are the accounting system of
  record.
- FR-54: Dimensions relevant to the expense flow to the posted
  accounting entries.
- FR-55: Reimbursement/recovery instructions are batchable; actual
  bank/payroll execution remains outside this document except for the
  handoff/result state.

### 6.10 Audit and reconciliation
- FR-56: Every material decision must have provenance: who/what made it,
  when, which rule/policy version, the input snapshot, and whether a
  human override occurred.
- FR-57: Every posting attempt is auditable by idempotency key,
  request/response status, BC company/tenant, and resulting BC record
  references where available.
- FR-58: The application periodically reconciles operational state
  against BC accounting state and creates a finding when expected and
  actual states diverge. **Exception, per BC-expert review**: if the
  BC-7 advance fallback is used (advance tracked application-side, only
  net settlement posted via Journal), the original advance's BC Employee
  Ledger Entry stays permanently Open/unapplied from BC's own
  perspective — this is an **expected structural divergence**, not an
  anomaly, and reconciliation must recognize it as such rather than
  flagging it every cycle.
- FR-59: Corrections after posting must use reversal/adjustment
  workflows rather than mutating historical approval evidence.
- FR-60: Compliance evidence retained outside BC must remain linkable to
  the final BC transaction.

## 7. Domain Model and Application-Side Data Model

### 7.1 Design principles

The application database is not a second accounting ledger. It stores
operational and decisioning data that BC does not need to own natively,
plus immutable audit/evidence needed to explain how a financial
transaction was produced.

Recommended relational model:

```
Tenant / Company
      |
      +---- Employee
      |
      +---- Policy / Rule Set
      |
      +---- Expense
      |       |
      |       +---- Expense Allocation
      |       +---- Receipt / Evidence
      |       +---- Compliance Assessment
      |       +---- Policy Evaluation
      |       +---- Duplicate Signal
      |
      +---- Expense Report
      |       |
      |       +---- Expense Report Line -> Expense Allocation
      |       +---- Approval Instance / Decision
      |       +---- Posting Attempt
      |       +---- Settlement
      |
      +---- Advance Request
              |
              +---- Advance Allocation

All major entities -> Audit Event
All BC-linked entities -> BC Reference
```

### 7.2 Recommended table inventory

| Table | Purpose | Owns accounting balance? |
|---|---|---|
| tenant | Product tenant/customer boundary | No |
| bc_company | BC company/tenant connection and identity | No |
| employee | Application-side employee identity mapping | No |
| expense | Canonical expense captured by employee/channel | No |
| expense_source | Receipt/source file and extraction source metadata | No |
| expense_allocation | Split/itemized financial treatment of one expense | No |
| expense_report | Batch/report submitted for approval | No |
| expense_report_line | Links report to expense allocation and captures report-specific state | No |
| advance_request | Operational request/approval/lifecycle of an employee advance | No |
| advance_allocation | Links expense settlement to an advance request/accounting reference | No |
| compliance_assessment | Versioned GST/TDS/payroll assessment | No |
| policy_evaluation | Versioned policy-rule result | No |
| approval_instance | Approval workflow instance and route | No |
| approval_decision | Immutable approve/reject/exception decision | No |
| duplicate_assessment | Duplicate/fraud signals and outcome | No |
| posting_attempt | Idempotent BC posting request/result tracking | No |
| settlement | Expected/actual employee reimbursement or recovery handoff | No |
| bc_reference | Stable mapping from application entity to BC record/ledger reference | No |
| audit_event | Immutable activity and decision audit trail | No |
| rule_set | Versioned policy/compliance configuration | No |
| rule_definition | Individual rule under a versioned rule set | No |
| exception_case | Human-review case for policy/compliance/posting exceptions | No |
| integration_event | Reliable integration/outbox/inbox processing record | No |
| setup_capability | Canonical catalog of configurable Expense capabilities and provider mode | No |
| setup_instance | Customer/company-specific enabled configuration for a capability | No |
| setup_version | Immutable/effective-dated snapshot of a setup configuration | No |
| setup_value | Typed values belonging to a setup instance (category, payment method, threshold, location, etc.) | No |
| provider_mapping | Maps canonical Opsmeld setup/capability to Microsoft BC or Opsmeld execution | No |
| provider_sync_state | Tracks projection/synchronization of canonical setup into BC | No |
| approval_policy | Versioned DOFA/approval configuration | No |
| approval_rule | One rule within an approval policy | No |
| approval_rule_condition | Conditions used to match an approval rule | No |
| approval_rule_action | Approver/route/exception action produced by a rule | No |
| approval_route | Resolved approval chain for a particular transaction | No |
| mapping_definition | Defines semantic business concept and BC representation per tenant/company | No |
| mapping_value | Maps a business value to BC Dimension Value / Job / Job Task / Location | No |
| employee_mapping_assignment | Employee-specific eligible/default assignments, including multiple projects | No |
| expense_allocation_mapping | Immutable transaction-time mapping snapshot | No |
| interaction | Channel interaction/session that can originate a structured expense or advance request | No |
| interaction_extraction | Extracted intent/entities, confidence, confirmation and provenance from a conversational message | No |

### 7.3 Configuration Control Plane

#### 7.3.1 What Opsmeld should configure

The following setup areas should be represented in the Opsmeld
configuration model. The table reflects the current Microsoft Expense
Management setup surface documented for Business Central 2026 Wave 1 and
extends it with India-first requirements and provider-neutral controls.
Microsoft currently documents setup for payment methods, expense
categories/subcategories, locations, groups, rules, posting groups,
approval workflows, number series, exchange-rate handling, cash advances,
report grouping/rounding, mandatory receipt/merchant controls, and
employee creation for Expense Users.

| Setup domain | Canonical Opsmeld setup | Current BC native capability | Recommended provider strategy |
|---|---|---|---|
| Expense categories | Category code, description, posting description, default payment method, refundable, attachment requirement, detail type, group, advance support | Yes | HYBRID |
| Expense subcategories | Itemization subcategories, description, posting description, refundable, description-required, active | Yes | HYBRID |
| Expense groups | Category grouping/reporting taxonomy | Yes | MICROSOFT_NATIVE or HYBRID |
| Payment methods | Method, funding source, reimbursement/settlement semantics, active | Yes | HYBRID |
| Posting groups | Employee and expense posting configuration / BC account mapping | Yes | MICROSOFT_NATIVE |
| Expense locations | Country/state/city, per-diem context | Yes | HYBRID |
| Expense rules | Limits, minimum/maximum, justification, merchant restrictions, location/currency/UOM conditions | Yes | HYBRID |
| Receipt controls | Receipt required, receipt-less thresholds, receipt number requirement | Partly | OPSMELD_NATIVE + project to BC where possible |
| Merchant controls | Merchant mandatory / allowed merchant restrictions | Yes/Partly | HYBRID |
| Report grouping | Period/trip/context grouping | Yes | OPSMELD_NATIVE as canonical; project supported grouping to BC where useful |
| Rounding | Precision and rounding type | Yes | HYBRID |
| Exchange-rate policy | Expense-date vs posting-date policy and source | Yes | HYBRID |
| Advance policy | Eligibility, approval, aging, blocking, settlement/recovery rules | Partial/native accounting support | HYBRID |
| Approval / DOFA | Conditions, authority, delegation, named override authority, exception route | Partial/native workflows | HYBRID initially |
| Dimension mapping | Cost Center / Department / Project / other semantic concepts to BC | Not a single native expense setup concept | OPSMELD_NATIVE configuration + BC mapping |
| Project strategy | Dimension-only / Job-only / Both | BC supports Project + Project Task on expenses | HYBRID |
| Employee assignments | Eligible/default departments, cost centers, projects/jobs, effective dates | Employee/user defaults exist but not sufficient for our multi-project model | OPSMELD_NATIVE |
| GST configuration | GSTIN, tax components, ITC rules, blocked-credit rules, overrides, evidence | India-specific gap to validate for Expense Management | OPSMELD_NATIVE |
| TDS configuration | Sections, thresholds, rates, vendor/AP routing rules | India-specific expense capability gap to validate | OPSMELD_NATIVE |
| Payroll tax treatment | Allowance/perquisite categories, regime-aware treatment, payroll handoff rules | Not part of the documented Expense setup surface | OPSMELD_NATIVE |
| Duplicate/fraud policy | Signals, confidence, thresholds, cross-employee scope, reviewer actions | Agent has duplicate handling, but product policy control is broader | OPSMELD_NATIVE / HYBRID |
| Compliance deadlines | Monthly operational cutoffs, FY-end ITC sweep, policy deadlines | Not a complete native expense setup concept | OPSMELD_NATIVE |
| Number series | Expense/report/advance/application identifiers and numbering strategy | Yes | MICROSOFT_NATIVE with Opsmeld reference IDs |
| User/employee linkage | Expense User ↔ BC Employee identity and company scope | Yes | HYBRID |
| Permissions/roles | Employee, approver, finance, payroll, rule owner, admin | BC permissions exist; product authorization adds cross-system roles | HYBRID |

The current Microsoft documentation explicitly says that Expense Agent
setup applies defaults for payment methods, posting groups, expense
categories, locations, management rules, and number series, and also
exposes controls for exchange rates, cash advances, report grouping,
rounding, receipts/merchant requirements, and rule enforcement.

#### 7.3.2 Canonical setup vs provider projection

For each setup domain, Opsmeld stores the canonical configuration first.
A provider adapter then decides whether to:

- create/update the equivalent BC setup;
- retain and evaluate it only in Opsmeld; or
- split responsibility between the two.

Example:

```
Canonical: Expense Category HOTEL
Opsmeld
  Category = HOTEL
  Refundable = true
  Receipt = mandatory
  Detail = itemize
  Default Payment Method = EMP_CASH
  Policy Rules = HOTEL-IND-01
          |
          +---- BC Provider
          |      BC Category = HOTEL
          |      BC Posting Group = EXP-HOTEL
          |      BC Payment Method = CASH
          |
          +---- Opsmeld Provider
                 GST/ITC rules
                 Perquisite rules
                 Duplicate rules
                 India policy rules
```

The canonical model remains stable even when the BC representation
changes between releases.

#### 7.3.3 Provider selection is per capability, company, and version

The provider is not one global switch for the entire product. A customer
may use:

```
Expense Categories       → MICROSOFT_NATIVE
Expense Rules             → HYBRID
Approval                 → OPSMELD_NATIVE
GST / ITC                → OPSMELD_NATIVE
Posting Groups            → MICROSOFT_NATIVE
Project Mapping           → HYBRID
Duplicate Detection       → OPSMELD_NATIVE
```

A provider decision is scoped by `tenant_id`, `bc_company_id`,
`capability`, effective date, and provider version.

#### 7.3.4 Future Microsoft capability adoption

When Microsoft introduces a capability that was previously Opsmeld-native:

```
Before
Capability → OPSMELD_NATIVE

Microsoft release adds equivalent capability
                ↓
      Validate semantic compatibility
                ↓
     Configure provider mapping
                ↓
      Synchronize canonical setup
                ↓
Capability → HYBRID / MICROSOFT_NATIVE
```

Historical transactions continue to point to the canonical
configuration/rule version that produced them. No restructuring of the
expense, report, compliance, or audit schema is required.

#### 7.3.5 Do not make BC setup tables the foreign-key target of core domain tables

Core entities such as `expense`, `expense_allocation`, `expense_report`,
`approval_instance`, and `compliance_assessment` must refer to stable
Opsmeld setup IDs/version IDs. BC IDs and record keys belong in
`provider_mapping` / `bc_reference`.

This prevents the core schema from becoming coupled to Microsoft table
names, field names, or page structures.

### 7.4 Configuration-driven BC mapping

#### 7.4.1 Principle

The application must map business concepts to the customer's actual BC
configuration. It must never assume that a concept is represented by a
particular BC Global Dimension or shortcut-dimension number.

For example:

```
Business Concept: Cost Center
        ↓
Mapping Definition
        ↓
BC Dimension Code = COSTCENTER
        ↓
BC Dimension Value = CC-100
```

A different customer may use a different Dimension Code for the same
business concept. Our application stores the semantic concept separately
from its BC representation.

Global Dimension 1 and Global Dimension 2 are therefore not modelled as
business concepts. They are implementation details discovered from
customer configuration.

#### 7.4.2 Supported mapping strategies

Each concept is configured per tenant + BC company.

| Business concept | Supported representation | Required configuration |
|---|---|---|
| Cost Center | BC Dimension | BC Dimension Code + allowed values |
| Department | BC Dimension | BC Dimension Code + allowed values |
| Project | Dimension | Dimension Code + project values |
| Project | Native Job | Job + optional Job Task |
| Project | Both | Dimension mapping + Job/Job Task mapping |
| Billable Customer | Dimension | Dimension Code + values |
| Billable Customer | Native Job relationship | Job/Task customer mapping where supported |
| Trip | Dimension or application-only | Optional BC dimension mapping |
| Branch / GST registration | BC Location | Location code + GST registration mapping, subject to BC SME confirmation |

#### 7.4.3 Project mapping modes

For Project, the customer chooses one of: `DIMENSION_ONLY`, `JOB_ONLY`,
`BOTH`.

For `BOTH`, the dimension and Job/Job Task mappings are maintained
independently. The application must not assume that the project code,
dimension value, Job No., and Job Task No. are the same identifier.

Example:

```
Application Project: PROJ-MUM-001
Dimension representation:
  Dimension Code = PROJECT
  Dimension Value = MUM-001
Job representation:
  Job No. = J-1042
  Job Task = 1000
```

#### 7.4.4 Employee-specific mapping and multiple projects/jobs

Employee mapping is assignment-based, not a single `employee.project`
field.

An employee may have multiple active assignments:

```
Employee E1001
  ├─ Project A / Job J100 / Task 10 / 60%
  ├─ Project B / Job J200 / Task 20 / 30%
  └─ Project C / Job J300 / Task 30 / 10%
```

Assignments support effective dates and an optional default. Allocation
percentage is optional planning metadata and must not automatically
drive accounting allocation unless explicitly configured.

When an expense is captured, mapping resolution follows this precedence:

1. Explicit employee selection on the expense/allocation.
2. Trip / report / business-context mapping, if configured.
3. Employee default assignment valid on the expense date.
4. Company-level default mapping.
5. Otherwise `Needs Review` because the system must not silently choose
   among multiple eligible projects/jobs.

If an employee works on multiple projects, a single expense may be split
across multiple allocations, each with its own project/job mapping.

#### 7.4.5 Mapping snapshot rule

Configuration can change over time. Therefore a transaction must not
depend on the current mapping after submission/posting.

At `Ready to Post`, persist a resolved mapping snapshot containing the
semantic concept, selected value, BC representation, mapping version, and
resolved BC codes. Historical transactions retain that snapshot even when
customer configuration later changes.

#### 7.4.6 Mapping object relationship

```
mapping_definition
      |
      +---- mapping_value
      |
      +---- employee_mapping_assignment
      |
      +---- expense_allocation_mapping (resolved immutable snapshot)
```

### 7.5 Setup and provider tables

#### 7.5.1 Table: setup_capability

Canonical catalog of configurable Expense capabilities. This is a
product capability, not a customer value.

| Column | Type | Notes |
|---|---|---|
| setup_capability_id | UUID | PK |
| capability_code | varchar | Stable code, e.g. `EXPENSE_CATEGORY`, `APPROVAL_POLICY`, `GST_ITC` |
| name | varchar | |
| domain | enum | Expense / Finance / Approval / Compliance / Mapping / Integration |
| version | varchar | Product capability version |
| supports_microsoft | boolean | Whether a Microsoft provider exists |
| supports_opsmeld | boolean | Whether Opsmeld provider exists |
| status | enum | Active / Deprecated |

#### 7.5.2 Table: setup_instance

Customer/company-specific configuration for a capability.

| Column | Type | Notes |
|---|---|---|
| setup_instance_id | UUID | PK |
| tenant_id | UUID | FK |
| bc_company_id | UUID | FK |
| setup_capability_id | UUID | FK |
| provider_mode | enum | MICROSOFT_NATIVE / OPSMELD_NATIVE / HYBRID |
| status | enum | Draft / Active / Suspended / Retired |
| current_version_id | UUID | FK to setup_version |
| created_at | timestamp | |
| updated_at | timestamp | |

Unique: (bc_company_id, setup_capability_id).

#### 7.5.3 Table: setup_version

Immutable/effective-dated canonical configuration snapshot.

| Column | Type | Notes |
|---|---|---|
| setup_version_id | UUID | PK |
| setup_instance_id | UUID | FK |
| version_no | integer | Monotonic |
| effective_from | timestamp | |
| effective_to | timestamp/null | |
| status | enum | Draft / Approved / Active / Retired |
| approved_by | UUID/null | |
| approved_at | timestamp/null | |
| change_reason | text | |
| config_hash | varchar | Immutable configuration hash |

#### 7.5.4 Table: setup_value

Typed child values for a setup version. Use structured columns for
values that must be queried/validated; use JSON only for
provider-specific extension attributes.

| Column | Type | Notes |
|---|---|---|
| setup_value_id | UUID | PK |
| setup_version_id | UUID | FK |
| value_type | varchar | Category / Subcategory / PaymentMethod / Location / Threshold / etc. |
| code | varchar | Stable canonical code |
| name | varchar | |
| parent_code | varchar/null | Category/group hierarchy |
| active | boolean | |
| data_json | json | Additional typed attributes |
| effective_from | timestamp | |
| effective_to | timestamp/null | |

#### 7.5.5 Table: provider_mapping

Maps canonical Opsmeld setup/capability/value to a provider
representation.

| Column | Type | Notes |
|---|---|---|
| provider_mapping_id | UUID | PK |
| tenant_id | UUID | FK |
| bc_company_id | UUID | FK |
| setup_capability_id | UUID | FK |
| setup_value_id | UUID/null | FK |
| provider_type | enum | MicrosoftBC / Opsmeld |
| provider_object_type | varchar | BC Expense Category / Dimension / Job / Workflow / etc. |
| provider_key | varchar | External key or object identifier |
| provider_parent_key | varchar/null | Parent relation such as category/project |
| mapping_status | enum | Pending / Active / Invalid / Retired |
| mapping_version | integer | |
| metadata_json | json | Provider-specific details |
| created_at | timestamp | |

#### 7.5.6 Table: provider_sync_state

Tracks projection of canonical configuration into BC.

| Column | Type | Notes |
|---|---|---|
| provider_sync_id | UUID | PK |
| provider_mapping_id | UUID | FK |
| canonical_version | integer | |
| provider_version | varchar/null | BC/provider version discovered |
| sync_status | enum | Pending / Synced / Failed / Drifted / NotApplicable |
| last_sync_at | timestamp/null | |
| last_error | text/null | |
| correlation_id | varchar/null | |

#### 7.5.7 Tables: approval configuration

**approval_policy** — Versioned DOFA policy owned by Opsmeld.

| Column | Type | Notes |
|---|---|---|
| approval_policy_id | UUID | PK |
| tenant_id | UUID | FK |
| bc_company_id | UUID | FK |
| policy_code | varchar | Stable policy identifier |
| name | varchar | |
| version | varchar | Immutable policy version |
| effective_from | timestamp | |
| effective_to | timestamp/null | |
| status | enum | Draft / Active / Retired |
| override_authority_employee_id | UUID/null | Named top-level authority |
| approved_by | UUID/null | |
| approved_at | timestamp/null | |

**approval_rule**

| Column | Type | Notes |
|---|---|---|
| approval_rule_id | UUID | PK |
| approval_policy_id | UUID | FK |
| rule_code | varchar | |
| priority | integer | |
| description | text | |
| action_type | enum | Approve / Route / Exception / Reject |
| active | boolean | |

**approval_rule_condition**

| Column | Type | Notes |
|---|---|---|
| condition_id | UUID | PK |
| approval_rule_id | UUID | FK |
| attribute_type | varchar | Amount / Category / Department / Grade / Project / etc. |
| operator | enum | EQ / NE / GT / GTE / LT / LTE / IN / BETWEEN |
| value_json | json | One or more canonical values |
| sequence | integer | AND evaluation order |

**approval_rule_action**

| Column | Type | Notes |
|---|---|---|
| action_id | UUID | PK |
| approval_rule_id | UUID | FK |
| sequence | integer | Route order |
| approver_type | enum | Employee / Manager / ManagerOfManager / Role / GradeRole / DepartmentHead / NamedEmployee / OverrideAuthority |
| approver_reference | varchar/null | Role/employee/grade reference |
| is_override_authority | boolean | |
| required | boolean | |

The existing runtime `approval_instance` and `approval_decision` tables
(7.23, 7.24) remain separate from this configuration.

### 7.6 Tables: conversational intake

The Teams/Outlook experience is a channel, not the domain model. A
natural-language message creates or updates an Opsmeld domain transaction
only after identity resolution, intent/entity extraction, validation, and
user confirmation where required.

**interaction** — represents the inbound/outbound conversational
interaction that may originate an expense or advance request.

| Column | Type | Notes |
|---|---|---|
| interaction_id | UUID | PK |
| tenant_id | UUID | FK |
| bc_company_id | UUID | FK |
| channel | enum | TEAMS / OUTLOOK / APP / OTHER |
| external_conversation_id | varchar | Teams chat/conversation or Outlook thread ID |
| external_message_id | varchar | Source message ID; must be idempotent |
| sender_external_user_id | varchar | Channel identity |
| employee_id | UUID/null | Resolved Opsmeld employee |
| message_text | text | Original user message or normalized representation |
| intent | enum/null | ADVANCE_REQUEST / EXPENSE_CAPTURE / REPORT_SUBMISSION / QUERY / UNKNOWN |
| processing_status | enum | RECEIVED / EXTRACTED / NEEDS_INFO / AWAITING_CONFIRMATION / CONFIRMED / REJECTED / FAILED |
| received_at | timestamp | |
| processed_at | timestamp/null | |

Indexes: unique(channel, external_message_id) within the tenant/
integration boundary.

**interaction_extraction** — stores what the system extracted from
natural language and whether the employee confirmed it.

| Column | Type | Notes |
|---|---|---|
| extraction_id | UUID | PK |
| interaction_id | UUID | FK |
| attribute_name | varchar | Example: amount, project, purpose, travel_start |
| canonical_value_json | json | Parsed value in the canonical domain format |
| raw_value | varchar/null | Original phrase where useful |
| confidence | decimal | 0–1 |
| required | boolean | Whether the field is mandatory for the intended operation |
| confirmed_by_user | boolean | Explicit confirmation |
| confirmed_at | timestamp/null | |
| extraction_model_version | varchar/null | Model/prompt version for audit |
| created_at | timestamp | |

Important: the extracted message is not itself a financial transaction.
`interaction` links to the resulting domain record through the
application event/audit relationship.

### 7.7 Table: tenant

Represents the customer boundary.

| Column | Type | Notes |
|---|---|---|
| tenant_id | UUID | PK |
| tenant_code | varchar | Unique business identifier |
| name | varchar | Customer name |
| status | enum | Active / Suspended / Closed |
| created_at | timestamp | |
| updated_at | timestamp | |

Indexes: unique(tenant_code).

### 7.8 Table: bc_company

Represents a BC company/legal entity accessible through the integration.

| Column | Type | Notes |
|---|---|---|
| bc_company_id | UUID | PK |
| tenant_id | UUID | FK → tenant |
| external_company_id | varchar | Stable BC company/environment identifier |
| company_name | varchar | Cached display value |
| currency_code | varchar(10) | Default/reporting currency where known |
| status | enum | Active / Disabled |
| integration_config_ref | varchar | Reference to secret/config store; do not store credentials here |
| created_at | timestamp | |
| updated_at | timestamp | |

Indexes: unique(tenant_id, external_company_id).

### 7.9 Table: employee

Application identity and BC employee mapping. Do not assume application
user ID equals BC Employee No.

| Column | Type | Notes |
|---|---|---|
| employee_id | UUID | PK |
| tenant_id | UUID | FK |
| bc_company_id | UUID | FK |
| user_external_id | varchar | Entra/M365/app identity reference |
| bc_employee_no | varchar | BC Employee No. where available |
| employee_name | varchar | Cached display value |
| grade_band | varchar | Optional lookup used by DOFA |
| manager_employee_id | UUID | Self FK |
| default_location_code | varchar | Used for branch/GST resolution when applicable |
| tax_regime | enum/null | New / Old / Unknown, where payroll process supplies it |
| status | enum | Active / Inactive |
| created_at | timestamp | |
| updated_at | timestamp | |

Indexes: unique(bc_company_id, bc_employee_no); unique(tenant_id,
user_external_id).

### 7.10 Table: expense

Canonical source-level expense record. One expense represents one
captured source transaction, even if later split into multiple
allocations.

| Column | Type | Notes |
|---|---|---|
| expense_id | UUID | PK |
| tenant_id | UUID | FK |
| bc_company_id | UUID | FK |
| employee_id | UUID | FK |
| source_channel | enum | App / Photo / Email / Teams / Outlook / Agent / API |
| source_reference | varchar | Message/upload/source ID |
| status | enum | Captured / Processing / NeedsReview / Ready / Attached / Submitted / Rejected / Archived |
| vendor_name | varchar | Normalized vendor |
| vendor_gstin | varchar | Nullable |
| invoice_number | varchar | Nullable |
| expense_date | date | |
| currency_code | varchar(10) | Transaction currency |
| gross_amount | decimal | Original amount |
| net_amount | decimal | Pre-tax/normalized amount where known |
| tax_amount | decimal | Total tax extracted |
| cgst_amount | decimal | Nullable |
| sgst_amount | decimal | Nullable |
| igst_amount | decimal | Nullable |
| category_code | varchar | Proposed/confirmed category |
| location_code | varchar | Branch/location used in GST mapping |
| project_code | varchar | Optional |
| trip_reference | varchar | Optional |
| invoice_validity_status | enum | Valid / Invalid / Unknown / Review |
| ocr_confidence | decimal | 0–1 or equivalent |
| captured_at | timestamp | |
| ready_at | timestamp | Nullable |
| created_at | timestamp | |
| updated_at | timestamp | |

Indexes: (employee_id, status), (bc_company_id, expense_date),
(vendor_gstin, invoice_number). Do not treat invoice-number uniqueness as
absolute.

### 7.11 Table: expense_source

Stores source evidence metadata. Binary objects should normally live in
object storage; this table stores references and hashes.

| Column | Type | Notes |
|---|---|---|
| expense_source_id | UUID | PK |
| expense_id | UUID | FK |
| source_type | enum | Receipt / Email / Attachment / Declaration |
| object_uri | varchar | Object-store reference |
| content_sha256 | varchar(64) | Exact source hash |
| mime_type | varchar | |
| file_size | bigint | |
| ocr_text_ref | varchar | Optional separate extracted text object |
| created_at | timestamp | |

Indexes: (expense_id), unique(content_sha256) only if tenant-wide
deduplication policy permits.

### 7.12 Table: mapping_definition

Defines a semantic business concept and how it is represented in a
specific BC company. One company may map Cost Center or Department to
any valid BC Dimension Code; no Global Dimension 1/2 assumption is made.

| Column | Type | Notes |
|---|---|---|
| mapping_definition_id | UUID | PK |
| tenant_id | UUID | FK |
| bc_company_id | UUID | FK |
| concept_type | enum | CostCenter / Department / Project / BillableCustomer / Trip / Branch |
| representation_type | enum | Dimension / Job / JobTask / Location / ApplicationOnly / Both |
| bc_dimension_code | varchar/null | Required for Dimension representation |
| status | enum | Draft / Active / Retired |
| effective_from | timestamp | |
| effective_to | timestamp/null | |
| version | integer | Increment when mapping definition changes |
| created_at | timestamp | |
| updated_at | timestamp | |

Constraints: active definitions for the same tenant/company/concept/
representation may not overlap in effective time. Project `Both` mode
requires both a dimension mapping and a Job mapping.

### 7.13 Table: mapping_value

Maps a semantic application value to the concrete BC value(s) used for
posting.

| Column | Type | Notes |
|---|---|---|
| mapping_value_id | UUID | PK |
| mapping_definition_id | UUID | FK |
| business_code | varchar | Stable application-side code |
| business_name | varchar | Display name |
| bc_dimension_value_code | varchar/null | Dimension value when applicable |
| bc_job_no | varchar/null | Job No. when applicable |
| bc_job_task_no | varchar/null | Job Task when applicable |
| bc_customer_no | varchar/null | Customer when applicable |
| bc_location_code | varchar/null | Location when applicable |
| status | enum | Active / Inactive |
| effective_from | timestamp | |
| effective_to | timestamp/null | |
| created_at | timestamp | |
| updated_at | timestamp | |

Indexes: unique(mapping_definition_id, business_code, effective_from).

### 7.14 Table: employee_mapping_assignment

Employee-specific eligibility/default assignment. This supports multiple
concurrent project/job assignments.

| Column | Type | Notes |
|---|---|---|
| employee_mapping_assignment_id | UUID | PK |
| employee_id | UUID | FK |
| mapping_definition_id | UUID | FK |
| mapping_value_id | UUID | FK |
| assignment_role | enum | Eligible / Default |
| allocation_percent | decimal/null | Optional planning metadata; not an automatic accounting split |
| valid_from | date | |
| valid_to | date/null | |
| priority | integer | Optional explicit preference |
| status | enum | Active / Inactive |
| created_at | timestamp | |
| updated_at | timestamp | |

Constraints: an employee may have many active `Eligible` assignments. At
most one active `Default` per employee + mapping definition unless an
explicit priority policy is configured.

### 7.15 Table: expense_allocation_mapping

Immutable transaction-time mapping snapshot. It preserves exactly which
semantic mapping and BC target were resolved for the allocation.

| Column | Type | Notes |
|---|---|---|
| expense_allocation_mapping_id | UUID | PK |
| expense_allocation_id | UUID | FK |
| mapping_definition_id | UUID | FK |
| mapping_value_id | UUID | FK |
| resolution_source | enum | Explicit / TripContext / EmployeeDefault / CompanyDefault / ReviewerOverride |
| mapping_definition_version | integer | Version used |
| bc_dimension_code | varchar/null | Immutable snapshot |
| bc_dimension_value_code | varchar/null | Immutable snapshot |
| bc_job_no | varchar/null | Immutable snapshot |
| bc_job_task_no | varchar/null | Immutable snapshot |
| bc_customer_no | varchar/null | Immutable snapshot |
| bc_location_code | varchar/null | Immutable snapshot |
| resolution_reason | varchar/null | Why mapping was selected |
| resolved_at | timestamp | |
| resolved_by | UUID/null | System/user |

Requirement: immutable once the related report is approved or posting
starts. A correction creates a new version/event rather than mutating the
historical snapshot.

### 7.16 Table: expense_allocation

This is the key table for split funding and itemization. One expense can
have one or many allocations whose monetary amounts sum to the source
expense amount, subject to rounding/tolerance rules.

| Column | Type | Notes |
|---|---|---|
| expense_allocation_id | UUID | PK |
| expense_id | UUID | FK |
| line_no | integer | Ordering within source expense |
| description | varchar | Itemized description |
| category_code | varchar | Accounting/policy category |
| amount | decimal | Allocation amount in transaction currency |
| tax_amount | decimal | Allocation tax |
| funding_source | enum | Employee / CorporateCard / CompanyPaid / EmployeeAdvance |
| advance_request_id | UUID/null | Required for EmployeeAdvance |
| settlement_method | enum | EmployeeReimbursement / EmployeeRecovery / CardSettlement / NoSettlement |
| cost_center_mapping_value_id | UUID/null | FK → mapping_value |
| department_mapping_value_id | UUID/null | FK → mapping_value |
| project_mapping_value_id | UUID/null | FK → mapping_value |
| trip_mapping_value_id | UUID/null | Optional FK → mapping_value |
| billable_customer_mapping_value_id | UUID/null | Optional FK → mapping_value |
| mapping_resolution_status | enum | Resolved / Ambiguous / Missing / Overridden |
| trip_reference | varchar | Optional |
| created_at | timestamp | |
| updated_at | timestamp | |

Constraint: sum of allocation gross amounts must reconcile to the parent
expense gross amount within configured rounding tolerance.

### 7.17 Table: expense_report

Batch/submission container.

| Column | Type | Notes |
|---|---|---|
| expense_report_id | UUID | PK |
| tenant_id | UUID | FK |
| bc_company_id | UUID | FK |
| employee_id | UUID | Claimant |
| submitted_by_employee_id | UUID | Supports submit-on-behalf-of |
| status | enum | Draft / Submitted / UnderReview / Exception / Approved / ReadyToPost / Posting / Posted / Settled / Rejected / Returned / Cancelled |
| report_number | varchar | Human-readable application reference |
| report_date | date | |
| period_start | date | Optional |
| period_end | date | Optional |
| trip_reference | varchar | Optional |
| policy_version_id | UUID/null | DOFA/policy version used |
| total_amount | decimal | Calculated |
| reimbursable_amount | decimal | Calculated |
| recovery_amount | decimal | Calculated |
| advance_offset_amount | decimal | Calculated |
| created_at | timestamp | |
| submitted_at | timestamp | Nullable |
| approved_at | timestamp | Nullable |
| posted_at | timestamp | Nullable |
| settled_at | timestamp | Nullable |
| updated_at | timestamp | |

Indexes: unique(bc_company_id, report_number), (employee_id, status),
(status, created_at).

### 7.18 Table: expense_report_line

Report-specific inclusion of an allocation. Keeps the source expense
independent from any particular report/version.

| Column | Type | Notes |
|---|---|---|
| expense_report_line_id | UUID | PK |
| expense_report_id | UUID | FK |
| expense_allocation_id | UUID | FK |
| line_no | integer | Report ordering |
| status | enum | Included / Approved / Rejected / Removed |
| rejection_reason_code | varchar | Nullable |
| approved_amount | decimal | Amount approved for this report |
| created_at | timestamp | |
| updated_at | timestamp | |

Constraint: an allocation cannot be actively included in two open reports
simultaneously unless policy explicitly permits it.

### 7.19 Table: advance_request

Operational request, not the accounting subledger.

| Column | Type | Notes |
|---|---|---|
| advance_request_id | UUID | PK |
| tenant_id | UUID | FK |
| bc_company_id | UUID | FK |
| employee_id | UUID | FK |
| request_number | varchar | Human-readable |
| purpose | varchar/text | |
| trip_reference | varchar | Optional |
| project_code | varchar | Optional |
| requested_amount | decimal | |
| currency_code | varchar(10) | |
| expected_settlement_date | date | Primary aging anchor |
| status | enum | Draft / Submitted / Approved / Rejected / Disbursed / PartiallySettled / Closed / Overdue |
| approved_amount | decimal | Nullable |
| approved_at | timestamp | Nullable |
| disbursed_at | timestamp | Nullable |
| closed_at | timestamp | Nullable |
| created_at | timestamp | |
| updated_at | timestamp | |

Important: `advance_request` should not become the authoritative
outstanding monetary balance if BC Employee Ledger Entry is confirmed as
the accounting mechanism.

### 7.20 Table: advance_allocation

Links an advance request to actual expense settlement and BC accounting
references.

| Column | Type | Notes |
|---|---|---|
| advance_allocation_id | UUID | PK |
| advance_request_id | UUID | FK |
| expense_report_id | UUID | FK |
| amount_applied | decimal | Application amount |
| bc_employee_ledger_entry_no | varchar | Nullable until BC reference known |
| application_status | enum | Pending / Applied / Unapplied / Reversed |
| created_at | timestamp | |
| updated_at | timestamp | |

Business rule: application-side amount is a reconciliation value; BC
remains authoritative for accounting balance/application once posted.

### 7.21 Table: compliance_assessment

Stores versioned compliance decisions. A new assessment supersedes a
previous one; historical records remain immutable.

| Column | Type | Notes |
|---|---|---|
| compliance_assessment_id | UUID | PK |
| expense_id | UUID | FK |
| expense_allocation_id | UUID/null | More precise line-level scope |
| assessment_type | enum | GST / ITC / TDS / PayrollTax |
| rule_set_id | UUID | FK |
| decision | enum | Yes / No / Blocked / Review / NotApplicable |
| reason_code | varchar | Structured reason |
| gstin_vendor | varchar | Input snapshot |
| gstin_company | varchar | Input snapshot |
| invoice_validity_status | varchar | Snapshot |
| tax_base_amount | decimal | |
| tax_amount | decimal | |
| tds_section | varchar | Nullable |
| tds_rate | decimal | Nullable |
| tds_amount | decimal | Nullable |
| payroll_tax_treatment | enum/null | Reimbursement / Allowance / Perquisite / Review |
| input_snapshot_json | json | Exact evaluated inputs |
| decision_explanation | text | Human-readable provenance |
| review_status | enum | NotRequired / Pending / Confirmed / Overridden |
| reviewed_by | UUID/null | Employee/Finance reviewer |
| reviewed_at | timestamp | Nullable |
| created_at | timestamp | |

Indexes: (expense_id, assessment_type, created_at), (rule_set_id).

### 7.22 Table: policy_evaluation

Stores a versioned result of expense/report policy rules.

| Column | Type | Notes |
|---|---|---|
| policy_evaluation_id | UUID | PK |
| entity_type | enum | Expense / Allocation / Report / Advance |
| entity_id | UUID | Entity being evaluated |
| rule_set_id | UUID | FK |
| result | enum | Pass / Fail / Review |
| severity | enum | Info / Warning / Error |
| rule_code | varchar | Specific rule |
| reason_code | varchar | Structured outcome |
| input_snapshot_json | json | Inputs used |
| evaluation_json | json | Detailed rule results |
| evaluated_at | timestamp | |

### 7.23 Table: approval_instance

Represents one approval cycle/version for a report.

| Column | Type | Notes |
|---|---|---|
| approval_instance_id | UUID | PK |
| expense_report_id | UUID | FK |
| policy_version_id | UUID | FK |
| route_version | integer | Incremented if rerouted |
| current_stage | varchar | Interim / Final / Exception |
| status | enum | Pending / InProgress / Approved / Rejected / Cancelled |
| started_at | timestamp | |
| completed_at | timestamp | Nullable |

### 7.24 Table: approval_decision

Immutable record of each approval/rejection/override decision.

| Column | Type | Notes |
|---|---|---|
| approval_decision_id | UUID | PK |
| approval_instance_id | UUID | FK |
| expense_report_line_id | UUID/null | Optional line-level decision |
| approver_employee_id | UUID | Decision maker |
| delegate_employee_id | UUID/null | Delegate acting on behalf |
| decision | enum | Approve / Reject / Override / Return |
| reason_code | varchar | Required for reject/override |
| comments | text | |
| policy_rule_snapshot_json | json | Rule inputs relevant to decision |
| decided_at | timestamp | |

Requirement: approval history must never be overwritten by subsequent
routing changes.

### 7.25 Table: duplicate_assessment

| Column | Type | Notes |
|---|---|---|
| duplicate_assessment_id | UUID | PK |
| expense_id | UUID | FK |
| matched_entity_type | enum | Expense / ReportLine / ExternalClaim |
| matched_entity_id | UUID/null | Internal match when applicable |
| signal_type | enum | ExactHash / VendorAmountDate / InvoiceNo / OCRSimilarity / ImageSimilarity / OrgWideMatch |
| confidence | decimal | 0–1 |
| risk_level | enum | Low / Medium / High |
| evidence_json | json | Matching attributes |
| review_status | enum | Pending / Cleared / Confirmed |
| created_at | timestamp | |

### 7.26 Table: exception_case

Central human-review object for compliance, policy, duplicate, or
posting exceptions.

| Column | Type | Notes |
|---|---|---|
| exception_case_id | UUID | PK |
| tenant_id | UUID | FK |
| entity_type | enum | Expense / Allocation / Report / Advance / Posting |
| entity_id | UUID | FK-by-convention |
| exception_type | enum | Policy / GST / TDS / Payroll / Duplicate / Posting / Data |
| severity | enum | Low / Medium / High / Critical |
| reason_code | varchar | Structured reason |
| status | enum | Open / UnderReview / Resolved / Waived / Rejected |
| assigned_to_employee_id | UUID/null | Reviewer |
| resolution_code | varchar/null | |
| resolution_notes | text | |
| opened_at | timestamp | |
| resolved_at | timestamp/null | |

### 7.27 Table: posting_attempt

Critical integration table for idempotency and posting reliability.

| Column | Type | Notes |
|---|---|---|
| posting_attempt_id | UUID | PK |
| tenant_id | UUID | FK |
| bc_company_id | UUID | FK |
| expense_report_id | UUID | FK |
| idempotency_key | varchar(128) | Unique per financial posting intent |
| posting_method | enum | ExpenseAPI / GeneralJournal / PaymentJournal / OtherBCSupported |
| request_hash | varchar(64) | Hash of canonical posting payload |
| status | enum | Created / Sent / Accepted / Posted / Failed / Unknown / Reconciled |
| bc_document_no | varchar/null | |
| bc_posting_reference | varchar/null | |
| bc_response_ref | varchar/null | Non-sensitive correlation/reference |
| error_code | varchar/null | |
| error_message | text/null | Sanitized |
| attempt_no | integer | Retry sequence |
| requested_at | timestamp | |
| completed_at | timestamp/null | |

Indexes: unique(bc_company_id, idempotency_key), (expense_report_id,
status).

Important: `Unknown` is a valid state after a timeout when the caller
cannot know whether BC posted. Reconciliation must resolve it before a
retry can create another financial transaction.

### 7.28 Table: settlement

Tracks the operational handoff/result of employee reimbursement or
recovery.

| Column | Type | Notes |
|---|---|---|
| settlement_id | UUID | PK |
| expense_report_id | UUID | FK |
| employee_id | UUID | FK |
| settlement_type | enum | Reimbursement / Recovery |
| amount | decimal | |
| currency_code | varchar(10) | |
| execution_method | enum | Bank / Payroll / Other |
| status | enum | Pending / Submitted / Processed / Failed / Cancelled |
| external_payment_reference | varchar/null | Bank/payroll reference |
| scheduled_at | timestamp/null | |
| processed_at | timestamp/null | |
| created_at | timestamp | |

For payroll recovery, add a child table if installment schedules are
required:

**settlement_installment**

| Column | Type | Notes |
|---|---|---|
| settlement_installment_id | UUID | PK |
| settlement_id | UUID | FK |
| sequence_no | integer | |
| due_date | date | |
| amount | decimal | |
| status | enum | Planned / SentToPayroll / Deducted / Failed / Waived |
| payroll_reference | varchar/null | |
| processed_at | timestamp/null | |

### 7.29 Table: bc_reference

Generic, stable cross-system mapping. Avoid storing only one BC
identifier because different posting methods may yield multiple linked
records.

| Column | Type | Notes |
|---|---|---|
| bc_reference_id | UUID | PK |
| bc_company_id | UUID | FK |
| entity_type | enum | Expense / Report / Advance / Posting / Ledger |
| entity_id | UUID | Application entity |
| bc_object_type | varchar | Table/API/business object name |
| bc_record_key | varchar | Natural/system key as returned by BC |
| bc_document_no | varchar/null | |
| reference_role | enum | Source / Posted / Applied / Reversal / Related |
| created_at | timestamp | |

Indexes: (bc_company_id, bc_object_type, bc_record_key), (entity_type,
entity_id).

### 7.30 Table: rule_set

Versioned rules package for policy/compliance decisions.

| Column | Type | Notes |
|---|---|---|
| rule_set_id | UUID | PK |
| tenant_id | UUID | FK; null only for centrally managed global rule sets |
| rule_set_type | enum | ExpensePolicy / DOFA / GST / TDS / Payroll |
| version | varchar | Immutable version identifier |
| effective_from | timestamp | |
| effective_to | timestamp/null | |
| status | enum | Draft / Active / Retired |
| approved_by | UUID/null | Rule owner |
| approved_at | timestamp/null | |
| change_reason | text | |
| created_at | timestamp | |

Constraint: active versions for the same rule-set scope may not overlap
in effective time.

### 7.31 Table: rule_definition

Individual rules under a rule-set version.

| Column | Type | Notes |
|---|---|---|
| rule_definition_id | UUID | PK |
| rule_set_id | UUID | FK |
| rule_code | varchar | Stable business identifier |
| description | text | |
| priority | integer | Evaluation order |
| condition_json | json | Machine-readable condition |
| action_json | json | Result/flag/route |
| reason_code | varchar | Default decision reason |
| enabled | boolean | |
| created_at | timestamp | |

### 7.32 Table: audit_event

Immutable audit log. This is not the same as application logs.

| Column | Type | Notes |
|---|---|---|
| audit_event_id | UUID | PK |
| tenant_id | UUID | FK |
| entity_type | varchar | Expense / Report / Approval / etc. |
| entity_id | UUID | Entity ID |
| event_type | varchar | Created / Changed / Approved / Overridden / Posted / etc. |
| actor_type | enum | Employee / System / Agent / Integration |
| actor_id | UUID/null | Human/system actor |
| event_version | integer | Entity event sequence |
| before_json | json/null | Prior relevant state |
| after_json | json/null | New relevant state |
| reason_code | varchar/null | |
| correlation_id | varchar | Trace across integration |
| occurred_at | timestamp | Immutable event time |

Requirement: audit events are append-only; correction creates a new
event rather than changing history.

### 7.33 Table: integration_event

Reliable event processing / outbox-inbox support.

| Column | Type | Notes |
|---|---|---|
| integration_event_id | UUID | PK |
| tenant_id | UUID | FK |
| event_type | varchar | Domain/integration event |
| aggregate_type | varchar | Expense / Report / Advance |
| aggregate_id | UUID | |
| event_version | integer | |
| idempotency_key | varchar(128) | Unique for event delivery intent |
| payload_json | json | Canonical event payload |
| status | enum | Pending / Published / Processed / Failed / DeadLetter |
| attempt_count | integer | |
| available_at | timestamp | |
| processed_at | timestamp/null | |
| last_error | text/null | |
| created_at | timestamp | |

Indexes: unique(tenant_id, idempotency_key), (status, available_at).

## 8. Mapping Resolution and Multi-Project Behaviour

### 8.1 Employee defaults are not exclusive assignments

An employee may have one default Cost Center and Department while
simultaneously having multiple eligible Project/Job assignments. Project
selection cannot therefore be inferred from employee master data alone.

### 8.2 Ambiguity handling

When multiple active project/job assignments are eligible and no
explicit/contextual mapping resolves the expense, the system sets
`mapping_resolution_status = Ambiguous` and requires a user/reviewer
selection.

The system must not silently choose a project based on most recently
used project, largest allocation percentage, alphabetical order, or
first database row unless that behaviour is explicitly configured as an
auditable customer policy.

### 8.3 Split project allocation

A single expense can be allocated across multiple projects/jobs:

```
Expense: ₹30,000
Allocation 1: ₹20,000 → Project A → Job J100 → Task 10
Allocation 2: ₹10,000 → Project B → Job J200 → Task 20
```

Each allocation receives its own `expense_allocation_mapping` snapshot.

### 8.4 Mapping configuration lifecycle

Mapping changes are versioned/effective-dated. Existing
submitted/posted transactions retain the version and BC codes selected
at resolution time. New expenses use the current active mapping.

### 8.5 Validation before posting

Before `Ready to Post`, every required semantic mapping must resolve to
a valid BC target. Missing or invalid mappings stop posting and create a
data/posting exception rather than silently dropping the dimension or
Job reference.

## 9. Relationship and Lifecycle Rules

### 9.1 Expense to allocations

```
Expense 1 ---- N ExpenseAllocation
```

An expense is the source transaction. Allocations describe how that
transaction is accounted for and settled.

Example:

```
Hotel invoice ₹12,000
    |
    +-- Business stay ₹9,000 -> Company Paid
    +-- Personal extension ₹3,000 -> Employee Paid
```

### 9.2 Expense to report

```
Expense 1 ---- N ExpenseAllocation 1 ---- N ExpenseReportLine N ---- 1 ExpenseReport
```

An allocation may only be active in one open report at a time unless a
specific correction/versioning model permits otherwise.

### 9.3 Advance

```
AdvanceRequest
      |
      +---- N AdvanceAllocation ---- 1 ExpenseReport
      |
      +---- BC Employee Ledger reference
```

The application tracks the operational request and linkages; BC is
authoritative for the accounting balance once disbursement/posting is
represented there.

### 9.4 Compliance

Compliance is assessed against the most precise entity available:

```
Expense
  |
  +-- Allocation A -> GST/ITC assessment
  +-- Allocation B -> GST/ITC assessment
  +-- Expense-level TDS assessment where appropriate
  +-- Report/employee-level payroll context where required
```

## 10. State Machines

### 10.1 Expense

```
Captured
   ↓
Processing
   ↓
Needs Review ──────→ Ready
                         ↓
                      Attached
                         ↓
                     Submitted
                         ↓
              Approved / Rejected
                         |
                    Rejected → Corrected → Ready
                         |
                     Archived
```

### 10.2 Report

```
Draft
  ↓
Submitted
  ↓
Under Review
  ├── Exception → Resolved → Under Review
  └── Returned → Draft/Resubmit
  ↓
Approved
  ↓
Ready to Post
  ↓
Posting
  ├── Failed → Exception / Retry
  ├── Unknown → Reconciliation Required
  └── Posted
          ↓
       Settled
```

Important: Approved ≠ Posted.

### 10.3 Advance

```
Draft
  ↓
Submitted
  ↓
Approved
  ↓
Disbursed
  ↓
Outstanding
  ├── Partial settlement → Outstanding
  ├── Full settlement → Closed
  └── Overdue → Finance Review
```

### 10.4 Post-posting correction

```
Posted
  ↓
Correction Required
  ↓
Reversal / Adjustment
  ↓
Reconciled
```

Historical approval and posting evidence must not be overwritten.

## 10.5 BC Mapping

The following is the proposed default mapping and must be confirmed
against the actual BC 2026W1 tenant before build.

| Need | Proposed mechanism | Application ownership | BC ownership |
|---|---|---|---|
| Cost center | Configured BC Dimension Code + Dimension Value | Canonical mapping in Opsmeld; never assume GD1/GD2 | Posted dimension |
| Department | Configured BC Dimension Code + Dimension Value | Canonical mapping in Opsmeld; never assume GD1/GD2 | Posted dimension |
| Project / Job | Dimension or Job/Job Task | Mapping intent | Native Job fields where used |
| Billable customer | Dimension or Job bill-to customer | Mapping intent | Native Job fields where used |
| Trip/batch reference | Application field + optional BC dimension | Application | Optional posted dimension |
| Branch / GSTIN | BC Location pattern if confirmed | Selected location | Native BC master |
| Vendor GSTIN / HSN/SAC / tax breakup | Application compliance data unless native BC capability is confirmed | Application | BC tax/accounting fields as supported |
| ITC decision | Application compliance assessment | Application | Post required accounting/tax outcome into BC if required by posting/tax process |
| TDS | Application assessment + AP workflow | Application | Final accounting/tax treatment through supported BC process |
| Advance request | advance_request | Application operational layer | Accounting in Employee Ledger Entry if confirmed |
| Advance application | advance_allocation + BC application reference | Application reconciliation | BC authoritative accounting application |
| Approval matrix | rule_set / rule_definition + approval tables, or native BC workflow where sufficient | Application unless native workflow is selected | Native workflow where used |
| Participants | Native BC feature if usable and fit for purpose; otherwise application source data | Depends | Depends |

## 10A. Microsoft Capability Gap and Provider Decision Matrix

The purpose of this matrix is not to decide that Opsmeld should replace
BC. It defines where canonical setup must exist in Opsmeld and where
execution can be delegated to BC.

**Native BC setup we should mirror into the canonical model.** Microsoft
currently documents native setup for Expense Categories, Subcategories,
Payment Methods, Expense Locations, Expense Groups, Expense Management
Rules, Employee/Expense Posting Groups, Approval Workflow, Number Series,
exchange-rate policy, cash advances, report grouping and rounding,
mandatory receipt/merchant controls, and Expense User/Employee linkage.

Recommendation: do not duplicate these as separate Opsmeld-specific
concepts such as `opsmeld_category` and `microsoft_category`. Instead,
use one canonical `setup_value` and a `provider_mapping` to Microsoft BC.

**Capability where Opsmeld must provide additional setup today.** These
are the areas where the product needs a richer canonical model than the
currently documented native Expense setup: India GST/ITC assessment, TDS
assessment/routing, payroll tax treatment, rule/version provenance,
employee multi-project assignments, semantic Cost Center/Department
mapping, flexible Project Dimension/Job/Both mapping, configurable DOFA
grade/band + named override authority, compliance deadlines/sweeps,
advanced duplicate/fraud policy, and application-side
reconciliation/idempotency configuration.

**Decision rule.** For every capability, ask three separate questions:

1. Can Microsoft execute it natively today?
2. Can Microsoft expose enough configuration/API to safely synchronize it?
3. Does Opsmeld need richer semantics or India-specific behavior than BC
   provides?

The provider mode is then selected from the answers. This avoids both
extremes: hard-coding Microsoft as the only architecture, or
unnecessarily rebuilding functionality that BC already provides.

**Example: future Microsoft rollout.** If Microsoft later adds India GST
configuration:

```
Current:
  GST / ITC → OPSMELD_NATIVE

Future:
  Microsoft adds native India GST support
        ↓
  compare semantic capability
        ↓
  configure provider_mapping
        ↓
  synchronize canonical rules where compatible
        ↓
  HYBRID or MICROSOFT_NATIVE
```

No historical `expense`, `expense_allocation`, `compliance_assessment`,
or `approval_decision` records need to change.

## 10B. Configuration Ownership and Setup Location

All expense-management setup must exist first in the Opsmeld canonical
configuration model. The system must never make the current Microsoft BC
schema the domain model. For each capability, Opsmeld stores the
canonical configuration and records how that configuration is executed
for the customer/company.

Each capability has a provider mode: `MICROSOFT_NATIVE`,
`OPSMELD_NATIVE`, `HYBRID`.

The provider mapping determines whether a canonical configuration is
synchronized to a BC-native setup, evaluated by Opsmeld, or split across
both systems.

### 10B.1 Where each configuration is created

| Configuration | Created / maintained in Opsmeld | Optional/required BC mapping | Execution owner |
|---|---|---|---|
| Company / BC company connection | Yes | BC company/environment reference | Opsmeld integration |
| Expense categories | Yes — canonical | Map to BC Expense Category/Subcategory where supported | Hybrid / BC |
| Payment methods | Yes — canonical | Map to BC Payment Method where supported | Hybrid / BC |
| Expense groups | Yes — canonical | Map to BC Expense Group where supported | Hybrid / BC |
| Expense locations / business locations | Yes — canonical | Map to BC Location where appropriate | Hybrid |
| Receipt requirement | Yes | Map to BC rule if supported | Opsmeld / Hybrid |
| Merchant requirement | Yes | Map to BC rule if supported | Opsmeld / Hybrid |
| Spending / expense policy | Yes | Map to BC Expense Management Rule where supported | Opsmeld / Hybrid |
| Cost center | Yes | Map semantic attribute to configured BC Dimension Code/Value | Opsmeld mapping + BC posting |
| Department | Yes | Map semantic attribute to configured BC Dimension Code/Value | Opsmeld mapping + BC posting |
| Project | Yes | Dimension / Job / Both provider mapping | Opsmeld mapping + BC posting |
| Job task | Yes where Job is used | Map to BC Job Task | Hybrid |
| Billable customer | Yes | Dimension or Job customer mapping | Hybrid |
| Trip / assignment | Yes | Optional BC dimension | Opsmeld |
| Employee → project/job eligibility | Yes | BC Job/Job Task validation where available | Opsmeld |
| Approval policy / DOFA | Yes | Map compatible rules to BC Workflow/Approval User Setup where useful | Opsmeld / Hybrid |
| Grade / band | Yes | Map to customer HR/employee data if available | Opsmeld |
| Named override authority | Yes | BC user/employee mapping where applicable | Opsmeld / Hybrid |
| Advance policy | Yes | BC payment/ledger mechanism where applicable | Opsmeld policy + BC accounting |
| GST treatment | Yes | Map to BC tax setup where supported | Opsmeld / Hybrid |
| ITC eligibility rules | Yes | Optional BC tax outcome mapping | Opsmeld |
| TDS rules | Yes | AP/BC tax-process mapping where supported | Opsmeld / Hybrid |
| Payroll/perquisite rules | Yes | Payroll handoff mapping | Opsmeld + Payroll |
| Receipt-less thresholds | Yes | No dependency on BC | Opsmeld |
| Duplicate detection rules | Yes | No dependency on BC | Opsmeld |
| Compliance deadlines / sweeps | Yes | No dependency on BC | Opsmeld |
| Audit / evidence retention policy | Yes | BC references only | Opsmeld |
| Currency / conversion policy | Yes | Map BC currency/exchange-rate identifiers | Hybrid |
| Numbering / external reference policy | Yes | Map to BC Number Series where used | Hybrid |

Rule: Admin configures the business rule in Opsmeld. A provider adapter
then determines whether that configuration is mirrored into BC, executed
in Opsmeld, or executed jointly.

### 10B.2 Provider mapping table

A generic `provider_mapping` record must be available for any setup item
that can be represented differently by Microsoft BC or Opsmeld.

```
provider_mapping
-------------------------
provider_mapping_id PK
tenant_id FK
bc_company_id FK
entity_type
opsmeld_entity_id
provider_type              -- MICROSOFT_BC / OPSMELD
provider_object_type       -- Dimension / Job / ExpenseCategory / Workflow / ...
provider_object_id
provider_object_code
mapping_direction           -- OUTBOUND / INBOUND / BIDIRECTIONAL
sync_mode                   -- MANUAL / EVENT / SCHEDULED
status
valid_from
valid_to
last_synced_at
created_at
updated_at
```

The canonical Opsmeld record remains stable even if the provider
representation changes.

### 10B.3 Setup resolution at transaction time

The configuration used by a transaction is resolved in this order unless
a specific configuration overrides it:

```
Explicit transaction selection
        ↓
Trip / project / report context
        ↓
Employee assignment/default
        ↓
Department / cost-center default
        ↓
Company default
```

The resolved result is copied into the transaction/allocation snapshot
so historical records do not change when administrator setup changes
later.

### 10B.4 Employee setup for multiple projects/jobs

An employee must not have a single `project_id` field.

Use:

```
employee_mapping_assignment
-------------------------
assignment_id PK
employee_id FK
mapping_type              -- PROJECT / JOB / COST_CENTER / DEPARTMENT / ...
mapping_value_id FK
bc_job_no
bc_job_task_no
is_default
is_primary
valid_from
valid_to
allocation_allowed
approval_context_allowed
created_at
updated_at
```

An employee may therefore have multiple simultaneous project/job
assignments.

Example:

```
Rahul
 ├─ Project Alpha / J-1001 / TRAVEL / Default
 ├─ Project Beta  / J-1002 / TRAVEL
 └─ Project Gamma / J-1003 / CLIENT
```

If an expense can legitimately belong to multiple projects,
`expense_allocation_mapping` stores multiple allocations rather than
forcing one project at employee level.

## 10C. Reference Workflow 1 — Conversational Advance Request → BC Journal → Outstanding

This is the primary employee experience for the first reference
implementation. Rahul does not open a form. He communicates naturally
through Teams; the same domain workflow can be invoked from Outlook.

### 10C.1 Step 0 — Administrator configures the company in Opsmeld

The administrator establishes the canonical configuration in Opsmeld
before employees can submit advances.

Created/maintained in Opsmeld: Company / BC company connection, Expense
categories and subcategories, Advance policy and limits, Receipt /
self-declaration policy, Cost Center semantic mapping, Department
semantic mapping, Project / Job mapping, Employee-to-project/job
assignments, DOFA / Approval policy, Delegation / override authority,
GST / ITC policy, TDS policy, Payroll / perquisite policy, Duplicate /
fraud rules, Compliance deadlines, Provider selection and BC mappings.

Example Project Alpha setup:

```
Opsmeld Project = PROJECT-ALPHA
Provider Mode = HYBRID
BC Dimension Code = PROJECT
BC Dimension Value = ALPHA
BC Job No. = J-1001
Default Job Task = TRAVEL
```

Cost Center and Department are semantic concepts; the administrator
selects the actual BC Dimension Code used by the customer. The system
must never assume Global Dimension 1 or Global Dimension 2.

### 10C.2 Step 1 — BC reference data is synchronized into Opsmeld

Before Rahul starts, Opsmeld has a synchronized local projection of the
BC data required by the Expense experience: Employee, Manager/hierarchy,
Projects/Jobs/Job Tasks, Dimensions/Dimension Values, Locations/GST
registration references, Expense Categories, Payment Methods, Customers,
other provider reference data required by configured capabilities.

This is reference-data projection, not duplicate ownership. BC remains
the source of truth for BC-owned master data.

Normal update path:

```
BC change
  ↓
Webhook/change notification where supported
  ↓
Fetch changed record
  ↓
Update Opsmeld projection
```

Scheduled reconciliation remains the backstop. If a webhook is
unavailable for a specific entity, Opsmeld uses scheduled/delta
synchronization and can also refresh the relevant record on demand
during a critical workflow.

### 10C.3 Step 2 — Rahul sends a natural-language request in Teams

Rahul writes to the Opsmeld Expense bot/chat in Teams:

> I need an advance of ₹30,000 for Project Alpha as I need to go to
> Mumbai for a client visit from 10th to 14th September.

Teams provides the authenticated sender identity. Opsmeld resolves it to
Rahul:

```
Teams User ID
   ↓
Opsmeld employee_id
   ↓
BC Employee No.
```

The message is stored in `interaction`.

### 10C.4 Step 3 — Opsmeld recognizes the intent

The conversational layer classifies the request: `Intent =
ADVANCE_REQUEST`. It extracts:

```
Amount          = ₹30,000
Currency        = INR
Project         = Project Alpha
Purpose         = Mumbai client visit
Travel Start    = 10-Sep-2026
Travel End      = 14-Sep-2026
```

Each extraction is stored in `interaction_extraction` with confidence
and model/version metadata.

Important control: Opsmeld does not immediately treat natural language
as an approved financial request. It first validates and, where
necessary, asks Rahul to confirm or complete missing information.

### 10C.5 Step 4 — Opsmeld validates the request

The Expense engine resolves the extracted information against canonical
setup and synchronized BC reference data.

Example:

```
Rahul active?                  YES
Project Alpha active?          YES
Rahul assigned to Alpha?       YES
Advance allowed for Rahul?     YES
₹30,000 within advance limit?  YES
Overdue advance blocking?      NO
Mandatory information present? YES
```

If something is missing, the bot asks only for that information.

Example:

> What is the expected date by which you will submit the expenses for
> settlement?

Rahul: 20 September.

The interaction remains `NEEDS_INFO` until the required information is
available.

### 10C.6 Step 5 — Handle project ambiguity

Rahul may be assigned to several projects. If the message does not
uniquely identify the project, Opsmeld must not silently choose one.

Example response:

> Which project should this advance be charged to? Alpha / Beta / Gamma

Rahul selects Alpha. The system then resolves the canonical project
mapping:

```
Project Alpha
   ├── BC Dimension = PROJECT / ALPHA
   ├── BC Job       = J-1001
   └── Job Task     = TRAVEL
```

### 10C.7 Step 6 — Ask Rahul for confirmation

Once all mandatory fields are resolved, Opsmeld presents a concise
confirmation card in Teams:

```
ADVANCE REQUEST
Amount:            ₹30,000
Project:           Alpha
Purpose:           Mumbai client visit
Travel:            10–14 Sep 2026
Expected Settlement: 20-Sep-2026
[ Submit for Approval ] [ Edit ] [ Cancel ]
```

Rahul clicks Submit for Approval or confirms through chat. Only after
this confirmation does Opsmeld create the formal `advance_request` in
`PENDING_APPROVAL` state.

### 10C.8 Step 7 — Create the Advance Request

Opsmeld creates:

```
Advance Request AR-000123
---------------------------
Employee             Rahul
Requested Amount     ₹30,000
Currency             INR
Project              Alpha
Purpose              Mumbai client visit
Travel Start         10-Sep-2026
Travel End           14-Sep-2026
Expected Settlement  20-Sep-2026
Source Channel       Teams
Source Interaction   <interaction_id>
Status               PENDING_APPROVAL
```

The request also receives the resolved mapping snapshot and relevant
policy/configuration versions.

### 10C.9 Step 8 — Find Rahul's advance approver

Opsmeld evaluates the current effective DOFA/approval policy:

```
Employee Grade = G5
Department     = Consulting
Advance Type   = Travel
Amount         = ₹30,000
Project        = Alpha
```

Example policy result:

```
₹25,001 – ₹100,000
→ Rahul's Manager
→ Finance Head
```

The resolved route is stored in `approval_route` / `approval_instance`.

### 10C.10 Step 9 — Approver receives a filled approval form in Teams/Outlook

Anita receives a Teams approval card (or the equivalent Outlook
actionable message):

```
┌──────────────────────────────────────────────┐
│ ADVANCE REQUEST — Rahul                      │
│                                              │
│ Amount       ₹30,000                         │
│ Project      Alpha                           │
│ Purpose      Mumbai Client Visit             │
│ Travel       10–14 Sep                       │
│ Settlement   20 Sep                          │
│                                              │
│ [ APPROVE ] [ REJECT ] [ CHANGE AMOUNT ]    │
└──────────────────────────────────────────────┘
```

The approval action is authenticated using the approver's Teams/Outlook
identity and resolved to the configured Opsmeld approver identity.

### 10C.11 Step 10 — Approve, reject, or change amount

**Approve.** Anita selects Approve. The decision is stored with
approver, timestamp, policy version, and route step. If Finance approval
is required, the request moves to the next stage.

**Reject.** Rejection requires a reason.

```
Decision       = REJECTED
Reason Code    = OVER_BUDGET (example)
Comments       = ...
Approver       = Anita
Timestamp      = ...
```

Rahul receives a Teams notification:

> Your advance request of ₹30,000 for Project Alpha was rejected by
> Anita. Reason: exceeds approved travel budget.

The request remains in history as `REJECTED`.

**Change amount.** If Anita changes the amount to ₹25,000:

```
Requested Amount = ₹30,000
Approved Amount  = ₹25,000
Decision         = APPROVED_WITH_CHANGE
Changed By       = Anita
Reason           = ...
```

The revised amount is re-evaluated against the approval policy if the
change crosses an approval threshold or otherwise changes the required
route.

Rahul receives: "Your advance request of ₹30,000 was approved for
₹25,000."

### 10C.12 Step 11 — Create BC Payment Journal, but do not post

When all required approvals are complete, Opsmeld creates an unposted BC
Payment Journal instruction/reference.

```
Advance Request AR-000123
       ↓
Approved Amount = ₹25,000
       ↓
Create BC Payment Journal
       ↓
Status = AWAITING_FINANCE
```

The journal contains the required BC accounting information and
configured dimensions. The Opsmeld Advance ID is stored as the
correlation/reference key where the BC posting surface permits it.
Opsmeld does not automatically post the journal.

### 10C.13 Step 12 — Accountant processes the BC journal

Finance receives a Teams/Outlook notification:

> Advance AR-000123 for Rahul has been approved and a Payment Journal
> has been created in Business Central. Please review and post.

The accountant reviews the journal in BC and performs the company's
normal accounting/payment controls. Physical bank transfer, cheque, or
payment-run handling remains the accountant's responsibility in the
initial product. The accountant posts the journal in BC.

### 10C.14 Step 13 — Opsmeld detects the BC posting

The BC integration detects that the correlated journal has been posted.

```
BC Journal = POSTED
       ↓
Opsmeld updates Advance Request
       ↓
Accounting Status = POSTED
Advance Status    = OUTSTANDING
```

BC remains authoritative for the actual accounting balance. Opsmeld
stores the BC Employee Ledger reference and expected outstanding amount.

Initial product assumption: `JOURNAL_POSTED` is sufficient to move the
advance into `OUTSTANDING`. Opsmeld does not claim to have independently
verified that Rahul physically received the cash.

### 10C.15 Step 14 — Notify Rahul

> Your advance for Project Alpha has been processed for ₹25,000 and the
> accounting entry has been posted. Finance has completed the accounting
> processing for this advance.

The wording should not claim bank receipt unless a future payment/bank
integration explicitly confirms it.

### 10C.16 Step 15 — Rahul submits expenses later

During the Mumbai trip, Rahul can continue to submit receipts through
Teams/Outlook/app without creating a report immediately. The captured
expenses are linked to the project/trip/advance context where available.

At settlement time:

```
Approved expenses < advance
    → employee recovery
Approved expenses = advance
    → close advance
Approved expenses > advance
    → apply advance + reimburse difference
```

The actual accounting application/recovery is reconciled to BC.

### 10C.17 Conversation-to-accounting trace

For auditability, the complete chain is retained:

```
Teams Message
   ↓
Interaction
   ↓
Intent / Entity Extraction
   ↓
User Confirmation
   ↓
Advance Request
   ↓
Approval Instance / Decisions
   ↓
BC Journal Creation
   ↓
BC Journal Posting
   ↓
Advance Outstanding
   ↓
Expense Report / Settlement
```

This allows Finance or an auditor to answer not only what was posted,
but also how the original request entered the system and who confirmed
each decision.

### 10C.18 Outlook follows the same domain workflow

The same process works if Rahul sends an Outlook message instead of
Teams:

```
Outlook message
   ↓
Identity resolution
   ↓
Intent = ADVANCE_REQUEST
   ↓
Entity extraction
   ↓
Validation / clarification
   ↓
Confirmation or actionable message
   ↓
Advance Request
   ↓
Approval in Teams or Outlook
   ↓
BC Payment Journal
```

Teams and Outlook therefore share the same `CreateAdvanceRequest` domain
operation; they do not implement separate advance business logic.

### 10C.19 Optional future provider: Microsoft Expense Agent

If Microsoft later provides an India-capable Expense Agent experience,
it can become another channel/provider without changing the canonical
`advance_request` or approval model. The integration only changes at the
channel/provider adapter layer.

## 10D. Advance processing control and responsibility boundary

The advance workflow intentionally stops short of bank/payment
confirmation. The responsibility boundary is:

| Event | Owner | Opsmeld treatment |
|---|---|---|
| Advance requested | Employee / Opsmeld | Create request |
| Business approval | Approver | Record approval decision |
| BC journal creation | Opsmeld | Create/reference unposted BC journal |
| Journal review | Finance/AP | Human accounting control |
| Journal posting | Finance/AP in BC | Detect/store BC posted status |
| Physical transfer / cheque / payment run | Finance/AP | Out of scope unless integrated |
| Advance outstanding balance | BC | BC is accounting authority |
| Expense settlement | Opsmeld + BC | Create/application relationship and reconcile |

Design rule: `JOURNAL_POSTED` is sufficient for Opsmeld to move the
advance into `OUTSTANDING` for settlement. `CASH_RECEIVED` is
deliberately not a required state in the initial product.

If a future bank or payment integration is added, it should be
implemented as an optional provider capability without changing the core
Advance Request model.

## 10E. Reference Workflow 2 — Conversational Expense Submission → Review → Approval → BC Posting → Advance Settlement

This workflow describes how an employee submits expenses through
Teams/Outlook without opening a traditional expense form first. The
conversational channel is only the intake surface; the resulting expense
is created in the canonical Opsmeld expense domain and follows the same
policy, compliance, approval, accounting and reconciliation process
regardless of channel.

### 10E.1 Scenario

Rahul has completed his Mumbai client visit for Project Alpha. He
previously received a ₹30,000 travel advance. During the trip he paid
some expenses personally and has receipts for each expense.

Example expenses:

```
Hotel             ₹14,160
Taxi               ₹2,000
Client dinner      ₹5,900
--------------------------
Total             ₹22,060
```

The design assumes the advance is already in `OUTSTANDING` status
because the approved BC Payment Journal was posted by Finance.

### 10E.2 Step 1 — Rahul submits an expense naturally in Teams

Rahul sends a message to the Opsmeld Expense bot/chat in Teams:

> I spent ₹14,160 on the hotel in Mumbai for Project Alpha. Here is the
> bill.

He attaches the hotel receipt/photo. Teams provides the authenticated
sender identity and the attachment metadata.

Opsmeld records the interaction before creating the expense transaction:

```
interaction
-------------------------
channel = TEAMS
sender = Rahul
intent = EXPENSE_CAPTURE
external_message_id = ...
attachment_count = 1
received_at = ...
```

The original message and source file remain linked to the expense for
auditability.

### 10E.3 Step 2 — Intent and entity recognition

The conversational intake layer identifies:

```
Intent              = EXPENSE_CAPTURE
Expense Type         = Hotel
Amount               = ₹14,160
Expense Date         = extracted from receipt
Vendor               = extracted from receipt
Project              = Project Alpha
Purpose              = Mumbai client visit
Payment/Funding      = Employee Paid (initial proposal)
Receipt               = Present
```

The extraction result is stored separately from the final approved
business values:

```
interaction_extraction
-------------------------
field_name
extracted_value
confidence
confirmed_by_user
confirmed_at
```

This allows an AI extraction to be corrected without losing the
original interpretation.

### 10E.4 Step 3 — Resolve Rahul and the project

Opsmeld resolves the Teams identity to the Opsmeld employee and BC
Employee reference. It then resolves Project Alpha using the canonical
mapping and the synchronized BC reference-data projection:

```
Opsmeld Project = PROJECT-ALPHA
BC Dimension Code = PROJECT
BC Dimension Value = ALPHA
BC Job No. = J-1001
Job Task = TRAVEL
```

Rahul has multiple active project assignments. If the message contained
enough context to identify Alpha, Opsmeld uses that context. If more
than one eligible project remains possible, Opsmeld asks Rahul to select
the project rather than guessing.

### 10E.5 Step 4 — Determine funding/reimbursement type

The conversational layer proposes Employee Paid because Rahul said he
spent the money and no corporate-card/company-paid source is identified.

Opsmeld should distinguish:

```
Funding Source       = EMPLOYEE
Settlement Method    = ADVANCE_OFFSET / REIMBURSEMENT / ...
```

For the current scenario, the employee-funded expense will ultimately be
settled against Rahul's outstanding advance.

The application should not immediately deduct from the advance merely
because the expense was captured. Settlement occurs only after the
expense is approved and becomes eligible for posting/application.

### 10E.6 Step 5 — Validate receipt and extracted data

Opsmeld evaluates the receipt:

```
Receipt Present              YES
OCR Confidence               0.97
Vendor Identified            YES
Expense Date Identified      YES
Amount Identified            YES
Tax Identified               YES
Duplicate Risk               LOW
```

If critical information is missing or confidence is below the
configured threshold, Rahul receives a clarification request such as:

> I could not reliably read the invoice date. Please confirm the
> expense date.

The expense remains in `NEEDS_REVIEW` until sufficient data is
available.

### 10E.7 Step 6 — Category, coding and mapping resolution

Opsmeld determines the expense category: `Category = Hotel`. Then it
resolves the required coding using configured precedence:

```
Explicit employee selection
        ↓
Trip / project / report context
        ↓
Employee project assignment/default
        ↓
Department / Cost Center default
        ↓
Company default
```

The resulting BC mapping is stored as an immutable transaction-time
snapshot:

```
expense_allocation_mapping
-------------------------
Cost Center = CC-100
Department  = Consulting
Project     = Alpha
BC Dimension PROJECT = ALPHA
BC Job      = J-1001
Job Task    = TRAVEL
```

This snapshot does not change if the administrator later changes
Project Alpha's mapping.

### 10E.8 Step 7 — Compliance and policy evaluation

Opsmeld runs the configured rules before submission.

```
Receipt requirement       PASS
Category limit             PASS
Project coding             PASS
GST invoice                PASS
GSTIN                      PASS/REVIEW
ITC                         ELIGIBLE / BLOCKED / NO / REVIEW
TDS                         NOT APPLICABLE / REVIEW
Payroll treatment           NOT APPLICABLE / REVIEW
Duplicate risk              LOW
Policy exception             NONE
```

Every material rule decision is versioned: Rule Set, Rule Version,
Decision, Reason Code, Input Snapshot, Decision Timestamp, Override /
Reviewer.

### 10E.9 Step 8 — Rahul confirms the expense

When the extracted information is sufficiently deterministic, Opsmeld
presents a filled summary in Teams:

```
EXPENSE CAPTURE
-----------------------------
Hotel – Mumbai
Amount          ₹14,160
Date            12-Sep-2026
Project         Alpha
Payment         Employee Paid
Receipt         Attached
GST             ₹2,160
[ SUBMIT ] [ EDIT ] [ CANCEL ]
```

Rahul selects Submit. This confirmation creates/activates the formal
Opsmeld expense record.

If the information was already explicitly provided and the configured
policy permits deterministic creation without a second confirmation,
the confirmation step may be skipped; however, this should be a
configuration decision, not an accidental behavior of the AI layer.

### 10E.10 Step 9 — Expense enters Rahul's pending-expense list

The expense becomes: `Expense Status = READY_FOR_REPORT`. Rahul can
continue capturing individual expenses without creating a report
immediately.

He then submits the taxi receipt ("Taxi ₹2,000 for Project Alpha.
Receipt attached.") and the dinner receipt ("Client dinner ₹5,900 for
Project Alpha. Receipt attached."). Opsmeld processes each as an
independent expense.

The employee's pending list becomes:

```
Mumbai Client Visit
-----------------------------
Hotel             ₹14,160
Taxi               ₹2,000
Client Dinner      ₹5,900
-----------------------------
Pending Total     ₹22,060
```

### 10E.11 Step 10 — Rahul creates the Expense Report conversationally

Rahul can say: "Submit my Mumbai trip expenses for reimbursement."
Opsmeld interprets: `Intent = EXPENSE_REPORT_SUBMISSION`. It finds
Rahul's pending eligible expenses and proposes a report:

```
Expense Report
-----------------------------
Employee = Rahul
Trip     = Mumbai Client Visit
Project  = Alpha
Expenses = 3
Total    = ₹22,060
Advance  = ₹30,000
```

Rahul reviews the report and selects Submit Report. The system then
creates `expense_report` and `expense_report_line`, and moves the report
to `PENDING_APPROVAL`.

### 10E.12 Step 11 — Recalculate policy and advance eligibility at report submission

The report-level process rechecks rules that depend on the complete
report, including: total amount thresholds; monthly employee limits;
duplicate expenses across the report; receipt completeness;
project/job coding completeness; advance settlement eligibility; report
submission deadlines; policy exceptions.

This is separate from the line-level checks performed when each expense
was captured.

### 10E.13 Step 12 — Determine the approval route

Opsmeld evaluates the active approval policy using the transaction
snapshot and employee configuration:

```
Employee       = Rahul
Grade          = G5
Department     = Consulting
Category       = Travel
Report Total   = ₹22,060
Project        = Alpha
```

The matching DOFA rule generates an approval route, e.g. Manager →
Finance. The approval instance records the policy and rule versions used
so that later policy changes do not rewrite history.

### 10E.14 Step 13 — Approver receives a filled approval card

```
EXPENSE REPORT — RAHUL
--------------------------------
Mumbai Client Visit
Project: Alpha
Hotel             ₹14,160
Taxi               ₹2,000
Client Dinner      ₹5,900
--------------------------------
Total             ₹22,060
Advance           ₹30,000
Expected Recovery  ₹7,940
[ APPROVE ] [ REJECT ] [ SEND BACK ]
```

The approver can inspect receipts and exception information before
deciding. For SEND BACK, a reason is required and Rahul receives the
correction request in Teams.

### 10E.15 Step 14 — Approval result

If approved: `Expense Report = APPROVED`. If rejected: `Expense Report =
REJECTED`, and Rahul receives the decision and reason.

If rejected, expenses remain available for correction/resubmission
according to the configured policy. The original report version and
decision history remain immutable.

### 10E.16 Step 15 — Calculate settlement against the advance

After report approval:

```
Outstanding Advance = ₹30,000
Approved Expenses   = ₹22,060
Difference           = ₹7,940
```

Therefore: `Settlement Result = EMPLOYEE_RECOVERY`, `Recovery Amount =
₹7,940`.

Opsmeld creates the settlement relationship but does not create a
second accounting ledger. BC remains authoritative for the employee's
accounting balance.

If instead Approved Expenses > Advance, the result is
`EMPLOYEE_REIMBURSEMENT` for the difference. If equal, `FULLY_SETTLED`
with a zero difference.

### 10E.17 Step 16 — Create BC accounting instruction

Once the report and settlement are approved, Opsmeld generates the
appropriate BC accounting instruction through the configured provider.
The exact mechanism depends on the BC SME decision:

```
MICROSOFT_NATIVE
    → use supported native Expense Management posting surface
OPSMELD / JOURNAL
    → create the supported BC journal/document needed to produce
      the final accounting result
HYBRID
    → use BC native components for the accounting portion while
      Opsmeld retains policy/compliance/workflow evidence
```

Opsmeld does not directly write posted ledger entries.

### 10E.18 Step 17 — Finance posts the accounting transaction

Where the configured process requires accountant control, the
accounting document/journal remains unposted until Finance reviews it.
Finance verifies: Employee, Expense accounts, Dimensions, Project / Job,
GST / tax treatment, Settlement amount, Posting date. Finance then posts
the accounting document in BC.

The accountant's physical payment/recovery processes remain outside the
initial Expense Agent scope unless separately integrated.

### 10E.19 Step 18 — Opsmeld reconciles the posted result

Opsmeld receives or detects the BC posting result through the configured
synchronization mechanism. It matches the BC transaction using stable
provider references/idempotency keys.

```
Opsmeld approved expense amount = ₹22,060
BC posted expense amount       = ₹22,060
Opsmeld expected recovery      = ₹7,940
BC employee balance reduction  = ₹7,940
```

If the values agree: `Reconciliation Status = RECONCILED`. If they
differ: `Reconciliation Status = EXCEPTION`. Opsmeld must not silently
overwrite either side.

### 10E.20 Step 19 — Rahul receives the final status

> Your Mumbai expense report for ₹22,060 has been approved and
> processed. ₹22,060 has been settled against your ₹30,000 advance.
> ₹7,940 remains to be recovered under the company's advance policy.

If the report exceeded the advance, Rahul instead receives the
reimbursement amount. The message should use accounting status language,
not claim that Opsmeld independently verified bank movement.

### 10E.21 Complete conversational expense flow

```
Rahul in Teams / Outlook
        ↓
Natural-language expense message + receipt
        ↓
Identity resolution
        ↓
Intent recognition
        ↓
OCR / entity extraction
        ↓
Validate employee / project / policy / receipt
        ↓
Resolve Cost Center / Department / Project / Job
        ↓
GST / ITC / TDS / payroll assessment
        ↓
Duplicate / fraud checks
        ↓
Employee confirmation (when required)
        ↓
Expense = READY_FOR_REPORT
        ↓
Repeat for remaining receipts
        ↓
Rahul: "Submit my Mumbai trip expenses"
        ↓
Expense Report created
        ↓
Report-level validation
        ↓
DOFA / Approval Policy evaluation
        ↓
Teams / Outlook Approval
      ↙         ↓         ↘
  Reject     Send Back    Approve
     ↓            ↓          ↓
  Rahul       Rahul       Settlement
                             ↓
                    Advance Netting
                    / Reimbursement
                    / Recovery
                             ↓
                       BC Accounting
                             ↓
                       Finance Review
                             ↓
                         BC Posting
                             ↓
                       Reconciliation
                             ↓
                       Rahul Notification
```

### 10E.22 Key domain rules demonstrated by this workflow

- Message ≠ Expense. The conversational message is source evidence/
  input; the Expense record is the structured financial domain object.
- Expense ≠ Expense Report. An employee can capture expenses continuously
  and submit them later as a batch.
- Capture validation ≠ Report validation. Some controls run per expense
  and others only make sense once the whole report is assembled.
- Funding source ≠ settlement method. An employee-paid expense can
  ultimately be settled against an advance, reimbursed separately, or
  otherwise handled according to policy.
- Approval ≠ Posting. A business approval must not be treated as a
  successful accounting posting.
- BC posting ≠ proof of cash receipt. Where payment/bank integration is
  not configured, Opsmeld stops at the agreed accounting-status boundary.
- Historical mapping is immutable. Transaction-time mapping snapshots
  preserve the coding that was actually approved even if administrator
  setup changes later.
- AI decisions are auditable. Extraction, policy, compliance and routing
  decisions retain source inputs, confidence/rule versions and human
  overrides.
- Multiple projects are supported. The employee is not permanently bound
  to one project; each expense/report resolves the correct project/job
  context.
- Provider-independent domain model. The conversational expense workflow
  remains unchanged whether a capability is executed by Microsoft BC,
  Opsmeld, or a hybrid provider.

## 10F. Reporting, Status and Management Visibility

Reporting is a first-class capability of the Expense domain. The
reporting layer must use the canonical Opsmeld domain model and BC
reference/projection data, while financial facts that have been posted
remain attributable to the corresponding BC records.

The system should not create a separate duplicate "reporting master" for
every transaction. Operational dashboards and reports are derived from
the transactional tables, approved configuration versions, synchronized
BC reference data, and BC reconciliation results. For scale,
read-optimized projections/materialized views may be introduced later
without changing the domain model.

### 10F.1 Reporting principles

- Role-based visibility: Employees see their own expenses/advances;
  managers see their teams and approval workload; Finance/AP sees
  accounting, settlement, exception and reconciliation views; Admin sees
  setup, synchronization and policy health; authorized leadership sees
  aggregated company-level trends.
- Status must be explainable: Every dashboard number should be drillable
  to the underlying Expense, Expense Report, Advance Request, Approval
  Instance, Settlement, BC Reference and Audit Event where applicable.
- Operational status and accounting status are separate: e.g. an Expense
  Report can be `APPROVED` while BC posting is still `READY_TO_POST`, or
  an Advance can be `JOURNAL_POSTED` while Finance processing
  confirmation is still pending.
- Historical snapshots are preserved: changes to employee/project/
  mapping/policy setup do not rewrite historical reports.
- BC remains authoritative for posted accounting facts: Opsmeld reporting
  may show the latest synchronized BC status and reconciliation state and
  must identify when BC data is stale or synchronization is incomplete.
- No false certainty: the product must not label an advance as "cash
  received" unless a future payment integration provides that evidence.
  Under the current scope, `BC_JOURNAL_POSTED` is the accounting boundary
  and `FINANCE_PROCESSING_CONFIRMED` is an optional operational
  confirmation.

### 10F.2 Employee — "My Expense Status"

Rahul should be able to ask in Teams or Outlook: "What is the current
status of my expenses?" or "Show my Mumbai trip expense status."

Opsmeld should return a concise status card with drill-down
links/actions:

```
MY EXPENSE STATUS — RAHUL
Pending expenses              3
Submitted reports             1
Reports awaiting approval     1
Approved / awaiting posting   0
Reimbursement due             ₹5,000
Advance outstanding           ₹7,940
Expenses needing action       1

Mumbai Trip
  Expenses          ₹22,060
  Report             ER-000123
  Approval            Approved
  Advance            ₹30,000
  Settled against    ₹22,060
  Recovery           ₹7,940
  BC accounting       Posted
```

The employee view should answer: what expenses have I captured but not
submitted; which expenses require my action; which reports are waiting
for approval; which advance is outstanding; how much has been settled
against my advance; is reimbursement due or is recovery due; what is the
current accounting status; what exception or missing information is
blocking progress.

The employee must not need Finance terminology to understand the
status. Internal technical states can be shown as secondary detail.

### 10F.3 Manager — Team Expense and Approval Dashboard

A manager should be able to ask: "Show my team's pending expenses and
approvals."

| View | Purpose |
|---|---|
| Pending approvals | Reports/advances awaiting the manager's decision |
| Team expenses | Expenses captured/submitted by direct/authorized reports |
| Policy exceptions | Out-of-policy items requiring review |
| Missing receipts | Items blocked or requiring employee action |
| Outstanding advances | Team members with unsettled advances |
| Aging | Advances/reports approaching or exceeding policy thresholds |
| Project spend | Team expenses by project/job/cost center |
| Approval turnaround | Time from submission to decision |
| Rejected/returned items | Items needing correction or follow-up |

The manager should be able to drill from an aggregate ("Team pending
approvals = 7") down through a specific employee/trip → Expense Report →
Expense lines → receipt/policy/compliance evidence.

### 10F.4 Finance / AP — Accounting and Settlement Dashboard

Finance is the primary operational owner of the accounting handoff.

| View | Purpose |
|---|---|
| Approved / Ready to Post | Reports approved by business but not yet posted to BC |
| BC Journal Created | Journal instructions/references created by Opsmeld |
| Journal Posting Exceptions | Posting failures or unresolved BC references |
| Posted Expenses | Reports confirmed posted in BC |
| Advance Outstanding | Employee advances with remaining balance |
| Advance Aging | Outstanding advances by age and settlement date |
| Recovery Required | Under-spent advances requiring recovery |
| Reimbursement Due | Over-spent advances / employee reimbursements |
| TDS Review | Transactions requiring TDS decision/action |
| GST / ITC Review | Tax/compliance exceptions and overrides |
| Duplicate / Fraud Review | Suspicious transactions awaiting Finance action |
| Reconciliation Exceptions | Opsmeld vs BC differences |
| Finance Processing Confirmation | Items requiring accountant confirmation of normal payment handling |

Finance should be able to filter by company, employee, department, cost
center, project/job/job task, category, date range, reimbursement/
funding type, status, policy exception, GST/ITC status, TDS status,
advance status, posting status.

### 10F.5 Company / Leadership Reporting

Authorized leadership should receive aggregated views without exposing
employee-level information unless permitted. Core management reports:
Expense Spend (by month/department/cost center/project/category),
Advance Exposure (requested/approved/disbursed/outstanding/recovery
required), Policy Compliance (compliant/exceptions/rejected/overridden),
Approval Performance (volume/aging/turnaround by approval level), GST /
Tax Exposure (captured/ITC eligible/ITC blocked/unresolved), TDS
Exposure (flagged/resolved/routed to AP), Duplicate / Fraud Risk
(suspected/confirmed/false positive), Accounting Health (approved →
journal created → posted → reconciled).

The report layer must support both operational and periodic reporting.
An operational dashboard answers "what needs action now?" A periodic
report answers "what happened during the period?".

### 10F.6 Administrator — Configuration and Integration Health

Administrators need a different reporting layer focused on whether the
Expense environment is configured and synchronized correctly. Required
views: missing mandatory setup; active/inactive policy versions;
approval rules with no valid approver; employees with missing or
conflicting project assignments; projects/jobs that no longer exist in
BC; dimension values that have become inactive in BC; provider mappings
with no valid BC target; failed setup synchronization; stale BC
reference projections; webhook/subscription health where applicable;
scheduled synchronization failures; configuration changes by
administrator; capabilities using `OPSMELD_NATIVE`, `MICROSOFT_NATIVE`,
and `HYBRID`.

Example:

```
CONFIGURATION HEALTH
BC Reference Sync
  Employees             Healthy
  Projects              Healthy
  Dimensions            Warning — 2 stale
  Job Tasks             Healthy
Provider Mapping
  Cost Center            Valid
  Department             Valid
  Project → Job          3 unmapped
  GST ITC                Opsmeld Native
  Approval               Hybrid
```

### 10F.7 Conversational reporting

Reporting must also be accessible through the same conversational
channels used for transaction entry, e.g. "What's the status of my
Mumbai expense?" (employee), "What approvals are waiting for me?"
(manager), "Show all approved expenses waiting to be posted to BC."
(finance), "Which project mappings are broken?" (admin).

The conversational interface should translate these requests into
authorized report queries. It must respect role-based data access and
must not expose data outside the user's authorization scope.

### 10F.8 Reporting data model

The reporting layer should primarily derive results from existing domain
tables rather than duplicate every transaction into a reporting-specific
database.

| Object | Purpose |
|---|---|
| report_definition | Defines reusable report/dashboard/query metadata and authorization scope |
| report_favorite | Stores user/team saved report configurations |
| dashboard_definition | Defines role-specific dashboard widgets and layout metadata |
| report_snapshot | Optional persisted point-in-time report result for scheduled reporting or audit |
| report_delivery | Tracks scheduled report generation/delivery |
| report_access_policy | Controls who can view which reporting scopes |
| report_metric_definition | Canonical metric definition so measures such as "outstanding advance" are not implemented differently in different screens |

These are reporting configuration/control tables, not a replacement for
the transactional domain tables.

### 10F.9 Canonical metrics

The following metrics must have one centrally defined calculation each:
Pending Expense, Submitted Expense, Pending Approval, Approved / Not
Posted, Posted, Reimbursed, Recovery Required, Advance Outstanding,
Advance Overdue, Policy Exception, Compliance Exception, Posting
Exception, Reconciliation Exception, Approval Aging, Expense-to-Report
Aging, Advance-to-Settlement Aging.

For example, Advance Outstanding should be calculated from the
operational advance lifecycle plus the authoritative BC employee-ledger/
reconciliation state, not from an arbitrary dashboard-maintained balance.

### 10F.10 Reporting freshness

| Report | Target freshness |
|---|---|
| Employee expense status | Near real-time / latest known sync |
| Manager approval queue | Near real-time |
| Finance ready-to-post queue | Near real-time |
| BC posting/reconciliation status | Near real-time where supported + scheduled reconciliation |
| Advance aging | Latest synchronized state; refresh on demand available |
| Monthly/quarterly management reports | Scheduled / batch is acceptable |
| Configuration health | Near real-time for local setup; latest synchronized BC state for external setup |

Every screen displaying BC-derived information should expose a "last
synchronized at" timestamp or equivalent freshness indicator when
useful.

### 10F.11 Reporting and audit relationship

A report number must be explainable back to source records:

```
Monthly Expense = ₹12,40,000
        ↓
Department / Cost Center / Project breakdown
        ↓
Expense Reports
        ↓
Expenses / Allocations
        ↓
BC References
        ↓
BC Posted Entries
```

A compliance metric must similarly drill to the assessment and rule
version that produced it. A reporting discrepancy must therefore be
treated as a data/reconciliation issue, not silently corrected in the
report layer.

## 11. BC Expert Questions

**Reframed per §2.0 ("inspiration, not replication"):** this design does
not need to plug into BC's new 2026W1 Expense Report/Expense Line module
at all — it only needs to post a finished transaction via BC's
long-standing General/Payment Journal API. That means the questions
below split into a **default path that needs no Wave 1 / Expense Agent
access** (testable on any existing BC environment, including an
India-localized one on an older wave) and an **optional exploration**
that only matters if we later decide it's worth leveraging BC's newer
native module instead of the safe Journal fallback.

**Default path — testable today, no Wave 1 needed**
- **BC-11 (default)**: Confirm the General/Payment Journal API accepts
  the fields this design needs (amount, dimensions, employee reference,
  posting date) and actually posts to Employee Ledger Entry / G/L Entry
  as expected. This is old, stable BC functionality — testable on
  whatever BC access is already available.
- **BC-7 (default)**: If Employee Ledger Entry application isn't
  API-exposed (plausible per the sharpened note below), track
  advance-vs-settlement application-side and post only the *net*
  settlement amount as a plain journal line — a fallback consistent
  with FR-18's intent (FR-18 says not to duplicate BC's advance
  subledger if BC's own mechanics suffice; it doesn't itself spell out
  the net-journal-line mechanic, corrected per BC-expert re-review).
  Same Journal API as BC-11, no special access needed. **Residual risk
  to carry forward (per BC-expert re-review)**: if this fallback is
  used, the original advance disbursement's Employee Ledger Entry in BC
  stays permanently Open/unapplied from BC's own perspective, since
  nothing calls BC's Application API — BC-native employee-balance
  reports will diverge from the app's view indefinitely unless a human
  periodically applies it in the BC client. FR-58 (§6.10) now names this
  as an expected, structural divergence pattern, not an anomaly.
- **BC-1 (default) — partially resolved, one real question remains (per
  second BC-expert re-review)**: GST/ITC *computation* is
  `OPSMELD_NATIVE` regardless of BC's Expense Line tax engine, so that
  part needed no test. But standard BC API v2.0's `generalJournalLines`
  entity is generic (US/CA-style tax fields) — India localization
  fields (GST Group Code, HSN/SAC Code, GST Jurisdiction Type) live in
  the India localization app, and country localization apps often
  extend client *pages* without extending the corresponding API *page*.
  **New, testable-today, non-blocking-for-schema question**: does the
  Journal API accept India-GST-specific fields on a line, or only the
  BC client does? This determines whether GST detail can land
  structurally in BC's own ledgers (for BC-side GSTR-1/2A/3B filing) or
  has to stay in our own system with only a summary amount posted to
  BC — i.e., who owns GST-return prep: this tool, or BC directly. That
  ownership question needs an explicit answer from whoever owns GST
  filing before it's locked in either way.

**Optional exploration — only if pursuing BC's native Expense Report
module instead of the Journal fallback; needs Wave 1 access, and the
Expense Agent Copilot UI specifically is reported as excluded from
India in the current rollout (per §4's confidence note — aggregated
search, not primary-source-verified; re-check before it matters)**
- **BC-11 (native path)**: Does BC 2026W1's Expense Report/Expense Line
  expose a supported write-capable API that produces the expected native
  ledger behavior? New BC feature UI surfaces routinely ship 1–2 release
  waves ahead of their public API v2.0 write endpoints — confirming the
  feature works in the BC client sandbox is not evidence of a supported
  write API.
- **BC-7 (native path)**: Employee Ledger Entries (Table 5217) support
  Open/Application status in the BC client the same way Vendor/Customer
  Ledger Entries do, but the public API has historically exposed
  `employeeLedgerEntries` **read-only** in several BC versions, with no
  `applyEmployeeEntries`-equivalent write action — worth confirming if
  the native path is ever pursued, but not blocking given the default
  fallback above.
- **BC-1 (native path)**: Does native Expense Line participate in the BC
  GST/Tax engine at all? India GST/tax engine hooks have historically
  lagged non-core document types, and Expense Reports is a newer,
  HR-adjacent object rather than a core Purchase/Sales document — treat
  `OPSMELD_NATIVE` as the probable outcome regardless, so this is
  confirmatory, not gating.

Costing-method awareness (FIFO/Standard/Average) does not apply to this
domain — employee expense/reimbursement has no inventory costing
dimension — confirmed by BC-expert review, no action needed.

**Priority P1**
- BC-8: Can native Workflow conditions express the required category AND
  amount logic together, and can a grade/band lookup supplement manager
  hierarchy without a custom approval engine?
- BC-2: Confirm the mapping layer can discover/resolve the actual BC
  Dimension Code used for Cost Center and Department in each
  customer/company. What BC metadata/API should validate allowed
  Dimension Values?
- BC-3: Should billable/rebillable expenses use Job No./Job Task when
  Jobs is licensed?
- BC-4: Confirm BC Location with GST Registration No. as the appropriate
  branch-GSTIN resolution mechanism.
- BC-5/BC-6: If extensions are needed, what is the supported extension
  pattern for Expense Line/Report that remains safe across Expense Agent
  writes/upgrades?
- BC-9: Confirm Participants semantics and whether the feature is usable
  independently of the Copilot Expense Agent.
- BC-10: Is there an India-localization roadmap that would materially
  change this design?

## 12. Domain Expert Questions

**Reframed 2026-09-06 — D-1/D-2/D-3 are out of scope for Opsmeld to
decide, and closed as build blockers.** These are each customer's
Finance team's own policy decisions, not something Opsmeld's design or
internal Finance/Compliance should pre-answer with one global value —
different customers legitimately choose differently. The system's job
is to **support** each as configurable policy, not to enforce Opsmeld's
own answer:

- D-1 (advance recovery mechanism) → FR-14 already requires the system
  support an installment schedule (Payment of Wages Act constraint on
  *how* recovery can happen structurally); *which* mechanism a given
  customer uses is configured per tenant, not fixed by Opsmeld.
- D-2 (perquisite tax treatment) → FR-39 already requires the system
  distinguish reimbursement from allowance/perquisite and be
  regime-aware per employee; the customer's payroll/tax team supplies
  applicable limits and regime data.
- D-3 (GST blocked-credit override authority) → FR-27/FR-34 already
  require a configurable named override authority and a reason-coded
  override path; *who* holds it is each customer's DOFA, configured at
  onboarding, not an Opsmeld default.

What Opsmeld still owns: shipping sensible starting defaults/templates
as a convenience — but the authoritative answer for any deployment is
customer-configured, never Opsmeld's internal decision.

**Priority P0 (remaining)**
- D-4: Typical receipt-less internal-control thresholds by
  company/sector; explicitly confirm these are policy norms, not
  statutory minima.
- D-7: Threshold and routing policy for employee-mediated vendor
  payments that should go to AP for TDS handling instead of
  reimbursement.

**Priority P1**
- D-5: Advance-aging policy anchored to trip/project expected settlement
  date; validate 15/30/45-day review bands.
- D-6: DOFA structure including category, department, grade/band,
  amount, and named override authority.
- D-8: Monthly GST operational submission cutoff plus financial-year-end
  ITC sweep timing. The system should support both operational cutoffs
  and statutory time-bar awareness.

## 13. Non-functional / Control Requirements

### 13.1 Idempotency
Any externally initiated financial action must have a durable
idempotency key. A retry after timeout must first reconcile the prior
attempt.

### 13.2 Immutability
Posted financial facts and historical approval/compliance decisions are
immutable. Corrections create new linked records/events.

### 13.3 Multi-company isolation
Every business entity is scoped to `tenant_id` and `bc_company_id`. The
same employee identity may map to different BC Employee No. values
across companies.

### 13.4 Currency
Expense currency must be retained separately from reporting/settlement
currency. Exchange rate, rate date, and conversion result must be
captured when conversion occurs.

### 13.5 Auditability
Every material decision must answer: What was decided? Based on which
rule/policy version? Using which inputs? Who/what decided it? When? Was
it overridden? What was ultimately posted to BC?

### 13.6 Security
Receipt binary content and secrets must not be stored directly in
relational tables unless explicitly required. Store files in controlled
object storage and credentials in a secret/configuration service.

## 14. Posting and Reconciliation Contract

The integration should conceptually behave as:

```
Approved Report
      ↓
Canonical Posting Payload
      ↓
Stable Idempotency Key
      ↓
Posting Attempt
      ↓
BC API / Journal Mechanism
      ↓
BC Accounting Result
      ↓
BC Reference Mapping
      ↓
Reconciliation
```

Required reconciliation outcomes:

| Application expectation | BC observed result | Outcome |
|---|---|---|
| Not posted | Not found | Retry allowed |
| Not posted | Posted | Mark application as Posted; do not retry |
| Sent | Unknown | Reconciliation Required |
| Posted | Posted with matching reference | Reconciled |
| Posted | Amount/dimension mismatch | Exception |
| Advance outstanding | Employee ledger shows closed/different amount | Exception |

## 15. Accounting Treatment Matrix

This matrix is intentionally conceptual until BC-11 and BC-7 are
confirmed.

| Scenario | Expense funding | Employee settlement | Expected BC accounting result |
|---|---|---|---|
| Employee-paid expense | Employee | Reimbursement | Expense + employee payable/reimbursement |
| Company-paid expense | Company | None | Expense accounting without employee reimbursement |
| Corporate-card expense | Corporate Card | Card settlement | Expense + card/vendor settlement path |
| Advance-funded expense | Employee Advance | Advance application | Expense + application against employee advance |
| Expense > advance | Employee Advance + employee | Reimburse difference | Apply advance + employee payable for difference |
| Expense < advance | Employee Advance | Recover difference | Apply expense against advance + employee recovery |
| Split invoice | Mixed | Mixed | Itemized accounting/settlement by allocation |
| TDS-required vendor payment | Employee-mediated | AP/TDS path where policy threshold met | Route to supported AP/vendor tax process |

## 16. Risks and Decisions

- **R1 — Native BC capability may reduce custom scope.** If BC supports
  enough native expense/tax/approval/advance capability, some
  application tables become mapping/audit layers rather than primary
  workflow stores.
- **R2 — Native BC capability may be insufficient.** If Expense Report
  APIs cannot accept the required validated data, posting may need a
  journal-based route. This must not be hidden behind assumptions.
  Confirmed: this codebase has no BC write path today (§4A) — plan the
  posting layer as new engineering effort from day one, not as
  extending an existing write capability, regardless of how BC-11
  resolves.
- **R3 — Duplicate accounting risk.** Any retryable BC call without
  durable idempotency/reconciliation can create duplicate financial
  postings.
- **R4 — Compliance rule drift.** GST/TDS/payroll decisions without
  versioned rules and input snapshots become difficult to defend
  historically.
- **R5 — Two-system disagreement.** If compliance results are
  maintained outside BC while tax filing is performed directly from BC,
  a formal reconciliation/exception mechanism is required. Do not
  declare either system universally the "legal truth" without
  Finance/Tax ownership agreement.
- **R6 — Employee advance duplication.** Do not build an
  application-side monetary advance ledger until BC confirms that
  native Employee Ledger Entry/application mechanics cannot cover the
  accounting requirement.

## 17. Build Decision Gate

No implementation should start until the following are answered. Per
§2.0/§11's reframing, BC-11/BC-7/BC-1 are satisfied by their **default
path** (Journal API + `OPSMELD_NATIVE` GST) unless a deliberate later
decision is made to pursue BC's native Expense Report module instead —
so these no longer require Wave 1 / India-inclusion access to close:

- BC-11: Confirm the Journal API posting path (default) — no Wave 1
  needed.
- BC-7: Confirm advance-vs-settlement tracked application-side with net
  Journal settlement (default) — no Wave 1 needed.
- BC-1: GST/ITC computation resolved by default (`OPSMELD_NATIVE`), but
  confirm whether the Journal API accepts India GST-specific fields
  (GST Group Code, HSN/SAC, Jurisdiction Type) — determines whether GST
  detail can land in BC natively or must stay app-side with only a
  summary posted (see §11's sharpened BC-1 note).
- BC-8: Native approval conditions versus small supplemental grade/band
  lookup.
- Mapping ownership: Confirm the semantic-to-BC mapping model,
  validation source, and whether project mapping may use Dimension,
  Job/Job Task, or both.
- Tax ownership: Whether compliance assessment remains
  application-owned with reconciliation to BC, or required compliance
  attributes must also be persisted in BC.
- Accounting ownership: Confirmation that BC remains the source of
  truth for final posted financial amounts and ledger balances.

Once these decisions are confirmed, the remaining implementation design
should be derived from the approved architecture rather than creating
parallel BC-like objects in the application.

## 18. Engineering Blueprint Contract

This section folds the former v1.0 engineering requirements into this
blueprint so there is one authoritative specification. The
implementation team should not invent alternate domain objects or
integration semantics without updating this document.

### 18.1 Canonical domain-to-implementation traceability

Every material requirement must trace through the following chain:

```
Business Requirement
    ↓
Canonical Domain Object
    ↓
Database Table(s)
    ↓
Domain/API Operation
    ↓
Event / Integration Message (where applicable)
    ↓
Provider Adapter
    ↓
BC Object/API or Opsmeld-native execution
    ↓
Audit / Reconciliation Record
    ↓
Reporting Metric
```

The canonical Opsmeld domain remains provider-independent. BC table IDs,
API field names and Microsoft-specific identifiers belong in
provider/reference mapping structures, not in the core domain contract.

### 18.2 Persistence rules

All tenant/company-owned tables must include a company/tenant boundary
appropriate to the deployment model. Domain records must have immutable
internal primary keys; external BC identifiers are separate fields.

Common audit columns should be standardized across mutable tables: `id`,
`company_id`/`tenant_id`, `created_at`, `created_by`, `updated_at`,
`updated_by`, `version`/`row_version`, `status` (where applicable),
`deleted_at` (only where soft-delete is explicitly permitted).

Transaction records must not be physically deleted merely because the
user withdraws or cancels a request. State transitions and audit events
preserve history.

### 18.3 Core table groups

**Interaction / conversational intake**: `interaction`,
`interaction_extraction`, `interaction_action`. Purpose: retain the
source Teams/Outlook interaction, extracted fields, confidence,
confirmation and resulting domain action. `external_message_id` and
`external_conversation_id` provide idempotency and traceability.

**Expense lifecycle**: `expense`, `expense_allocation`, `expense_report`,
`expense_report_expense`, `receipt`/`source_evidence` (or equivalent
attachment store). A single expense can have multiple allocations.
Allocations carry the transaction-time mapping snapshot. A report groups
expenses; it is not the expense itself.

**Advance lifecycle**: `advance_request`, `advance_allocation`/
settlement linkage, `settlement`, `settlement_installment`. The
operational advance request is owned by Opsmeld. The accounting balance
remains in BC where the BC Employee Ledger Entry/application mechanism
is confirmed as suitable.

**Approval**: `approval_policy`, `approval_rule`,
`approval_rule_condition`, `approval_rule_action`, `approval_instance`,
`approval_step`, `approval_decision`. Configuration and runtime
execution are separate. A runtime approval captures the exact
policy/rule version used.

**Policy/compliance**: `policy`, `policy_version`, `policy_rule`,
`policy_condition`, `policy_action`, `compliance_assessment`,
`compliance_assessment_evidence`. GST/ITC, TDS, payroll/perquisite,
receipt and duplicate decisions are versioned and auditable.

**Mapping/configuration**: `setup_capability`, `setup_instance`,
`setup_version`, `setup_value`, `mapping_definition`, `mapping_value`,
`employee_mapping_assignment`, `provider_mapping`. Canonical business
semantics are mapped to Microsoft BC, Opsmeld or Hybrid provider
implementations.

**BC reference projection and synchronization**: `bc_entity_projection`,
`sync_state`, `sync_event`/`sync_error`. These are synchronized
projections/cache records, not authoritative copies of BC master data.

**Integration / accounting**: `bc_posting_instruction`,
`bc_posting_reference`, `external_operation`, `integration_event`,
`reconciliation_case`. These tables capture the durable boundary
between Opsmeld intent and BC execution.

**Exceptions and audit**: `exception_case`, `audit_event`,
`notification`. All business-critical exceptions and decisions use a
common framework.

### 18.4 Required key constraints and indexes

The exact DBMS syntax is implementation-specific, but the following
logical constraints are mandatory:

- `interaction`: unique on (provider, external_message_id) within the
  company/tenant.
- `provider_mapping`: unique for (company_id, capability, provider,
  canonical_key, effective_from) where the business rules require one
  active mapping.
- `employee_mapping_assignment`: prevent overlapping active assignments
  for the same employee, mapping type and assignment key unless
  explicitly marked multi-valued.
- `approval_policy`: unique version per policy code/company/effective
  period.
- `expense_report_expense`: prevent an expense from being attached
  twice to the same report unless the model explicitly supports
  revisions.
- `external_operation`: unique idempotency key per operation scope.
- BC projections: unique (bc_company_id, entity_type, bc_record_id).
- Transaction tables: indexes on employee, company, status, created
  date, approval status and BC reference IDs.

### 18.5 API/domain contract catalogue

The following domain operations are required. Exact HTTP/gRPC framework
is implementation-specific.

```
POST /interactions
POST /advance-requests
POST /advance-requests/{id}/confirm
POST /advance-requests/{id}/cancel
POST /approvals/{id}/decision
POST /expenses/capture
POST /expenses/{id}/confirm
POST /expense-reports
POST /expense-reports/{id}/submit
POST /expense-reports/{id}/withdraw
GET  /me/expenses/status
GET  /me/advances/status
GET  /manager/team-expenses
GET  /finance/expense-queue
GET  /reports/{report_definition}
```

Every command endpoint must define: authorization, validation,
idempotency behavior, state preconditions, success response, retry
semantics and stable error codes.

### 18.6 Conversational command contract

Teams and Outlook adapters must call the same domain operations. They
must not maintain separate approval, expense or advance business logic.

```
Channel message
    ↓
Identity resolution
    ↓
Intent classification
    ↓
Entity extraction
    ↓
Confidence/ambiguity check
    ↓
Validation against Opsmeld setup + BC projections
    ↓
Clarification / explicit confirmation if required
    ↓
Domain command
```

AI may extract/classify/propose. It may not independently approve,
override a policy, alter an approved accounting amount or post
financial records. Those actions require deterministic domain rules
and/or an authorized human decision.

### 18.7 BC integration contract

The Microsoft provider adapter must encapsulate: authentication, company
selection, API/entity mapping, read/write operations, webhook
subscription, polling, error translation and reconciliation.

For every supported BC object the implementation must document: BC
capability, BC entity/API, Direction (READ/WRITE/BOTH), canonical
Opsmeld object, field mapping, external key, supported operations,
change detection mechanism, failure semantics, reconciliation method.

No core domain table should require a direct foreign key to a Microsoft
BC table.

### 18.8 Idempotency and retry

All externally retriable commands must carry a durable idempotency key.
This is mandatory for: conversational message ingestion, expense
capture, report submission, approval decisions, BC journal creation and
other accounting instructions.

A timeout after a BC write must be treated as `UNKNOWN`, not
automatically as `FAILED`. The adapter must reconcile before retrying a
financial operation.

### 18.9 State-transition contract

The authoritative state machine for advances is:

```
REQUESTED
  ↓
UNDER_APPROVAL
  ├── REJECTED
  └── APPROVED
        ↓
    JOURNAL_CREATED
        ├── POSTING_EXCEPTION
        └── JOURNAL_POSTED
                ↓
            OUTSTANDING
                ├── PARTIALLY_SETTLED
                ├── RECOVERY_REQUIRED
                └── CLOSED
```

The authoritative state machine for expenses/reports must separately
distinguish capture, review, approval, posting and settlement. APPROVED
never means POSTED.

### 18.10 Approval decision contract

An approval decision must preserve: `approval_policy_id`,
`approval_policy_version`, `matched_rule_id`, route/step, approver,
delegate (if any), decision, `original_amount`, `approved_amount`
(where changed), `reason_code`, comments, `decided_at`.

Changing an amount is a distinct decision (`APPROVED_WITH_CHANGE`) and
must be auditable. Rejections and material changes require reasons
according to configured policy.

### 18.11 Configuration versioning

Policies, approval matrices, compliance rules and mapping definitions
are versioned. A transaction stores the policy/mapping versions used at
each material decision point. Later configuration changes do not
rewrite historical decisions.

### 18.12 Security and authorization

Authorization is enforced at domain/API level, not only in Teams/Outlook
UI. Minimum personas are: Employee, Manager/Approver, Finance/AP,
Payroll, Expense Administrator, Auditor/Read-only, Integration Service.

Data access must be scoped by company/tenant and, where required,
employee reporting hierarchy, department, cost center or designated
finance role. Receipt/tax/payroll evidence receives the same or
stricter access control as the underlying expense.

### 18.13 Notifications

Notifications are events/actions generated from domain state, not
ad-hoc messages embedded in business logic. Each notification should
record: recipient, channel, message/template key, source entity,
trigger event, delivery status, attempt count, `delivered_at`.

Teams/Outlook delivery failure must not roll back an already committed
financial transaction. Delivery is retriable and separately auditable.

### 18.14 Exception framework

All non-routine cases should use `exception_case`, including:
`MAPPING_EXCEPTION`, `POLICY_EXCEPTION`, `GST_EXCEPTION`,
`TDS_EXCEPTION`, `DUPLICATE_SUSPECTED`, `APPROVAL_EXCEPTION`,
`BC_POSTING_EXCEPTION`, `SYNC_EXCEPTION`, `RECONCILIATION_EXCEPTION`.

Each exception has severity, owner, status, resolution, timestamps and
evidence links.

### 18.15 Reporting architecture

Operational reporting may query the transactional domain directly at
first, but the data model must allow reporting projections/materialized
aggregates later. Reporting must never become a second system of
record.

Canonical metrics must have one definition and be drillable to the
underlying transaction/audit record. Examples include Pending Approval,
Advance Outstanding, Recovery Required, Ready for BC Posting, BC Posting
Exception, GST ITC Blocked, and Unreconciled.

### 18.16 Synchronization contract

BC reference data uses a hybrid synchronization model:

```
BC change notification/webhook where supported
          ↓
fetch changed entity
          ↓
update Opsmeld projection
          ↓
mark sync state

Scheduled delta/full reconciliation
          ↓
repair missed/stale changes
```

Webhook is a change signal, not the sole source of synchronization
truth. Each entity type has a configured freshness target.

### 18.17 Build decision gates

Implementation cannot proceed past the corresponding gate until the
following are resolved:

- **Gate A — BC accounting path**: Expense API vs journal API; exact
  supported posting method.
- **Gate B — Advance accounting**: confirm native Employee Ledger
  Entry/application behavior is sufficient so Opsmeld does not create a
  duplicate subledger.
- **Gate C — Tax/compliance ownership**: confirm which tax data must
  ultimately be visible inside BC for the customer's filing process.
- **Gate D — Native capability/provider matrix**: classify each
  capability as `MICROSOFT_NATIVE`, `OPSMELD_NATIVE` or `HYBRID`.
- **Gate E — Security and tenant isolation**: approve domain
  authorization and company-boundary model.

### 18.18 Blueprint completeness criterion

This blueprint is considered the complete candidate when the SME review
resolves all P0 questions and the implementation team can trace every
in-scope FR to a canonical domain object, table, API/domain command,
provider behavior, audit event and report metric. Low-level
framework/code decisions may remain implementation choices; business
ownership and integration semantics may not.

## Appendix A — Internal Review Changes Incorporated (v0.2 → v0.4)

The following previously identified corrections are incorporated into
the main design rather than left only as review notes:

- Employee Ledger Entry/application mechanics are treated as the first
  option for accounting advances; `advance_request` is operational only.
- Funding source and settlement method are explicitly separated.
- Approval is separated from posting success.
- Idempotency and unknown posting outcomes are explicit requirements.
- Actual expense reimbursement is separated from allowance/perquisite
  treatment.
- Compliance decisions are rule-versioned and retain input evidence.
- Sec 17(5) blocked ITC supports a controlled override path.
- Receipt-less expenses default to ITC No.
- Advance aging is anchored to expected settlement/trip end rather than
  generic AP aging only.
- Employee-mediated vendor cash payments can be routed to AP above a
  configurable policy threshold.
- Financial-year-end ITC sweep is treated separately from monthly
  operational submission nudges.
- Named DOFA override authority is supported.
- Audit/reconciliation is a first-class capability.

## Appendix B — Principles for Custom Tables

- Do not create a custom accounting ledger where BC already has the
  accounting object.
- Keep source evidence and application workflow data outside BC when
  native BC does not need to own it.
- Store structured compliance decisions, not just booleans.
- Version all rules that can change a financial/compliance decision.
- Make all financial side effects idempotent and reconcilable.
- Never overwrite historical financial/approval/compliance evidence.
- Prefer stable application IDs plus a dedicated BC reference table
  over embedding BC IDs in every business table.
- Use object storage for receipt binaries and hashes/references in the
  relational model.
- Keep tenant and BC company scope on every business entity.
- Design the domain model independently of any single Microsoft user
  interface/channel.
- Configure semantic-to-BC mappings per customer/company; never
  hard-code GD1/GD2 as Cost Center/Department.
- Treat employee project/job membership as many-to-many, effective-dated
  assignments, with transaction-time mapping snapshots.

## Council Go/No-Go Review (2026-09-06)

**Verdict: Approve with conditions — scoped to continuing the
design/validation phase. Not approved to start this schema's build or
write production code.** Full review convened all twelve advisory
personas plus CEO synthesis; investigation read this document's
structure plus the full domain-model section through table 7.26, and
cross-checked claims against the live repo rather than trusting the
docs' own assertions.

### New finding from this review (not previously in this document)

This repo's actual persistence layer today is JSON files
(`open(path, "w")` in `data_trust.py`/`config.py`) — no ORM, no
Postgres/MySQL driver, no web framework (`server.py` runs on stdlib
`http.server`). Section 7's 40-table relational schema with UUID PKs,
effective-dated versioning, and idempotent posting (FR-51/52) and
reconciliation (FR-58) assumes infrastructure — a real RDBMS,
migrations, likely a real web framework — that doesn't exist in this
codebase yet. Three roles (Product Manager, Solution Architect, Tech
Expert) converged on this independently. **This is the actual source of
build-scope risk, more than any BC limitation** — resolve it (pick a DB
+ framework) before this schema is treated as final.

### Six conditions before build starts

1. **BC-11, BC-7, BC-1 (default paths) and BC-8** (§11) answered against
   whatever BC access is already available — Wave 1 / India-inclusion
   access is not required per the §2.0/§11 reframing, since the default
   posting path uses BC's long-standing Journal API, not the new
   Expense Report module.
2. **CLOSED 2026-09-06 — reframed as out of scope, not deferred.** D-1,
   D-2, D-3 (§12) are each customer's own Finance-team policy decisions,
   not an Opsmeld build blocker. The system already requires
   configurable support for all three (FR-14, FR-27, FR-34, FR-39); no
   Opsmeld-internal Finance/Compliance sign-off is needed on a specific
   global answer, because there isn't meant to be one.
3. **Infrastructure decision — CLOSED 2026-09-06.** The Expense Agent
   will be a **new standalone repository**, not a module inside
   opsmeld-recon-engine, on **Python/FastAPI + PostgreSQL**. Rationale:
   this repo's architecture (JSON files, stdlib `http.server`, read-only
   reconciliation conventions) is a scale/risk mismatch for a
   write-capable, financially-sensitive, always-on system — matches the
   Solution Architect/Tech Expert finding in the Council Go/No-Go Review
   below. A separate deployable keeps blast radius and release cadence
   independent. PostgreSQL gives real transactions (needed for FR-51/52)
   and row-level security (feeds condition 4 below) rather than a
   `tenant_id` column alone. **What's reused isn't the repo — it's two
   patterns, copied/adapted, not imported as a dependency**:
   `MCP/core/bc_mcp_client.py`'s MSAL auth/token/company-discovery logic,
   and `MCP/modules/data_trust_engine/llm_interpreter.py`'s
   provider-failover + cost-tracking pattern (extended for vision/OCR
   calls) — this also closes condition 6 below.
4. **CLOSED 2026-09-06 — see §19.** Two-layer design: an app-layer
   authorization gate ported/adapted from `MCP/core/authorization.py`'s
   six-gate shape (Session → Org → Subscription → Permission → Company
   ACL → BC probe — the correct file; `data_trust_engine/authorization.py`
   is Data Trust's narrower company-discovery variant, not the one this
   design generalizes from), plus **new** PostgreSQL Row-Level Security
   enforcing `tenant_id` (and nested `bc_company_id`) at the database
   level — not achievable with JSON files, which is exactly why this was
   open before the infra decision (condition 3) closed. §19.5 states the
   concrete verification test. `expense_source` PII now has a stated
   per-tenant object-storage scoping model (§19.4).
5. **CLOSED 2026-09-06 — see §20.** Reuses `LLMInterpreter`'s
   cost-tracking formula, extended to vision/OCR pricing (Claude Haiku
   4.5 primary, per current `claude-api` skill pricing) and a stated
   image-tokenization formula. Rough estimate: ~$1–2/month (50
   employees) to ~$18–25/month (1,000 employees) — a minor cost line at
   any realistic scale; §20.5 states this plainly so it isn't mistaken
   for the real cost driver (infrastructure/engineering is).
6. **CLOSED 2026-09-06 — see condition 3.** OCR/extraction and the
   conversational-intake AI layer (§2.3A, §10C, §10E) reuse
   `LLMInterpreter`'s provider-failover and cost-tracking pattern,
   copied/adapted into the new standalone repo rather than imported as a
   dependency on this one. Still open: OCR (receipt image → structured
   fields) is a materially different task from the tool-use
   classification `llm_interpreter.py` currently does — vision-capable
   model calls at receipt volume need their own cost/latency line (feeds
   condition 5, still open).

### What was validated as sound

- The system-of-record boundary (§2.1) and provider-mode abstraction
  (§2.2) explicitly refuse to duplicate BC's ledger (FR-18, R6) — the
  right shape.
- The AI/deterministic boundary (§2.3) matches how Data Trust actually
  behaves in production — findings are read-only, human-reviewed, never
  auto-acted.
- The India compliance reasoning (§6.7) reflects real Indian SME
  operational reality, not generic SaaS assumptions.
- Reusing the "local record linked to BC by key, BC read via API, never
  written via table extension" pattern from Data Trust is correct reuse.

### Biggest risk named by the CEO synthesis

Scope creep from "approve the design direction" into "approve full
build" without conditions 1–3 closing first.

**Update (2026-09-06, post-review):** §2.0/§11 clarified this design
doesn't need to replicate BC's native Expense Report module — it only
needs BC's long-standing General/Payment Journal API to post the final
transaction, which needs no Wave 1 or India-inclusion access to confirm.
**First concrete next step, revised**: confirm the Journal API posting
path (BC-11 default), including whether it accepts India GST-specific
fields (BC-1's remaining open question), and advance-vs-settlement
tracking with net Journal settlement (BC-7 default) on whatever BC
access is already available — no need to chase Wave 1 access first.

## 19. Row-Level Tenant Isolation Design (closes council condition 4)

Two independent, stacked layers — not a `tenant_id` column alone.

### 19.1 Layer 1: app-layer authorization gate (ported from this repo)

Directly modeled on `MCP/core/authorization.py`'s `CentralAuthorizationEngine.authorize()` — verified by reading the actual file, not assumed. That engine evaluates six sequential gates: Session → Organization Status → Module Subscription → User Permission → Company ACL → BC backend probe. This shape is **ported/adapted into the new repo as a FastAPI dependency**, not imported as a package dependency (same reuse philosophy as condition 3):

```python
async def require_context(
    request: Request,
    session: Session = Depends(get_session),
) -> RequestContext:
    if not session or session.is_expired():
        raise HTTPException(401, "UNAUTHENTICATED")
    if not org_is_active(session.organization_id):
        raise HTTPException(403, "ORGANIZATION_SUSPENDED")
    if not module_subscribed(session.organization_id, "expense_agent"):
        raise HTTPException(403, "MODULE_NOT_SUBSCRIBED")
    if permission and permission not in session.permissions:
        raise HTTPException(403, "USER_NOT_PERMITTED")
    if company_id and company_id not in session.allowed_companies:
        raise HTTPException(403, "COMPANY_NOT_PERMITTED")
    return RequestContext(tenant_id=session.tenant_id, bc_company_id=company_id, ...)
```

This layer decides *business* authorization (is this user allowed to act on this tenant/company at all) — same as the original.

### 19.2 Layer 2: PostgreSQL Row-Level Security (new — JSON files couldn't do this)

This is what actually answers the council's finding ("isolation as an enforced boundary, not just a column"). Every tenant-scoped table gets RLS enabled and a policy:

```sql
ALTER TABLE expense ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON expense
  USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
-- Repeat for every table in §7's inventory that carries tenant_id.
```

The FastAPI dependency above, once it resolves `RequestContext`, sets the session variable for that request's transaction before any query runs:

```python
async def db_session(ctx: RequestContext = Depends(require_context)):
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": str(ctx.tenant_id)})
        yield conn
```

**The critical property**: the database role the application connects as must **not** have `BYPASSRLS`. That means even a bug in application code — a forgotten `WHERE tenant_id = ...` clause, a copy-pasted query, a new endpoint someone forgot to scope — **cannot leak cross-tenant rows**, because Postgres enforces the policy regardless of what the query asks for. This is the fail-closed backstop the app-layer gate alone can't guarantee (a gate is only as strong as every code path remembering to call it; RLS doesn't depend on that).

### 19.3 Company-level scoping (nested under tenant)

A tenant can have multiple BC companies (`bc_company_id`), so a single `tenant_id` policy isn't sufficient everywhere. Tables scoped to a specific company add a second policy clause checking `bc_company_id` against a session-scoped allow-list (a `SET LOCAL app.current_company_ids` array, populated from `session.allowed_companies` after Gate 5 above), mirroring the Company ACL check `core/authorization.py` already does at the app layer — just enforced twice now.

### 19.4 Receipt/PII object storage

`expense_source` (§7.11) stores receipt images/PII, called out as a gap in the council review. Object storage keys are prefixed by `tenant_id` (`s3://.../{tenant_id}/{expense_id}/...`), bucket policy denies cross-prefix access by IAM role, and any signed URL issued to a client is generated only after the same `require_context` gate passes — never by predictable/guessable path alone.

### 19.5 How this gets verified

A security review should be able to connect to Postgres as the application's normal (non-bypass) role, scope a session to tenant A, and run `SELECT * FROM expense` with **no** `WHERE` clause — RLS must return zero rows belonging to tenant B, regardless of query shape. That's the concrete, repeatable test this design commits to being checkable against, not just described.

## 20. LLM/OCR Cost Model (closes council condition 5)

### 20.1 Methodology and grounding

Reuses `MCP/modules/data_trust_engine/llm_interpreter.py`'s failover chain (Anthropic Claude primary → OpenAI secondary → Gemini tertiary → deterministic fallback) and its cost-tracking formula (`estimated_cost = input_tokens × rate_in + output_tokens × rate_out`, verified by reading the actual file), extended to a vision call for OCR rather than the current text-only tool-use interpretation.

**Pricing sources — verified via the `claude-api` skill (Anthropic) and existing repo code (OpenAI), not training-memory recall**:

| Model | Input $/1M tokens | Output $/1M tokens | Source |
|---|---|---|---|
| Claude Haiku 4.5 (primary, matches `llm_interpreter.py`'s existing choice) | $1.00 | $5.00 | `claude-api` skill pricing table (cached 2026-06-24 — confirm before commercial commitments) |
| Claude Sonnet 5 (fallback tier, if higher accuracy needed) | $2.00 | $10.00 | Same source |
| OpenAI gpt-4o-mini (secondary, per existing failover) | $0.15 | $0.60 | Existing constants in `llm_interpreter.py` line 104 — **not independently reverified this session** (outside the `claude-api` skill's scope); confirm current OpenAI pricing before relying on this figure |

**Image tokenization** (verified via web search, not assumed): Claude's vision token cost approximates `(width_px × height_px) / 750`, with the long edge resized down to a model-dependent cap (~1568px for the Haiku/Sonnet tier) before tokenization. A typical smartphone receipt photo, resized to fit that cap, lands around **1,500–2,500 input tokens**; this model uses **2,000 tokens/image** as the central estimate.

### 20.2 Per-call cost

**OCR/extraction call** (Haiku 4.5, one call per captured receipt — matches FR-2's single-pass extraction):
- Input: ~2,000 image tokens + ~400 tokens (system prompt + tool schema) = 2,400 tokens
- Output: ~200 tokens (structured JSON extraction, similar scale to the existing `record_candidate_interpretation` tool's 512-token cap)
- Cost = 2,400 × $0.000001 + 200 × $0.000005 = **$0.0034/receipt**

**Conversational intake turn** (Haiku 4.5, text-only — Teams/Outlook intent/entity extraction, §2.3A):
- Input: ~600 tokens, Output: ~150 tokens
- Cost = 600 × $0.000001 + 150 × $0.000005 = **$0.00135/turn**

Duplicate/fraud detection (FR-28–30) is signal-based (hash/vendor/amount/date matching), not an LLM call, so it adds no LLM cost.

### 20.3 Assumptions (adjustable — flag before treating as final)

| Assumption | Value | Basis |
|---|---|---|
| Receipts/employee/month | 4 | Rough blended estimate (field-heavy roles higher, office roles lower) — **replace with real pilot data as soon as available** |
| % of captures via conversational intake (vs. app/photo direct) | 30% | Estimate, no data yet |
| Conversational turns per captured expense | 2 | Intent classification + confirmation |
| Primary-model (Haiku) success rate | ~95% | Assumed; failover overflow to OpenAI/Gemini not separately modeled below |

### 20.4 Per-tenant monthly estimate

| Tenant size | Receipts/month | OCR cost | Conversational cost | **Total/month** |
|---|---|---|---|---|
| Small (50 employees) | 200 | $0.68 | $0.16 | **~$0.84** |
| Medium (200 employees) | 800 | $2.72 | $0.65 | **~$3.37** |
| Large (1,000 employees) | 4,000 | $13.60 | $3.24 | **~$16.84** |

Add a 20–30% buffer for retries on low-quality images, multi-page bills, and failover overflow to costlier providers: realistic range **~$1–$2 (small)**, **~$4–$6 (medium)**, **~$18–$25/month (large)**.

### 20.5 The actual finding

At any realistic scale, LLM/OCR spend is a minor line item — even a 1,000-employee tenant costs roughly the same as a single SaaS seat license, not a meaningful driver of unit economics. **The CFO question that actually matters is infrastructure and engineering cost (the new Postgres/FastAPI service, ongoing maintenance, human review time for exceptions), not per-call LLM pricing.** Worth saying plainly rather than letting a "cost estimate" checkbox imply LLM spend is the risk here.

### 20.6 What's not modeled (caveats)

- Failover overflow cost if Haiku is unavailable and Gemini/OpenAI carry more volume than the assumed 5%.
- `llm_interpreter.py`'s Gemini branch doesn't currently set `estimated_cost` at all (verified by reading the file) — a gap worth fixing when this pattern is ported, not just carried forward silently.
- Vision-capable OCR is a materially different workload from the existing tool-use text interpretation this pattern was built for — real production numbers should replace this estimate once pilot volume exists.

## 21. Change Log

| Version | Change |
|---|---|
| v0.2 | Initial reviewed functional design with BC/domain corrections. |
| v0.3–v0.6 | Canonical configuration, provider abstraction, BC projections, mapping, advance accounting and finance posting workflow. |
| v0.7 | Conversational Teams/Outlook advance intake and approval workflow. |
| v0.8 | Conversational expense submission workflow. |
| v0.9 | Reporting plus consolidated engineering blueprint: persistence, APIs, events, BC adapter contract, sync, security, reliability, exceptions and traceability. |
| v1.0 | Structural consolidation: fixed duplicate section numbers (10/14/15), fixed duplicate 7.3.1–7.3.6, filled missing 7.5/7.6, relocated 10E/10F to narrative order. No content changes. Split into this engineering blueprint plus a lean `expense-agent-spec.md` for SME review. |
| v1.1 | Folded in BC-expert review: added §4A verified finding (no BC write path exists in this codebase today — `bc_mcp_client.py`'s `_execute_bc_rest`/`_execute_bc_rest_url` are GET-only), sharpened BC-11 (API write-capability must be confirmed as documented/stable, not inferred from sandbox behavior; plan Journal API as day-1 path), BC-7 (ask specifically about Employee Ledger Entry *application* API, not just entry read access — historically read-only), and BC-1 (treat OPSMELD_NATIVE for GST as the probable outcome). Updated R2 accordingly. |
| v1.2 | Full council Go/No-Go review: approved for design/validation phase only, not for build. New finding — this repo's persistence layer today is JSON files, no DB/framework, which the schema assumes but didn't name as a prerequisite. Six conditions set before schema/code work (see "Council Go/No-Go Review" section above). |
| v1.3 | Added §2.0 ("inspiration, not replication") clarifying this design doesn't need to mirror BC's native Expense Report module — the only hard BC dependency is posting via BC's long-standing General/Payment Journal API. Split BC-11/BC-7/BC-1 in §11 into a default path (testable on any existing BC access, no Wave 1/India-inclusion needed) and an optional native-path exploration. Updated §17's Build Decision Gate and the Council review's next-step guidance accordingly — resolves the "no Wave 1 access" blocker by removing the dependency on it. |
| v1.4 | Closed council conditions 3 and 6: infrastructure decision made — new standalone repository (not a module in opsmeld-recon-engine), Python/FastAPI + PostgreSQL. Reuses two proven patterns from this repo (`bc_mcp_client.py`'s MSAL auth, `llm_interpreter.py`'s provider-failover/cost-tracking), copied/adapted rather than imported as a dependency. Remaining open conditions: 1 (BC default-path testing), 2 (Finance/Compliance sign-off), 4 (row-level isolation design), 5 (LLM/OCR cost estimate). |
| v1.5 | Second BC-expert re-review of v1.3's reframing, folded in: (1) BC-1's "nothing to test" was overclaimed — restored a real, testable-today question about whether the Journal API exposes India GST-specific fields (GST Group Code/HSN-SAC/Jurisdiction Type), which decides who owns GST-return prep (this tool vs. BC); (2) softened "confirmed excluded from India" to "reported as excluded" with an explicit confidence note (aggregated search, not primary-source-verified) and reconciled §4's two differently-worded availability claims; (3) reworded the FR-18 citation on BC-7's fallback from "existing fallback" to "consistent with FR-18's intent"; (4) added a named residual risk to BC-7's default path and FR-58: the fallback leaves BC's own Employee Ledger Entry for the original advance permanently Open/unapplied — reconciliation must treat this as expected structural divergence, not an anomaly. |
| v1.6 | Third BC-expert pass, attempting to close the §4 confidence gap directly: a second `WebFetch` to `learn.microsoft.com` was independently blocked (same limitation, different review session — corroborates it's real). Aggregated search surfaced two India-availability claims that don't fully reconcile: a general "July 2026" regional-expansion date for Expense Agent vs. a narrower claim about a specific GPT-5.3-chat *model-version* rollout excluding India/UK/Australia (not necessarily the feature itself). Documented both in §4 rather than picking one, and added the concrete recommendation: someone with actual BC admin-center/tenant portal access should check the live "Feature availability by country/region" page directly. If the July 2026 date is accurate and feature-wide, it would change §11's "optional native-path exploration" timing. |
| v1.7 | Closed council conditions 4 and 5 — the two remaining conditions answerable without a real BC SME or Finance/Compliance sign-off. Added §19 (Row-Level Tenant Isolation Design): a two-layer model — an app-layer gate ported from `MCP/core/authorization.py`'s six-gate shape (correcting the council's citation of `data_trust_engine/authorization.py`, which is Data Trust's narrower company-discovery variant, not the general-purpose engine) plus new PostgreSQL Row-Level Security enforcing tenant/company isolation at the DB level, with a concrete verification test. Added §20 (LLM/OCR Cost Model): current Claude Haiku 4.5/Sonnet 5 pricing verified via the `claude-api` skill, an image-tokenization formula verified via web search, and a per-tenant monthly estimate (~$1–25/month across 50–1,000 employees) — with the finding stated plainly that LLM cost is a minor line item, not the real cost driver. |
| v1.8 | Reframed and closed condition 2 (§12): D-1/D-2/D-3 (advance recovery mechanism, perquisite tax treatment, GST override authority) are each customer's own Finance-team policy decision, not an Opsmeld build blocker — the system already requires configurable support for all three (FR-14, FR-27, FR-34, FR-39). No Opsmeld-internal Finance/Compliance sign-off needed on a specific global answer, since there isn't meant to be one; Opsmeld ships sensible defaults/templates, customers configure the authoritative values. 5 of 6 conditions now closed — only condition 1 (BC SME sandbox testing) remains, and it cannot be closed by further design work. |
