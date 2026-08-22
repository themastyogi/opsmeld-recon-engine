# Opsmeld Reconciliation Engine — BC MCP client (v0)

Minimal, working foundation for talking to the Business Central MCP server
without a human clicking through a login every time it runs.

## How the auth actually works

BC's native MCP server only supports **delegated (user) OAuth** — there's
no true "service account" mode for it. The practical workaround:

1. **First run ever, per client tenant:** `initialize()` triggers an MSAL
   *device-code* flow. It prints a URL + short code. Open the URL in any
   browser, sign in as that client's BC admin, approve once.
2. **Every run after that:** MSAL silently reuses the cached refresh
   token (stored in `./token_cache/<client_name>.bin`). No browser, no
   prompt, no clicking — this is what a nightly cron job will do.
3. Refresh tokens are long-lived but not infinite — if unused for a long
   stretch, or if the client's admin revokes consent, the silent path
   will fail and fall back to asking for a new device-code login. In a
   real unattended job, treat that fallback as a **failure to alert on**,
   not something to let block silently — see the comment in
   `get_access_token()`.

## Files

- `bc_mcp_client.py` — the actual client: token handling + MCP session
  handshake (`initialize`) + `list_tools()` / `call_tool()`.
- `example_list_customers.py` — smallest working example, pulls 5
  customers from the CRONUS IN demo company using the config we already
  validated via curl.
- `requirements.txt` — `pip install -r requirements.txt` (msal, httpx).

## Running it

This needs to run somewhere that can reach `login.microsoftonline.com`
and `mcp.businesscentral.dynamics.com` — your Codespace, not a locked-down
sandbox. From the Codespace terminal:

```bash
pip install -r requirements.txt --break-system-packages
python3 example_list_customers.py
```

First run prints a device-code URL — complete it in a browser. Run it
again immediately after and it should complete silently with no prompt,
proving the cached-token path works.

## Known gap: multi-tenant / multiple clients

Right now `app_client_id` in the example points at the "Opsmeld BC MCP
Inspector" app we registered earlier, which is scoped to opsmeld.com's
own tenant only. For a second real client (their own BC tenant), that
app needs to be converted to **multi-tenant** in Entra (Authentication →
Supported account types → "Accounts in any organizational directory"),
and each new client's admin needs to complete a one-time admin-consent
step before their `BCClientConfig` will work. `CLIENTS` in the example
is a plain Python list for now — in the real engine this should come
from wherever client configs actually live (a small database table is
enough).

## Security notes — don't skip these before any real deployment

- `token_cache/*.bin` files contain refresh tokens — treat them as
  credentials. The `.gitignore` below excludes the whole folder; do not
  remove that.
- In production, don't leave these as plain files on a shared box —
  move the cache into a proper secrets manager (Key Vault, etc.) once
  you're past prototyping.
- Each `BCClientConfig` should live per-client with tightly scoped read
  permissions on the BC side (the same "Available Tools" allow-list
  pattern we set up for the Reconciliation Engine MCP configuration —
  read-only until you deliberately add write access for the fix-proposal
  step).
