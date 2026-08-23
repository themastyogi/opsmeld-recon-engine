"""
Opsmeld Reconciliation Engine - Real AR Manager Module
Deep Accounts Receivable Reconciliation: Live Customer Data, Trapped Cash Analytics, Unapplied Payment Limbo Detection,
and One-Click Fix Staging for Business Central. Strictly operates on live Business Central data.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from core.bc_mcp_client import BCMCPClient
from core.config_loader import load_client_config, load_engine_rules, ClientConfig, EngineRules
from core.ledger_theme import LEDGER_CSS, escape_html


class ARManagerReport:
    def __init__(self, client: BCMCPClient, rules: EngineRules):
        self.client = client
        self.rules = rules.raw_rules.get("ar_manager", {})
        self.critical_days = self.rules.get("tier_critical_overdue_days", 60)
        self.watch_days = self.rules.get("tier_watch_overdue_days", 30)
        self.credit_limit_warning_pct = self.rules.get("credit_limit_warning_pct", 0.85)

    def fetch_data(self) -> Dict[str, Any]:
        """Fetches customer list and deep customer ledger entries from live Business Central MCP server."""
        customers_resp = self.client.call_tool("customers_get_list")
        if "error" in customers_resp:
            return {"error": customers_resp["error"], "customers": []}

        customers = customers_resp.get("value", [])
        if not isinstance(customers, list):
            customers = []

        entries_resp = self.client.call_tool("cust_ledger_entries_get")
        ledger_entries = entries_resp.get("value", []) if isinstance(entries_resp.get("value"), list) else []

        # Attach deep ledger metrics to each customer profile
        for c in customers:
            c_number = c.get("number")
            c_entries = [e for e in ledger_entries if e.get("customer_no") == c_number]
            
            trapped_cash = sum(e.get("amount", 0.0) for e in c_entries if e.get("overdue_days", 0) >= self.critical_days and e.get("doc_type") == "Invoice")
            unapplied_cash = sum(abs(e.get("amount", 0.0)) for e in c_entries if e.get("doc_type") == "Payment" and e.get("open"))
            
            c["trapped_cash"] = trapped_cash
            c["unapplied_cash"] = unapplied_cash
            c["has_unapplied_limbo"] = (unapplied_cash > 0 and c.get("balance_due", 0.0) > 0)
            c["max_overdue_days"] = max([e.get("overdue_days", 0) for e in c_entries] or [0])

        return {"error": None, "customers": customers}

    def tier_customer(self, customer: Dict[str, Any]) -> Dict[str, Any]:
        """Classifies customer into semantic risk tiers: 'collect', 'watch', or 'clear'."""
        balance = float(customer.get("balance_due", 0.0))
        credit_limit = float(customer.get("credit_limit", 0.0))
        trapped = float(customer.get("trapped_cash", 0.0))
        has_limbo = customer.get("has_unapplied_limbo", False)
        
        utilization = (balance / credit_limit) if credit_limit > 0 else 0.0
        
        if utilization >= 1.0 or trapped > 0 or balance > 15000.0:
            tier = "collect"
            tier_label = "COLLECT / CRITICAL"
        elif utilization >= self.credit_limit_warning_pct or has_limbo or balance > 3000.0:
            tier = "watch"
            tier_label = "WATCH / ATTENTION"
        else:
            tier = "clear"
            tier_label = "CLEAR / HEALTHY"

        processed = dict(customer)
        processed["tier"] = tier
        processed["tier_label"] = tier_label
        processed["credit_utilization_pct"] = round(utilization * 100, 1)
        return processed

    def propose_fix(self, customer_no: str) -> Dict[str, Any]:
        """Generates a staged fix action in Business Central for a specific customer discrepancy."""
        res = self.client.call_tool("gen_journal_line_create", {
            "account_no": customer_no,
            "batch_name": "OPSMELD-RECON",
            "description": f"Opsmeld Fix: Unapplied payment matching for {customer_no}"
        })
        return res

    def render_html(self, customers: List[Dict[str, Any]], client_name: str, error_msg: Optional[str] = None) -> str:
        """Renders executive commercial AR Manager dashboard using LEDGER_CSS design system."""
        if error_msg:
            return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Opsmeld AR Manager - Error</title>
    <style>{LEDGER_CSS}</style>
</head>
<body>
    <div style="margin-bottom: 16px;"><a href="/" style="color: var(--text-muted); text-decoration: none;">← Back to Control Center</a></div>
    <h1>Business Central Live Connection Status</h1>
    <div style="background: var(--rust-bg); border: 1px solid var(--rust-border); color: var(--rust-text); border-radius: 8px; padding: 20px; margin-top: 20px;">
        <h3 style="margin-top:0;">⚠️ Live Business Central Query Error</h3>
        <p>{escape_html(error_msg)}</p>
        <p style="font-size:0.9rem; margin-bottom:0;">Please verify your Entra Tenant ID, Client ID, and Business Central MCP Server Configuration settings under <strong>Settings</strong>.</p>
    </div>
</body>
</html>"""

        total_balance = sum(c["balance_due"] for c in customers)
        total_trapped_cash = sum(c.get("trapped_cash", 0.0) for c in customers)
        total_unapplied_limbo = sum(c.get("unapplied_cash", 0.0) for c in customers if c.get("has_unapplied_limbo"))
        
        collect_count = sum(1 for c in customers if c["tier"] == "collect")
        watch_count = sum(1 for c in customers if c["tier"] == "watch")
        clear_count = sum(1 for c in customers if c["tier"] == "clear")

        limbo_customers = [c for c in customers if c.get("has_unapplied_limbo")]
        limbo_banner_html = ""
        if limbo_customers:
            limbo_items = "".join([f"<li><strong>{escape_html(c['name'])} ({c['number']})</strong>: ${c['unapplied_cash']:,.2f} unapplied payment sitting idle against ${c['balance_due']:,.2f} balance due.</li>" for c in limbo_customers])
            limbo_banner_html = f"""
            <div style="background: var(--amber-bg); border: 1px solid var(--amber-border); border-radius: 8px; padding: 16px; margin-bottom: 24px;">
                <h3 style="color: var(--amber-text); margin: 0 0 8px 0;">⚠️ Unapplied Cash Limbo Detected (${total_unapplied_limbo:,.2f})</h3>
                <p style="margin: 0 0 8px 0; font-size: 0.9rem; color: var(--text-main);">The following accounts have open unapplied payments sitting idle while overdue balance exists. Applying these will immediately reduce trapped AR:</p>
                <ul style="margin: 0; padding-left: 20px; font-size: 0.9rem;">
                    {limbo_items}
                </ul>
            </div>
            """

        rows_html = ""
        for c in customers:
            fix_button_html = f"""
            <form method="POST" action="/api/ar-manager/stage-fix" style="display:inline;">
                <input type="hidden" name="customer_no" value="{escape_html(c['number'])}">
                <button type="submit" style="padding: 4px 8px; background: #0E6251; color: white; border: none; border-radius: 4px; font-size: 0.75rem; cursor: pointer;">⚡ Stage Fix</button>
            </form>
            """ if c["tier"] in ["collect", "watch"] else '<span style="color: var(--text-muted); font-size: 0.8rem;">No Action Required</span>'

            rows_html += f"""
            <tr>
                <td class="mono doc-id">{escape_html(c.get('number'))}</td>
                <td><strong>{escape_html(c.get('name'))}</strong></td>
                <td class="mono amount">${c.get('balance_due', 0.0):,.2f}</td>
                <td class="mono amount" style="color: var(--rust-text);">${c.get('trapped_cash', 0.0):,.2f}</td>
                <td class="mono amount" style="color: var(--amber-text);">${c.get('unapplied_cash', 0.0):,.2f}</td>
                <td class="mono">${c.get('credit_limit', 0.0):,.2f}</td>
                <td><span class="stamp stamp-{c['tier']}">{escape_html(c['tier_label'])}</span></td>
                <td>{fix_button_html}</td>
            </tr>
            """

        if not rows_html:
            rows_html = '<tr><td colspan="8" style="text-align:center; padding:24px; color: var(--text-muted);">No customer records found in Business Central.</td></tr>'

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Opsmeld Financial Intelligence - AR Manager - {escape_html(client_name)}</title>
    <style>{LEDGER_CSS}</style>
</head>
<body>
    <div style="margin-bottom: 16px;"><a href="/" style="color: var(--text-muted); text-decoration: none;">← Back to Control Center</a></div>
    <h1>AR Reconciliation & Working Capital Intelligence</h1>
    <p style="color: var(--text-muted);">Client: <strong>{escape_html(client_name)}</strong> | Operational Persona: Accounts Receivable Manager</p>
    
    <div class="stat-grid">
        <div class="stat-tile"><div class="label">Total Outstanding AR</div><div class="value mono">${total_balance:,.2f}</div></div>
        <div class="stat-tile"><div class="label">Trapped AR Cash (>60 Days)</div><div class="value mono" style="color: var(--rust-text);">${total_trapped_cash:,.2f}</div></div>
        <div class="stat-tile"><div class="label">Unapplied Payment Limbo</div><div class="value mono" style="color: var(--amber-text);">${total_unapplied_limbo:,.2f}</div></div>
        <div class="stat-tile"><div class="label">High Risk Accounts</div><div class="value mono" style="color: var(--rust-text);">{collect_count}</div></div>
    </div>

    {limbo_banner_html}

    <div class="ledger-card">
        <h2>Customer Accounts & Action Priority</h2>
        <table class="ledger-table">
            <thead>
                <tr>
                    <th>Customer No.</th>
                    <th>Customer Name</th>
                    <th>Balance Due</th>
                    <th>Trapped Cash (>60D)</th>
                    <th>Unapplied Cash</th>
                    <th>Credit Limit</th>
                    <th>Risk Stamp</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </div>
</body>
</html>"""

    def generate_report(self, output_path: str = "ar_manager_report.html") -> str:
        """Executes full report flow: Fetch -> Tier -> Render -> Write."""
        data = self.fetch_data()
        error_msg = data.get("error")
        customers = data.get("customers", [])
        tiered_customers = [self.tier_customer(c) for c in customers]
        html_out = self.render_html(tiered_customers, self.client.config.name, error_msg=error_msg)
        
        path = Path(output_path)
        path.write_text(html_out, encoding="utf-8")
        return str(path.resolve())


def main():
    config = load_client_config()
    rules = load_engine_rules()
    client = BCMCPClient(config)
    report = ARManagerReport(client, rules)
    report.generate_report()


if __name__ == "__main__":
    main()
