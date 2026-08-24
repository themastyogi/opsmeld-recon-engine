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
from modules.ar_manager import ARManagerReport
from web.templates import render_dashboard_html, render_settings_html

CURRENT_DEVICE_FLOW = None



class OpsmeldWebHandler(BaseHTTPRequestHandler):

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
        """Extracts session token from Cookie header or Authorization header."""
        cookie_header = self.headers.get("Cookie", "")
        if "session=" in cookie_header:
            for part in cookie_header.split(";"):
                if part.strip().startswith("session="):
                    return part.strip().split("=")[1]
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:].strip()
        return None

    def _is_authenticated(self) -> bool:
        """Returns True if request has a valid session token or is local preview mode."""
        token = self._get_session_token()
        return get_auth_manager().validate_session(token)

    def do_GET(self):
        global CURRENT_DEVICE_FLOW
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path in ["/", "/index.html", "/dashboard", "/collections"]:
            index_path = Path(__file__).resolve().parent.parent / "index.html"
            if not index_path.exists():
                index_path = Path(__file__).resolve().parent.parent.parent / "index.html"
            
            if index_path.exists():
                html = index_path.read_text(encoding="utf-8")
            else:
                config = load_client_config()
                html = render_dashboard_html(config.name, {})
            
            self._set_headers()
            self.wfile.write(html.encode("utf-8"))

        elif path == "/settings":
            config = load_client_config()
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
            self.wfile.write(html.encode("utf-8"))

        elif path == "/reports/ar-manager":
            config = load_client_config()
            rules = load_engine_rules()
            client = BCMCPClient(config)
            report = ARManagerReport(client, rules)
            res = report.fetch_data()
            error_msg = res.get("error")
            customers = res.get("customers", [])
            tiered = [report.tier_customer(c) for c in customers]
            html = report.render_html(tiered, config.name, error_msg=error_msg)
            self._set_headers()
            self.wfile.write(html.encode("utf-8"))

        elif path == "/api/ar-manager/data":
            config = load_client_config()
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
            self.wfile.write(json.dumps(data).encode("utf-8"))

        elif path == "/api/ar-manager/procedure-detail":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            tier = query_params.get("tier", ["high"])[0]
            customer_no_list = query_params.get("customer_no", [None])
            customer_no = customer_no_list[0] if customer_no_list else None
            config = load_client_config()
            rules = load_engine_rules()
            client = BCMCPClient(config)
            report = ARManagerReport(client, rules)
            detail = report.get_procedure_detail(tier, customer_no=customer_no)
            self._set_headers("application/json")
            self.wfile.write(json.dumps(detail).encode("utf-8"))

        elif path == "/api/ar-manager/control-tower":
            config = load_client_config()
            rules = load_engine_rules()
            client = BCMCPClient(config)
            report = ARManagerReport(client, rules)
            ct_data = report.get_control_tower_data()
            self._set_headers("application/json")
            self.wfile.write(json.dumps(ct_data).encode("utf-8"))

        elif path == "/api/ar-manager/collections":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            try:
                page = int(query_params.get("page", ["1"])[0])
            except ValueError:
                page = 1
            try:
                page_size = int(query_params.get("page_size", ["20"])[0])
            except ValueError:
                page_size = 20

            config = load_client_config()
            rules = load_engine_rules()
            client = BCMCPClient(config)
            report = ARManagerReport(client, rules)
            collections_data = report.get_collections_workload_page(page=page, page_size=page_size)
            self._set_headers("application/json")
            self.wfile.write(json.dumps(collections_data).encode("utf-8"))

        elif path == "/api/debug/bc":
            import os
            if os.environ.get("ALLOW_DEBUG_ENDPOINT", "").lower() != "true":
                self._set_headers("application/json", 403)
                self.wfile.write(json.dumps({"error": "Forbidden: Debug endpoint disabled on client preview instance."}).encode("utf-8"))
                return

            config = load_client_config()
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
            self.wfile.write(json.dumps(debug_info).encode("utf-8"))

        elif path == "/api/auth/login":
            config = load_client_config()
            client = BCMCPClient(config)
            flow = client.start_device_flow()
            CURRENT_DEVICE_FLOW = flow
            self._set_headers("application/json")
            self.wfile.write(json.dumps(flow).encode("utf-8"))

        elif path == "/api/auth/poll":
            if not CURRENT_DEVICE_FLOW:
                self._set_headers("application/json")
                self.wfile.write(json.dumps({"status": "error", "message": "No active device flow"}).encode("utf-8"))
            else:
                config = load_client_config()
                client = BCMCPClient(config)
                result = client.complete_device_flow(CURRENT_DEVICE_FLOW)
                if result and result.get("status") == "success":
                    CURRENT_DEVICE_FLOW = None
                self._set_headers("application/json")
                self.wfile.write(json.dumps(result).encode("utf-8"))

        elif path == "/api/auth/session_status":
            is_auth = self._is_authenticated()
            self._set_headers("application/json")
            self.wfile.write(json.dumps({"authenticated": is_auth, "user": "admin@opsmeld.com" if is_auth else None}).encode("utf-8"))

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/api/auth/login_app":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                username = data.get("username", "")
                password = data.get("password", "")
            except Exception:
                post_data = urllib.parse.parse_qs(body)
                username = post_data.get("username", [""])[0]
                password = post_data.get("password", [""])[0]

            token = get_auth_manager().authenticate(username, password)
            if token:
                res = {"status": "success", "token": token, "username": username}
                self._set_headers("application/json", 200, cookie=token)
                self.wfile.write(json.dumps(res).encode("utf-8"))
            else:
                res = {"error": "Invalid credentials. Please check your provisioned email and password."}
                self._set_headers("application/json", 401)
                self.wfile.write(json.dumps(res).encode("utf-8"))
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/api/settings":
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

            config = load_client_config()
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
            self.wfile.write(html.encode("utf-8"))

        elif path == "/api/ar-manager/stage-fix":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            post_data = urllib.parse.parse_qs(body)
            customer_no = post_data.get("customer_no", [""])[0]

            config = load_client_config()
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
            self.wfile.write(html.encode("utf-8"))

        else:
            self._set_headers("text/plain", 400)
            self.wfile.write(b"400 Bad Request")


class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def create_server(host: str = "0.0.0.0", port: int = 8000) -> HTTPServer:
    return ReusableHTTPServer((host, port), OpsmeldWebHandler)
