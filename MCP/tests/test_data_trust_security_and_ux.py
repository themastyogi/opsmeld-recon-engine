"""
Comprehensive Unit Tests for Data Trust Platform Security, Company Access & UX Specification.
Verifies forged-company security, stale-company authorization revocation, conditional 404 mapping,
server-authorized admin diagnostics, run_id correlation, and legacy findings API backward compatibility.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import MagicMock
from modules.data_trust_engine.authorization import CompanyAccessManager
from modules.data_trust_engine.company_context import DataTrustState, map_http_error, build_user_message
from modules.data_trust_engine.engine import DataTrustEngineOrchestrator


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
        # Discovered companies only contains COMPANY_A
        self.mock_client._execute_bc_rest.return_value = {
            "value": [{"id": "GUID-COMP-A", "name": "COMPANY_A", "displayName": "Company A"}]
        }

        # Request company_id = COMPANY_B (forged request)
        is_auth, state, info = self.auth_mgr.validate_company_access(self.mock_client, requested_company="COMPANY_B")

        self.assertFalse(is_auth)
        self.assertEqual(state, DataTrustState.ACCESS_DENIED)
        self.assertIn("don't have permission to view Data Trust data for this company", info["message"])

        # Orchestrator execution with forged company returns ACCESS_DENIED and 0 findings
        orchestrator = DataTrustEngineOrchestrator(mcp_client=self.mock_client)
        res = orchestrator.run_recon(company_id="COMPANY_B")
        self.assertEqual(res["status"], DataTrustState.ACCESS_DENIED)
        self.assertEqual(len(res["findings"]), 0)

    def test_stale_company_authorization_revocation(self):
        """User views Company A -> authorization revoked -> selects Company A again -> returns ACCESS_DENIED."""
        # Initial run: Company A is authorized
        self.mock_client._execute_bc_rest.return_value = {
            "value": [{"id": "GUID-COMP-A", "name": "COMPANY_A", "displayName": "Company A"}]
        }
        is_auth_1, state_1, _ = self.auth_mgr.validate_company_access(self.mock_client, requested_company="COMPANY_A")
        self.assertTrue(is_auth_1)

        # Access revoked in BC -> /companies returns empty list or permission denied
        self.mock_client._execute_bc_rest.return_value = {"value": []}
        is_auth_2, state_2, info_2 = self.auth_mgr.validate_company_access(self.mock_client, requested_company="COMPANY_A")

        self.assertFalse(is_auth_2)
        self.assertEqual(state_2, DataTrustState.ACCESS_DENIED)

    def test_conditional_404_error_mapping(self):
        """404 on company resolution -> COMPANY_NOT_FOUND; 404 on known endpoint -> DATA_REQUEST_INVALID."""
        # 1. Company resolution 404
        comp_err = map_http_error(http_status=404, is_company_resolution=True, run_id="DT-101")
        self.assertEqual(comp_err["status"], DataTrustState.COMPANY_NOT_FOUND)
        self.assertIn("selected company could not be found", comp_err["message"])

        # 2. Known endpoint 404
        ep_err = map_http_error(http_status=404, is_company_resolution=False, endpoint="vendorLedgerEntries", run_id="DT-101")
        self.assertEqual(ep_err["status"], DataTrustState.DATA_REQUEST_INVALID)
        self.assertIn("Unable to retrieve Business Central data", ep_err["message"])

    def test_run_id_correlation_and_clean_diagnostics_null(self):
        """Execution payload contains unique run_id; clean SUCCESS run sets diagnostics = None."""
        orchestrator = DataTrustEngineOrchestrator(mcp_client=None)  # Preview mode
        res = orchestrator.run_recon(company_id="CRONUS IN")

        self.assertTrue(res["run_id"].startswith("DT-"))
        self.assertIsNone(res["diagnostics"])
        self.assertEqual(res["status"], DataTrustState.SUCCESS)

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
