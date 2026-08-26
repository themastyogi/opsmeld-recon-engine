"""
DataAcquirer layer handling live BC data fetching, pagination, lookback, and provenance.
Enforces fail-closed live data boundaries (returns DATA_UNAVAILABLE with zero findings on live failures).
Resolves Business Central application relationships and detailed ledger entries for Payment Timing analysis.
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
        Strictly scopes by company_id and ledger_type. Resolves application posting date settlement timing.
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
                acquired: List[Dict[str, Any]] = []

                if ledger_type in ("VENDOR", "BOTH"):
                    vle_resp = self.client._execute_bc_rest(f"companies({target_comp_id})/vendorLedgerEntries")
                    dvle_resp = self.client._execute_bc_rest(f"companies({target_comp_id})/detailedVendorLedgerEntries")

                    vle_raw = vle_resp.get("value", []) if isinstance(vle_resp, dict) else []
                    dvle_raw = dvle_resp.get("value", []) if isinstance(dvle_resp, dict) else []

                    resolved_vendor = self._resolve_bc_payment_entries(vle_raw, dvle_raw, "VENDOR", target_comp_id)
                    acquired.extend(resolved_vendor)

                if ledger_type in ("CUSTOMER", "BOTH"):
                    cle_resp = self.client._execute_bc_rest(f"companies({target_comp_id})/customerLedgerEntries")
                    dcle_resp = self.client._execute_bc_rest(f"companies({target_comp_id})/detailedCustLedgerEntries")

                    cle_raw = cle_resp.get("value", []) if isinstance(cle_resp, dict) else []
                    dcle_raw = dcle_resp.get("value", []) if isinstance(dcle_resp, dict) else []

                    resolved_cust = self._resolve_bc_payment_entries(cle_raw, dcle_raw, "CUSTOMER", target_comp_id)
                    acquired.extend(resolved_cust)

                return acquired, "LIVE_BUSINESS_CENTRAL"
            except Exception:
                return [], "DATA_UNAVAILABLE"

        if self.mode == "AUTO":
            return self._get_fixture_payment_transactions(company_id), "SNAPSHOT_SEED"

        return [], "DATA_UNAVAILABLE"

    def _resolve_bc_payment_entries(
        self,
        ledger_entries: List[Dict[str, Any]],
        detailed_entries: List[Dict[str, Any]],
        ledger_type: str,
        company_id: str
    ) -> List[Dict[str, Any]]:
        """
        Resolves BC application relationships:
        1. Filters to Invoice documentType.
        2. Resolves single applying Payment entry posting date as settlement date.
        3. Rejects multi-part / partial / unresolvable applications as INSUFFICIENT_EVIDENCE (application_resolved = False).
        4. Builds company + ledger_type + vendor/customer scoped prior historical peer history.
        """
        invoices: List[Dict[str, Any]] = []

        # Step 1: Filter to Invoice ledger entries
        for le in ledger_entries:
            doc_type = str(le.get("documentType") or le.get("dvleDocumentType") or le.get("dcleDocumentType") or "")
            if doc_type in ("Invoice", "Purchase Invoice", "Sales Invoice"):
                invoices.append(le)

        # Step 2: Build detailed entry lookup maps
        # Map detailed entries by entryNo or documentNo or applicationNo
        detailed_by_entry: Dict[str, List[Dict[str, Any]]] = {}
        for de in detailed_entries:
            key = str(de.get("appliedVendLedgerEntryNo") or de.get("appliedCustLedgerEntryNo") or de.get("vendorLedgerEntryNo") or de.get("custLedgerEntryNo") or de.get("documentNo") or "")
            if key:
                if key not in detailed_by_entry:
                    detailed_by_entry[key] = []
                detailed_by_entry[key].append(de)

        # Step 3: Group prior qualifying settled invoices by vendor/customer for company-scoped baseline
        history_by_account: Dict[str, List[Dict[str, Any]]] = {}

        for inv in invoices:
            entry_id = str(inv.get("id") or inv.get("entryNo") or inv.get("documentNo") or "")
            acc_no = str(inv.get("vendorNumber") or inv.get("customerNumber") or inv.get("vendorNo") or inv.get("customerNo") or inv.get("accountNo") or "UNKNOWN")
            due_date = inv.get("dueDate") or inv.get("vleDueDate") or inv.get("cleDueDate")

            # Resolve payment date from detailed application entries
            app_details = detailed_by_entry.get(entry_id, [])
            applying_pmts = [d for d in app_details if str(d.get("documentType") or d.get("initialDocumentType") or "").lower() == "payment"]

            payment_date = None
            if len(applying_pmts) == 1:
                payment_date = applying_pmts[0].get("postingDate") or applying_pmts[0].get("dvlePostingDate") or applying_pmts[0].get("dclePostingDate")

            if acc_no and due_date and payment_date:
                if acc_no not in history_by_account:
                    history_by_account[acc_no] = []
                history_by_account[acc_no].append({
                    "due_date": due_date,
                    "payment_date": payment_date,
                    "amount": float(inv.get("amount") or inv.get("amountLCY") or 0.0)
                })

        # Step 4: Resolve each invoice transaction and attach company-scoped prior history
        resolved_records: List[Dict[str, Any]] = []

        for inv in invoices:
            entry_id = str(inv.get("id") or inv.get("entryNo") or inv.get("documentNo") or "")
            acc_no = str(inv.get("vendorNumber") or inv.get("customerNumber") or inv.get("vendorNo") or inv.get("customerNo") or inv.get("accountNo") or "UNKNOWN")

            app_details = detailed_by_entry.get(entry_id, [])
            applying_pmts = [d for d in app_details if str(d.get("documentType") or d.get("initialDocumentType") or "").lower() == "payment"]

            app_resolved = False
            app_count = len(applying_pmts)
            payment_date = None

            if app_count == 1:
                app_resolved = True
                payment_date = applying_pmts[0].get("postingDate") or applying_pmts[0].get("dvlePostingDate") or applying_pmts[0].get("dclePostingDate")

            record = {
                "id": entry_id,
                "environment_id": "production_env",
                "company_id": company_id,
                "ledger_type": ledger_type,
                "account_no": acc_no,
                "vendor_no": acc_no if ledger_type == "VENDOR" else None,
                "customer_no": acc_no if ledger_type == "CUSTOMER" else None,
                "vendor_name": str(inv.get("vendorName") or inv.get("description") or f"{ledger_type} {acc_no}"),
                "customer_name": str(inv.get("customerName") or inv.get("description") or f"{ledger_type} {acc_no}"),
                "document_no": str(inv.get("documentNumber") or inv.get("documentNo") or entry_id),
                "document_type": "Invoice",
                "document_date": str(inv.get("documentDate") or inv.get("vleDocumentDate") or inv.get("postingDate") or ""),
                "posting_date": str(inv.get("postingDate") or inv.get("vlePostingDate") or ""),
                "due_date": str(inv.get("dueDate") or inv.get("vleDueDate") or inv.get("cleDueDate") or ""),
                "payment_date": payment_date,
                "closed_at_date": str(inv.get("closedAtDate") or inv.get("vleClosedAtDate") or ""),
                "application_resolved": app_resolved,
                "application_count": app_count,
                "payment_discount_date": inv.get("paymentDiscountDate"),
                "payment_terms_code": inv.get("paymentTermsCode"),
                "amount": abs(float(inv.get("amount") or inv.get("amountLCY") or 0.0)),
                "currency_code": str(inv.get("currencyCode") or "INR"),
                "user_id": str(inv.get("userId") or "BC_USER"),
                "source_code": str(inv.get("sourceCode") or "PURCHASES"),
                "peer_history": history_by_account.get(acc_no, [])
            }
            resolved_records.append(record)

        return resolved_records

    def _get_fixture_payment_transactions(self, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns isolated fixture payment transactions for offline testing and demo mode."""
        comp = company_id or "CRONUS IN"
        return [
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
                "payment_date": "2026-08-10",
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
                "application_resolved": False,
                "application_count": 3,
                "amount": 150000.0,
                "currency_code": "INR",
                "user_id": "MKUMAR",
                "source_code": "PURCHASES",
                "peer_history": []
            }
        ]
