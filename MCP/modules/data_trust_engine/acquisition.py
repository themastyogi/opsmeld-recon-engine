"""
DataAcquirer layer handling live BC data fetching, pagination, lookback, and provenance.
Enforces fail-closed live data boundaries (returns DATA_UNAVAILABLE with zero findings on live failures).
"""
from typing import Optional, Dict, Any, List, Tuple
from core.bc_mcp_client import BCMCPClient


class DataAcquirer:
    def __init__(self, mcp_client: Optional[BCMCPClient] = None, mode: str = "AUTO"):
        self.client = mcp_client
        self.mode = mode  # LIVE_BUSINESS_CENTRAL | TEST_FIXTURE | DEMO_FIXTURE | AUTO

    def acquire_transactions(self) -> Tuple[List[Dict[str, Any]], str]:
        """
        Acquires transaction data and returns (transactions, provenance_state).
        On live production runs (mcp_client provided), if BC retrieval fails, returns ([], DATA_UNAVAILABLE).
        Live production runs NEVER fall back to synthetic fixtures.
        """
        if self.mode in ("TEST_FIXTURE", "DEMO_FIXTURE"):
            from modules.data_trust import DataTrustEngine
            return DataTrustEngine(None)._get_sample_transactions(), "SNAPSHOT_SEED"

        if self.client:
            # Explicit live production run
            token = self.client.get_access_token()
            if not token:
                return [], "DATA_UNAVAILABLE"
            try:
                comp_resp = self.client._execute_bc_rest("companies")
                if isinstance(comp_resp, dict) and "value" in comp_resp and comp_resp["value"]:
                    comp_id = comp_resp["value"][0]["id"]
                    gl_resp = self.client._execute_bc_rest(f"companies({comp_id})/generalLedgerEntries")
                    if isinstance(gl_resp, dict) and "value" in gl_resp and gl_resp["value"]:
                        return gl_resp["value"], "LIVE_BUSINESS_CENTRAL"
            except Exception:
                return [], "DATA_UNAVAILABLE"
            return [], "DATA_UNAVAILABLE"

        # Local offline preview mode (mcp_client is None)
        if self.mode == "AUTO":
            from modules.data_trust import DataTrustEngine
            return DataTrustEngine(None)._get_sample_transactions(), "SNAPSHOT_SEED"

        return [], "DATA_UNAVAILABLE"

    def acquire_payment_transactions(
        self,
        company_id: Optional[str] = None,
        ledger_type: str = "BOTH"
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Acquires payment and invoice ledger transactions for Payment Timing & Due-Date Compliance analysis.
        Strictly scopes by company_id and ledger_type.
        Fail-closed boundary: on live BC query failure, returns ([], "DATA_UNAVAILABLE").
        """
        if self.mode in ("TEST_FIXTURE", "DEMO_FIXTURE"):
            return self._get_fixture_payment_transactions(company_id), "SNAPSHOT_SEED"

        if self.client:
            token = self.client.get_access_token()
            if not token:
                return [], "DATA_UNAVAILABLE"
            try:
                comp_resp = self.client._execute_bc_rest("companies")
                if not (isinstance(comp_resp, dict) and "value" in comp_resp and comp_resp["value"]):
                    return [], "DATA_UNAVAILABLE"

                target_comp_id = company_id or comp_resp["value"][0]["id"]
                fetched_entries: List[Dict[str, Any]] = []

                if ledger_type in ("VENDOR", "BOTH"):
                    vle_resp = self.client._execute_bc_rest(f"companies({target_comp_id})/vendorLedgerEntries")
                    if isinstance(vle_resp, dict) and "value" in vle_resp:
                        for entry in vle_resp["value"]:
                            entry["ledger_type"] = "VENDOR"
                            entry["company_id"] = target_comp_id
                            fetched_entries.append(entry)

                if ledger_type in ("CUSTOMER", "BOTH"):
                    cle_resp = self.client._execute_bc_rest(f"companies({target_comp_id})/customerLedgerEntries")
                    if isinstance(cle_resp, dict) and "value" in cle_resp:
                        for entry in cle_resp["value"]:
                            entry["ledger_type"] = "CUSTOMER"
                            entry["company_id"] = target_comp_id
                            fetched_entries.append(entry)

                return fetched_entries, "LIVE_BUSINESS_CENTRAL"
            except Exception:
                return [], "DATA_UNAVAILABLE"

        if self.mode == "AUTO":
            return self._get_fixture_payment_transactions(company_id), "SNAPSHOT_SEED"

        return [], "DATA_UNAVAILABLE"

    def _get_fixture_payment_transactions(self, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns isolated fixture payment transactions for offline testing and demo mode."""
        comp = company_id or "CRONUS IN"
        return [
            # 1. Vendor Early Payment Anomaly (with 25 prior qualifying settled transactions)
            {
                "id": "PT-VEND-101",
                "environment_id": "production_env",
                "company_id": comp,
                "ledger_type": "VENDOR",
                "account_no": "V00010",
                "vendor_no": "V00010",
                "vendor_name": "Fabrikam Supplies",
                "document_no": "INV-10452",
                "document_type": "Invoice",
                "document_date": "2026-07-20",
                "posting_date": "2026-07-20",
                "due_date": "2026-08-20",
                "payment_date": "2026-08-11",
                "closed_at_date": "2026-08-11",
                "application_resolved": True,
                "application_count": 1,
                "payment_discount_date": "2026-08-15",
                "payment_terms_code": "30 Days",
                "amount": 185000.0,
                "currency_code": "INR",
                "user_id": "MKUMAR",
                "source_code": "PURCHASES",
                "peer_history": [
                    {"payment_date": "2026-07-18", "due_date": "2026-07-20", "amount": 120000.0}
                    for _ in range(25)
                ]
            },
            # 2. Customer Late Payment Policy Violation
            {
                "id": "PT-CUST-202",
                "environment_id": "production_env",
                "company_id": comp,
                "ledger_type": "CUSTOMER",
                "account_no": "C00020",
                "customer_no": "C00020",
                "customer_name": "Global Retail Ltd",
                "document_no": "SINV-80210",
                "document_type": "Invoice",
                "document_date": "2026-07-01",
                "posting_date": "2026-07-01",
                "due_date": "2026-07-31",
                "payment_date": "2026-08-15",
                "closed_at_date": "2026-08-15",
                "application_resolved": True,
                "application_count": 1,
                "payment_discount_date": "2026-07-15",
                "payment_terms_code": "30 Days",
                "amount": 420000.0,
                "currency_code": "INR",
                "user_id": "JSMITH",
                "source_code": "SALES",
                "peer_history": [
                    {"payment_date": "2026-06-30", "due_date": "2026-06-30", "amount": 350000.0}
                    for _ in range(25)
                ]
            },
            # 3. Missed Payment Discount Informational
            {
                "id": "PT-VEND-303",
                "environment_id": "production_env",
                "company_id": comp,
                "ledger_type": "VENDOR",
                "account_no": "V00030",
                "vendor_no": "V00030",
                "vendor_name": "TechComponents Inc",
                "document_no": "PINV-70912",
                "document_type": "Invoice",
                "document_date": "2026-08-01",
                "posting_date": "2026-08-01",
                "due_date": "2026-08-31",
                "payment_date": "2026-08-20",
                "closed_at_date": "2026-08-20",
                "application_resolved": True,
                "application_count": 1,
                "payment_discount_date": "2026-08-10",
                "payment_terms_code": "2/10 Net 30",
                "amount": 95000.0,
                "currency_code": "INR",
                "user_id": "MKUMAR",
                "source_code": "PURCHASES",
                "peer_history": []
            },
            # 4. Sequence Anomaly (Payment Date < Document Date)
            {
                "id": "PT-VEND-404",
                "environment_id": "production_env",
                "company_id": comp,
                "ledger_type": "VENDOR",
                "account_no": "V00040",
                "vendor_no": "V00040",
                "vendor_name": "Apex Logistics",
                "document_no": "PINV-60114",
                "document_type": "Invoice",
                "document_date": "2026-08-15",
                "posting_date": "2026-08-15",
                "due_date": "2026-08-30",
                "payment_date": "2026-08-10",  # Payment date < Document date -> P6
                "closed_at_date": "2026-08-10",
                "application_resolved": True,
                "application_count": 1,
                "payment_terms_code": "15 Days",
                "amount": 34000.0,
                "currency_code": "INR",
                "user_id": "JSMITH",
                "source_code": "PURCHASES",
                "peer_history": []
            },
            # 5. Multiple Application Events / Unresolved Application -> INSUFFICIENT_EVIDENCE MVP Boundary
            {
                "id": "PT-VEND-505",
                "environment_id": "production_env",
                "company_id": comp,
                "ledger_type": "VENDOR",
                "account_no": "V00050",
                "vendor_no": "V00050",
                "vendor_name": "MultiPart Vendor",
                "document_no": "PINV-50999",
                "document_type": "Invoice",
                "document_date": "2026-08-01",
                "posting_date": "2026-08-01",
                "due_date": "2026-08-31",
                "payment_date": "2026-08-25",
                "closed_at_date": "2026-08-25",
                "application_resolved": False,  # Multiple application events
                "application_count": 3,
                "amount": 150000.0,
                "currency_code": "INR",
                "user_id": "MKUMAR",
                "source_code": "PURCHASES",
                "peer_history": []
            }
        ]
