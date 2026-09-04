"""
Opsmeld Reconciliation Engine - Business Central Token Acquisition & Discovery Tests
Verifies that BCMCPClient prioritizes real delegated user tokens, disables broken client_secret
flow by default, and that live company discovery succeeds with LIVE_BUSINESS_CENTRAL.
"""

import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from core.bc_mcp_client import BCMCPClient
from core.auth import get_auth_manager
from core.models import get_datastore
from web.app import OpsmeldWebHandler


class TestBCTokenAcquisition(unittest.TestCase):

    def setUp(self):
        # Ensure default test environment state
        if "OPSMELD_ENABLE_CLIENT_SECRET_AUTH" in os.environ:
            del os.environ["OPSMELD_ENABLE_CLIENT_SECRET_AUTH"]

    def test_user_access_token_returned_directly_without_msal(self):
        """Construct a BCMCPClient with user_access_token and assert get_access_token() returns it directly without MSAL."""
        with patch.dict(os.environ, {"BC_CLIENT_SECRET": "secret_that_would_fail_bc"}):
            with patch("msal.ConfidentialClientApplication") as mock_confidential:
                client = BCMCPClient(user_token="real-delegated-entra-token-xyz")
                token = client.get_access_token()

                self.assertEqual(token, "real-delegated-entra-token-xyz")
                mock_confidential.assert_not_called()

    def test_client_secret_path_disabled_by_default_even_with_secret_configured(self):
        """Confirm get_access_token() never attempts client_secret path by default even when BC_CLIENT_SECRET is set."""
        with patch.dict(os.environ, {"BC_CLIENT_SECRET": "configured_secret_123"}):
            # Ensure flag is unset
            os.environ.pop("OPSMELD_ENABLE_CLIENT_SECRET_AUTH", None)
            with patch("msal.ConfidentialClientApplication") as mock_confidential:
                client = BCMCPClient(user_token="")
                # Mock token cache path as nonexistent
                client.token_cache_path = MagicMock()
                client.token_cache_path.exists.return_value = False

                token = client.get_access_token()

                self.assertEqual(token, "")
                mock_confidential.assert_not_called()

    def test_client_secret_path_activated_only_when_explicitly_flagged(self):
        """Verify client_secret flow can be re-enabled if OPSMELD_ENABLE_CLIENT_SECRET_AUTH='true'."""
        with patch.dict(os.environ, {
            "BC_CLIENT_SECRET": "valid_unattended_secret",
            "OPSMELD_ENABLE_CLIENT_SECRET_AUTH": "true",
            "BC_TENANT_ID": "test-tenant-id",
            "BC_APP_CLIENT_ID": "test-app-client-id"
        }):
            mock_app_instance = MagicMock()
            mock_app_instance.acquire_token_for_client.return_value = {"access_token": "app-permission-token-abc"}
            with patch("msal.ConfidentialClientApplication", return_value=mock_app_instance) as mock_confidential:
                client = BCMCPClient(user_token="")
                token = client.get_access_token()

                self.assertEqual(token, "app-permission-token-abc")
                mock_confidential.assert_called_once()

    def test_user_token_precedes_client_secret_even_when_flag_enabled(self):
        """Even when OPSMELD_ENABLE_CLIENT_SECRET_AUTH is enabled, user_access_token takes precedence."""
        with patch.dict(os.environ, {
            "BC_CLIENT_SECRET": "some_secret",
            "OPSMELD_ENABLE_CLIENT_SECRET_AUTH": "true"
        }):
            with patch("msal.ConfidentialClientApplication") as mock_confidential:
                client = BCMCPClient(user_token="user-delegated-token-priority")
                token = client.get_access_token()

                self.assertEqual(token, "user-delegated-token-priority")
                mock_confidential.assert_not_called()

    def test_execute_bc_rest_uses_user_token_in_auth_header(self):
        """Verify _execute_bc_rest passes the user's delegated token in Authorization header."""
        client = BCMCPClient(user_token="bearer-user-token-777")
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"value": [{"id": "guid-1", "name": "Company 1"}]}).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            result = client._execute_bc_rest("companies")
            self.assertIn("value", result)
            self.assertEqual(len(result["value"]), 1)

            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            self.assertEqual(req.headers.get("Authorization"), "Bearer bearer-user-token-777")

    def test_authorized_companies_live_scenario_with_delegated_session(self):
        """
        Re-runs the exact scenario that previously failed with 401 DATA_UNAVAILABLE:
        A real Entra login session with a valid delegated access_token hits /api/data-trust/authorized-companies.
        With client_secret flow bypassed, BCMCPClient uses the delegated token and discovers live companies,
        returning data_source: 'LIVE_BUSINESS_CENTRAL' and status: 'SUCCESS' (not DATA_UNAVAILABLE).
        """
        with patch.dict(os.environ, {
            "OPSMELD_BOOTSTRAP_ORG_NAME": "Real Corp Discovery Test",
            "OPSMELD_BOOTSTRAP_ADMIN_EMAIL": "discovery_admin@realcorp.com",
            "OPSMELD_BOOTSTRAP_ADMIN_NAME": "Discovery Admin",
            "BC_CLIENT_SECRET": "broken_secret_would_cause_401"
        }):
            ds = get_datastore()
            ds.bootstrap_from_env()

            auth_mgr = get_auth_manager()
            session_token = auth_mgr.login_entra_user(
                email="discovery_admin@realcorp.com",
                display_name="Discovery Admin",
                access_token="live-delegated-user-access-token-12345",
                tenant_id="c37ac1c0-bc8f-f111-832d-7c1e5233db45"
            )

            live_companies_payload = {
                "value": [
                    {"id": "ac6b97ba-bc8f-f111-832d-7c1e5233db45", "name": "CRONUS IN", "displayName": "CRONUS IN"},
                    {"id": "c37ac1c0-bc8f-f111-832d-7c1e5233db45", "name": "My Company", "displayName": "My Company"},
                    {"id": "c4e0106b-159e-f111-8072-7ced8d9f80ff", "name": "Sandbox", "displayName": "Sandbox"}
                ]
            }

            handler = MagicMock(spec=OpsmeldWebHandler)
            handler.headers = {"Cookie": f"session={session_token}"}
            handler.wfile = io.BytesIO()
            handler.path = "/api/data-trust/authorized-companies"
            handler._get_session_token.return_value = session_token
            handler._get_client_key.return_value = "default_client"

            handler._handle_do_GET = OpsmeldWebHandler._handle_do_GET.__get__(handler, OpsmeldWebHandler)
            handler.do_GET = OpsmeldWebHandler.do_GET.__get__(handler, OpsmeldWebHandler)
            handler._require_auth = OpsmeldWebHandler._require_auth.__get__(handler, OpsmeldWebHandler)
            handler._set_headers = OpsmeldWebHandler._set_headers.__get__(handler, OpsmeldWebHandler)
            handler._write_response = OpsmeldWebHandler._write_response.__get__(handler, OpsmeldWebHandler)

            with patch("msal.ConfidentialClientApplication") as mock_confidential:
                with patch("urllib.request.urlopen") as mock_urlopen:
                    mock_resp = MagicMock()
                    mock_resp.read.return_value = json.dumps(live_companies_payload).encode("utf-8")
                    mock_urlopen.return_value.__enter__.return_value = mock_resp

                    handler.do_GET()

                    mock_confidential.assert_not_called()

                    call_args = mock_urlopen.call_args
                    req = call_args[0][0]
                    self.assertEqual(req.headers.get("Authorization"), "Bearer live-delegated-user-access-token-12345")

                    response_json = json.loads(handler.wfile.getvalue().decode("utf-8"))
                    self.assertEqual(response_json.get("status"), "SUCCESS")
                    self.assertEqual(response_json.get("data_source"), "LIVE_BUSINESS_CENTRAL")
                    self.assertIsNone(response_json.get("error_detail"))
                    self.assertGreater(len(response_json.get("companies", [])), 0)
                    self.assertNotEqual(response_json.get("status"), "DATA_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
