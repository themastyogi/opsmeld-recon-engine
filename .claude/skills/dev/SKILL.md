---
name: dev
description: Launch the local Opsmeld Reconciliation Engine dev server and follow this repo's coding conventions (module layout, config loading, RBAC patterns) when writing or editing code here. Use when the user asks to run the app locally, or wants code changes made that should match existing repo patterns. For running the test suite, use the test skill instead — this skill is for writing/running code, not testing it.
---

## Running the local server

The web console lives in `MCP/`. From the `MCP/` directory (imports like
`web.app` and `modules.*` are resolved relative to it):

```bash
cd MCP
python server.py
```

- Serves on `http://localhost:8000` (override with `PORT` or
  `WEBSITES_PORT` env vars; falls back to 8000 and retries on port
  conflicts).
- Settings/tenant config UI is at `http://localhost:8000/settings`.
- Before first run, check that dependencies from `MCP/requirements.txt`
  (`msal`, `urllib3`) are installed, and that any required secrets
  (`BC_CLIENT_SECRET`, etc.) are in a git-ignored `.env` — never commit
  raw keys.
- `MCP/config/clients.json` (see `clients.json.example`) holds per-tenant
  configuration; don't overwrite a real one with the example blindly.

## Repo conventions to follow when writing code

- **Module layout**: business logic lives under `MCP/modules/` (e.g.
  `ar_manager.py`, `data_trust.py`, `data_trust_engine/`); core
  infrastructure (auth, config loading, RBAC, BC client) lives under
  `MCP/core/`; the web layer (`server.py`, `web/app.py`,
  `web/templates.py`) stays thin and delegates to modules — don't put
  business logic directly in the web layer.
- **Config loading**: goes through `MCP/core/config_loader.py` —
  don't read `clients.json` or env vars directly from a new module; use
  the existing loader so tenant scoping stays consistent.
- **Auth & RBAC**: `MCP/core/auth.py`, `MCP/core/authorization.py`, and
  `MCP/core/rbac.py` are the source of truth for who can see/do what.
  Any new endpoint or data path must go through these rather than
  reimplementing a check inline — this repo treats tenant/company
  isolation as a hard security boundary (see `data_trust_architecture_guards`
  tests), so a new bypass path is a regression, not a shortcut.
  Fail closed on auth/config errors, not open.
- **Safety mode**: document-creating actions (Sales Orders, Purchase
  Invoices, journal vouchers) are staged as unposted drafts
  (`Do Not Post`) — never post directly to BC from this codebase without
  that safety gate.
- **Styling**: the "Ledger Design System" (`MCP/core/ledger_theme.py`,
  Spectral/Inter/IBM Plex Mono, XSS-safe templating) is the existing
  convention for any UI/template work — don't introduce a second styling
  approach.
- **Tests**: when you touch a module, add or update its test file under
  `MCP/tests/` following the existing `unittest.TestCase` style used
  throughout that directory — but running the suite is the test skill's
  job, not this one's.

Match the file/module/naming conventions already present in the directory
you're editing rather than introducing a new pattern, unless the task
specifically calls for a new module.
