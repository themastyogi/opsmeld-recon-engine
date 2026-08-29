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

CURRENT_DEVICE_FLOW = None



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
        self.end_headers()

    def _get_session_token(self) -> Optional[str]:
        """Extracts session token from Authorization header or Cookie header."""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            val = auth_header[7:].strip()
            if val:
                return val
        cookie_header = self.headers.get("Cookie", "")
        if "session=" in cookie_header:
            for part in cookie_header.split(";"):
                if part.strip().startswith("session="):
                    val = part.strip().split("=")[1]
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

        if company_id is not None and (not company_id or not GUID_REGEX.match(company_id)):
            self._set_headers("application/json", 400)
            self._write_response(json.dumps({
                "error": "Missing or invalid company_id. Please provide a valid Business Central company GUID.",
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
        global CURRENT_DEVICE_FLOW
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path in ["/", "/index.html", "/dashboard", "/collections"]:
            index_path = Path(__file__).resolve().parent / "index.html"
            if not index_path.exists():
                index_path = Path(__file__).resolve().parent.parent / "index.html"
            
            if index_path.exists():
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
            client = BCMCPClient(config)
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
            client = BCMCPClient(config)
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
            else:
                self._write_response(json.dumps({
                    "authenticated": True,
                    "user": {
                        "id": session.user_id,
                        "email": session.email,
                        "display_name": session.display_name
                    },
                    "roles": sorted(session.roles),
                    "permissions": sorted(list(session.permissions)),
                    "allowed_companies": sorted(list(session.allowed_companies))
                }).encode("utf-8"))

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
            import os
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

        elif path == "/api/auth/login":
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            client = BCMCPClient(config)
            flow = client.start_device_flow()
            CURRENT_DEVICE_FLOW = flow
            self._set_headers("application/json")
            self._write_response(json.dumps(flow).encode("utf-8"))

        elif path == "/api/auth/poll":
            if not CURRENT_DEVICE_FLOW:
                self._set_headers("application/json")
                self._write_response(json.dumps({"status": "error", "message": "No active device flow"}).encode("utf-8"))
            else:
                client_key = self._get_client_key(parsed_url)
                config = load_client_config(client_key)
                client = BCMCPClient(config)
                result = client.complete_device_flow(CURRENT_DEVICE_FLOW)
                if result and result.get("status") == "success":
                    CURRENT_DEVICE_FLOW = None
                self._set_headers("application/json")
                self._write_response(json.dumps(result).encode("utf-8"))

        elif path == "/api/auth/session_status":
            is_auth = self._is_authenticated()
            self._set_headers("application/json")
            self._write_response(json.dumps({"authenticated": is_auth, "user": "admin@opsmeld.com" if is_auth else None}).encode("utf-8"))

        # Route-level security boundary: _require_auth() enforced before company discovery or orchestrator creation
        elif path == "/api/data-trust/authorized-companies":
            session_info = self._require_auth(required_permission="data_trust:read")
            if not session_info:
                return
            client_key = self._get_client_key(parsed_url)
            config = load_client_config(client_key)
            client = BCMCPClient(config)
            mgr = CompanyAccessManager()
            discovered, data_source = mgr.get_discovered_companies_with_provenance(client)
            status = "SUCCESS" if data_source == "LIVE_BUSINESS_CENTRAL" and len(discovered) > 0 else "DATA_UNAVAILABLE"
            self._set_headers("application/json")
            self._write_response(json.dumps({
                "status": status,
                "data_source": data_source,
                "companies": discovered
            }).encode("utf-8"))

        elif path == "/api/data-trust/run-recon":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            company_id = query_params.get("company_id", [None])[0]
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
            company_id = query_params.get("company_id", [None])[0] or query_params.get("c", [None])[0]
            session_info = self._require_auth(required_permission="data_trust:read", company_id=company_id)
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
                if f.get("data_source") not in ("SNAPSHOT_SEED", "TEST_FIXTURE", "DEMO_FIXTURE")
                and f.get("transaction_details", {}).get("document_no") != "PINV-9999"
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
                "findings": filtered
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
    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path in ["/api/auth/login", "/api/auth/login_app"]:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
            token = None
            username = "admin@opsmeld.com"
            display_name = "Vikas Kumar (CRONUS IN)"

            if body:
                try:
                    data = json.loads(body)
                    if "username" in data or "email" in data:
                        u = data.get("username") or data.get("email")
                        p = data.get("password")
                        if u and p:
                            token = get_auth_manager().authenticate(u, p)
                        elif u and u not in ("admin", "admin@opsmeld.com"):
                            token = None
                        else:
                            token = get_auth_manager().login_entra_user(data.get("email"), data.get("display_name"))
                    else:
                        token = get_auth_manager().login_entra_user()
                except Exception:
                    post_data = urllib.parse.parse_qs(body)
                    u = post_data.get("username", [""])[0] or post_data.get("email", [""])[0]
                    p = post_data.get("password", [""])[0]
                    if u and p:
                        token = get_auth_manager().authenticate(u, p)
                    elif u:
                        token = None
                    else:
                        self._set_headers("application/json", 400)
                        self._write_response(json.dumps({"error": "Bad Request: Invalid payload"}).encode("utf-8"))
                        return
            else:
                token = get_auth_manager().login_entra_user()

            if token:
                res = {"status": "success", "token": token, "username": display_name, "email": username}
                self._set_headers("application/json", 200, cookie=token)
                self._write_response(json.dumps(res).encode("utf-8"))
            else:
                res = {"error": "Invalid credentials. Please check your provisioned email and password."}
                self._set_headers("application/json", 401)
                self._write_response(json.dumps(res).encode("utf-8"))
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
            data = json.loads(body)
            org_id = data.get("organization_id", "org_abc_001")
            new_status = data.get("status")
            modules = data.get("modules")

            ds = get_datastore()
            org = ds.get_organization(org_id)
            if org and new_status:
                org.status = new_status
            if org and modules is not None:
                ds.org_modules[org_id] = set(modules)

            self._set_headers("application/json", 200)
            self._write_response(json.dumps({"status": "success", "organization_id": org_id, "org_status": org.status if org else None}).encode("utf-8"))
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

            user_identity = session_info.get("username") or "admin@opsmeld.com"
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

class ReusableHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def create_server(host: str = "0.0.0.0", port: int = 8000) -> HTTPServer:
    return ReusableHTTPServer((host, port), OpsmeldWebHandler)
