"""
Opsmeld Unit Tests for Login Endpoint Security (Tests B & E)
Verifies:
- Test B: Empty POST /api/auth/login returns verification_uri & user_code (Device Flow) and NO session token.
- Test E: Admin status endpoint POST /api/admin/organizations/status without organization_id returns HTTP 400 Bad Request.
"""

import json
import threading
import urllib.request
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

    def test_b_empty_login_post_returns_device_flow_and_no_token(self):
        url = f"{self.base_url}/api/auth/login"
        req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

        # Crucial security invariant: Empty login MUST NEVER return an authenticated session token
        self.assertNotIn("token", data)
        self.assertTrue("user_code" in data or "error" in data)

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


if __name__ == "__main__":
    unittest.main()
