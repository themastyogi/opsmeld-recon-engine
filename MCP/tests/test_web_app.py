"""
Unit tests for Opsmeld Web Management Console HTTP endpoints and templates.
"""

from http.server import HTTPServer
import threading
import urllib.request
import urllib.parse
import unittest
from web.app import create_server


class TestWebApp(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.port = 8009
        cls.server = create_server(host="127.0.0.1", port=cls.port)
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_dashboard_home_route(self):
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.status, 200)
            html = response.read().decode("utf-8")
            self.assertIn("opsmeld", html)
            self.assertIn("Collections", html)

    def test_settings_route(self):
        url = f"http://127.0.0.1:{self.port}/settings"
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.status, 200)
            html = response.read().decode("utf-8")
            self.assertIn("Configuration Center", html)

    def test_ar_manager_report_route(self):
        url = f"http://127.0.0.1:{self.port}/reports/ar-manager"
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.status, 200)
            html = response.read().decode("utf-8")
            self.assertIn("Business Central", html)

    def test_save_settings_api(self):
        url = f"http://127.0.0.1:{self.port}/api/settings"
        data = urllib.parse.urlencode({
            "name": "Test Company Corp",
            "tenant_id": "test-tenant-123",
            "app_client_id": "test-client-456",
            "environment": "Production",
            "company_name": "CRONUS USA, Inc."
        }).encode("utf-8")

        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            html = response.read().decode("utf-8")
            self.assertIn("Configuration saved successfully!", html)


    def test_data_trust_config_post_valid_and_invalid(self):
        """Proves POST /api/data-trust/config unpacks (saved, errors) and returns 400 + validation errors array on invalid JSON config."""
        import json
        from core.auth import get_auth_manager

        # Step 1: Obtain session token using server's active admin credentials
        auth_mgr = get_auth_manager()
        token = auth_mgr.authenticate(auth_mgr.admin_user, auth_mgr.admin_pass)
        headers = {"Cookie": f"session={token}", "Content-Type": "application/json"}

        # Step 2: POST Invalid configuration payload
        invalid_payload = {
            "inventory_costing": {
                "enabled": True,
                "historical_pattern": {
                    "minimum_history": -10
                }
            }
        }
        url = f"http://127.0.0.1:{self.port}/api/data-trust/config"
        req = urllib.request.Request(url, data=json.dumps(invalid_payload).encode("utf-8"), headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req) as response:
                self.fail("Expected HTTP 400 Bad Request on invalid configuration, but request succeeded.")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            body = json.loads(e.read().decode("utf-8"))
            self.assertEqual(body.get("status"), "error")
            self.assertEqual(body.get("message"), "Failed to save Data Trust configuration")
            self.assertTrue(isinstance(body.get("errors"), list))
            self.assertTrue(any("minimum_history" in err for err in body.get("errors", [])))


if __name__ == "__main__":
    unittest.main()
