"""
DataAcquirer layer handling live BC data fetching, pagination, lookback, and provenance.
Enforces fail-closed live data boundaries (returns DATA_UNAVAILABLE with zero findings on live failures).
Includes tenant-scoped CompanyResolver for exact Business Central company GUID resolution.
"""
import re
import logging
from typing import Optional, Dict, Any, List, Tuple
from core.bc_mcp_client import BCMCPClient

logger = logging.getLogger("OpsmeldReconEngine.Acquisition")

GUID_REGEX = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class CompanyResolver:
    """
    Tenant/Environment-scoped Business Central Company GUID Resolver with caching.
    Enforces exact matching rules:
    - 1 exact match -> return GUID
    - 0 matches -> return None (DATA_UNAVAILABLE)
    - >1 ambiguous matches -> return None (DATA_UNAVAILABLE)
    Never defaults to first company returned.
    """
    def __init__(self):
        self._cache: Dict[str, str] = {}  # key: {tenant_id}:{environment}:{company_name} -> GUID

    def resolve_company_guid(self, client: BCMCPClient, company_name_or_id: Optional[str] = None) -> Optional[str]:
        if company_name_or_id and GUID_REGEX.match(company_name_or_id):
            return company_name_or_id

        tenant_id = getattr(client.config, "tenant_id", "default_tenant")
        environment = getattr(client.config, "environment", "Production")
        requested_name = company_name_or_id or getattr(client.config, "company_name", None)

        cache_key = f"{tenant_id}:{environment}:{requested_name or 'DEFAULT'}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        comp_resp = client._execute_bc_rest("companies")
        if not isinstance(comp_resp, dict) or comp_resp.get("is_error") or "error" in comp_resp:
            logger.warning(f"Company resolution failed for endpoint 'companies': {comp_resp.get('error')}")
            return None

        comp_list = comp_resp.get("value", []) if isinstance(comp_resp.get("value"), list) else []
        if not comp_list:
            logger.warning(f"Zero companies returned for tenant '{tenant_id}' environment '{environment}'")
            return None

        if not requested_name:
            # If no company name requested, require exactly 1 company in environment
            if len(comp_list) == 1 and comp_list[0].get("id"):
                guid = comp_list[0]["id"]
                self._cache[cache_key] = guid
                return guid
            else:
                logger.warning(f"Ambiguous company resolution: {len(comp_list)} companies exist, but no explicit company name requested.")
                return None

        matches = [
            c for c in comp_list
            if str(c.get("name")).lower() == requested_name.lower()
            or str(c.get("displayName")).lower() == requested_name.lower()
            or str(c.get("id")).lower() == requested_name.lower()
        ]

        if len(matches) == 1 and matches[0].get("id"):
            guid = matches[0]["id"]
            self._cache[cache_key] = guid
            return guid
        elif len(matches) > 1:
            logger.warning(f"Ambiguous company resolution: {len(matches)} matching companies found for name '{requested_name}'.")
            return None
        else:
            logger.warning(f"Zero companies matched requested name '{requested_name}' in tenant '{tenant_id}' environment '{environment}'.")
            return None


class DataAcquirer:
    def __init__(self, mcp_client: Optional[BCMCPClient] = None, mode: str = "AUTO"):
        self.client = mcp_client
        self.mode = mode  # LIVE_BUSINESS_CENTRAL | TEST_FIXTURE | DEMO_FIXTURE | AUTO
        self.company_resolver = CompanyResolver()

    def acquire_transactions(self) -> Tuple[List[Dict[str, Any]], str]:
        """
        Acquires transaction data and returns (transactions, provenance_state).
        On live production runs (mcp_client provided), if BC retrieval fails, returns ([], DATA_UNAVAILABLE).
        Live production runs NEVER fall back to synthetic fixtures.
        """
        if self.mode in ("TEST_FIXTURE", "DEMO_FIXTURE"):
            from modules.data_trust_engine.fixtures import get_sample_transactions
            return get_sample_transactions(), "SNAPSHOT_SEED"

        if self.client:
            token = self.client.get_access_token()
            if not token:
                return [], "DATA_UNAVAILABLE"

            comp_guid = self.company_resolver.resolve_company_guid(self.client)
            if not comp_guid:
                return [], "DATA_UNAVAILABLE"

            try:
                gl_resp = self.client._execute_bc_rest(f"companies({comp_guid})/generalLedgerEntries")
                if isinstance(gl_resp, dict) and not gl_resp.get("is_error") and "error" not in gl_resp and "value" in gl_resp:
                    return gl_resp["value"], "LIVE_BUSINESS_CENTRAL"
                return [], "DATA_UNAVAILABLE"
            except Exception as e:
                logger.error(f"Live G/L acquisition exception: {str(e)}")
                return [], "DATA_UNAVAILABLE"

        return [], "DATA_UNAVAILABLE"

    def acquire_payment_transactions(
        self,
        company_id: Optional[str] = None,
        ledger_type: str = "BOTH"
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Acquires payment and invoice ledger transactions for Payment Timing & Due-Date Compliance analysis.
        Strictly scopes by company_id and ledger_type. Resolves application posting date settlement timing.
        Fail-closed boundary: on live BC query failure or resolution failure, returns ([], "DATA_UNAVAILABLE").
        """
        if self.mode in ("TEST_FIXTURE", "DEMO_FIXTURE"):
            return self._get_fixture_payment_transactions(company_id), "SNAPSHOT_SEED"

        if self.client:
            token = self.client.get_access_token()
            if not token:
                return [], "DATA_UNAVAILABLE"

            comp_guid = self.company_resolver.resolve_company_guid(self.client, company_id)
            if not comp_guid:
                return [], "DATA_UNAVAILABLE"

            try:
                acquired: List[Dict[str, Any]] = []

                if ledger_type in ("VENDOR", "BOTH"):
                    vle_resp = self.client._execute_bc_rest(f"companies({comp_guid})/vendorLedgerEntries")
                    dvle_resp = self.client._execute_bc_rest(f"companies({comp_guid})/detailedVendorLedgerEntries")

                    if isinstance(vle_resp, dict) and (vle_resp.get("is_error") or "error" in vle_resp):
                        logger.error(f"vendorLedgerEntries request failed: {vle_resp.get('error')}")
                        return [], "DATA_UNAVAILABLE"

                    vle_raw = vle_resp.get("value", []) if isinstance(vle_resp, dict) else []
                    dvle_raw = dvle_resp.get("value", []) if isinstance(dvle_resp, dict) and "error" not in dvle_resp else []

                    resolved_vendor = self._resolve_bc_payment_entries(vle_raw, dvle_raw, "VENDOR", comp_guid)
                    acquired.extend(resolved_vendor)

                if ledger_type in ("CUSTOMER", "BOTH"):
                    cle_resp = self.client._execute_bc_rest(f"companies({comp_guid})/customerLedgerEntries")
                    dcle_resp = self.client._execute_bc_rest(f"companies({comp_guid})/detailedCustLedgerEntries")

                    if isinstance(cle_resp, dict) and (cle_resp.get("is_error") or "error" in cle_resp):
                        logger.error(f"customerLedgerEntries request failed: {cle_resp.get('error')}")
                        return [], "DATA_UNAVAILABLE"

                    cle_raw = cle_resp.get("value", []) if isinstance(cle_resp, dict) else []
                    dcle_raw = dcle_resp.get("value", []) if isinstance(dcle_resp, dict) and "error" not in dcle_resp else []

                    resolved_cust = self._resolve_bc_payment_entries(cle_raw, dcle_raw, "CUSTOMER", comp_guid)
                    acquired.extend(resolved_cust)

                return acquired, "LIVE_BUSINESS_CENTRAL"
            except Exception as e:
                logger.error(f"Payment acquisition exception: {str(e)}")
                return [], "DATA_UNAVAILABLE"

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

        for le in ledger_entries:
            doc_type = str(le.get("documentType") or le.get("dvleDocumentType") or le.get("dcleDocumentType") or "")
            if doc_type in ("Invoice", "Purchase Invoice", "Sales Invoice"):
                invoices.append(le)

        detailed_by_entry: Dict[str, List[Dict[str, Any]]] = {}
        for de in detailed_entries:
            key = str(de.get("appliedVendLedgerEntryNo") or de.get("appliedCustLedgerEntryNo") or de.get("vendorLedgerEntryNo") or de.get("custLedgerEntryNo") or de.get("documentNo") or "")
            if key:
                if key not in detailed_by_entry:
                    detailed_by_entry[key] = []
                detailed_by_entry[key].append(de)

        history_by_account: Dict[str, List[Dict[str, Any]]] = {}

        for inv in invoices:
            entry_id = str(inv.get("id") or inv.get("entryNo") or inv.get("documentNo") or "")
            acc_no = str(inv.get("vendorNumber") or inv.get("customerNumber") or inv.get("vendorNo") or inv.get("customerNo") or inv.get("accountNo") or "UNKNOWN")
            due_date = inv.get("dueDate") or inv.get("vleDueDate") or inv.get("cleDueDate")

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

            env_id = self.client.config.environment if (self.client and hasattr(self.client, "config") and getattr(self.client.config, "environment", None)) else "Production"
            record = {
                "id": entry_id,
                "environment_id": env_id,
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
        comp = company_id or "FIXTURE_COMPANY"
        return [
            {
                "id": "PT-VEND-101",
                "environment_id": "test_fixture_env",
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
