"""
DataAcquirer layer handling live BC data fetching, pagination, lookback, and provenance.
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
        On live runs (client present), if BC fails, returns ([], DATA_UNAVAILABLE).
        """
        if self.mode == "TEST_FIXTURE" or self.mode == "DEMO_FIXTURE":
            return [], "SNAPSHOT_SEED"

        if self.client:
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

        # If mcp_client is None in AUTO mode, return SNAPSHOT_SEED for local preview
        return [], "SNAPSHOT_SEED"
