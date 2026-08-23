"""
bc_mcp_client.py

Minimal client for the Business Central MCP server that:
  1. Acquires an Entra access token via MSAL (device-code flow the FIRST time
     only; every run after that is silent, using a cached refresh token —
     no browser, no clicking).
  2. Performs the MCP session handshake (initialize -> capture Mcp-Session-Id).
  3. Exposes simple tools/list and tools/call helpers.

One BCClientConfig = one client's Business Central tenant. For multiple
clients (multi-tenant), create one BCMCPClient per client config; each
gets its own token cache file, so refreshing one client's token never
touches another's.

SECURITY NOTE
-------------
The token cache file (see `cache_path` below) contains a refresh token.
Treat it like a password: encrypt at rest in production (e.g. store the
cache contents in a secrets manager rather than a plain file on disk),
restrict file permissions, and never commit it to source control.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
import msal

MCP_URL = "https://mcp.businesscentral.dynamics.com/"
BC_RESOURCE_SCOPE = ["https://api.businesscentral.dynamics.com/.default"]


@dataclass
class BCClientConfig:
    """Everything needed to talk to one client's Business Central tenant."""

    client_name: str          # your internal label, e.g. "acme-manufacturing"
    tenant_id: str            # the CLIENT's Entra tenant ID (not yours)
    environment_name: str     # e.g. "Production"
    company: str              # e.g. "CRONUS IN"
    configuration_name: str   # the MCP Server Configuration name in BC
    app_client_id: str        # YOUR multi-tenant Entra app's client ID
    cache_dir: str = "./token_cache"

    @property
    def cache_path(self) -> str:
        os.makedirs(self.cache_dir, exist_ok=True)
        return os.path.join(self.cache_dir, f"{self.client_name}.bin")


class BCMCPClient:
    def __init__(self, config: BCClientConfig):
        self.config = config
        self._session_id: Optional[str] = None
        self._msal_app = self._build_msal_app()

    # ------------------------------------------------------------------ #
    # Token acquisition
    # ------------------------------------------------------------------ #
    def _build_msal_app(self) -> msal.PublicClientApplication:
        cache = msal.SerializableTokenCache()
        if os.path.exists(self.config.cache_path):
            cache.deserialize(open(self.config.cache_path, "r").read())

        app = msal.PublicClientApplication(
            client_id=self.config.app_client_id,
            authority=f"https://login.microsoftonline.com/{self.config.tenant_id}",
            token_cache=cache,
        )
        self._cache = cache
        return app

    def _save_cache(self) -> None:
        if self._cache.has_state_changed:
            with open(self.config.cache_path, "w") as f:
                f.write(self._cache.serialize())

    def get_access_token(self) -> str:
        """
        Returns a valid access token. Silent (no prompt) if a cached
        refresh token exists and is still valid; otherwise falls back to
        an interactive device-code flow (ONE TIME per client, during
        onboarding — not something that should happen on a scheduled run).
        """
        accounts = self._msal_app.get_accounts()
        result = None
        if accounts:
            result = self._msal_app.acquire_token_silent(
                BC_RESOURCE_SCOPE, account=accounts[0]
            )

        if not result:
            # No cached/refreshable token — do the one-time interactive
            # device-code login. In production this branch should only
            # ever run during a client's initial onboarding, driven by a
            # human, not inside an unattended nightly job. Raise instead
            # of silently prompting if you want the job to fail loudly.
            flow = self._msal_app.initiate_device_flow(scopes=BC_RESOURCE_SCOPE)
            if "user_code" not in flow:
                raise RuntimeError(f"Failed to create device flow: {flow}")
            print(flow["message"])  # tells the human where to sign in
            result = self._msal_app.acquire_token_by_device_flow(flow)

        self._save_cache()

        if "access_token" not in result:
            raise RuntimeError(
                f"Token acquisition failed for {self.config.client_name}: "
                f"{result.get('error')}: {result.get('error_description')}"
            )
        return result["access_token"]

    # ------------------------------------------------------------------ #
    # MCP protocol
    # ------------------------------------------------------------------ #
    def _headers(self, token: str, include_session: bool = True) -> dict:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "TenantId": self.config.tenant_id,
            "EnvironmentName": self.config.environment_name,
            "Company": self.config.company,
            "ConfigurationName": self.config.configuration_name,
        }
        if include_session and self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    @staticmethod
    def _parse_sse_json(text: str) -> dict:
        """The MCP server returns text/event-stream; pull the JSON payload
        out of the 'data: {...}' line."""
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:"):].strip())
        raise ValueError(f"No 'data:' line found in response: {text!r}")

    def initialize(self) -> dict:
        """Performs the MCP handshake and stores the session ID for
        subsequent calls. Safe to call again if the session expires."""
        token = self.get_access_token()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "opsmeld-recon-engine", "version": "0.1"},
            },
        }
        resp = httpx.post(
            MCP_URL, headers=self._headers(token, include_session=False),
            json=payload, timeout=30,
        )
        resp.raise_for_status()
        self._session_id = resp.headers.get("mcp-session-id")
        if not self._session_id:
            raise RuntimeError("Server did not return an Mcp-Session-Id header")
        return self._parse_sse_json(resp.text)

    def _call(self, method: str, params: dict, request_id: int = 2) -> dict:
        if not self._session_id:
            self.initialize()
        token = self.get_access_token()
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        resp = httpx.post(
            MCP_URL, headers=self._headers(token), json=payload, timeout=60,
        )
        if resp.status_code == 400 and "session" in resp.text.lower():
            # session likely expired server-side; re-init once and retry
            self._session_id = None
            self.initialize()
            token = self.get_access_token()
            resp = httpx.post(
                MCP_URL, headers=self._headers(token), json=payload, timeout=60,
            )
        resp.raise_for_status()
        return self._parse_sse_json(resp.text)

    def list_tools(self) -> list[dict]:
        result = self._call("tools/list", {})
        return result.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> Any:
        result = self._call("tools/call", {"name": name, "arguments": arguments})
        content = result.get("result", {}).get("content", [])
        # Tool responses come back as a list of {"type": "text", "text": "..."}
        # blocks; the last one is usually the actual JSON payload.
        for block in reversed(content):
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except (json.JSONDecodeError, KeyError):
                    return block["text"]
        return result
