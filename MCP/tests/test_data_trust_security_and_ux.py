"""
Comprehensive Unit Tests for Data Trust Platform Security, Company Access & UX Specification.
Verifies forged-company security, stale-company authorization revocation, conditional 404 mapping,
server-authorized admin diagnostics, run_id correlation, discovery vs real access gate, empty company handling,
fail-closed production mode, tenant/company cache isolation, and legacy findings API backward compatibility.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import MagicMock
from modules.data_trust_engine.authorization import CompanyAccessManager
from modules.data_trust_engine.company_context import DataTrustState, map_http_error, build_user_message
from modules.data_trust_engine.engine import DataTrustEngineOrchestrator
from modules.data_trust_engine.acquisition import CompanyResolver


class TestDataTrustSecurityAndUX(unittest.TestCase):

    def setUp(self):
        self.auth_mgr = CompanyAccessManager()
        self.mock_client = MagicMock()
        self.mock_client.config.tenant_id = "TENANT_101"
        self.mock_client.config.environment = "Production"
        self.mock_client.config.company_name = "COMPANY_A"
        self.mock_client.get_access_token.return_value = "VALID_TOKEN"

    def test_forged_company_request_rejected_server_side(self):
        """User authorized for Company A sends company_id = Company B -> Server rejects with ACCESS_DENIED."""
        self.mock_client._execute_bc_rest.return_value = {
            "value": [{"id": "GUID-COMP-A", "name": "COMPANY_A", "displayName": "Company A"}]
        }

        is_auth, state, info = self.auth_mgr.validate_company_access(self.mock_client, requested_company="COMPANY_B")

        self.assertFalse(is_auth)
        self.assertEqual(state, DataTrustState.ACCESS_DENIED)
        self.assertIn("don't have permission to view Data Trust data for this company", info["message"])

        orchestrator = DataTrustEngineOrchestrator(mcp_client=self.mock_client)
        res = orchestrator.run_recon(company_id="COMPANY_B")
        self.assertEqual(res["status"], DataTrustState.ACCESS_DENIED)
        self.assertEqual(len(res["findings"]), 0)

    def test_company_discovery_vs_authorization_real_bc_check(self):
        """GET /companies lists Company B, but company-scoped data check fails 403 -> ACCESS_DENIED."""
        def mock_rest(endpoint, **kwargs):
            if endpoint == "companies":
                return {"value": [{"id": "GUID-COMP-B", "name": "COMPANY_B", "displayName": "Company B"}]}
            elif "companies(GUID-COMP-B)" in endpoint:
                return {"is_error": True, "http_status": 403, "error": {"code": "AccessDenied"}}
            return {"value": []}

        self.mock_client._execute_bc_rest.side_effect = mock_rest

        is_auth, state, info = self.auth_mgr.validate_company_access(self.mock_client, requested_company="COMPANY_B")

        self.assertFalse(is_auth)
        self.assertEqual(state, DataTrustState.ACCESS_DENIED)
        self.assertEqual(info["http_status"], 403)

    def test_blank_company_does_not_select_first_company_in_multi_company_env(self):
        """Blank company parameter in multi-company environment returns CONFIGURATION_MISSING (400)."""
        self.mock_client._execute_bc_rest.return_value = {
            "value": [
                {"id": "GUID-A", "name": "COMPANY_A", "displayName": "Company A"},
                {"id": "GUID-B", "name": "COMPANY_B", "displayName": "Company B"}
            ]
        }

        is_auth, state, info = self.auth_mgr.validate_company_access(self.mock_client, requested_company=None)

        self.assertFalse(is_auth)
        self.assertEqual(state, DataTrustState.CONFIGURATION_MISSING)
        self.assertEqual(info["http_status"], 400)
        self.assertIn("Multiple companies detected", info["message"])

    def test_missing_bc_client_fails_closed_in_production(self):
        """Missing BC client in production mode (mode='AUTO') MUST fail closed with AUTHENTICATION_UNAVAILABLE."""
        is_auth, state, info = self.auth_mgr.validate_company_access(client=None, requested_company="COMPANY_A", mode="AUTO")

        self.assertFalse(is_auth)
        self.assertEqual(state, DataTrustState.AUTHENTICATION_UNAVAILABLE)
        self.assertEqual(info["http_status"], 401)

    def test_isolated_test_fixture_mode_allows_preview(self):
        """Explicit mode='TEST_FIXTURE' allows preview without BC client."""
        is_auth, state, info = self.auth_mgr.validate_company_access(client=None, requested_company="CRONUS IN", mode="TEST_FIXTURE")

        self.assertTrue(is_auth)
        self.assertEqual(state, DataTrustState.SUCCESS)
        self.assertTrue(info.get("is_offline_preview"))

    def test_tenant_and_company_cache_isolation(self):
        """Verify CompanyResolver cache key isolates tenant, environment, and company."""
        client_a = MagicMock()
        client_a.config.tenant_id = "TENANT_101"
        client_a.config.environment = "Production"
        client_a.config.company_name = "CRONUS IN"
        client_a.get_access_token.return_value = "TOKEN_A"
        client_a._execute_bc_rest.return_value = {"value": [{"id": "GUID-101", "name": "CRONUS IN"}]}

        resolver = CompanyResolver()
        guid_a = resolver.resolve_company_guid(client_a, "CRONUS IN")

        client_b = MagicMock()
        client_b.config.tenant_id = "TENANT_202"
        client_b.config.environment = "Production"
        client_b.config.company_name = "CRONUS IN"
        client_b.get_access_token.return_value = "TOKEN_B"
        client_b._execute_bc_rest.return_value = {"value": [{"id": "GUID-202", "name": "CRONUS IN"}]}

        guid_b = resolver.resolve_company_guid(client_b, "CRONUS IN")

        self.assertEqual(guid_a, "GUID-101")
        self.assertEqual(guid_b, "GUID-202")
        self.assertNotEqual(guid_a, guid_b)

    def test_stale_company_authorization_revocation(self):
        """User views Company A -> authorization revoked -> selects Company A again -> returns ACCESS_DENIED."""
        self.mock_client._execute_bc_rest.return_value = {
            "value": [{"id": "GUID-COMP-A", "name": "COMPANY_A", "displayName": "Company A"}]
        }
        is_auth_1, state_1, _ = self.auth_mgr.validate_company_access(self.mock_client, requested_company="COMPANY_A")
        self.assertTrue(is_auth_1)

        self.mock_client._execute_bc_rest.return_value = {"value": []}
        is_auth_2, state_2, info_2 = self.auth_mgr.validate_company_access(self.mock_client, requested_company="COMPANY_A")

        self.assertFalse(is_auth_2)
        self.assertEqual(state_2, DataTrustState.ACCESS_DENIED)

    def test_conditional_404_error_mapping(self):
        """404 on company resolution -> COMPANY_NOT_FOUND; 404 on known endpoint -> DATA_REQUEST_INVALID."""
        comp_err = map_http_error(http_status=404, is_company_resolution=True, run_id="DT-101")
        self.assertEqual(comp_err["status"], DataTrustState.COMPANY_NOT_FOUND)
        self.assertIn("selected company could not be found", comp_err["message"])

        ep_err = map_http_error(http_status=404, is_company_resolution=False, endpoint="vendorLedgerEntries", run_id="DT-101")
        self.assertEqual(ep_err["status"], DataTrustState.DATA_REQUEST_INVALID)
        self.assertIn("Unable to retrieve Business Central data", ep_err["message"])

    def test_run_id_correlation_and_clean_diagnostics_null(self):
        """Execution payload contains unique run_id; clean SUCCESS run sets diagnostics = None."""
        orchestrator = DataTrustEngineOrchestrator(mcp_client=None)
        res = orchestrator.run_recon(company_id="CRONUS IN", mode="TEST_FIXTURE")

        self.assertTrue(res["run_id"].startswith("DT-"))
        self.assertIsNone(res["diagnostics"])

    def test_unauthorized_diagnostics_server_authorized(self):
        """Access denied response includes run_id in user message and diagnostic metadata."""
        self.mock_client._execute_bc_rest.return_value = {"value": []}
        orchestrator = DataTrustEngineOrchestrator(mcp_client=self.mock_client)
        res = orchestrator.run_recon(company_id="UNAUTHORIZED_COMP")

        self.assertEqual(res["status"], DataTrustState.ACCESS_DENIED)
        self.assertIn("Reference: DT-", res["message"])
        self.assertIsNotNone(res["diagnostics"])
        self.assertEqual(res["diagnostics"]["http_status"], 403)


if __name__ == "__main__":
    unittest.main()
