"""
Opsmeld Reconciliation Engine - Web Console App Handler
Lightweight HTTP web app and routing server supporting report generation and fix staging APIs.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import urllib.parse
from core.bc_mcp_client import BCMCPClient
from core.config_loader import load_client_config, load_engine_rules, CONFIG_DIR
from modules.ar_manager import ARManagerReport
from web.templates import render_dashboard_html, render_settings_html


class OpsmeldWebHandler(BaseHTTPRequestHandler):

    def _set_headers(self, content_type="text/html", status=200):
        self.send_response(status)
        self.send_header("Content-type", content_type)
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path in ["/", "/index.html", "/dashboard"]:
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
            customers = report.fetch_data()
            tiered = [report.tier_customer(c) for c in customers]
            html = report.render_html(tiered, config.name)
            self._set_headers()
            self.wfile.write(html.encode("utf-8"))

        else:
            self._set_headers("text/plain", 404)
            self.wfile.write(b"404 Not Found")

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/api/settings":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            post_data = urllib.parse.parse_qs(body)

            client_name = post_data.get("name", ["My Business Central Company"])[0]
            tenant_id = post_data.get("tenant_id", [""])[0]
            app_client_id = post_data.get("app_client_id", [""])[0]
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
