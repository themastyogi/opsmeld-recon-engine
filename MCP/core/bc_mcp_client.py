"""
Opsmeld Reconciliation Engine - Business Central MCP Client
Handles MSAL OAuth 2.0 authentication, token caching, and live JSON-RPC MCP tool execution.
Strictly queries live Business Central endpoints with zero mock/stub fallback data.
"""

import json
import os
from pathlib import Path
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional
from core.config_loader import ClientConfig, load_client_config


class BCMCPClient:
    """
    Client wrapper for Microsoft Dynamics 365 Business Central Model Context Protocol (MCP) server.
    Manages OAuth2 token acquisition via MSAL and executes live JSON-RPC 2.0 tool requests.
    """

    def __init__(self, config: Optional[ClientConfig] = None):
        self.config = config or load_client_config()
        self.token_cache_path = self.config.get_absolute_cache_path()
        self._available_tools: Optional[List[Dict[str, Any]]] = None

    def get_access_token(self) -> str:
        """Acquires OAuth2 token via MSAL (silent cache persistence or Client Secret flow)."""
        try:
            import msal
        except ImportError:
            return ""

        cache = msal.SerializableTokenCache()
        if self.token_cache_path.exists():
            with open(self.token_cache_path, "r", encoding="utf-8") as f:
                try:
                    cache.deserialize(f.read())
                    app = msal.PublicClientApplication(
                        client_id=self.config.app_client_id,
                        authority=f"https://login.microsoftonline.com/{self.config.tenant_id}",
                        token_cache=cache,
                    )
                    accounts = app.get_accounts()
                    if accounts:
                        result = app.acquire_token_silent(self.config.scopes, account=accounts[0])
                        if result and "access_token" in result:
                            return result["access_token"]
                except Exception:
                    pass

        client_secret = getattr(self.config, "client_secret", None) or os.environ.get("BC_CLIENT_SECRET")
        if client_secret:
            app = msal.ConfidentialClientApplication(
                client_id=self.config.app_client_id,
                client_credential=client_secret,
                authority=f"https://login.microsoftonline.com/{self.config.tenant_id}",
            )
            result = app.acquire_token_for_client(scopes=self.config.scopes)
            if result and "access_token" in result:
                return result["access_token"]

        return ""

    def start_device_flow(self) -> Dict[str, Any]:
        """Initiates MSAL Device Code Flow for 1-click user authentication."""
        try:
            import msal
            cache = msal.SerializableTokenCache()
            app = msal.PublicClientApplication(
                client_id=self.config.app_client_id,
                authority=f"https://login.microsoftonline.com/{self.config.tenant_id}",
                token_cache=cache
            )
            scopes = ["https://api.businesscentral.dynamics.com/Financials.ReadWrite.All"]
            flow = app.initiate_device_flow(scopes=scopes)
            if "user_code" not in flow:
                scopes = ["https://api.businesscentral.dynamics.com/user_impersonation"]
                flow = app.initiate_device_flow(scopes=scopes)
            return flow
        except Exception as e:
            return {"error": str(e)}

    def complete_device_flow(self, flow: Dict[str, Any]) -> Dict[str, Any]:
        """Completes device code flow and persists token cache."""
        try:
            import msal
            cache = msal.SerializableTokenCache()
            app = msal.PublicClientApplication(
                client_id=self.config.app_client_id,
                authority=f"https://login.microsoftonline.com/{self.config.tenant_id}",
                token_cache=cache
            )
            result = app.acquire_token_by_device_flow(flow)
            if "access_token" in result:
                self.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.token_cache_path, "w", encoding="utf-8") as f:
                    f.write(cache.serialize())
                return {"status": "success", "access_token": result["access_token"]}
            return {"error": result.get("error_description", "Authentication pending or failed.")}
        except Exception as e:
            return {"error": str(e)}

    def _execute_jsonrpc(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a live HTTP JSON-RPC 2.0 POST request against the BC MCP server."""
        token = self.get_access_token()
        if not token:
            return {"error": "Authentication token missing. Please sign in via MSAL or configure BC_CLIENT_SECRET."}
        
        if not self.config.mcp_server_url:
            return {"error": "Business Central MCP Server URL is not configured."}

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        req = urllib.request.Request(self.config.mcp_server_url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                if "error" in res_data:
                    return {"error": f"JSON-RPC Error: {res_data['error'].get('message', res_data['error'])}"}
                return res_data.get("result", {})
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode('utf-8') if e.fp else str(e)
            if e.code == 403 and "user is expected to be authenticated" in err_msg.lower():
                return {
                    "error": (
                        "HTTP 403 Forbidden: Business Central requires User Context or Entra App Permission. "
                        f"In Business Central, search for 'Microsoft Entra Applications', add Client ID '{self.config.app_client_id}', "
                        "and assign User Permissions (e.g. D365 FULL ACCESS), or click '🔑 Sign In with Microsoft'."
                    )
                }
            return {"error": f"HTTP {e.code}: {err_msg}"}
        except Exception as e:
            return {"error": f"Connection Error: {str(e)}"}

    def list_tools(self) -> List[Dict[str, Any]]:
        """Discovers tools available on the configured Business Central MCP server instance."""
        live_result = self._execute_jsonrpc("tools/list", {})
        if "tools" in live_result:
            self._available_tools = live_result["tools"]
            return self._available_tools

        return []

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Executes a named tool on the Business Central MCP server strictly without fallback data."""
        arguments = arguments or {}
        live_result = self._execute_jsonrpc("tools/call", {"name": name, "arguments": arguments})
        return live_result
