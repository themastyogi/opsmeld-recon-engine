"""
Opsmeld Unit Tests for Login Endpoint Security (Tests B & E)
Verifies:
- Test B: Empty POST /api/auth/login returns HTTP 400 Bad Request and NO session token.
- Test E: Admin status endpoint POST /api/admin/organizations/status without organization_id returns HTTP 400 Bad Request.
"""

import json
import threading
import urllib.request
import urllib.error
import unittest
from web.app import create_server
from core.auth import get_auth_manager


class TestLoginEndpointSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 8097
        cls.server = create_server(host="127.0.0.1", port=cls.port)
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_b_empty_login_post_returns_400_and_no_token(self):
        url = f"{self.base_url}/api/auth/login"
        req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        # Crucial security invariant: Empty login MUST return 400 Bad Request and NEVER return a session token
        self.assertEqual(ctx.exception.code, 400)
        data = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertNotIn("token", data)
        self.assertIn("error", data)

    def test_e_admin_status_without_org_id_returns_400(self):
        auth_mgr = get_auth_manager()
        admin_token = auth_mgr.create_session(
            user_id="usr_admin_test",
            email="admin@opsmeld.com",
            display_name="Platform Admin",
            roles=["ENTERPRISE_ADMIN"],
            organization_id="org_abc_001",
            provisioned=True
        )

        url = f"{self.base_url}/api/admin/organizations/status"
        req = urllib.request.Request(
            url,
            data=json.dumps({"status": "ACTIVE"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {admin_token}"
            }
        )

        try:
            with urllib.request.urlopen(req) as resp:
                self.fail("Expected HTTP 400 Bad Request but succeeded")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            data = json.loads(e.read().decode("utf-8"))
            self.assertEqual(data.get("error"), "organization_id required")

    def test_pkce_authorize_endpoint_generates_challenge_and_stores_state(self):
        """Task 7 Part B: /api/auth/entra/authorize generates S256 code_challenge and stores flow state."""
        import urllib.parse
        from web.app import _PENDING_AUTH_FLOWS

        url = f"{self.base_url}/api/auth/entra/authorize?json=true"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

        auth_url = data.get("auth_url", "")
        self.assertIn("code_challenge=", auth_url)
        self.assertIn("code_challenge_method=S256", auth_url)
        self.assertIn("response_type=code", auth_url)

        parsed = urllib.parse.urlparse(auth_url)
        qs = urllib.parse.parse_qs(parsed.query)
        state = qs.get("state", [None])[0]
        self.assertIsNotNone(state)
        self.assertIn(state, _PENDING_AUTH_FLOWS)
        flow, ts = _PENDING_AUTH_FLOWS[state]
        self.assertIn("code_verifier", flow)

    def test_pkce_callback_rejects_missing_or_invalid_state(self):
        """Task 7 Part B: /api/auth/callback fails with 400 on missing or invalid/expired state."""
        # 1. Missing state
        url_no_state = f"{self.base_url}/api/auth/callback?code=some_auth_code"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url_no_state)
        self.assertEqual(ctx.exception.code, 400)

        # 2. Invalid state
        url_bad_state = f"{self.base_url}/api/auth/callback?code=some_auth_code&state=invalid_or_expired_state"
        with self.assertRaises(urllib.error.HTTPError) as ctx2:
            urllib.request.urlopen(url_bad_state)
        self.assertEqual(ctx2.exception.code, 400)

    def test_pkce_callback_successful_exchange_creates_session(self):
        """Task 7 Part B: /api/auth/callback successfully exchanges auth code using PKCE flow and creates session."""
        from unittest.mock import patch
        from web.app import _PENDING_AUTH_FLOWS
        import time

        test_state = "test_valid_pkce_state_xyz"
        mock_flow = {
            "state": test_state,
            "code_verifier": "verifier_secret_1234567890",
            "redirect_uri": "http://127.0.0.1:8097/api/auth/callback",
            "scope": ["https://api.businesscentral.dynamics.com/Financials.ReadWrite.All"]
        }
        _PENDING_AUTH_FLOWS[test_state] = (mock_flow, time.time())

        # Custom HTTP redirect handler to prevent following the 302 redirect so we can inspect cookies
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirectHandler)
        callback_url = f"{self.base_url}/api/auth/callback?code=valid_entra_auth_code&state={test_state}"

        with patch("msal.PublicClientApplication.acquire_token_by_auth_code_flow") as mock_acquire:
            mock_acquire.return_value = {
                "access_token": "fake_live_bc_token_abc",
                "id_token_claims": {
                    "preferred_username": "admin@opsmeld.com",
                    "name": "Platform Admin",
                    "oid": "oid_admin_001",
                    "tid": "db961cfa-b4ab-42c5-9ab4-90b82e0da387"
                }
            }

            try:
                resp = opener.open(callback_url)
                status_code = resp.status
                headers = dict(resp.headers)
            except urllib.error.HTTPError as e:
                status_code = e.code
                headers = dict(e.headers)

            self.assertEqual(status_code, 302)
            self.assertEqual(headers.get("Location"), "/?login=success")
            cookie = headers.get("Set-Cookie", "")
            self.assertIn("session=", cookie)

            # Confirm MSAL acquire_token_by_auth_code_flow was called with the exact stored PKCE flow
            self.assertTrue(mock_acquire.called)
            called_flow, called_resp = mock_acquire.call_args[0]
            self.assertEqual(called_flow["code_verifier"], "verifier_secret_1234567890")
            self.assertEqual(called_resp.get("code"), "valid_entra_auth_code")
            self.assertEqual(called_resp.get("state"), test_state)


if __name__ == "__main__":
    unittest.main()
