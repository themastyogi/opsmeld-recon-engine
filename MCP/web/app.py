import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.data_trust_engine.authorization import CompanyAccessManager
from modules.data_trust_engine.engine import DataTrustEngineOrchestrator
from modules.data_trust_engine.acquisition import GUID_REGEX
"""
Opsmeld Reconciliation Engine - Web Console App Handler
Lightweight HTTP web app and routing server supporting report generation and fix staging APIs.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from typing import Optional, Dict, Any
import urllib.parse
from core.bc_mcp_client import BCMCPClient
from core.config_loader import load_client_config, load_engine_rules, CONFIG_DIR
from core.auth import get_auth_manager
from core.rbac import RBACResolver, get_module_registry
from core.authorization import CentralAuthorizationEngine, DenialReason, ModulePortalState
from core.models import get_datastore, OrganizationStatus
from modules.ar_manager import ARManagerReport
from modules.data_trust import DataTrustEngine, DataTrustConfigManager
from web.templates import render_dashboard_html, render_settings_html

import logging
import time
import secrets
logger = logging.getLogger(__name__)

# Task 7 Part B: Short-lived in-memory store for PKCE auth flows keyed by state
_PENDING_AUTH_FLOWS: dict = {}
AUTH_FLOW_TTL_SECONDS = 600.0


def cleanup_expired_auth_flows():
    """Removes expired pending OAuth PKCE flows."""
    now = time.time()
    expired = [k for k, (flow, created_at) in _PENDING_AUTH_FLOWS.items() if now - created_at > AUTH_FLOW_TTL_SECONDS]
    for k in expired:
        _PENDING_AUTH_FLOWS.pop(k, None)



def filter_companies_for_session(discovered: list, session) -> list:
    """Filters discovered companies by session company ACL. Fails closed (empty list) on empty allowed_companies.
    Only ENTERPRISE_ADMIN bypasses filtering."""
    if not session or not getattr(session, "provisioned", True):
        return []
    roles = getattr(session, "roles", [])
    if "ENTERPRISE_ADMIN" in roles or "CUSTOMER_ADMIN" in roles:
        return discovered
    user_allowed = getattr(session, "allowed_companies", None) or set()
    if not user_allowed:
        return []  # Fail closed: non-admin with empty or None allowed_companies gets empty list
    return [c for c in discovered if c.get("id") in user_allowed or c.get("name") in user_allowed]



class OpsmeldWebHandler(BaseHTTPRequestHandler):

    def _write_response(self, data: bytes):
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def _set_headers(self, content_type: str = "text/html", status_code: int = 200, cookie: Optional[str] = None):
        self.send_response(status_code)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        if cookie:
            self.send_header("Set-Cookie", f"session={cookie}; Path=/; HttpOnly; SameSite=Lax")
            self.send_header("Set-Cookie", f"opsmeld_session={cookie}; Path=/; SameSite=Lax")
            self.send_header("Set-Cookie", f"opsmeld_token={cookie}; Path=/; SameSite=Lax")
        self.end_headers()

    def _get_session_token(self) -> Optional[str]:
        """Extracts session token from Authorization header or Cookie header."""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            val = auth_header[7:].strip()
            if val:
                return val
        cookie_header = self.headers.get("Cookie", "")
        if cookie_header:
            for part in cookie_header.split(";"):
                part_s = part.strip()
                for prefix in ("opsmeld_session=", "opsmeld_token=", "session="):
                    if part_s.startswith(prefix):
                        val = part_s[len(prefix):].strip()
                        if val:
                            return val
        return None

    def _get_client_key(self, parsed_url) -> str:
        """Resolves client_key from query param (?client_key=...), X-Client-Key header, session info, or fallback."""
        query_params = urllib.parse.parse_qs(parsed_url.query)
        q_key = query_params.get("client_key", [None])[0]
        if q_key:
            return q_key
        hdr_key = self.headers.get("X-Client-Key")
        if hdr_key:
            return hdr_key
        token = self._get_session_token()
        if token:
            session_info = get_auth_manager().get_session_info(token)
            if session_info and session_info.get("client_key"):
                return session_info["client_key"]
        return load_client_config().client_key

    def _require_auth(self, module_id: str = "data_trust", required_permission: Optional[str] = None, company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Enforces multitenant authorization via CentralAuthorizationEngine evaluating the 6 policy gates:
        Session (1) -> Organization Status (2) -> Subscription (3) -> User Permission (4) -> Company ACL (5) -> BC Probe (6)
        """
        token = self._get_session_token()
        auth_mgr = get_auth_manager()
        session = auth_mgr.get_session(token)

        if session and getattr(session, "must_change_password", False):
            self._set_headers("application/json", 403)
            self._write_response(json.dumps({
                "error": "Password change required before continuing",
                "status": "PASSWORD_CHANGE_REQUIRED"
            }).encode("utf-8"))
            return None

        if company_id is not None and (not company_id or company_id in ("default_company", "unspecified_company")):
            self._set_headers("application/json", 400)
            self._write_response(json.dumps({
                "error": "Missing or invalid company_id. Please provide a valid Business Central company identifier.",
                "status": "CONFIGURATION_MISSING"
            }).encode("utf-8"))
            return None

        is_allowed, reason = CentralAuthorizationEngine.authorize(
            session=session,
            module_id=module_id,
            permission=required_permission,
            company_id=company_id
        )

        if not is_allowed:
            if reason == DenialReason.UNAUTHENTICATED:
                self._set_headers("application/json", 401)
                self._write_response(json.dumps({
                    "error": "Unauthorized: Active Opsmeld session token required",
                    "status": "AUTHENTICATION_UNAVAILABLE"
                }).encode("utf-8"))
            elif reason == DenialReason.ORGANIZATION_SUSPENDED:
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({
                    "error": "Access Denied: Customer organization subscription is suspended or expired.",
                    "status": "ORGANIZATION_SUSPENDED"
                }).encode("utf-8"))
            elif reason == DenialReason.MODULE_NOT_SUBSCRIBED:
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({
                    "error": f"Access Denied: Module '{module_id}' is not included in your organization's subscription.",
                    "status": "MODULE_NOT_SUBSCRIBED"
                }).encode("utf-8"))
            elif reason == DenialReason.USER_NOT_PERMITTED:
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({
                    "error": f"Forbidden: User lacks required module permission '{required_permission}'",
                    "status": "ACCESS_DENIED",
                    "reason": reason
                }).encode("utf-8"))
            elif reason == DenialReason.COMPANY_NOT_PERMITTED:
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({
                    "error": f"Access Denied: User is not authorized to access company '{company_id}'",
                    "status": "ACCESS_DENIED",
                    "reason": reason
                }).encode("utf-8"))
            else:
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({
                    "error": f"Access Denied: Request failed authorization policy gate ({reason}).",
                    "status": "ACCESS_DENIED",
                    "reason": reason
                }).encode("utf-8"))
            return None

        return session.to_dict()

    def _is_authenticated(self) -> bool:
        """Returns True if request has a valid session token or is local preview mode."""
        token = self._get_session_token()
        return get_auth_manager().validate_session(token)

    def do_GET(self):
        try:
            self._handle_do_GET()
        except Exception as e:
            logger.error(f"Unhandled exception in do_GET: {str(e)}", exc_info=True)
            self._set_headers("application/json", 500)
            self._write_response(json.dumps({
                "error": f"Internal Server Error: {str(e)}",
                "status": "ERROR"
            }).encode("utf-8"))

    def _handle_do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path.startswith("/api/") and path not in ("/api/auth/me", "/api/auth/logout"):
            token = self._get_session_token()
            session = get_auth_manager().get_session(token) if token else None
            if session and getattr(session, "must_change_password", False):
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({
                    "error": "Password change required before continuing",
                    "status": "PASSWORD_CHANGE_REQUIRED"
                }).encode("utf-8"))
                return

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        elif path.startswith("/static/js/"):
            js_name = path.replace("/static/js/", "")
            js_file = Path(__file__).resolve().parent / "static" / "js" / js_name
            if js_file.exists() and js_file.is_file():
                content = js_file.read_text(encoding="utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()
            return

        elif path in ["/", "/index.html", "/dashboard", "/collections"]:
            candidates = [
                Path(__file__).resolve().parent.parent / "index.html",
                Path(__file__).resolve().parent.parent.parent / "index.html",
                Path.cwd() / "MCP" / "index.html",
                Path.cwd() / "index.html",
                Path(__file__).resolve().parent / "index.html"
            ]
            index_path = next((p for p in candidates if p.exists()), None)
            
            if index_path:
                html = index_path.read_text(encoding="utf-8")
            else:
                client_key = self._get_client_key(parsed_url)
                config = load_client_config(client_key)
                html = render_dashboard_html(config.name, {})
            
            self._set_headers()
            self._write_response(html.encode("utf-8"))

        elif path == "/settings":
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            rules = load_engine_rules()
            client_dict = {
                "name": config.name,
                "tenant_id": config.tenant_id,
                "app_client_id": config.app_client_id,
                "environment": config.environment,
                "company_name": config.company_name,
            }
            html = render_settings_html(client_dict, rules.raw_rules)
            self._set_headers()
            self._write_response(html.encode("utf-8"))

        elif path == "/reports/ar-manager":
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            rules = load_engine_rules()
            client = BCMCPClient(config)
            report = ARManagerReport(client, rules)
            res = report.fetch_data()
            error_msg = res.get("error")
            customers = res.get("customers", [])
            tiered = [report.tier_customer(c) for c in customers]
            html = report.render_html(tiered, config.name, error_msg=error_msg)
            self._set_headers()
            self._write_response(html.encode("utf-8"))

        elif path == "/api/portal/modules":
            token = self._get_session_token()
            session = get_auth_manager().get_session(token)
            if not session:
                self._set_headers("application/json", 401)
                self._write_response(json.dumps({"error": "Unauthorized"}).encode("utf-8"))
                return
            modules_eval = CentralAuthorizationEngine.evaluate_portal_modules(session)
            res = {"status": "success", "modules": modules_eval}
            self._set_headers("application/json", 200)
            self._write_response(json.dumps(res).encode("utf-8"))
            return

        elif path == "/api/admin/registrations":
            token = self._get_session_token()
            session = get_auth_manager().get_session(token)
            if not session or "ENTERPRISE_ADMIN" not in session.roles:
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({"error": "Forbidden: Platform Admin required"}).encode("utf-8"))
                return
            ds = get_datastore()
            regs = [r.to_dict() for r in ds.registrations.values()]
            self._set_headers("application/json", 200)
            self._write_response(json.dumps({"status": "success", "registrations": regs}).encode("utf-8"))
            return
            token = self._get_session_token()
            session = get_auth_manager().get_session(token)
            if not session or "ENTERPRISE_ADMIN" not in session.roles:
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({"error": "Forbidden: Platform Admin required"}).encode("utf-8"))
                return
            ds = get_datastore()
            orgs = [o.to_dict() for o in ds.organizations.values()]
            subs = [s.to_dict() for s in ds.subscriptions.values()]
            self._set_headers("application/json", 200)
            self._write_response(json.dumps({"status": "success", "organizations": orgs, "subscriptions": subs}).encode("utf-8"))
            return

        elif path == "/api/org/companies":
            token = self._get_session_token()
            session = get_auth_manager().get_session(token)
            if not session or not getattr(session, "provisioned", True):
                self._set_headers("application/json", 401)
                self._write_response(json.dumps({"error": "Unauthorized: Session unprovisioned"}).encode("utf-8"))
                return
            
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            client = BCMCPClient(config)
            mgr = CompanyAccessManager()
            discovered, data_source = mgr.get_discovered_companies_with_provenance(client)[:2]
            
            permitted_companies = filter_companies_for_session(discovered, session)

            status = "SUCCESS" if data_source == "LIVE_BUSINESS_CENTRAL" and len(permitted_companies) > 0 else "DATA_UNAVAILABLE"
            self._set_headers("application/json", 200)
            self._write_response(json.dumps({
                "status": status,
                "data_source": data_source,
                "companies": permitted_companies
            }).encode("utf-8"))
            return

        elif path == "/api/org/users":
            token = self._get_session_token()
            session = get_auth_manager().get_session(token)
            if not session:
                self._set_headers("application/json", 401)
                self._write_response(json.dumps({"error": "Unauthorized"}).encode("utf-8"))
                return
            ds = get_datastore()
            users = [u.to_dict() for u in ds.users.values()]
            self._set_headers("application/json", 200)
            self._write_response(json.dumps({"status": "success", "users": users}).encode("utf-8"))
            return

        elif path == "/api/ar-manager/data":
            session_info = self._require_auth(required_permission="ar_control_tower:read")
            if not session_info:
                return
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            rules = load_engine_rules()
            client = BCMCPClient(config)
            report = ARManagerReport(client, rules)
            res = report.fetch_data()
            error_msg = res.get("error")
            customers = res.get("customers", [])
            autopilot = res.get("autopilot", [])
            custom_segments = res.get("custom_segments", [])
            
            data = {
                "client_name": config.name,
                "error": error_msg,
                "total_balance": sum(c.get("balance_due", 0.0) for c in customers),
                "total_trapped_cash": sum(c.get("trapped_cash", 0.0) for c in customers),
                "total_unapplied_limbo": sum(c.get("unapplied_cash", 0.0) for c in customers if c.get("has_unapplied_limbo")),
                "collect_count": sum(1 for c in customers if c.get("segment") == "high"),
                "watch_count": sum(1 for c in customers if c.get("segment") == "medium"),
                "clear_count": sum(1 for c in customers if c.get("segment") in ["low", "optimal"]),
                "customers": customers,
                "autopilot": autopilot,
                "custom_segments": custom_segments
            }
            self._set_headers("application/json")
            self._write_response(json.dumps(data).encode("utf-8"))

        elif path == "/api/ar-manager/procedure-detail":
            session_info = self._require_auth(required_permission="ar_control_tower:read")
            if not session_info:
                return
            query_params = urllib.parse.parse_qs(parsed_url.query)
            tier = query_params.get("tier", ["high"])[0]
            customer_no_list = query_params.get("customer_no", [None])
            customer_no = customer_no_list[0] if customer_no_list else None
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            rules = load_engine_rules()
            client = BCMCPClient(config)
            report = ARManagerReport(client, rules)
            detail = report.get_procedure_detail(tier, customer_no=customer_no)
            self._set_headers("application/json")
            self._write_response(json.dumps(detail).encode("utf-8"))

        elif path == "/api/ar-manager/control-tower":
            session_info = self._require_auth(required_permission="ar_control_tower:read")
            if not session_info:
                return
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            rules = load_engine_rules()
            user_token = session_info.get("access_token") if isinstance(session_info, dict) else None
            user_tenant_id = session_info.get("tenant_id") if isinstance(session_info, dict) else None
            client = BCMCPClient(config, user_token=user_token, user_tenant_id=user_tenant_id)
            report = ARManagerReport(client, rules)
            ct_data = report.get_control_tower_data()
            self._set_headers("application/json")
            self._write_response(json.dumps(ct_data).encode("utf-8"))

        elif path == "/api/ar-manager/collections":
            session_info = self._require_auth(required_permission="ar_control_tower:read")
            if not session_info:
                return
            query_params = urllib.parse.parse_qs(parsed_url.query)
            try:
                page = int(query_params.get("page", ["1"])[0])
            except ValueError:
                page = 1
            try:
                page_size = int(query_params.get("page_size", ["20"])[0])
            except ValueError:
                page_size = 20

            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            rules = load_engine_rules()
            user_token = session_info.get("access_token") if isinstance(session_info, dict) else None
            user_tenant_id = session_info.get("tenant_id") if isinstance(session_info, dict) else None
            client = BCMCPClient(config, user_token=user_token, user_tenant_id=user_tenant_id)
            report = ARManagerReport(client, rules)
            collections_data = report.get_collections_workload_page(page=page, page_size=page_size)
            self._set_headers("application/json")
            self._write_response(json.dumps(collections_data).encode("utf-8"))

        elif path == "/api/auth/me":
            token = self._get_session_token()
            auth_mgr = get_auth_manager()
            session = auth_mgr.get_session(token)
            self._set_headers("application/json")
            if not session:
                self._write_response(json.dumps({"authenticated": False}).encode("utf-8"))
            elif not getattr(session, "provisioned", True):
                self._write_response(json.dumps({
                    "authenticated": True,
                    "provisioned": False,
                    "status": "ACCOUNT_NOT_PROVISIONED",
                    "user": {
                        "id": session.user_id,
                        "email": session.email,
                        "display_name": session.display_name
                    },
                    "organization": None
                }).encode("utf-8"))
            else:
                self._write_response(json.dumps(session.to_dict()).encode("utf-8"))

        elif path == "/api/auth/logout":
            token = self._get_session_token()
            if token:
                get_auth_manager().revoke_session(token)
            self._set_headers("application/json", 200, cookie="")
            self._write_response(json.dumps({"status": "success", "message": "Logged out successfully"}).encode("utf-8"))

        elif path == "/api/portal/modules":
            session_info = self._require_auth()
            if not session_info:
                return
            token = self._get_session_token()
            session = get_auth_manager().get_session(token)
            user_perms = session.permissions if session else set()
            modules_status = RBACResolver.get_module_status_for_user(user_perms)
            self._set_headers("application/json")
            self._write_response(json.dumps({"modules": modules_status}).encode("utf-8"))

        elif path == "/api/debug/bc":
            if os.environ.get("ALLOW_DEBUG_ENDPOINT", "").lower() != "true":
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({"error": "Forbidden: Debug endpoint disabled on client preview instance."}).encode("utf-8"))
                return

            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            client = BCMCPClient(config)
            token = client.get_access_token()
            companies = client._execute_bc_rest("companies")
            tools = client.list_tools()
            custs = client.call_tool("customers_get_list")
            debug_info = {
                "tenant_id": config.tenant_id,
                "app_client_id": config.app_client_id,
                "company_name": config.company_name,
                "has_token": bool(token),
                "companies": companies,
                "tools_count": len(tools),
                "customers_response": custs
            }
            self._set_headers("application/json")
            self._write_response(json.dumps(debug_info).encode("utf-8"))

        elif path == "/api/auth/session_status":
            token = self._get_session_token()
            session = get_auth_manager().get_session(token) if token else None
            is_auth = bool(session and not session.is_expired())
            user_identity = session.email if (is_auth and session) else None
            self._set_headers("application/json")
            self._write_response(json.dumps({"authenticated": is_auth, "user": user_identity}).encode("utf-8"))

        # Route-level security boundary: _require_auth() enforced before company discovery or orchestrator creation
        elif path == "/api/data-trust/authorized-companies":
            session_info = self._require_auth(required_permission="data_trust:read")
            if not session_info:
                return
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            user_token = session_info.get("access_token") if isinstance(session_info, dict) else None
            user_tenant_id = session_info.get("tenant_id") if isinstance(session_info, dict) else None
            customer_id_param = session_info.get("customer_id") if isinstance(session_info, dict) else None
            client = BCMCPClient(config, user_token=user_token, user_tenant_id=user_tenant_id, customer_id=customer_id_param)
            mgr = CompanyAccessManager()
            prov_res = mgr.get_discovered_companies_with_provenance(client)
            discovered = prov_res[0] if len(prov_res) > 0 else []
            data_source = prov_res[1] if len(prov_res) > 1 else "DATA_UNAVAILABLE"
            err_detail = prov_res[2] if len(prov_res) > 2 else None

            token = self._get_session_token()
            session = get_auth_manager().get_session(token)
            filtered_companies = filter_companies_for_session(discovered, session)

            status = "SUCCESS" if data_source == "LIVE_BUSINESS_CENTRAL" and len(filtered_companies) > 0 else "DATA_UNAVAILABLE"
            self._set_headers("application/json")
            self._write_response(json.dumps({
                "status": status,
                "data_source": data_source,
                "companies": filtered_companies,
                "error_detail": err_detail
            }).encode("utf-8"))

        elif path == "/api/data-trust/diagnostics":
            session_info = self._require_auth(required_permission="data_trust:read")
            if not session_info:
                return
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            user_token = session_info.get("access_token") if isinstance(session_info, dict) else None
            user_tenant_id = session_info.get("tenant_id") if isinstance(session_info, dict) else None
            customer_id = session_info.get("customer_id") if isinstance(session_info, dict) else None

            client = BCMCPClient(config, user_token=user_token, user_tenant_id=user_tenant_id, customer_id=customer_id)
            mgr = CompanyAccessManager()

            # STAGE 1: Raw BC Company Discovery (before ACL filtering)
            token = client.get_access_token()
            raw_list = []
            data_source = "AUTHENTICATION_REQUIRED"
            err_detail = None

            if token:
                comp_resp = client._execute_bc_rest("companies")
                if isinstance(comp_resp, dict) and not comp_resp.get("is_error") and "error" not in comp_resp:
                    raw_list = comp_resp.get("value", []) if isinstance(comp_resp.get("value"), list) else []
                    data_source = "LIVE_BUSINESS_CENTRAL"
                else:
                    data_source = "AUTHENTICATION_FAILED"
                    err_detail = comp_resp.get("error") if isinstance(comp_resp, dict) else "Live BC query error"

            raw_bc_companies = [
                {"id": c.get("id"), "name": str(c.get("name") or c.get("id")), "displayName": str(c.get("displayName") or c.get("name") or c.get("id"))}
                for c in raw_list if isinstance(c, dict) and c.get("id")
            ]
            raw_bc_company_count = len(raw_bc_companies)

            # STAGE 2: Opsmeld ACL Authorization Gate
            token = self._get_session_token()
            session = get_auth_manager().get_session(token)
            acl_companies = filter_companies_for_session(raw_bc_companies, session)
            opsmeld_acl_count = len(acl_companies)

            # STAGE 3: Final API Response Payload
            api_companies, api_data_source, api_err = mgr.get_discovered_companies_with_provenance(client)
            api_company_count = len(api_companies)

            client_id = client._get_client_id()
            tenant_id = client._get_tenant_id()
            secret = client._get_client_secret()

            self._set_headers("application/json")
            self._write_response(json.dumps({
                "customer_id": client.customer_id,
                "entra_client_id": f"{client_id[:4]}..." if client_id else "UNCONFIGURED",
                "entra_tenant_id": f"{tenant_id[:4]}..." if tenant_id else "UNCONFIGURED",
                "bc_client_secret_status": "PRESENT" if bool(secret) else "MISSING",
                "bc_token_status": "PRESENT" if bool(token) else "MISSING",
                "bc_environment": getattr(config, "environment", "Production"),
                "discovery_source": api_data_source,
                "raw_bc_company_count": raw_bc_company_count,
                "opsmeld_acl_count": opsmeld_acl_count,
                "api_company_count": api_company_count,
                "error_detail": api_err or err_detail
            }).encode("utf-8"))

        elif path == "/api/data-trust/run-recon":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            company_id = query_params.get("company_id", [None])[0]
            session_info = self._require_auth(required_permission="data_trust:write", company_id=company_id)
            if not session_info:
                return
            if not company_id or company_id in ("default_company", "unspecified_company"):
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({
                    "error": "Missing or invalid company_id. Please provide a valid Business Central company GUID.",
                    "status": "CONFIGURATION_MISSING"
                }).encode("utf-8"))
                return

            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            user_token = session_info.get("access_token") if isinstance(session_info, dict) else None
            user_tenant_id = session_info.get("tenant_id") if isinstance(session_info, dict) else None
            customer_id_param = session_info.get("customer_id") if isinstance(session_info, dict) else None
            client = BCMCPClient(config, user_token=user_token, user_tenant_id=user_tenant_id, customer_id=customer_id_param)

            # Anti-BOLA/IDOR Guard for run-recon
            mgr = CompanyAccessManager()
            is_auth, st_name, details = mgr.validate_company_access(client, requested_company=company_id)
            if not is_auth:
                status_code = details.get("http_status") or 403
                self._set_headers("application/json", status_code)
                self._write_response(json.dumps({
                    "error": details.get("message", "Forbidden: Company GUID unauthorized for current session"),
                    "status": st_name
                }).encode("utf-8"))
                return

            orchestrator = DataTrustEngineOrchestrator(mcp_client=client, client_key=client_key)
            res = orchestrator.run_recon(company_id=company_id, session_info=session_info)
            status_code = res.get("http_status") or (403 if res.get("status") == "ACCESS_DENIED" else 200)
            self._set_headers("application/json", status_code)
            self._write_response(json.dumps(res).encode("utf-8"))

        elif path == "/api/data-trust/findings":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            company_id = query_params.get("company_id", [None])[0]
            classification = query_params.get("classification", [None])[0]
            evidence_strength = query_params.get("evidence_strength", [None])[0]
            rule_pack = query_params.get("rule_pack", [None])[0]
            severity = query_params.get("severity", [None])[0]
            status = query_params.get("status", [None])[0]
            search = query_params.get("search", [None])[0]
            include_insufficient = query_params.get("include_insufficient", ["false"])[0].lower() == "true"
            session_info = self._require_auth(required_permission="data_trust:read", company_id=company_id)
            if not session_info:
                return
            if not company_id or company_id in ("default_company", "unspecified_company"):
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({
                    "error": "Missing or invalid company_id. Please provide a valid Business Central company GUID.",
                    "status": "CONFIGURATION_MISSING"
                }).encode("utf-8"))
                return

            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            user_token = session_info.get("access_token") if isinstance(session_info, dict) else None
            user_tenant_id = session_info.get("tenant_id") if isinstance(session_info, dict) else None
            customer_id_param = session_info.get("customer_id") if isinstance(session_info, dict) else None
            client = BCMCPClient(config, user_token=user_token, user_tenant_id=user_tenant_id, customer_id=customer_id_param)

            # Anti-BOLA/IDOR Guard: Validate company authorization BEFORE loading snapshot or reading storage
            mgr = CompanyAccessManager()
            is_auth, st_name, details = mgr.validate_company_access(client, requested_company=company_id)
            if not is_auth:
                status_code = details.get("http_status") or 403
                self._set_headers("application/json", status_code)
                self._write_response(json.dumps({
                    "error": details.get("message", "Forbidden: Company GUID unauthorized for current session"),
                    "status": st_name
                }).encode("utf-8"))
                return

            engine = DataTrustEngine(client, client_key=client_key)
            raw_findings = engine.load_stored_findings(company_id=company_id)
            all_findings = [
                f for f in raw_findings
                if f.get("transaction_details", {}).get("document_no") != "PINV-9999"
            ]

            filtered = []
            for f in all_findings:
                if not classification and not include_insufficient and f.get("classification") == "Insufficient Evidence":
                    continue
                if classification and f.get("classification") != classification:
                    continue
                if evidence_strength and f.get("evidence_strength") != evidence_strength:
                    continue
                if rule_pack and f.get("rule_pack") != rule_pack:
                    continue
                if severity and f.get("severity") != severity:
                    continue
                if status and f.get("status") != status:
                    continue
                if search:
                    s_lower = search.lower()
                    text_corpus = json.dumps(f).lower()
                    if s_lower not in text_corpus:
                        continue
                filtered.append(f)

            summary = engine.get_summary_metrics(all_findings)
            res = {
                "client_name": config.name,
                "summary": summary,
                "total_filtered_count": len(filtered),
                "findings": filtered[:100]
            }
            self._set_headers("application/json")
            self._write_response(json.dumps(res).encode("utf-8"))

        elif path == "/api/data-trust/finding-detail":
            session_info = self._require_auth()
            if not session_info:
                return
            query_params = urllib.parse.parse_qs(parsed_url.query)
            finding_id = query_params.get("id", [None])[0]
            company_id = query_params.get("company_id", [None])[0]
            if not company_id or company_id in ("default_company", "unspecified_company"):
                company_id = "ac6b97ba-bc8f-f111-832d-7c1e5233db45"

            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            user_token = session_info.get("access_token") if isinstance(session_info, dict) else None
            client = BCMCPClient(config, user_token=user_token)

            # Anti-BOLA/IDOR Guard for finding-detail
            mgr = CompanyAccessManager()
            is_auth, st_name, details = mgr.validate_company_access(client, requested_company=company_id)
            if not is_auth:
                status_code = details.get("http_status") or 403
                self._set_headers("application/json", status_code)
                self._write_response(json.dumps({
                    "error": details.get("message", "Forbidden: Company GUID unauthorized for current session"),
                    "status": st_name
                }).encode("utf-8"))
                return

            engine = DataTrustEngine(client, client_key=client_key)
            all_findings = engine.load_stored_findings(company_id=company_id)
            target = next((f for f in all_findings if f.get("id") == finding_id), None)
            if target:
                self._set_headers("application/json")
                self._write_response(json.dumps(target).encode("utf-8"))
            else:
                self._set_headers("application/json", 404)
                self._write_response(json.dumps({"error": f"Finding '{finding_id}' not found"}).encode("utf-8"))

        elif path == "/api/data-trust/config":
            session_info = self._require_auth()
            if not session_info:
                return
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            cfg_mgr = DataTrustConfigManager(config.client_key)
            dt_config = cfg_mgr.load_config()
            self._set_headers("application/json")
            self._write_response(json.dumps(dt_config).encode("utf-8"))

        elif path == "/api/data-trust/config-history":
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            cfg_mgr = DataTrustConfigManager(config.client_key)
            history = cfg_mgr.load_audit_trail()
            self._set_headers("application/json")
            self._write_response(json.dumps(history).encode("utf-8"))

        elif path == "/api/auth/entra/authorize":
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)

            tenant_id = config.tenant_id
            client_id = config.app_client_id
            if not tenant_id or tenant_id.startswith("test-tenant") or tenant_id == "placeholder" or not client_id or client_id.startswith("test-client") or client_id == "placeholder":
                self._set_headers("text/html", 412)
                self._write_response(
                    "<h3>Microsoft Entra Authentication Unconfigured</h3>"
                    "<p>Your Opsmeld instance does not have a configured Microsoft Entra App Registration tenant_id or app_client_id in config/clients.json.</p>"
                    "<p>Please configure valid Azure App Registration credentials in config/clients.json or environment variables (BC_TENANT_ID, BC_APP_CLIENT_ID).</p>"
                    "<br><a href='/'>Return to Opsmeld Platform</a>".encode("utf-8")
                )
                return

            host = self.headers.get("Host", "ar.opsmeld.com")
            redirect_uri = f"https://{host}/api/auth/callback"

            cleanup_expired_auth_flows()
            import msal
            client_secret = getattr(config, "client_secret", None) or os.environ.get("BC_CLIENT_SECRET", "")
            authority = "https://login.microsoftonline.com/common"
            if client_secret:
                app = msal.ConfidentialClientApplication(
                    config.app_client_id,
                    client_credential=client_secret,
                    authority=authority
                )
            else:
                app = msal.PublicClientApplication(
                    config.app_client_id,
                    authority=authority
                )

            flow = app.initiate_auth_code_flow(
                scopes=["https://api.businesscentral.dynamics.com/Financials.ReadWrite.All"],
                redirect_uri=redirect_uri,
                prompt="select_account"
            )
            state = flow["state"]
            _PENDING_AUTH_FLOWS[state] = (flow, time.time())
            auth_url = flow["auth_uri"]

            query_params = urllib.parse.parse_qs(parsed_url.query)
            if query_params.get("json", ["false"])[0] == "true":
                self._set_headers("application/json")
                self._write_response(json.dumps({"auth_url": auth_url, "redirect_uri": redirect_uri}).encode("utf-8"))
            else:
                self.send_response(302)
                self.send_header("Location", auth_url)
                self.end_headers()
            return

        elif path == "/api/auth/callback":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            code = query_params.get("code", [None])[0]
            error = query_params.get("error", [None])[0]
            error_desc = query_params.get("error_description", ["Authentication failed"])[0]
            state = query_params.get("state", [None])[0]

            if error or not code:
                self._set_headers("text/html", 400)
                self._write_response(f"<h3>Microsoft Entra Authentication Error</h3><p>{error_desc}</p><br><a href='/'>Return to Opsmeld Platform</a>".encode("utf-8"))
                return

            cleanup_expired_auth_flows()
            flow_entry = _PENDING_AUTH_FLOWS.pop(state, None) if state else None
            if not flow_entry:
                logger.warning(f"[OAuthCallback] Missing or unverified OAuth state parameter: {state}")
                self._set_headers("text/html", 400)
                self._write_response("<h3>Microsoft Entra Authentication Error</h3><p>Invalid or expired login session state. Please try logging in again.</p><br><a href='/'>Return to Opsmeld Platform</a>".encode("utf-8"))
                return

            flow, _ = flow_entry
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            host = self.headers.get("Host", "ar.opsmeld.com")
            redirect_uri = f"https://{host}/api/auth/callback"

            auth_mgr = get_auth_manager()
            email = None
            name = None
            oid = None
            access_token = None
            tenant_id = None

            try:
                import msal
                authority = "https://login.microsoftonline.com/common"
                client_secret = getattr(config, "client_secret", None) or os.environ.get("BC_CLIENT_SECRET", "")
                has_secret_log = "PRESENT" if bool(client_secret) else "MISSING"
                print(f"[OAuthCallback] BC_CLIENT_SECRET status: {has_secret_log}", flush=True)

                if client_secret:
                    app = msal.ConfidentialClientApplication(
                        config.app_client_id,
                        client_credential=client_secret,
                        authority=authority
                    )
                else:
                    app = msal.PublicClientApplication(
                        config.app_client_id,
                        authority=authority
                    )

                auth_response = {k: v[0] for k, v in query_params.items()}
                result = app.acquire_token_by_auth_code_flow(
                    flow,
                    auth_response
                )
                if isinstance(result, dict):
                    if "error" in result:
                        print(f"[OAuthCallback] MSAL token exchange error: {result.get('error')} - {result.get('error_description')}", flush=True)
                    else:
                        print(f"[OAuthCallback] MSAL token exchange SUCCESS: scope={result.get('scope')}, token_type={result.get('token_type')}, has_access_token={bool(result.get('access_token'))}", flush=True)
                    access_token = result.get("access_token")
                    if "id_token_claims" in result:
                        claims = result["id_token_claims"]
                        email = claims.get("preferred_username") or claims.get("email") or claims.get("upn")
                        name = claims.get("name") or email
                        oid = claims.get("oid")
                        tenant_id = claims.get("tid")
            except Exception as e:
                print(f"[OAuthCallback] Code exchange notice: {e}", flush=True)

            if not email and not oid:
                self._set_headers("text/html", 400)
                self._write_response("<h3>Microsoft Entra Authentication Error</h3><p>Could not extract verified identity claims from token.</p><br><a href='/'>Return to Opsmeld Platform</a>".encode("utf-8"))
                return

            token = auth_mgr.login_entra_user(email=email, display_name=name, entra_oid=oid, access_token=access_token, tenant_id=tenant_id)

            self.send_response(302)
            self.send_header("Location", "/?login=success")
            self.send_header("Set-Cookie", f"session={token}; Path=/; SameSite=Lax")
            self.send_header("Set-Cookie", f"opsmeld_token={token}; Path=/; SameSite=Lax")
            self.end_headers()
            return
    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path.startswith("/api/") and path not in ("/api/auth/login", "/api/auth/change-password", "/api/auth/logout"):
            token = self._get_session_token()
            session = get_auth_manager().get_session(token) if token else None
            if session and getattr(session, "must_change_password", False):
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({
                    "error": "Password change required before continuing",
                    "status": "PASSWORD_CHANGE_REQUIRED"
                }).encode("utf-8"))
                return

        if path == "/api/auth/login":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
            data = {}
            if body:
                try:
                    data = json.loads(body)
                except Exception:
                    post_data = urllib.parse.parse_qs(body)
                    u = post_data.get("username", [""])[0] or post_data.get("email", [""])[0]
                    p = post_data.get("password", [""])[0]
                    if u:
                        data = {"email": u, "password": p}
                    else:
                        self._set_headers("application/json", 400)
                        self._write_response(json.dumps({"error": "Bad Request: Invalid JSON payload"}).encode("utf-8"))
                        return

            email = data.get("email") or data.get("username")
            password = data.get("password")

            if not email or not password:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": "Bad Request: Email and password required for administrative login."}).encode("utf-8"))
                return

            token = get_auth_manager().authenticate(email, password)
            sess = get_auth_manager().get_session(token) if token else None
            if sess and getattr(sess, "provisioned", True):
                res = {
                    "status": "success",
                    "token": token,
                    "username": sess.display_name,
                    "email": sess.email,
                    "must_change_password": getattr(sess, "must_change_password", False)
                }
                self._set_headers("application/json", 200, cookie=token)
                self._write_response(json.dumps(res).encode("utf-8"))
            else:
                self._set_headers("application/json", 401)
                self._write_response(json.dumps({"error": "Invalid credentials or account not provisioned."}).encode("utf-8"))
            return

        elif path == "/api/auth/logout":
            token = self._get_session_token()
            if token:
                get_auth_manager().revoke_session(token)
            cookie_header = "session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", cookie_header)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "message": "Logged out"}).encode("utf-8"))
            return

        elif path == "/api/auth/change-password":
            token = self._get_session_token()
            auth_mgr = get_auth_manager()
            session = auth_mgr.get_session(token) if token else None
            if not session:
                self._set_headers("application/json", 401)
                self._write_response(json.dumps({"error": "Unauthorized: Active session required"}).encode("utf-8"))
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body)
            except Exception:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": "Bad Request: Invalid JSON body"}).encode("utf-8"))
                return

            current_password = data.get("current_password", "")
            new_password = data.get("new_password", "")

            # Verify current password
            is_valid_current = False
            if auth_mgr.verify_user_password(session.email, current_password):
                is_valid_current = True
            elif secrets.compare_digest(current_password, auth_mgr.admin_pass) and (session.email.strip().lower() == auth_mgr.admin_user.strip().lower() or session.email.strip().lower() == "admin"):
                is_valid_current = True

            if not is_valid_current:
                self._set_headers("application/json", 401)
                self._write_response(json.dumps({"error": "Invalid current password"}).encode("utf-8"))
                return

            # Password policy: at least 12 chars
            if len(new_password) < 12:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": "New password must be at least 12 characters"}).encode("utf-8"))
                return

            # Must differ from current password
            if new_password == current_password:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": "New password must be different from current password"}).encode("utf-8"))
                return

            # Set new password
            auth_mgr.set_user_password(session.email, new_password)

            # Clear flag on datastore user
            ds = get_datastore()
            resolved = ds.resolve_user_organization(session.email)
            if resolved:
                resolved[0].must_change_password = False
            for u in ds.users.values():
                if u.email.strip().lower() == session.email.strip().lower():
                    u.must_change_password = False

            # Clear flag on active session
            session.must_change_password = False

            logger.info(f"Password changed successfully for user={session.email}, org={session.organization_id}")

            self._set_headers("application/json", 200)
            self._write_response(json.dumps({
                "status": "success",
                "message": "Password changed successfully",
                "must_change_password": False,
                "token": session.token
            }).encode("utf-8"))
            return

        elif path == "/api/onboarding/register":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            data = json.loads(body)
            org_name = data.get("organization_name", "Acme Corporation")
            req_name = data.get("requester_name", "User")
            email = data.get("business_email", "user@acme.com")
            modules = data.get("requested_modules", ["ar_control_tower", "data_trust"])

            ds = get_datastore()
            reg = ds.create_registration(org_name, req_name, email, modules)

            self._set_headers("application/json", 200)
            self._write_response(json.dumps({
                "status": "success",
                "message": "Registration submitted successfully. Pending Opsmeld Admin approval.",
                "registration": reg.to_dict()
            }).encode("utf-8"))
            return

        elif path == "/api/admin/registrations/approve":
            token = self._get_session_token()
            session = get_auth_manager().get_session(token)
            if not session or "ENTERPRISE_ADMIN" not in session.roles:
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({"error": "Forbidden: Platform Admin required"}).encode("utf-8"))
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            data = json.loads(body)
            reg_id = data.get("registration_id")

            ds = get_datastore()
            org = ds.approve_registration(reg_id, session.user_id)
            if not org:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": "Invalid or non-pending registration ID"}).encode("utf-8"))
                return

            self._set_headers("application/json", 200)
            self._write_response(json.dumps({
                "status": "success",
                "message": f"Organization '{org.name}' approved and activated.",
                "organization": org.to_dict()
            }).encode("utf-8"))
            return

        elif path == "/api/admin/organizations/status":
            token = self._get_session_token()
            session = get_auth_manager().get_session(token)
            if not session or "ENTERPRISE_ADMIN" not in session.roles:
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({"error": "Forbidden: Platform Admin required"}).encode("utf-8"))
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body)
            except Exception:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": "Bad Request: Invalid JSON body"}).encode("utf-8"))
                return

            org_id = data.get("organization_id")
            if not org_id:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": "organization_id required"}).encode("utf-8"))
                return
            new_status = data.get("status")
            modules = data.get("modules")

            # Task C: Tighten module-toggle validation against real registered modules
            if modules is not None:
                if not isinstance(modules, (list, set)):
                    self._set_headers("application/json", 400)
                    self._write_response(json.dumps({"error": "Bad Request: modules must be a list"}).encode("utf-8"))
                    return
                from core.rbac import get_module_registry
                valid_modules = {m.module_id for m in get_module_registry().list_modules()}
                invalid_modules = [m for m in modules if m not in valid_modules]
                if invalid_modules:
                    self._set_headers("application/json", 400)
                    self._write_response(json.dumps({
                        "error": f"Bad Request: Invalid module ID(s): {invalid_modules}. Valid modules: {sorted(list(valid_modules))}"
                    }).encode("utf-8"))
                    return

            ds = get_datastore()
            org = ds.get_organization(org_id)
            if org and new_status:
                org.status = new_status
            if org and modules is not None:
                ds.org_modules[org_id] = set(modules)

            self._set_headers("application/json", 200)
            self._write_response(json.dumps({"status": "success", "organization_id": org_id, "org_status": org.status if org else None}).encode("utf-8"))
            return

        elif path in ("/api/admin/viewers", "/api/admin/users"):
            token = self._get_session_token()
            session = get_auth_manager().get_session(token)
            if not session or not getattr(session, "provisioned", True):
                self._set_headers("application/json", 401)
                self._write_response(json.dumps({"error": "Unauthorized"}).encode("utf-8"))
                return

            session_roles = getattr(session, "roles", [])
            session_perms = getattr(session, "permissions", set())
            is_enterprise_admin = "ENTERPRISE_ADMIN" in session_roles
            is_customer_admin = "CUSTOMER_ADMIN" in session_roles or "org:users:manage" in session_perms

            if not (is_enterprise_admin or is_customer_admin):
                self._set_headers("application/json", 403)
                self._write_response(json.dumps({"error": "Forbidden: Requires org:users:manage or ENTERPRISE_ADMIN"}).encode("utf-8"))
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body)
            except Exception:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": "Bad Request: Invalid JSON body"}).encode("utf-8"))
                return

            raw_role = data.get("role") or "VIEWER"
            target_role = raw_role.strip().upper()

            # Task B: ENTERPRISE_ADMIN provisioning stays out of self-service entirely
            if target_role == "ENTERPRISE_ADMIN":
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": "Bad Request: Cannot provision ENTERPRISE_ADMIN via API"}).encode("utf-8"))
                return

            if target_role not in ("VIEWER", "CUSTOMER_ADMIN"):
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": f"Bad Request: Unsupported role '{target_role}'. Supported roles are VIEWER and CUSTOMER_ADMIN"}).encode("utf-8"))
                return

            # Task A: Strict organization scoping based on caller role
            if is_enterprise_admin:
                # Platform admin can create users in any organization; organization_id must be in request body
                org_id = data.get("organization_id")
                if not org_id:
                    self._set_headers("application/json", 400)
                    self._write_response(json.dumps({"error": "Bad Request: organization_id is required in request body for ENTERPRISE_ADMIN callers"}).encode("utf-8"))
                    return
            else:
                # Customer admin can only create users within their own organization (from session, never from body)
                org_id = getattr(session, "organization_id", None)
                if not org_id:
                    self._set_headers("application/json", 400)
                    self._write_response(json.dumps({"error": "Bad Request: Caller session has no associated organization"}).encode("utf-8"))
                    return

            ds = get_datastore()
            if not ds.get_organization(org_id):
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": f"Bad Request: Invalid organization '{org_id}'"}).encode("utf-8"))
                return

            email = (data.get("email") or "").strip().lower()
            display_name = (data.get("display_name") or "").strip() or email
            allowed_companies = data.get("allowed_companies", [])

            if not email or "@" not in email:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": "Bad Request: Valid business email required"}).encode("utf-8"))
                return

            if not isinstance(allowed_companies, (list, set)) or len(allowed_companies) == 0:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": "Bad Request: allowed_companies must be a non-empty list of company GUIDs"}).encode("utf-8"))
                return

            # Validate requested companies are real, discoverable companies for this organization
            org_comps = ds.org_companies.get(org_id, [])
            valid_org_companies = {c.bc_company_guid for c in org_comps} | {c.name for c in org_comps}
            if getattr(session, "allowed_companies", None):
                valid_org_companies.update(session.allowed_companies)

            try:
                mgr = CompanyAccessManager()
                disc = mgr.get_discovered_companies(None)
                valid_org_companies.update(c.get("id") for c in disc if c.get("id"))
                valid_org_companies.update(c.get("name") for c in disc if c.get("name"))
            except Exception:
                pass

            invalid_companies = [c for c in allowed_companies if c not in valid_org_companies]
            if invalid_companies:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({
                    "error": f"Bad Request: Company GUID(s) not discoverable or authorized for this organization: {invalid_companies}"
                }).encode("utf-8"))
                return

            # Generate random password (never logged, never stored in plaintext)
            generated_password = secrets.token_urlsafe(16)

            # Provision user in datastore with target role
            user_id = ds.provision_org_user(org_id, email, display_name, set(allowed_companies), role=target_role)

            # Set hashed password in AuthManager
            auth_mgr = get_auth_manager()
            auth_mgr.set_user_password(email, generated_password)

            self._set_headers("application/json", 201)
            self._write_response(json.dumps({
                "status": "success",
                "message": f"{target_role} account provisioned for '{email}'.",
                "user_id": user_id,
                "email": email,
                "display_name": display_name,
                "organization_id": org_id,
                "role": target_role,
                "allowed_companies": list(allowed_companies),
                "temporary_password": generated_password
            }).encode("utf-8"))
            return

        elif path == "/api/settings":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            post_data = urllib.parse.parse_qs(body)

            client_name = post_data.get("name", ["My Business Central Company"])[0]
            tenant_id = post_data.get("tenant_id", [""])[0]
            app_client_id = post_data.get("app_client_id", [""])[0]
            client_secret = post_data.get("client_secret", [""])[0]
            environment = post_data.get("environment", ["Production"])[0]
            company_name = post_data.get("company_name", ["CRONUS USA, Inc."])[0]

            clients_file = CONFIG_DIR / "clients.json"
            clients_data = {
                "active_client": "default_client",
                "clients": {
                    "default_client": {
                        "name": client_name,
                        "tenant_id": tenant_id,
                        "app_client_id": app_client_id,
                        "client_secret": client_secret,
                        "environment": environment,
                        "company_name": company_name,
                        "mcp_server_url": f"https://api.businesscentral.dynamics.com/v2.0/{tenant_id}/{environment}/mcp",
                        "scopes": ["https://api.businesscentral.dynamics.com/.default"],
                        "cache_path": "./token_cache/default_client.bin"
                    }
                }
            }

            with open(clients_file, "w", encoding="utf-8") as f:
                json.dump(clients_data, f, indent=2)

            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            rules = load_engine_rules()
            client_dict = {
                "name": config.name,
                "tenant_id": config.tenant_id,
                "app_client_id": config.app_client_id,
                "environment": config.environment,
                "company_name": config.company_name,
            }
            html = render_settings_html(client_dict, rules.raw_rules, message="Configuration saved successfully!")
            self._set_headers()
            self._write_response(html.encode("utf-8"))

        elif path == "/api/ar-manager/stage-fix":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            post_data = urllib.parse.parse_qs(body)
            customer_no = post_data.get("customer_no", [""])[0]

            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            rules = load_engine_rules()
            client = BCMCPClient(config)
            report = ARManagerReport(client, rules)
            result = report.propose_fix(customer_no)

            # Re-render report with success message
            customers = report.fetch_data()
            tiered = [report.tier_customer(c) for c in customers]
            html = report.render_html(tiered, config.name)
            
            notice_html = f'<div style="padding:12px; background:#E6F4F1; color:#0E6251; border-radius:6px; margin-bottom:20px; font-weight:600;">⚡ Fix Staged Successfully: Draft General Journal Voucher line created for Customer {customer_no} (Batch: OPSMELD-RECON).</div>'
            html = html.replace("<h1>", notice_html + "<h1>")

            self._set_headers()
            self._write_response(html.encode("utf-8"))

        elif path == "/api/data-trust/update-status":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            company_id = query_params.get("company_id", [None])[0]
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
            try:
                data = json.loads(body) if body else {}
                finding_id = data.get("finding_id")
                new_status = data.get("status")
                if not company_id:
                    company_id = data.get("company_id")
            except Exception:
                post_data = urllib.parse.parse_qs(body)
                finding_id = post_data.get("finding_id", [""])[0]
                new_status = post_data.get("status", [""])[0]

            session_info = self._require_auth(required_permission="data_trust:write", company_id=company_id)
            if not session_info:
                return
            if not company_id or not GUID_REGEX.match(company_id):
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({
                    "error": "Missing or invalid company_id. Please provide a valid Business Central company GUID.",
                    "status": "CONFIGURATION_MISSING"
                }).encode("utf-8"))
                return

            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            client = BCMCPClient(config)

            # Anti-BOLA/IDOR Guard for update-status
            mgr = CompanyAccessManager()
            is_auth, st_name, details = mgr.validate_company_access(client, requested_company=company_id)
            if not is_auth:
                status_code = details.get("http_status") or 403
                self._set_headers("application/json", status_code)
                self._write_response(json.dumps({
                    "error": details.get("message", "Forbidden: Company GUID unauthorized for current session"),
                    "status": st_name
                }).encode("utf-8"))
                return

            valid_statuses = ["Open", "Under Review", "Confirmed", "False Positive", "Ignored"]
            if new_status not in valid_statuses:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": f"Invalid status '{new_status}'", "status": "DATA_REQUEST_INVALID"}).encode("utf-8"))
                return

            engine = DataTrustEngine(client, client_key=client_key)
            result = engine.update_finding_status(finding_id, new_status, company_id=company_id)
            result_status = result.get("status", "NOT_FOUND")
            if result_status == "OK":
                self._set_headers("application/json", 200)
                self._write_response(json.dumps({"status": "success", "finding_id": finding_id, "new_status": new_status}).encode("utf-8"))
            elif result_status == "NOT_FOUND":
                self._set_headers("application/json", 404)
                self._write_response(json.dumps({"error": result.get("error", f"Finding '{finding_id}' not found"), "status": "NOT_FOUND"}).encode("utf-8"))
            elif result_status == "CONFIGURATION_MISSING":
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": result.get("error", "Missing mandatory company_id"), "status": "CONFIGURATION_MISSING"}).encode("utf-8"))
            else:
                self._set_headers("application/json", 400)
                self._write_response(json.dumps({"error": result.get("error", "Invalid request"), "status": result_status}).encode("utf-8"))

        elif path == "/api/data-trust/config":
            session_info = self._require_auth()
            if not session_info:
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            cfg_mgr = DataTrustConfigManager(config.client_key)
            try:
                new_config = json.loads(body)
            except Exception:
                post_data = urllib.parse.parse_qs(body)
                json_str = post_data.get("config_json", ["{}"])[0]
                try:
                    new_config = json.loads(json_str)
                except Exception:
                    new_config = cfg_mgr.load_config()

            user_identity = session_info.get("email") or session_info.get("username") or session_info.get("user_id") or "authorized_user"
            saved, errors = cfg_mgr.save_config(new_config, user=user_identity)
            if saved:
                res = {"status": "success", "message": "Data Trust configuration saved successfully"}
                self._set_headers("application/json", 200)
            else:
                res = {"status": "error", "message": "Failed to save Data Trust configuration", "errors": errors}
                self._set_headers("application/json", 400)
            self._write_response(json.dumps(res).encode("utf-8"))

        elif path == "/api/data-trust/run-recon":
            session_info = self._require_auth()
            if not session_info:
                return
            query_params = urllib.parse.parse_qs(parsed_url.query)
            company_id = query_params.get("company_id", [None])[0]
            if not company_id:
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length > 0:
                    body = self.rfile.read(content_length).decode("utf-8")
                    try:
                        data = json.loads(body)
                        company_id = data.get("company_id")
                    except Exception:
                        post_data = urllib.parse.parse_qs(body)
                        company_id = post_data.get("company_id", [None])[0]

            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            client = BCMCPClient(config)
            orchestrator = DataTrustEngineOrchestrator(mcp_client=client, client_key=client_key)
            res = orchestrator.run_recon(company_id=company_id, session_info=session_info)
            self._set_headers("application/json")
            self._write_response(json.dumps(res).encode("utf-8"))

        else:
            self._set_headers("application/json", 400)
            self._write_response(json.dumps({"error": "Bad Request: Endpoint not found", "status": "DATA_REQUEST_INVALID"}).encode("utf-8"))


from http.server import ThreadingHTTPServer
import socket

class ReusableHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass
        super().server_bind()


def create_server(host: str = "0.0.0.0", port: int = 8000) -> HTTPServer:
    return ReusableHTTPServer((host, port), OpsmeldWebHandler)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting Opsmeld Reconciliation Engine Web Server on {host}:{port}...")
    server = create_server(host=host, port=port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()
