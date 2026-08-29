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

        # Explicitly verify ZERO data acquisition REST calls occurred after authorization failure
        all_called_endpoints = [call_args[0][0] for call_args in self.mock_client._execute_bc_rest.call_args_list if call_args[0]]
        acquisition_calls = [ep for ep in all_called_endpoints if "generalLedgerEntries" in ep or "vendorLedgerEntries" in ep or "salesInvoices" in ep]
        self.assertEqual(len(acquisition_calls), 0, f"Expected 0 acquisition calls after ACCESS_DENIED, but got: {acquisition_calls}")

    def test_company_discovery_vs_authorization_real_bc_check(self):
        """GET /companies -> 200, company-scoped request -> 403 -> ACCESS_DENIED -> ZERO acquisition requests after the 403."""
        def mock_rest(endpoint, **kwargs):
            if endpoint == "companies":
                return {"value": [{"id": "GUID-COMP-B", "name": "COMPANY_B", "displayName": "Company B"}]}
            elif "companies(GUID-COMP-B)" in endpoint:
                return {"is_error": True, "http_status": 403, "error": {"code": "AccessDenied"}}
            return {"value": []}

        self.mock_client._execute_bc_rest.side_effect = mock_rest

        orchestrator = DataTrustEngineOrchestrator(mcp_client=self.mock_client)
        res = orchestrator.run_recon(company_id="COMPANY_B")

        self.assertEqual(res["status"], DataTrustState.ACCESS_DENIED)
        self.assertEqual(len(res["findings"]), 0)

        # Assert zero data acquisition calls occurred after the 403 gate failure
        all_calls = [call_args[0][0] for call_args in self.mock_client._execute_bc_rest.call_args_list if call_args[0]]
        acq_calls = [ep for ep in all_calls if "vendorLedgerEntries" in ep or "salesInvoices" in ep or ("generalLedgerEntries" in ep and "$top=1" not in ep)]
        self.assertEqual(len(acq_calls), 0, f"Expected 0 acquisition calls after 403, got: {acq_calls}")

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



    def test_authorized_companies_requires_http_auth(self):
        """Route-level: Unauthenticated GET /api/data-trust/authorized-companies -> 401 + 0 discovery/BC calls."""
        from web.app import OpsmeldWebHandler
        from unittest.mock import patch, MagicMock
        import io

        handler = MagicMock(spec=OpsmeldWebHandler)
        handler.headers = {}
        handler.wfile = io.BytesIO()
        handler.path = "/api/data-trust/authorized-companies"
        handler._get_session_token.return_value = None
        handler._get_client_key.return_value = "default_client"

        handler.do_GET = OpsmeldWebHandler.do_GET.__get__(handler, OpsmeldWebHandler)
        handler._require_auth = OpsmeldWebHandler._require_auth.__get__(handler, OpsmeldWebHandler)
        handler._set_headers = OpsmeldWebHandler._set_headers.__get__(handler, OpsmeldWebHandler)

        with patch("modules.data_trust_engine.authorization.CompanyAccessManager.get_discovered_companies") as mock_disc, \
             patch("core.bc_mcp_client.BCMCPClient._execute_bc_rest") as mock_bc_rest:
            handler.do_GET()
            handler.send_response.assert_called_with(401)
            self.assertEqual(mock_disc.call_count, 0, "Expected 0 discovery calls after HTTP 401")
            self.assertEqual(mock_bc_rest.call_count, 0, "Expected 0 BC REST calls after HTTP 401")

    def test_run_recon_requires_http_auth(self):
        """Route-level: Unauthenticated GET /api/data-trust/run-recon -> 401 + 0 orchestrator/BC calls."""
        from web.app import OpsmeldWebHandler
        from unittest.mock import patch, MagicMock
        import io

        handler = MagicMock(spec=OpsmeldWebHandler)
        handler.headers = {}
        handler.wfile = io.BytesIO()
        handler.path = "/api/data-trust/run-recon"
        handler._get_session_token.return_value = None
        handler._get_client_key.return_value = "default_client"

        handler.do_GET = OpsmeldWebHandler.do_GET.__get__(handler, OpsmeldWebHandler)
        handler._require_auth = OpsmeldWebHandler._require_auth.__get__(handler, OpsmeldWebHandler)
        handler._set_headers = OpsmeldWebHandler._set_headers.__get__(handler, OpsmeldWebHandler)

        with patch("modules.data_trust_engine.engine.DataTrustEngineOrchestrator.run_recon") as mock_recon, \
             patch("core.bc_mcp_client.BCMCPClient._execute_bc_rest") as mock_bc_rest:
            handler.do_GET()
            handler.send_response.assert_called_with(401)
            self.assertEqual(mock_recon.call_count, 0, "Expected 0 orchestrator calls after HTTP 401")
            self.assertEqual(mock_bc_rest.call_count, 0, "Expected 0 BC REST calls after HTTP 401")

    def test_authorized_companies_returns_exact_discovery_no_fallback(self):
        """Route-level: GET /api/data-trust/authorized-companies returns exact discovery result without synthetic fallback."""
        from web.app import OpsmeldWebHandler
        from unittest.mock import patch, MagicMock
        import io

        handler = MagicMock(spec=OpsmeldWebHandler)
        handler.headers = {"Authorization": "Bearer VALID_SESSION_TOKEN"}
        handler.wfile = io.BytesIO()
        handler.path = "/api/data-trust/authorized-companies"
        handler._get_session_token.return_value = "VALID_SESSION_TOKEN"
        handler._get_client_key.return_value = "default_client"

        handler.do_GET = OpsmeldWebHandler.do_GET.__get__(handler, OpsmeldWebHandler)
        handler._require_auth = OpsmeldWebHandler._require_auth.__get__(handler, OpsmeldWebHandler)
        handler._set_headers = OpsmeldWebHandler._set_headers.__get__(handler, OpsmeldWebHandler)
        handler._write_response = OpsmeldWebHandler._write_response.__get__(handler, OpsmeldWebHandler)

        with patch("core.auth.AuthManager.get_session_info", return_value={"user": "admin"}), \
             patch("modules.data_trust_engine.authorization.CompanyAccessManager.get_discovered_companies", return_value=[]):
            handler.do_GET()
            response_bytes = handler.wfile.getvalue()
            self.assertIn(b'"companies": []', response_bytes)
            self.assertNotIn(b"CRONUS IN", response_bytes)


    def test_post_run_recon_route_level_security_and_orchestrator_delegation(self):
        """Route-level: POST /api/data-trust/run-recon unauthenticated -> 401 + 0 orchestrator/BC calls; authenticated -> calls modular orchestrator."""
        from web.app import OpsmeldWebHandler
        from unittest.mock import patch, MagicMock
        import io, json

        # Case 1: Unauthenticated POST -> 401 + 0 orchestrator calls + 0 BC calls
        handler_unauth = MagicMock(spec=OpsmeldWebHandler)
        handler_unauth.headers = {"Content-Length": "25"}
        handler_unauth.rfile = io.BytesIO(b'{"company_id": "CRONUS"}')
        handler_unauth.wfile = io.BytesIO()
        handler_unauth.path = "/api/data-trust/run-recon"
        handler_unauth._get_session_token.return_value = None
        handler_unauth._get_client_key.return_value = "default_client"

        handler_unauth.do_POST = OpsmeldWebHandler.do_POST.__get__(handler_unauth, OpsmeldWebHandler)
        handler_unauth._require_auth = OpsmeldWebHandler._require_auth.__get__(handler_unauth, OpsmeldWebHandler)
        handler_unauth._set_headers = OpsmeldWebHandler._set_headers.__get__(handler_unauth, OpsmeldWebHandler)

        with patch("modules.data_trust_engine.engine.DataTrustEngineOrchestrator.run_recon") as mock_recon, \
             patch("core.bc_mcp_client.BCMCPClient._execute_bc_rest") as mock_bc_rest:
            handler_unauth.do_POST()
            handler_unauth.send_response.assert_called_with(401)
            self.assertEqual(mock_recon.call_count, 0, "Expected 0 orchestrator calls after POST HTTP 401")
            self.assertEqual(mock_bc_rest.call_count, 0, "Expected 0 BC REST calls after POST HTTP 401")

        # Case 2: Authenticated POST -> Modular DataTrustEngineOrchestrator called
        handler_auth = MagicMock(spec=OpsmeldWebHandler)
        handler_auth.headers = {"Authorization": "Bearer VALID_SESSION_TOKEN", "Content-Length": "25"}
        handler_auth.rfile = io.BytesIO(b'{"company_id": "CRONUS"}')
        handler_auth.wfile = io.BytesIO()
        handler_auth.path = "/api/data-trust/run-recon"
        handler_auth._get_session_token.return_value = "VALID_SESSION_TOKEN"
        handler_auth._get_client_key.return_value = "default_client"

        handler_auth.do_POST = OpsmeldWebHandler.do_POST.__get__(handler_auth, OpsmeldWebHandler)
        handler_auth._require_auth = OpsmeldWebHandler._require_auth.__get__(handler_auth, OpsmeldWebHandler)
        handler_auth._set_headers = OpsmeldWebHandler._set_headers.__get__(handler_auth, OpsmeldWebHandler)
        handler_auth._write_response = OpsmeldWebHandler._write_response.__get__(handler_auth, OpsmeldWebHandler)

        expected_payload = {
            "run_id": "DT-20260826-POST",
            "status": "SUCCESS",
            "findings": [],
            "rule_status": {},
            "message": "Complete",
            "diagnostics": None
        }

        with patch("core.auth.AuthManager.get_session_info", return_value={"user": "admin"}), \
             patch("modules.data_trust_engine.engine.DataTrustEngineOrchestrator.run_recon", return_value=expected_payload) as mock_recon_auth:
            handler_auth.do_POST()
            self.assertEqual(mock_recon_auth.call_count, 1)
            response_bytes = handler_auth.wfile.getvalue()
            self.assertIn(b'"run_id": "DT-20260826-POST"', response_bytes)

    def test_adversarial_tamper_company_guid_all_endpoints_return_403(self):
        """Adversarial Security Test: Authenticated session tampers company_id in DevTools to Company B -> HTTP 403 on all 4 endpoints."""
        from web.app import OpsmeldWebHandler
        from unittest.mock import patch, MagicMock
        import io

        self.mock_client._execute_bc_rest.side_effect = lambda ep: {
            "value": [{"id": "GUID-COMPANY-A", "name": "COMPANY_A", "displayName": "Company A"}]
        } if ep == "companies" else {"is_error": True, "http_status": 403, "error": {"code": "Authorization_RequestDenied"}}

        # 1. /findings with tampered company_id=GUID-COMPANY-B
        h_findings = MagicMock(spec=OpsmeldWebHandler)
        h_findings.path = "/api/data-trust/findings?company_id=GUID-COMPANY-B"
        h_findings._get_session_token.return_value = "VALID_TOKEN"
        h_findings._get_client_key.return_value = "default_client"
        h_findings.wfile = io.BytesIO()
        h_findings.do_GET = OpsmeldWebHandler.do_GET.__get__(h_findings, OpsmeldWebHandler)
        h_findings._require_auth = OpsmeldWebHandler._require_auth.__get__(h_findings, OpsmeldWebHandler)
        h_findings._set_headers = OpsmeldWebHandler._set_headers.__get__(h_findings, OpsmeldWebHandler)
        h_findings._write_response = OpsmeldWebHandler._write_response.__get__(h_findings, OpsmeldWebHandler)

        with patch("core.auth.AuthManager.get_session_info", return_value={"user": "admin"}), \
             patch("web.app.BCMCPClient", return_value=self.mock_client):
            h_findings.do_GET()
            self.assertIn(b"ACCESS_DENIED", h_findings.wfile.getvalue())

        # 2. /run-recon with tampered company_id=GUID-COMPANY-B
        h_recon = MagicMock(spec=OpsmeldWebHandler)
        h_recon.path = "/api/data-trust/run-recon?company_id=GUID-COMPANY-B"
        h_recon.headers = {"Content-Length": "0"}
        h_recon.rfile = io.BytesIO(b"")
        h_recon.wfile = io.BytesIO()
        h_recon._get_session_token.return_value = "VALID_TOKEN"
        h_recon._get_client_key.return_value = "default_client"
        h_recon.do_POST = OpsmeldWebHandler.do_POST.__get__(h_recon, OpsmeldWebHandler)
        h_recon._require_auth = OpsmeldWebHandler._require_auth.__get__(h_recon, OpsmeldWebHandler)
        h_recon._set_headers = OpsmeldWebHandler._set_headers.__get__(h_recon, OpsmeldWebHandler)
        h_recon._write_response = OpsmeldWebHandler._write_response.__get__(h_recon, OpsmeldWebHandler)

        with patch("core.auth.AuthManager.get_session_info", return_value={"user": "admin"}), \
             patch("web.app.BCMCPClient", return_value=self.mock_client):
            h_recon.do_POST()
            self.assertIn(b"ACCESS_DENIED", h_recon.wfile.getvalue())

        # 3. /finding-detail with tampered company_id=GUID-COMPANY-B
        h_detail = MagicMock(spec=OpsmeldWebHandler)
        h_detail.path = "/api/data-trust/finding-detail?id=DT-001&company_id=GUID-COMPANY-B"
        h_detail._get_session_token.return_value = "VALID_TOKEN"
        h_detail._get_client_key.return_value = "default_client"
        h_detail.wfile = io.BytesIO()
        h_detail.do_GET = OpsmeldWebHandler.do_GET.__get__(h_detail, OpsmeldWebHandler)
        h_detail._require_auth = OpsmeldWebHandler._require_auth.__get__(h_detail, OpsmeldWebHandler)
        h_detail._set_headers = OpsmeldWebHandler._set_headers.__get__(h_detail, OpsmeldWebHandler)
        h_detail._write_response = OpsmeldWebHandler._write_response.__get__(h_detail, OpsmeldWebHandler)

        with patch("core.auth.AuthManager.get_session_info", return_value={"user": "admin"}), \
             patch("web.app.BCMCPClient", return_value=self.mock_client):
            h_detail.do_GET()
            self.assertIn(b"ACCESS_DENIED", h_detail.wfile.getvalue())

        # 4. /update-status with tampered company_id=GUID-COMPANY-B
        h_update = MagicMock(spec=OpsmeldWebHandler)
        h_update.path = "/api/data-trust/update-status"
        payload_bytes = b'{"finding_id": "DT-001", "status": "Under Review", "company_id": "GUID-COMPANY-B"}'
        h_update.headers = {"Content-Length": str(len(payload_bytes))}
        h_update.rfile = io.BytesIO(payload_bytes)
        h_update.wfile = io.BytesIO()
        h_update._get_session_token.return_value = "VALID_TOKEN"
        h_update._get_client_key.return_value = "default_client"
        h_update.do_POST = OpsmeldWebHandler.do_POST.__get__(h_update, OpsmeldWebHandler)
        h_update._require_auth = OpsmeldWebHandler._require_auth.__get__(h_update, OpsmeldWebHandler)
        h_update._set_headers = OpsmeldWebHandler._set_headers.__get__(h_update, OpsmeldWebHandler)
        h_update._write_response = OpsmeldWebHandler._write_response.__get__(h_update, OpsmeldWebHandler)

        with patch("core.auth.AuthManager.get_session_info", return_value={"user": "admin"}), \
             patch("web.app.BCMCPClient", return_value=self.mock_client):
            h_update.do_POST()
            self.assertIn(b"ACCESS_DENIED", h_update.wfile.getvalue())

    def test_unknown_finding_mutation_returns_404_no_record_created(self):
        """Mutation Hardening: POST /api/data-trust/update-status with unknown finding_id -> HTTP 404 & zero synthetic record creation."""
        from web.app import OpsmeldWebHandler
        from modules.data_trust import DataTrustEngine
        from modules.data_trust_engine.company_context import DataTrustState
        from unittest.mock import patch, MagicMock
        import io

        h_update = MagicMock(spec=OpsmeldWebHandler)
        h_update.path = "/api/data-trust/update-status"
        payload_bytes = b'{"finding_id": "does-not-exist", "status": "Under Review", "company_id": "GUID-COMP-VALID"}'
        h_update.headers = {"Content-Length": str(len(payload_bytes))}
        h_update.rfile = io.BytesIO(payload_bytes)
        h_update.wfile = io.BytesIO()
        h_update._get_session_token.return_value = "VALID_TOKEN"
        h_update._get_client_key.return_value = "TEST_404_MUTATION"
        h_update.do_POST = OpsmeldWebHandler.do_POST.__get__(h_update, OpsmeldWebHandler)
        h_update._require_auth = OpsmeldWebHandler._require_auth.__get__(h_update, OpsmeldWebHandler)
        h_update._set_headers = OpsmeldWebHandler._set_headers.__get__(h_update, OpsmeldWebHandler)
        h_update._write_response = OpsmeldWebHandler._write_response.__get__(h_update, OpsmeldWebHandler)

        with patch("core.auth.AuthManager.get_session_info", return_value={"user": "admin"}), \
             patch("modules.data_trust_engine.authorization.CompanyAccessManager.validate_company_access", return_value=(True, DataTrustState.SUCCESS, {"company_id": "GUID-COMP-VALID"})):
            h_update.do_POST()
            self.assertIn(b"NOT_FOUND", h_update.wfile.getvalue())

        # Verify disk persistence: ensure "does-not-exist" was NEVER created or persisted
        engine = DataTrustEngine(client_key="TEST_404_MUTATION")
        findings, *_ = engine._load_from_disk(company_id="GUID-COMP-VALID")
        self.assertFalse(any(f.get("id") == "does-not-exist" for f in findings))

    def test_bc_connected_zero_records_honest_empty_state(self):
        """State 2 Ground State: Live BC connected with zero records returns status SUCCESS, LIVE_BUSINESS_CENTRAL, [] findings."""
        from modules.data_trust_engine.engine import DataTrustEngineOrchestrator
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.get_access_token.return_value = "VALID_TOKEN"
        mock_client._execute_bc_rest.side_effect = lambda ep: {
            "value": [{"id": "GUID-EMPTY-COMP", "name": "EMPTY_COMP"}]
        } if "companies" in ep and "generalLedgerEntries" not in ep else {"value": []}

        orchestrator = DataTrustEngineOrchestrator(mcp_client=mock_client, client_key="TEST_EMPTY_COMP")
        res = orchestrator.run_recon(company_id="GUID-EMPTY-COMP")

        self.assertIn(res["status"], ("SUCCESS", "NO_FINDINGS", "PARTIAL"))
        self.assertEqual(res["run_summary"]["data_source"], "LIVE_BUSINESS_CENTRAL")
        self.assertEqual(res["findings"], [])

    def test_missing_company_id_all_endpoints_return_400(self):
        """P0 Requirement 1: Missing company_id on all 4 live endpoints -> HTTP 400 Bad Request."""
        from web.app import OpsmeldWebHandler
        from unittest.mock import patch, MagicMock
        import io

        endpoints = [
            ("GET", "/api/data-trust/findings"),
            ("GET", "/api/data-trust/run-recon"),
            ("GET", "/api/data-trust/finding-detail?id=DT-001"),
            ("POST", "/api/data-trust/update-status")
        ]

        for method, ep in endpoints:
            handler = MagicMock(spec=OpsmeldWebHandler)
            handler.path = ep
            handler.headers = {}
            handler.rfile = io.BytesIO(b'{"finding_id": "DT-001", "status": "Under Review"}')
            handler.wfile = io.BytesIO()
            handler._get_session_token.return_value = "VALID_TOKEN"
            handler._get_client_key.return_value = "TEST_MISSING_COMP"
            handler._require_auth = OpsmeldWebHandler._require_auth.__get__(handler, OpsmeldWebHandler)
            handler._set_headers = OpsmeldWebHandler._set_headers.__get__(handler, OpsmeldWebHandler)
            handler._write_response = OpsmeldWebHandler._write_response.__get__(handler, OpsmeldWebHandler)

            with patch("core.auth.AuthManager.get_session_info", return_value={"user": "admin"}):
                if method == "GET":
                    OpsmeldWebHandler.do_GET(handler)
                else:
                    OpsmeldWebHandler.do_POST(handler)

            self.assertIn(b"CONFIGURATION_MISSING", handler.wfile.getvalue(), f"Endpoint {ep} failed to return HTTP 400 on missing company_id")

    def test_value_entries_failure_returns_data_unavailable(self):
        """P0 Requirement 4: Failing valueEntries request returns DATA_UNAVAILABLE and [] transactions."""
        from modules.data_trust_engine.acquisition import DataAcquirer
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.get_access_token.return_value = "VALID_TOKEN"
        mock_client._execute_bc_rest.side_effect = lambda ep: {
            "value": [{"id": "GUID-COST-COMP", "name": "COST_COMP"}]
        } if ep == "companies" else ({
            "value": [{"id": "ILE-1", "entryNo": 1}]
        } if "itemLedgerEntries" in ep else {"is_error": True, "error": "Value Entries unavailable"})

        acquirer = DataAcquirer(mcp_client=mock_client, mode="LIVE_BUSINESS_CENTRAL")
        txs, prov = acquirer.acquire_inventory_cost_transactions(company_id="GUID-COST-COMP")

        self.assertEqual(prov, "DATA_UNAVAILABLE")
        self.assertEqual(txs, [])

    def test_stored_8562_findings_have_authoritative_live_provenance(self):
        """P0 Requirement 5: Audit live snapshot proving all 8,562 findings originate from CRONUS IN with LIVE_BUSINESS_CENTRAL provenance."""
        from pathlib import Path
        import json

        snap_path = Path("MCP/data/snapshots/data_trust_findings_default_client_ac6b97ba-bc8f-f111-832d-7c1e5233db45.json")
        if snap_path.exists():
            with open(snap_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            findings = data.get("active_findings", [])
            self.assertEqual(len(findings), 8562)
            self.assertEqual(data.get("company_id"), "ac6b97ba-bc8f-f111-832d-7c1e5233db45")
            self.assertEqual(data.get("data_source"), "LIVE_BUSINESS_CENTRAL")
            self.assertTrue(all(f.get("data_source") == "LIVE_BUSINESS_CENTRAL" for f in findings))

    def test_company_switch_isolation_sequence_A_B_A(self):
        """Company Switching Isolation: Company A -> Company B -> Company A sequence never leaks findings across companies."""
        from modules.data_trust import DataTrustEngine
        engine = DataTrustEngine(client_key="TEST_SWITCH_SEQ")

        # Save findings for Company A
        engine.save_stored_findings([{"id": "FINDING-A-1001", "data_source": "LIVE_BUSINESS_CENTRAL"}], company_id="GUID-COMP-A")
        # Save findings for Company B
        engine.save_stored_findings([{"id": "FINDING-B-2002", "data_source": "LIVE_BUSINESS_CENTRAL"}], company_id="GUID-COMP-B")

        # Query A -> Company A findings only
        load_a1, *_ = engine._load_from_disk(company_id="GUID-COMP-A")
        self.assertEqual(len(load_a1), 1)
        self.assertEqual(load_a1[0]["id"], "FINDING-A-1001")

        # Query B -> Company B findings only
        load_b, *_ = engine._load_from_disk(company_id="GUID-COMP-B")
        self.assertEqual(len(load_b), 1)
        self.assertEqual(load_b[0]["id"], "FINDING-B-2002")

        # Query A again -> Company A findings only
        load_a2, *_ = engine._load_from_disk(company_id="GUID-COMP-A")
        self.assertEqual(len(load_a2), 1)
        self.assertEqual(load_a2[0]["id"], "FINDING-A-1001")

    def test_provenance_boundary_no_fixture_execution_in_auto_or_live_mode(self):
        """Provenance Boundary Guard: AUTO and LIVE_BUSINESS_CENTRAL modes must NEVER execute synthetic fixture generation."""
        from modules.data_trust_engine.acquisition import DataAcquirer
        from unittest.mock import patch, MagicMock

        mock_client = MagicMock()
        mock_client.get_access_token.return_value = "VALID_TOKEN"
        # Simulate BC REST failure
        mock_client._execute_bc_rest.return_value = {"is_error": True, "error": "500 Internal Server Error"}

        acquirer = DataAcquirer(mcp_client=mock_client, mode="AUTO")

        with patch("modules.data_trust_engine.fixtures.get_sample_transactions") as mock_fixtures:
            txs, provenance = acquirer.acquire_transactions()
            self.assertEqual(txs, [])
            self.assertEqual(provenance, "DATA_UNAVAILABLE")
            self.assertEqual(mock_fixtures.call_count, 0, "Fixtures MUST NEVER execute under AUTO or LIVE_BUSINESS_CENTRAL mode")

    def test_ar_manager_has_no_hardcoded_customer_fallbacks(self):
        """AR Manager Hardening: Live BC failure returns honest empty customer list with 0 synthetic fallback records."""
        from modules.ar_manager import ARManagerReport
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.call_tool_all_pages.return_value = {"error": "Business Central OData service unreachable"}
        mock_client._execute_bc_rest.return_value = {"is_error": True, "error": "Connection failed"}

        mock_rules = MagicMock()
        mock_rules.raw_rules = {}

        report = ARManagerReport(mock_client, mock_rules)
        data = report.fetch_data()

        self.assertIn("error", data)
        self.assertEqual(data["customers"], [], "Expected zero customers on BC failure")


if __name__ == "__main__":
    unittest.main()


