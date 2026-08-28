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
        ledger_type: str = "BOTH",
        lookback_months: Optional[float] = None
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Acquires payment and invoice ledger transactions for Payment Timing & Due-Date Compliance analysis.
        Strictly scopes by company_id and ledger_type. Resolves application posting date settlement timing.
        Fail-closed boundary: on live BC query failure or resolution failure, returns ([], "DATA_UNAVAILABLE").
        """
        if self.mode in ("TEST_FIXTURE", "DEMO_FIXTURE"):
            txs = self._get_fixture_payment_transactions(company_id)
            if lookback_months is not None and float(lookback_months) > 0:
                txs = self._filter_by_lookback(txs, float(lookback_months))
            return txs, "SNAPSHOT_SEED"

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
                    if isinstance(vle_resp, dict) and (vle_resp.get("is_error") or "error" in vle_resp):
                        logger.warning(f"vendorLedgerEntries endpoint not available ({vle_resp.get('error')}). Querying purchaseInvoices.")
                        vle_resp = self.client._execute_bc_rest(f"companies({comp_guid})/purchaseInvoices")

                    dvle_resp = self.client._execute_bc_rest(f"companies({comp_guid})/detailedVendorLedgerEntries")

                    vle_raw = vle_resp.get("value", []) if isinstance(vle_resp, dict) and "error" not in vle_resp else []
                    dvle_raw = dvle_resp.get("value", []) if isinstance(dvle_resp, dict) and "error" not in dvle_resp else []

                    resolved_vendor = self._resolve_bc_payment_entries(vle_raw, dvle_raw, "VENDOR", comp_guid)
                    acquired.extend(resolved_vendor)

                if ledger_type in ("CUSTOMER", "BOTH"):
                    cle_resp = self.client._execute_bc_rest(f"companies({comp_guid})/customerLedgerEntries")
                    if isinstance(cle_resp, dict) and (cle_resp.get("is_error") or "error" in cle_resp):
                        logger.warning(f"customerLedgerEntries endpoint not available ({cle_resp.get('error')}). Querying salesInvoices.")
                        cle_resp = self.client._execute_bc_rest(f"companies({comp_guid})/salesInvoices")

                    dcle_resp = self.client._execute_bc_rest(f"companies({comp_guid})/detailedCustLedgerEntries")

                    cle_raw = cle_resp.get("value", []) if isinstance(cle_resp, dict) and "error" not in cle_resp else []
                    dcle_raw = dcle_resp.get("value", []) if isinstance(dcle_resp, dict) and "error" not in dcle_resp else []

                    resolved_cust = self._resolve_bc_payment_entries(cle_raw, dcle_raw, "CUSTOMER", comp_guid)
                    acquired.extend(resolved_cust)

                if lookback_months is not None and float(lookback_months) > 0:
                    acquired = self._filter_by_lookback(acquired, float(lookback_months))

                return acquired, "LIVE_BUSINESS_CENTRAL"
            except Exception as e:
                logger.error(f"Payment acquisition exception: {str(e)}")
                return [], "DATA_UNAVAILABLE"

        return [], "DATA_UNAVAILABLE"

    def acquire_inventory_cost_transactions(
        self,
        company_id: Optional[str] = None,
        lookback_months: Optional[int] = None
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Acquires Item Ledger Entries and Value Entries for Inventory Costing analysis.
        Filters acquired population by lookback_months if provided.
        Enforces partial acquisition fail-closed rule: if Item Ledger succeeds but Value Entry fails,
        returns ([], "DATA_UNAVAILABLE").
        """
        if self.mode in ("TEST_FIXTURE", "DEMO_FIXTURE"):
            txs = self._get_fixture_inventory_cost_transactions(company_id)
            if lookback_months is not None and float(lookback_months) > 0:
                txs = self._filter_by_lookback(txs, float(lookback_months))
            return txs, "SNAPSHOT_SEED"

        if self.client:
            token = self.client.get_access_token()
            if not token:
                return [], "DATA_UNAVAILABLE"

            comp_guid = self.company_resolver.resolve_company_guid(self.client, company_id)
            if not comp_guid:
                return [], "DATA_UNAVAILABLE"

            try:
                # Step A: Retrieve Item Ledger Entries
                ile_resp = self.client._execute_bc_rest(f"companies({comp_guid})/itemLedgerEntries")
                if isinstance(ile_resp, dict) and (ile_resp.get("is_error") or "error" in ile_resp):
                    logger.error(f"itemLedgerEntries request failed: {ile_resp.get('error')}")
                    return [], "DATA_UNAVAILABLE"

                # Step B: Retrieve Value Entries (fallback to empty list if endpoint is not published in standard v2.0 API)
                ve_resp = self.client._execute_bc_rest(f"companies({comp_guid})/valueEntries")
                if isinstance(ve_resp, dict) and (ve_resp.get("is_error") or "error" in ve_resp):
                    logger.warning(f"valueEntries endpoint not available ({ve_resp.get('error')}). Proceeding with Item Ledger Entries.")
                    ve_raw = []
                else:
                    ve_raw = ve_resp.get("value", []) if isinstance(ve_resp, dict) else []

                ile_raw = ile_resp.get("value", []) if isinstance(ile_resp, dict) else []
                ve_raw = ve_resp.get("value", []) if isinstance(ve_resp, dict) else []

                env_id = self.client.config.environment if (hasattr(self.client, "config") and getattr(self.client.config, "environment", None)) else "Production"
                resolved_cost_txs = self._resolve_bc_inventory_cost_entries(ile_raw, ve_raw, comp_guid, env_id)
                if lookback_months is not None and float(lookback_months) > 0:
                    resolved_cost_txs = self._filter_by_lookback(resolved_cost_txs, float(lookback_months))
                return resolved_cost_txs, "LIVE_BUSINESS_CENTRAL"
            except Exception as e:
                logger.error(f"Inventory Costing acquisition exception: {str(e)}")
                return [], "DATA_UNAVAILABLE"

        return [], "DATA_UNAVAILABLE"

    def _filter_by_lookback(self, txs: List[Dict[str, Any]], lookback_months: float) -> List[Dict[str, Any]]:
        """Filters transactions by lookback_months relative to latest business date in population."""
        from datetime import datetime, date, timedelta

        def parse_tx_date(tx: Dict[str, Any]) -> Optional[date]:
            d_str = str(tx.get("posting_date") or tx.get("document_date") or tx.get("valuation_date") or "")
            if not d_str:
                return None
            try:
                return datetime.strptime(d_str[:10], "%Y-%m-%d").date()
            except Exception:
                return None

        dates = [parse_tx_date(t) for t in txs]
        valid_dates = [d for d in dates if d]
        if not valid_dates:
            return txs

        ref_date = max(valid_dates)
        cutoff_date = ref_date - timedelta(days=int(lookback_months * 30.4375))

        filtered = []
        for t in txs:
            d = parse_tx_date(t)
            if not d or d >= cutoff_date:
                filtered.append(t)
        return filtered

    def _resolve_bc_inventory_cost_entries(
        self,
        item_ledger_entries: List[Dict[str, Any]],
        value_entries: List[Dict[str, Any]],
        company_id: str,
        environment_id: str
    ) -> List[Dict[str, Any]]:
        """Normalizes Item Ledger & Value Entry payloads and maps cost fields without synthetic string fallbacks."""
        ve_by_ile: Dict[str, List[Dict[str, Any]]] = {}
        for ve in value_entries:
            ile_no = str(ve.get("itemLedgerEntryNo") or ve.get("itemLedgerEntryNo_") or ve.get("entryNo") or "")
            if ile_no:
                if ile_no not in ve_by_ile:
                    ve_by_ile[ile_no] = []
                ve_by_ile[ile_no].append(ve)

        records: List[Dict[str, Any]] = []
        for ile in item_ledger_entries:
            ile_id = str(ile.get("id") or ile.get("entryNo") or ile.get("itemLedgerEntryNo") or "")
            matched_ves = ve_by_ile.get(ile_id, [])

            qty = float(ile.get("quantity")) if ile.get("quantity") is not None else float(ile.get("invoicedQuantity", 0.0))

            act_cost = float(ile.get("costAmountActual") or (matched_ves[0].get("costAmountActual") if matched_ves else 0.0) or 0.0)
            exp_cost = float(ile.get("costAmountExpected") or (matched_ves[0].get("costAmountExpected") if matched_ves else 0.0) or 0.0)
            cost_unit = act_cost / qty if qty > 0 else 0.0

            ve_primary = matched_ves[0] if matched_ves else {}

            rec = {
                "id": f"IC-ILE-{ile_id}",
                "environment_id": environment_id,
                "company_id": company_id,
                "company_name": company_id,
                "item_no": ile.get("itemNo") or ile.get("itemNumber"),
                "item_description": ile.get("description") or ile.get("itemDescription"),
                "location_code": ile.get("locationCode"),
                "variant_code": ile.get("variantCode"),
                "vendor_no": ile.get("sourceNo") or ile.get("vendorNo"),
                "vendor_name": ile.get("sourceName") or ile.get("vendorName"),
                "source_type": ile.get("sourceType"),
                "source_no": ile.get("sourceNo"),
                "item_ledger_entry_no": ile_id,
                "value_entry_no": str(ve_primary.get("entryNo") or ve_primary.get("id") or "") if ve_primary else None,
                "posting_date": ile.get("postingDate"),
                "document_date": ile.get("documentDate") or ile.get("postingDate"),
                "valuation_date": ve_primary.get("valuationDate") or ile.get("postingDate"),
                "document_no": ile.get("documentNo") or ile.get("documentNumber"),
                "document_type": ile.get("documentType"),
                "entry_type": ile.get("entryType"),
                "quantity": qty,
                "invoiced_quantity": float(ile.get("invoicedQuantity")) if ile.get("invoicedQuantity") is not None else qty,
                "cost_per_unit": abs(cost_unit),
                "cost_amount_actual": abs(act_cost),
                "cost_amount_expected": abs(exp_cost),
                "cost_posted_to_gl": float(ve_primary["costPostedToGL"]) if ve_primary and ve_primary.get("costPostedToGL") is not None else None,
                "expected_cost_posted_to_gl": float(ve_primary["expectedCostPostedToGL"]) if ve_primary and ve_primary.get("expectedCostPostedToGL") is not None else None,
                "purchase_amount_actual": float(ve_primary["purchaseAmountActual"]) if ve_primary and ve_primary.get("purchaseAmountActual") is not None else None,
                "purchase_amount_expected": float(ve_primary["purchaseAmountExpected"]) if ve_primary and ve_primary.get("purchaseAmountExpected") is not None else None,
                "expected_cost": float(ve_primary["expectedCost"]) if ve_primary and ve_primary.get("expectedCost") is not None else None,
                "adjustment": ve_primary.get("adjustment"),
                "partial_revaluation": ve_primary.get("partialRevaluation"),
                "average_cost_exception": ve_primary.get("averageCostException"),
                "valued_by_average_cost": ve_primary.get("valuedByAverageCost"),
                "item_charge_no": ve_primary.get("itemChargeNo"),
                "variance_type": ve_primary.get("varianceType"),
                "dimension_set_id": ve_primary.get("dimensionSetID"),
                "source_code": ile.get("sourceCode"),
                "reason_code": ile.get("reasonCode"),
                "currency_code": ile.get("currencyCode") or ve_primary.get("currencyCode")
            }
            records.append(rec)

        return records

    def _get_fixture_inventory_cost_transactions(self, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns synthetic inventory costing transactions for offline testing & demo modes."""
        comp = company_id or "FIXTURE_COMPANY"
        base_records = []
        
        # Build 30 historical baseline entries for Item X + Vendor A (Median = 105.0)
        for i in range(1, 31):
            base_records.append({
                "id": f"IC-BASE-{i}",
                "environment_id": "test_fixture_env",
                "company_id": comp,
                "company_name": comp,
                "item_no": "ITEM-X",
                "item_description": "Industrial Widget X",
                "location_code": "DELHI",
                "variant_code": "DEFAULT",
                "vendor_no": "VENDOR-A",
                "vendor_name": "Fabrikam Supplies",
                "source_type": "Vendor",
                "source_no": "VENDOR-A",
                "item_ledger_entry_no": f"100{i}",
                "value_entry_no": f"200{i}",
                "posting_date": f"2026-07-{min(i, 28):02d}",
                "document_date": f"2026-07-{min(i, 28):02d}",
                "valuation_date": f"2026-07-{min(i, 28):02d}",
                "document_no": f"PINV-10{i}",
                "document_type": "Purchase Invoice",
                "entry_type": "Purchase",
                "quantity": 10.0,
                "invoiced_quantity": 10.0,
                "cost_per_unit": 105.0 + (i % 3),
                "cost_amount_actual": 1050.0,
                "cost_amount_expected": 1050.0,
                "cost_posted_to_gl": 1050.0,
                "expected_cost_posted_to_gl": 1050.0,
                "purchase_amount_actual": 1050.0,
                "purchase_amount_expected": 1050.0,
                "expected_cost": 1050.0,
                "adjustment": False,
                "partial_revaluation": False,
                "average_cost_exception": False,
                "valued_by_average_cost": False,
                "item_charge_no": "",
                "variance_type": "",
                "dimension_set_id": "DIM-1",
                "source_code": "PURCHASES",
                "reason_code": "",
                "currency_code": "INR"
            })

        # Add current transaction: unexplained cost spike (+38% -> 145.0)
        base_records.append({
            "id": "IC-CURR-SPIKE",
            "environment_id": "test_fixture_env",
            "company_id": comp,
            "company_name": comp,
            "item_no": "ITEM-X",
            "item_description": "Industrial Widget X",
            "location_code": "DELHI",
            "variant_code": "DEFAULT",
            "vendor_no": "VENDOR-A",
            "vendor_name": "Fabrikam Supplies",
            "source_type": "Vendor",
            "source_no": "VENDOR-A",
            "item_ledger_entry_no": "1099",
            "value_entry_no": "2099",
            "posting_date": "2026-08-25",
            "document_date": "2026-08-25",
            "valuation_date": "2026-08-25",
            "document_no": "DOC-TEST-INV-1099",
            "document_type": "Purchase Invoice",
            "entry_type": "Purchase",
            "quantity": 10.0,
            "invoiced_quantity": 10.0,
            "cost_per_unit": 145.0,
            "cost_amount_actual": 1450.0,
            "cost_amount_expected": 1450.0,
            "cost_posted_to_gl": 1450.0,
            "expected_cost_posted_to_gl": 1450.0,
            "purchase_amount_actual": 1450.0,
            "purchase_amount_expected": 1450.0,
            "expected_cost": 1450.0,
            "adjustment": False,
            "partial_revaluation": False,
            "average_cost_exception": False,
            "valued_by_average_cost": False,
            "item_charge_no": "",
            "variance_type": "",
            "dimension_set_id": "DIM-1",
            "source_code": "PURCHASES",
            "reason_code": "",
            "currency_code": "INR"
        })

        return base_records

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
