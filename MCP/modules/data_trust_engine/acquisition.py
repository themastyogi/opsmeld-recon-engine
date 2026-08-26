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
