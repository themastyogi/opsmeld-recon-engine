"""
Comprehensive Unit Tests for Company GUID Resolution, Caching, and REST Error Handling.
Verifies exact match, 0 match failure, ambiguous match failure, tenant-scoped caching,
http error vs legitimate empty value distinction, and fail-closed DATA_UNAVAILABLE behavior.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import MagicMock
from modules.data_trust_engine.acquisition import CompanyResolver, DataAcquirer


class TestCompanyResolutionAndErrorHandling(unittest.TestCase):

    def setUp(self):
        self.resolver = CompanyResolver()
        self.mock_client = MagicMock()
        self.mock_client.config.tenant_id = "TENANT_101"
        self.mock_client.config.environment = "Production"
        self.mock_client.config.company_name = "CRONUS IN"

    def test_exact_company_name_match_returns_guid(self):
        """1 exact company match returns the exact Business Central GUID."""
        self.mock_client._execute_bc_rest.return_value = {
            "value": [
                {"id": "7e21a83b-4835-ed11-9a84-000d3a2b9186", "name": "CRONUS IN", "displayName": "CRONUS India"}
            ]
        }
        guid = self.resolver.resolve_company_guid(self.mock_client, "CRONUS IN")
        self.assertEqual(guid, "7e21a83b-4835-ed11-9a84-000d3a2b9186")

    def test_zero_company_match_returns_none(self):
        """0 matching companies returns None (fail-closed DATA_UNAVAILABLE)."""
        self.mock_client._execute_bc_rest.return_value = {
            "value": [
                {"id": "7e21a83b-4835-ed11-9a84-000d3a2b9186", "name": "CRONUS IN", "displayName": "CRONUS India"}
            ]
        }
        guid = self.resolver.resolve_company_guid(self.mock_client, "NON_EXISTENT_COMPANY")
        self.assertIsNone(guid)

    def test_ambiguous_company_match_returns_none(self):
        """Multiple (>1) ambiguous company matches return None (does NOT silently choose first)."""
        self.mock_client._execute_bc_rest.return_value = {
            "value": [
                {"id": "GUID-1", "name": "CRONUS IN", "displayName": "CRONUS India"},
                {"id": "GUID-2", "name": "CRONUS IN", "displayName": "CRONUS India Regional"}
            ]
        }
        guid = self.resolver.resolve_company_guid(self.mock_client, "CRONUS IN")
        self.assertIsNone(guid)

    def test_tenant_and_environment_scoped_caching(self):
        """Cache keys are scoped by {tenant_id}:{environment}:{company_name}."""
        self.mock_client.config.tenant_id = "TENANT_A"
        self.mock_client._execute_bc_rest.return_value = {
            "value": [{"id": "GUID-ALPHA", "name": "CRONUS", "displayName": "CRONUS"}]
        }
        guid_a = self.resolver.resolve_company_guid(self.mock_client, "CRONUS")
        self.assertEqual(guid_a, "GUID-ALPHA")

        # Change tenant context to TENANT_B -> must NOT reuse cached GUID from TENANT_A
        self.mock_client.config.tenant_id = "TENANT_B"
        self.mock_client._execute_bc_rest.return_value = {
            "value": [{"id": "GUID-BETA", "name": "CRONUS", "displayName": "CRONUS"}]
        }
        guid_b = self.resolver.resolve_company_guid(self.mock_client, "CRONUS")
        self.assertEqual(guid_b, "GUID-BETA")

    def test_distinguish_legitimate_empty_value_vs_http_error(self):
        """HTTP 200 with value=[] is legitimate empty data; HTTP 400/404/500 is error -> DATA_UNAVAILABLE."""
        acquirer = DataAcquirer(mcp_client=self.mock_client)
        self.mock_client.get_access_token.return_value = "VALID_TOKEN"

        # Mock companies resolution
        self.mock_client._execute_bc_rest.side_effect = lambda path: {
            "companies": {"value": [{"id": "COMP-GUID-99", "name": "CRONUS IN"}]},
            "companies(COMP-GUID-99)/generalLedgerEntries": {"value": []},  # Legitimate empty HTTP 200
            "companies(COMP-GUID-99)/vendorLedgerEntries": {"is_error": True, "http_status": 400, "error": "HTTP 400: RequestDataInvalid", "value": []}
        }.get(path, {"value": []})

        # Legitimate empty GL entries returns LIVE_BUSINESS_CENTRAL with empty list
        gl_txs, gl_prov = acquirer.acquire_transactions()
        self.assertEqual(gl_txs, [])
        self.assertEqual(gl_prov, "LIVE_BUSINESS_CENTRAL")

        # HTTP 400 REST error on vendorLedgerEntries returns DATA_UNAVAILABLE
        pt_txs, pt_prov = acquirer.acquire_payment_transactions(company_id="CRONUS IN")
        self.assertEqual(pt_txs, [])
        self.assertEqual(pt_prov, "DATA_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
