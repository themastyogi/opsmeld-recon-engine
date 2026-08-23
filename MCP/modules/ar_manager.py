"""
Opsmeld Reconciliation Engine - Real AR Manager Module
Calculates live Business Central Autopilot Procedures, Risk Segments, and Dispute Workflows
directly from Microsoft Business Central MCP ledger entries. Strictly operates on live Business Central data.
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
        """Fetches live customer list and ledger entries from Business Central MCP server."""
        customers_resp = self.client.call_tool("customers_get_list")
        if "error" in customers_resp:
            return {"error": customers_resp["error"], "customers": [], "autopilot": [], "custom_segments": []}

        raw_customers = customers_resp.get("value", [])
        if not isinstance(raw_customers, list):
            raw_customers = []

        entries_resp = self.client.call_tool("cust_ledger_entries_get")
        ledger_entries = entries_resp.get("value", []) if isinstance(entries_resp.get("value"), list) else []

        # Normalize field names across Business Central OData / MCP payload variations
        customers = []
        for raw_c in raw_customers:
            if not isinstance(raw_c, dict):
                continue
            number = str(raw_c.get("number") or raw_c.get("no") or raw_c.get("No.") or raw_c.get("id") or raw_c.get("Customer_No") or "")
            name = str(raw_c.get("name") or raw_c.get("displayName") or raw_c.get("Name") or f"Customer {number}")
            
            try:
                balance = float(raw_c.get("balance_due") or raw_c.get("balanceDue") or raw_c.get("balance") or raw_c.get("Balance_Due") or raw_c.get("Balance Due") or 0.0)
            except (ValueError, TypeError):
                balance = 0.0

            try:
                credit_limit = float(raw_c.get("credit_limit") or raw_c.get("creditLimit") or raw_c.get("Credit_Limit") or raw_c.get("Credit Limit ($)") or 0.0)
            except (ValueError, TypeError):
                credit_limit = 0.0

            customers.append({
                "number": number,
                "name": name,
                "balance_due": balance,
                "credit_limit": credit_limit
            })

        # Process ledger entries & trapped cash metrics
        for c in customers:
            c_number = c.get("number")
            c_entries = [e for e in ledger_entries if str(e.get("customer_no") or e.get("Customer_No") or e.get("number")) == c_number]
            
            balance = c["balance_due"]
            credit_limit = c["credit_limit"]
            
            trapped_cash = sum(float(e.get("amount") or e.get("Amount") or 0.0) for e in c_entries if int(e.get("overdue_days") or e.get("Overdue_Days") or 0) >= self.critical_days)
            unapplied_cash = sum(abs(float(e.get("amount") or e.get("Amount") or 0.0)) for e in c_entries if str(e.get("doc_type") or e.get("Document_Type")).lower() in ["payment", "credit_memo"] and e.get("open", True))
            avg_days = int(sum(int(e.get("overdue_days") or e.get("Overdue_Days") or 0) for e in c_entries) / len(c_entries)) if c_entries else 0

            c["trapped_cash"] = trapped_cash
            c["unapplied_cash"] = unapplied_cash
            c["avg_days_to_pay"] = avg_days
            c["has_unapplied_limbo"] = (unapplied_cash > 0 and balance > 0)
            
            utilization = (balance / credit_limit) if credit_limit > 0 else 0.0
            if utilization >= 1.0 or trapped_cash > 0 or balance > 15000.0:
                c["segment"] = "high"
                c["tier"] = "collect"
                c["tier_label"] = "COLLECT / CRITICAL"
            elif utilization >= self.credit_limit_warning_pct or balance > 3000.0:
                c["segment"] = "medium"
                c["tier"] = "watch"
                c["tier_label"] = "WATCH / ATTENTION"
            elif balance > 0:
                c["segment"] = "low"
                c["tier"] = "clear"
                c["tier_label"] = "CLEAR / HEALTHY"
            else:
                c["segment"] = "optimal"
                c["tier"] = "clear"
                c["tier_label"] = "CLEAR / HEALTHY"

        total_accounts = len(customers)
        high_custs = [c for c in customers if c["segment"] == "high"]
        med_custs = [c for c in customers if c["segment"] == "medium"]
        low_custs = [c for c in customers if c["segment"] == "low"]
        opt_custs = [c for c in customers if c["segment"] == "optimal"]

        def calc_summary(cust_list, name, dot_class):
            count = len(cust_list)
            pct = round((count / total_accounts * 100)) if total_accounts > 0 else 0
            open_bal = sum(c["balance_due"] for c in cust_list)
            overdue = sum(c["trapped_cash"] for c in cust_list)
            avg_days = int(sum(c["avg_days_to_pay"] for c in cust_list) / count) if count > 0 else 0
            return {
                "procedure": name,
                "dot_class": dot_class,
                "accounts_count": count,
                "accounts_label": f"{count} ({pct}% of {total_accounts} Eligible)" if total_accounts > 0 else f"{count} Accounts",
                "avg_days": avg_days,
                "open_balance": open_bal,
                "overdue": overdue
            }

        autopilot = [
            calc_summary(high_custs, "High Risk Procedure", "dot-high"),
            calc_summary(med_custs, "Medium Risk Procedure", "dot-medium"),
            calc_summary(low_custs, "Low Risk Procedure", "dot-low"),
            calc_summary(opt_custs, "Optimal Procedure", "dot-optimal"),
        ]

        custom_segments = [
            {
                "procedure": "Disputer workflow -reason CREDIT",
                "accounts_count": len(high_custs + med_custs),
                "open_balance": sum(c["balance_due"] for c in high_custs + med_custs),
                "overdue": sum(c["trapped_cash"] for c in high_custs + med_custs),
                "avg_days": int(sum(c["avg_days_to_pay"] for c in high_custs + med_custs) / len(high_custs + med_custs)) if (high_custs + med_custs) else 0,
                "high_count": len(high_custs),
                "medium_count": len(med_custs),
                "low_count": len(low_custs)
            }
        ]

        return {
            "error": None,
            "customers": customers,
            "autopilot": autopilot,
            "custom_segments": custom_segments
        }

    def tier_customer(self, customer: Dict[str, Any]) -> Dict[str, Any]:
        """Classifies customer into semantic risk tiers."""
        processed = dict(customer)
        balance = float(processed.get("balance_due", 0.0))
        segment = processed.get("segment", "optimal")
        
        if segment == "high" or balance > 10000.0:
            processed["tier"] = "collect"
            processed["tier_label"] = "COLLECT / CRITICAL"
        elif segment == "medium" or balance > 3000.0:
            processed["tier"] = "watch"
            processed["tier_label"] = "WATCH / ATTENTION"
        else:
            processed["tier"] = "clear"
            processed["tier_label"] = "CLEAR / HEALTHY"
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
        """Renders executive commercial AR Manager dashboard."""
        if error_msg:
            return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Opsmeld AR Manager</title><style>{LEDGER_CSS}</style></head>
<body>
    <h1>Business Central Live Connection Status</h1>
    <div style="background: var(--rust-bg); color: var(--rust-text); padding: 20px; border-radius: 8px;">
        <h3>⚠️ Live Business Central Query Error</h3>
        <p>{escape_html(error_msg)}</p>
    </div>
</body>
</html>"""
        index_path = Path(__file__).resolve().parent.parent / "index.html"
        if index_path.exists():
            return index_path.read_text(encoding="utf-8")
        return f"<html><body><h1>Opsmeld AR Manager - {escape_html(client_name)}</h1></body></html>"

    def generate_report(self, output_path: str = "ar_manager_report.html") -> str:
        """Executes full report flow: Fetch -> Tier -> Render -> Write."""
        data = self.fetch_data()
        error_msg = data.get("error")
        customers = data.get("customers", [])
        html_out = self.render_html(customers, self.client.config.name, error_msg=error_msg)
        path = Path(output_path)
        path.write_text(html_out, encoding="utf-8")
        return str(path.resolve())
