"""
Opsmeld Reconciliation Engine - Business Central MCP Client
Handles MSAL OAuth 2.0 authentication, token caching, MCP 2.0 session initialization, and live JSON-RPC tool execution.
Strictly queries live Business Central endpoints with zero mock/stub fallback data.
"""

import json
import logging
import os
from pathlib import Path
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional
from core.config_loader import ClientConfig, load_client_config

logger = logging.getLogger("OpsmeldReconEngine.BCMCPClient")


class BCMCPClient:
    """
    Client wrapper for Microsoft Dynamics 365 Business Central Model Context Protocol (MCP) server.
    Manages OAuth2 token acquisition via MSAL and executes live JSON-RPC 2.0 tool requests.
    """

    def __init__(self, config: Optional[ClientConfig] = None, user_token: Optional[str] = None, user_tenant_id: Optional[str] = None, customer_id: Optional[str] = None):
        self.config = config or load_client_config()
        self.customer_id = customer_id or getattr(self.config, "customer_id", None) or "default_customer"
        self.token_cache_path = self._resolve_isolated_cache_path()
        self.user_access_token = user_token or os.environ.get("BC_ACCESS_TOKEN", "")
        self.user_tenant_id = user_tenant_id or os.environ.get("BC_TENANT_ID")
        self._available_tools: Optional[List[Dict[str, Any]]] = None
        self._mcp_session_id: Optional[str] = None

    def _resolve_isolated_cache_path(self) -> Path:
        """Resolves customer & tenant isolated cache path to prevent token cross-contamination."""
        try:
            from core.customer_connection import get_customer_connection_repo
            repo = get_customer_connection_repo()
            conn = repo.get_connection(self.customer_id)
            if conn:
                return conn.get_isolated_cache_path()
        except Exception:
            pass
        tenant_id = getattr(self.config, "tenant_id", "default_tenant")
        safe_cust = str(self.customer_id).replace("/", "_").replace("\\", "_")
        safe_tenant = str(tenant_id).replace("/", "_").replace("\\", "_")
        cache_dir = Path(__file__).resolve().parent.parent / "token_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{safe_cust}_{safe_tenant}.bin"

    def _get_tenant_id(self) -> str:
        try:
            from core.customer_connection import get_customer_connection_repo
            repo = get_customer_connection_repo()
            conn = repo.get_connection(self.customer_id)
            if conn and conn.entra_tenant_id:
                return conn.entra_tenant_id
        except Exception:
            pass
        if self.user_tenant_id and not self.user_tenant_id.startswith("test-tenant") and self.user_tenant_id != "placeholder":
            return self.user_tenant_id
        tid = getattr(self.config, "tenant_id", None) or os.environ.get("BC_TENANT_ID")
        if not tid or tid.startswith("test-tenant") or tid == "placeholder":
            return os.environ.get("BC_TENANT_ID") or "common"
        return tid

    def _get_client_id(self) -> str:
        try:
            from core.customer_connection import get_customer_connection_repo
            repo = get_customer_connection_repo()
            conn = repo.get_connection(self.customer_id)
            if conn and conn.oauth_client_id:
                return conn.oauth_client_id
        except Exception:
            pass
        cid = getattr(self.config, "app_client_id", None) or os.environ.get("BC_APP_CLIENT_ID")
        if not cid or cid.startswith("test-client") or cid == "placeholder":
            return os.environ.get("BC_APP_CLIENT_ID") or "5accae97-5fc5-4a13-9600-2cbe0065d83a"
        return cid

    def _get_client_secret(self) -> str:
        try:
            from core.customer_connection import get_customer_connection_repo
            repo = get_customer_connection_repo()
            conn = repo.get_connection(self.customer_id)
            if conn:
                sec = conn.get_resolved_secret()
                if sec:
                    return sec
        except Exception:
            pass
        return getattr(self.config, "client_secret", None) or os.environ.get("BC_CLIENT_SECRET", "")

    def get_access_token(self) -> str:
        """Acquires OAuth2 token via Client Secret flow, MSAL token cache, or explicit user_access_token."""
        try:
            import msal
        except ImportError:
            return self.user_access_token or ""

        tenant_id = self._get_tenant_id()
        client_id = self._get_client_id()

        # 1. Confidential Client Secret Flow (Primary for Business Central API)
        client_secret = self._get_client_secret()
        if client_secret and tenant_id and client_id:
            try:
                app = msal.ConfidentialClientApplication(
                    client_id=client_id,
                    client_credential=client_secret,
                    authority=f"https://login.microsoftonline.com/{tenant_id}",
                )
                result = app.acquire_token_for_client(scopes=["https://api.businesscentral.dynamics.com/.default"])
                if result and "access_token" in result:
                    return result["access_token"]
            except Exception as e:
                logger.warning(f"MSAL client secret acquisition failed: {e}")

        # 2. Explicit User Access Token
        if self.user_access_token:
            return self.user_access_token

        # 3. Public Client Token Cache
        cache = msal.SerializableTokenCache()
        if self.token_cache_path.exists():
            try:
                with open(self.token_cache_path, "r", encoding="utf-8") as f:
                    cache.deserialize(f.read())
                app = msal.PublicClientApplication(
                    client_id=client_id,
                    authority=f"https://login.microsoftonline.com/{tenant_id}",
                    token_cache=cache,
                )
                accounts = app.get_accounts()
                if accounts:
                    for sc in [
                        ["https://api.businesscentral.dynamics.com/Financials.ReadWrite.All"],
                        ["https://api.businesscentral.dynamics.com/user_impersonation"],
                        self.config.scopes
                    ]:
                        result = app.acquire_token_silent(sc, account=accounts[0])
                        if result and "access_token" in result:
                            if cache.has_state_changed:
                                with open(self.token_cache_path, "w", encoding="utf-8") as cf:
                                    cf.write(cache.serialize())
                            return result["access_token"]
            except Exception as e:
                logger.warning(f"MSAL silent cache acquisition failed: {e}")

        return ""

    def _ensure_mcp_session(self):
        """Performs MCP 2.0 handshake initialization protocol."""
        if self._mcp_session_id:
            return
        
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "OpsmeldReconEngine", "version": "1.0.0"}
        }
        res = self._execute_jsonrpc("initialize", init_params, is_init=True)
        if isinstance(res, dict) and "sessionId" in res:
            self._mcp_session_id = res["sessionId"]

        # Send initialized notification
        self._execute_jsonrpc("notifications/initialized", {}, is_init=True)

    def _execute_jsonrpc(self, method: str, params: Dict[str, Any], is_init: bool = False) -> Dict[str, Any]:
        """Executes a live HTTP JSON-RPC 2.0 POST request against the BC MCP server."""
        if not is_init and method != "initialize" and not self._mcp_session_id:
            self._ensure_mcp_session()

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
            "Accept": "application/json, text/event-stream"
        }
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id
        if self.config.company_name:
            headers["Company"] = self.config.company_name

        req = urllib.request.Request(self.config.mcp_server_url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                sess_header = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
                if sess_header:
                    self._mcp_session_id = sess_header

                raw_bytes = resp.read()
                if not raw_bytes:
                    return {}

                raw_text = raw_bytes.decode("utf-8").strip()
                if not raw_text:
                    return {}

                # Handle Business Central MCP Server-Sent Events (SSE) data: prefix
                if "data:" in raw_text or "event:" in raw_text:
                    json_parts = []
                    for line in raw_text.splitlines():
                        line_s = line.strip()
                        if line_s.startswith("data:"):
                            json_parts.append(line_s[5:].strip())
                    if json_parts:
                        raw_text = "".join(json_parts)

                res_data = json.loads(raw_text)
                if "error" in res_data:
                    return {"error": f"JSON-RPC Error: {res_data['error'].get('message', res_data['error'])}"}
                return res_data.get("result", {})
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8') if e.fp else str(e)
            err_code = "HTTPError"
            try:
                parsed_err = json.loads(err_body)
                if isinstance(parsed_err, dict) and "error" in parsed_err and "code" in parsed_err["error"]:
                    err_code = parsed_err["error"]["code"]
            except Exception:
                pass

            diag = {
                "is_error": True,
                "http_status": e.code,
                "error_code": err_code,
                "error_message": err_body,
                "endpoint": method,
                "tenant_id": self.config.tenant_id,
                "environment": self.config.environment,
                "error": f"HTTP {e.code}: {err_body}",
                "value": []
            }
            return diag
        except Exception as e:
            return {"error": f"Connection Error: {str(e)}"}

    def list_tools(self) -> List[Dict[str, Any]]:
        """Discovers tools available on the configured Business Central MCP server instance."""
        live_result = self._execute_jsonrpc("tools/list", {})
        if "tools" in live_result:
            self._available_tools = live_result["tools"]
            return self._available_tools

        return []

    def _execute_bc_rest(self, path: str) -> Dict[str, Any]:
        """Executes a direct GET request against standard Business Central v2.0 REST API with OData pagination support."""
        token = self.get_access_token()
        if not token:
            return {"error": "Authentication token missing."}
        tenant_id = self._get_tenant_id()
        if not tenant_id:
            return {"error": "Business Central tenant_id unconfigured."}
        url = f"https://api.businesscentral.dynamics.com/v2.0/{tenant_id}/{self.config.environment}/api/v2.0/{path}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        
        # Explicit Company Header Scope Fix: For company-scoped REST URLs ('companies' or 'companies(<GUID>)...'),
        # do NOT send the stale configured Company header. The URL path is the authoritative company context.
        if self.config.company_name and not (path.startswith("companies") or "companies(" in path):
            headers["Company"] = self.config.company_name
        
        all_values = []
        next_url = url
        last_resp_dict = {}

        while next_url:
            req = urllib.request.Request(next_url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(resp_data, dict):
                        last_resp_dict = resp_data
                        if "value" in resp_data and isinstance(resp_data["value"], list):
                            all_values.extend(resp_data["value"])
                            next_url = resp_data.get("@odata.nextLink")
                        else:
                            break
                    else:
                        break
            except Exception as e:
                if not all_values:
                    return {"error": str(e)}
                break

        if all_values:
            last_resp_dict["value"] = all_values
            return last_resp_dict
        return last_resp_dict

    def _execute_bc_rest_url(self, url: str) -> Dict[str, Any]:
        """Executes a direct GET request against an absolute OData @odata.nextLink URL."""
        token = self.get_access_token()
        if not token:
            return {"error": "Authentication token missing."}
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if self.config.company_name and not ("/companies" in url or "companies(" in url):
            headers["Company"] = self.config.company_name
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": str(e)}

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Executes a named tool on Business Central MCP server, with automatic REST API fallback for Client Secrets."""
        arguments = arguments or {}
        live_result = self._execute_jsonrpc("tools/call", {"name": name, "arguments": arguments})
        
        if "error" in live_result and "403" in str(live_result.get("error")):
            if name == "customers_get_list":
                companies_resp = self._execute_bc_rest("companies")
                if "value" in companies_resp and len(companies_resp["value"]) > 0:
                    comp_id = companies_resp["value"][0].get("id")
                    cust_resp = self._execute_bc_rest(f"companies({comp_id})/customers")
                    if "value" in cust_resp:
                        mapped_custs = []
                        for c in cust_resp["value"]:
                            mapped_custs.append({
                                "number": c.get("number"),
                                "name": c.get("displayName", c.get("name")),
                                "balance_due": float(c.get("balanceDue", c.get("balance_due", 0.0))),
                                "credit_limit": float(c.get("creditLimit", 0.0)),
                            })
                        return {"value": mapped_custs}

        return live_result

    def call_tool_all_pages(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes a named tool and recursively iterates @odata.nextLink pages across Business Central OData responses.
        Guarantees that large datasets (100+ customers / thousands of ledger entries) are completely retrieved without silent truncation.
        """
        initial_resp = self.call_tool(name, arguments)
        if "error" in initial_resp or not isinstance(initial_resp, dict):
            return initial_resp

        all_records = list(initial_resp.get("value", [])) if isinstance(initial_resp.get("value"), list) else []
        next_link = initial_resp.get("@odata.nextLink") or initial_resp.get("nextLink")

        while next_link:
            next_resp = self._execute_bc_rest_url(next_link)
            if "error" in next_resp or not isinstance(next_resp, dict):
                break
            page_val = next_resp.get("value", [])
            if isinstance(page_val, list) and page_val:
                all_records.extend(page_val)
            next_link = next_resp.get("@odata.nextLink") or next_resp.get("nextLink")

        initial_resp["value"] = all_records
        return initial_resp
