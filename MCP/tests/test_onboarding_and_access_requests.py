"""
Unit tests for Self-Service Onboarding & Access Request APIs:
- POST /api/onboarding/register (Registration submission)
- POST /api/onboarding/request-access (Request access to existing organization)
"""

import json
import threading
import unittest
import urllib.request
import urllib.error
from web.app import create_server
from core.auth import get_auth_manager
from core.models import get_datastore


class TestOnboardingAndAccessRequests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 8099
        cls.server = create_server(host="127.0.0.1", port=cls.port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.auth_mgr = get_auth_manager()
        self.ds = get_datastore()

        # Unprovisioned session (authenticated via Entra ID, but not associated with an org)
        self.unprov_token = self.auth_mgr.create_session(
            user_id="usr_unprov_test_101",
            email="newcomer@corporate.com",
            display_name="New Comer",
            roles=[],
            organization_id=None,
            allowed_companies=set(),
            provisioned=False
        )

    def test_registration_endpoint_creates_real_registration_in_datastore(self):
        """Task A: POST /api/onboarding/register records an OrganizationRegistration in the datastore."""
        url = f"{self.base_url}/api/onboarding/register"
        payload = {
            "organization_name": "Globex Corporation",
            "requester_name": "Hank Scorpio",
            "business_email": "hank@globex.com",
            "requested_modules": ["ar_control_tower", "data_trust"]
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(data.get("status"), "success")
        reg_info = data.get("registration", {})
        reg_id = reg_info.get("registration_id")
        self.assertIsNotNone(reg_id)

        # Directly verify presence in datastore
        self.assertIn(reg_id, self.ds.registrations)
        stored_reg = self.ds.registrations[reg_id]
        self.assertEqual(stored_reg.organization_name, "Globex Corporation")
        self.assertEqual(stored_reg.business_email, "hank@globex.com")

    def test_request_access_requires_active_session(self):
        """Task B: POST /api/onboarding/request-access fails with 401 when unauthenticated."""
        url = f"{self.base_url}/api/onboarding/request-access"
        payload = {"organization_name": "ABC Manufacturing"}
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 401)
        err = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(err.get("status"), "UNAUTHENTICATED")

    def test_request_access_requires_organization_name(self):
        """Task B: POST /api/onboarding/request-access fails with 400 when organization_name is missing/empty."""
        url = f"{self.base_url}/api/onboarding/request-access"
        req = urllib.request.Request(
            url,
            data=json.dumps({"organization_name": ""}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.unprov_token}"
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        err = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(err.get("status"), "MISSING_ORGANIZATION_NAME")

    def test_request_access_returns_404_for_non_existent_organization(self):
        """Task B: POST /api/onboarding/request-access returns 404 when organization name is not found."""
        url = f"{self.base_url}/api/onboarding/request-access"
        non_existent_org = "Completely NonExistent Entity XYZ 999"
        req = urllib.request.Request(
            url,
            data=json.dumps({"organization_name": non_existent_org}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.unprov_token}"
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)
        err = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(err.get("status"), "ORGANIZATION_NOT_FOUND")
        self.assertIn("not found", err.get("error", "").lower())
        self.assertIn("Register Your Organization", err.get("error", ""))

    def test_request_access_creates_access_request_for_existing_organization(self):
        """Task B: POST /api/onboarding/request-access creates real AccessRequest in datastore using session identity."""
        url = f"{self.base_url}/api/onboarding/request-access"
        # Case-insensitive match against ABC Manufacturing (org_abc_001)
        req = urllib.request.Request(
            url,
            data=json.dumps({"organization_name": "abc manufacturing"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.unprov_token}"
            }
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(data.get("status"), "success")
        self.assertIn("submitted successfully", data.get("message", ""))
        req_dict = data.get("request", {})
        request_id = req_dict.get("request_id")
        self.assertIsNotNone(request_id)

        # Verify identity was pulled strictly from session, not untrusted client input
        self.assertEqual(req_dict.get("email"), "newcomer@corporate.com")
        self.assertEqual(req_dict.get("user_id"), "usr_unprov_test_101")
        self.assertEqual(req_dict.get("organization_id"), "org_abc_001")

        # Directly verify presence in datastore
        self.assertIn(request_id, self.ds.access_requests)
        stored_req = self.ds.access_requests[request_id]
        self.assertEqual(stored_req.organization_id, "org_abc_001")
        self.assertEqual(stored_req.email, "newcomer@corporate.com")
        self.assertEqual(stored_req.display_name, "New Comer")


if __name__ == "__main__":
    unittest.main()
