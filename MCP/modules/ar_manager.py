"""
Opsmeld Reconciliation Engine - AR Manager Module (Accounts Receivable)
Analyzes customer balances, flags credit limit & aging risks, and renders interactive AR ledger reports.
"""

from pathlib import Path
from typing import Any, Dict, List
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

    def fetch_data(self) -> List[Dict[str, Any]]:
        """Fetches customer list from Business Central via MCP."""
        response = self.client.call_tool("customers_get_list")
        return response.get("value", [])

    def tier_customer(self, customer: Dict[str, Any]) -> Dict[str, Any]:
        """Classifies customer into semantic tiers: 'collect', 'watch', or 'clear'."""
        balance = float(customer.get("balance_due", 0.0))
        credit_limit = float(customer.get("credit_limit", 0.0))
        
        # Calculate credit utilization ratio
        utilization = (balance / credit_limit) if credit_limit > 0 else 0.0
        
        if utilization >= 1.0 or balance > 10000.0:
            tier = "collect"
            tier_label = "COLLECT / RISK"
        elif utilization >= self.credit_limit_warning_pct or balance > 3000.0:
            tier = "watch"
            tier_label = "WATCH"
        else:
            tier = "clear"
            tier_label = "CLEAR"

        processed = dict(customer)
        processed["tier"] = tier
        processed["tier_label"] = tier_label
        processed["credit_utilization_pct"] = round(utilization * 100, 1)
        return processed

    def render_html(self, customers: List[Dict[str, Any]], client_name: str) -> str:
        """Renders HTML AR Manager report using LEDGER_CSS design system."""
        total_balance = sum(c["balance_due"] for c in customers)
        collect_count = sum(1 for c in customers if c["tier"] == "collect")
        watch_count = sum(1 for c in customers if c["tier"] == "watch")
        clear_count = sum(1 for c in customers if c["tier"] == "clear")

        rows_html = ""
        for c in customers:
            rows_html += f"""
            <tr>
                <td class="mono doc-id">{escape_html(c.get('number'))}</td>
                <td><strong>{escape_html(c.get('name'))}</strong></td>
                <td class="mono amount">${c.get('balance_due', 0.0):,.2f}</td>
                <td class="mono amount">${c.get('credit_limit', 0.0):,.2f}</td>
                <td class="mono">{c['credit_utilization_pct']}%</td>
                <td><span class="stamp stamp-{c['tier']}">{escape_html(c['tier_label'])}</span></td>
            </tr>
            """

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>AR Manager Ledger - {escape_html(client_name)}</title>
    <style>
    {LEDGER_CSS}
    </style>
</head>
<body>
    <h1>Accounts Receivable Manager View</h1>
    <p style="color: var(--text-muted);">Client: <strong>{escape_html(client_name)}</strong> | Operational Persona: AR Collections</p>
    
    <div class="stat-grid">
        <div class="stat-tile">
            <div class="label">Total Outstanding AR</div>
            <div class="value mono">${total_balance:,.2f}</div>
        </div>
        <div class="stat-tile">
            <div class="label">Collect (High Risk)</div>
            <div class="value mono" style="color: var(--rust-text);">{collect_count}</div>
        </div>
        <div class="stat-tile">
            <div class="label">Watch (Attention)</div>
            <div class="value mono" style="color: var(--amber-text);">{watch_count}</div>
        </div>
        <div class="stat-tile">
            <div class="label">Clear (Healthy)</div>
            <div class="value mono" style="color: var(--teal-text);">{clear_count}</div>
        </div>
    </div>

    <div class="ledger-card">
        <h2>Customer Accounts Overview</h2>
        <table class="ledger-table">
            <thead>
                <tr>
                    <th>Customer No.</th>
                    <th>Customer Name</th>
                    <th>Balance Due</th>
                    <th>Credit Limit</th>
                    <th>Limit Used</th>
                    <th>Status Stamp</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
        return html_content

    def generate_report(self, output_path: str = "ar_manager_report.html") -> str:
        """Executes full report flow: Fetch -> Tier -> Render -> Write."""
        raw_customers = self.fetch_data()
        tiered_customers = [self.tier_customer(c) for c in raw_customers]
        html_out = self.render_html(tiered_customers, self.client.config.name)
        
        path = Path(output_path)
        path.write_text(html_out, encoding="utf-8")
        
        counts = {
            "collect": sum(1 for c in tiered_customers if c["tier"] == "collect"),
            "watch": sum(1 for c in tiered_customers if c["tier"] == "watch"),
            "clear": sum(1 for c in tiered_customers if c["tier"] == "clear"),
        }
        print(f"[AR MANAGER REPORT] Generated '{output_path}' for '{self.client.config.name}'. Tiers: {counts}")
        return str(path.resolve())


def main():
    config = load_client_config()
    rules = load_engine_rules()
    client = BCMCPClient(config)
    report = ARManagerReport(client, rules)
    report.generate_report()


if __name__ == "__main__":
    main()
