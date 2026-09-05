"""
Unit & Integration tests for Admin Approval Flow for Pending Access Requests:
- GET /api/admin/access-requests (Task A)
- POST /api/admin/access-requests/decision (Task B)
"""

import json
import socket
import threading
import time
import unittest
import urllib.request
import urllib.error
from web.app import create_server
from core.auth import get_auth_manager
from core.models import get_datastore, AccessRequestStatus


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestAccessRequestApprovalFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = get_free_port()
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

        # Customer Admin for Org ABC ("org_abc_001")
        self.admin_a_token = self.auth_mgr.create_session(
            user_id="usr_admin_org_a",
            email="admin@abc.com",
            display_name="Admin ABC",
            roles=["CUSTOMER_ADMIN"],
            organization_id="org_abc_001",
            allowed_companies={"ac6b97ba-bc8f-f111-832d-7c1e5233db45"},
            provisioned=True
        )

        # Customer Admin for Org XYZ ("org_xyz_002")
        self.admin_b_token = self.auth_mgr.create_session(
            user_id="usr_admin_org_b",
            email="admin@xyz.com",
            display_name="Admin XYZ",
            roles=["CUSTOMER_ADMIN"],
            organization_id="org_xyz_002",
            allowed_companies=set(),
            provisioned=True
        )

        # Platform Enterprise Admin (cross-tenant)
        self.enterprise_admin_token = self.auth_mgr.create_session(
            user_id="usr_enterprise_admin",
            email="superadmin@opsmeld.com",
            display_name="Super Admin",
            roles=["ENTERPRISE_ADMIN"],
            organization_id=None,
            allowed_companies=set(),
            provisioned=True
        )

        # Regular Viewer (non-admin)
        self.viewer_token = self.auth_mgr.create_session(
            user_id="usr_viewer_regular",
            email="viewer@abc.com",
            display_name="Regular Viewer",
            roles=["VIEWER"],
            organization_id="org_abc_001",
            allowed_companies=set(),
            provisioned=True
        )

    def test_customer_admin_sees_only_own_org_requests_and_joins_org_name(self):
        """Task A: CUSTOMER_ADMIN only sees requests for their own organization; includes organization_name."""
        # Create request for Org ABC
        req_a = self.ds.create_access_request(
            organization_id="org_abc_001",
            user_id="usr_pending_a",
            email="alice@abc.com",
            display_name="Alice ABC"
        )
        # Create request for Org XYZ
        req_b = self.ds.create_access_request(
            organization_id="org_xyz_002",
            user_id="usr_pending_b",
            email="bob@xyz.com",
            display_name="Bob XYZ"
        )

        url = f"{self.base_url}/api/admin/access-requests"
        req = urllib.request.Request(url, headers={"Cookie": f"session={self.admin_a_token}"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "success")
            req_ids = [r["request_id"] for r in data.get("requests", [])]
            self.assertIn(req_a.request_id, req_ids)
            self.assertNotIn(req_b.request_id, req_ids)

            # Check joined organization_name
            for r in data.get("requests", []):
                if r["request_id"] == req_a.request_id:
                    self.assertEqual(r["organization_name"], "ABC Manufacturing")
                    self.assertEqual(r["status"], "PENDING")

    def test_enterprise_admin_sees_requests_across_all_orgs(self):
        """Task A: ENTERPRISE_ADMIN sees pending requests across every organization."""
        req_a = self.ds.create_access_request(
            organization_id="org_abc_001",
            user_id="usr_pending_a2",
            email="alice2@abc.com",
            display_name="Alice2 ABC"
        )
        req_b = self.ds.create_access_request(
            organization_id="org_xyz_002",
            user_id="usr_pending_b2",
            email="bob2@xyz.com",
            display_name="Bob2 XYZ"
        )

        url = f"{self.base_url}/api/admin/access-requests"
        req = urllib.request.Request(url, headers={"Cookie": f"session={self.enterprise_admin_token}"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            req_ids = [r["request_id"] for r in data.get("requests", [])]
            self.assertIn(req_a.request_id, req_ids)
            self.assertIn(req_b.request_id, req_ids)

    def test_status_filtering_query_param(self):
        """Task A: ?status=PENDING (default), ?status=APPROVED, and ?status=ALL filtering."""
        req_pending = self.ds.create_access_request(
            organization_id="org_abc_001",
            user_id="usr_filter_pending",
            email="filter_pending@abc.com",
            display_name="Filter Pending"
        )
        req_approved = self.ds.create_access_request(
            organization_id="org_abc_001",
            user_id="usr_filter_approved",
            email="filter_approved@abc.com",
            display_name="Filter Approved"
        )
        req_approved.status = AccessRequestStatus.APPROVED

        # Default query (PENDING)
        url_default = f"{self.base_url}/api/admin/access-requests"
        req1 = urllib.request.Request(url_default, headers={"Cookie": f"session={self.admin_a_token}"})
        with urllib.request.urlopen(req1) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            req_ids = [r["request_id"] for r in data.get("requests", [])]
            self.assertIn(req_pending.request_id, req_ids)
            self.assertNotIn(req_approved.request_id, req_ids)

        # Filter APPROVED
        url_approved = f"{self.base_url}/api/admin/access-requests?status=APPROVED"
        req2 = urllib.request.Request(url_approved, headers={"Cookie": f"session={self.admin_a_token}"})
        with urllib.request.urlopen(req2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            req_ids = [r["request_id"] for r in data.get("requests", [])]
            self.assertNotIn(req_pending.request_id, req_ids)
            self.assertIn(req_approved.request_id, req_ids)

        # Filter ALL
        url_all = f"{self.base_url}/api/admin/access-requests?status=ALL"
        req3 = urllib.request.Request(url_all, headers={"Cookie": f"session={self.admin_a_token}"})
        with urllib.request.urlopen(req3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            req_ids = [r["request_id"] for r in data.get("requests", [])]
            self.assertIn(req_pending.request_id, req_ids)
            self.assertIn(req_approved.request_id, req_ids)

    def test_customer_admin_cannot_decide_request_for_another_org(self):
        """Task B: CUSTOMER_ADMIN for Org A receives 403 when trying to decide on Org B's request."""
        req_b = self.ds.create_access_request(
            organization_id="org_xyz_002",
            user_id="usr_target_b",
            email="target@xyz.com",
            display_name="Target XYZ"
        )

        url = f"{self.base_url}/api/admin/access-requests/decision"
        payload = {"request_id": req_b.request_id, "decision": "APPROVED"}
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": f"session={self.admin_a_token}"}
        )

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)

        # Ensure request remains PENDING and untouched
        self.assertEqual(self.ds.access_requests[req_b.request_id].status, AccessRequestStatus.PENDING)

    def test_non_admin_cannot_list_or_decide_access_requests(self):
        """Task B: Non-admin caller receives 403 Forbidden on both endpoints."""
        # List endpoint
        url_list = f"{self.base_url}/api/admin/access-requests"
        req_list = urllib.request.Request(url_list, headers={"Cookie": f"session={self.viewer_token}"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_list)
        self.assertEqual(ctx.exception.code, 403)

        # Decision endpoint
        req_a = self.ds.create_access_request(
            organization_id="org_abc_001",
            user_id="usr_forbidden_test",
            email="forbidden@abc.com",
            display_name="Forbidden Test"
        )
        url_dec = f"{self.base_url}/api/admin/access-requests/decision"
        req_dec = urllib.request.Request(
            url_dec,
            data=json.dumps({"request_id": req_a.request_id, "decision": "APPROVED"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": f"session={self.viewer_token}"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_dec)
        self.assertEqual(ctx.exception.code, 403)

    def test_approve_request_provisions_viewer_and_enables_immediate_login(self):
        """Task B: Approving request creates user with VIEWER role who can immediately authenticate (must_change_password=False)."""
        requester_email = "charlie@external.com"
        requester_name = "Charlie Requester"

        # Simulate unprovisioned user submitting an access request to Org ABC
        access_req = self.ds.create_access_request(
            organization_id="org_abc_001",
            user_id="usr_unprov_charlie",
            email=requester_email,
            display_name=requester_name
        )

        # Customer Admin A approves the request
        url = f"{self.base_url}/api/admin/access-requests/decision"
        payload = {"request_id": access_req.request_id, "decision": "APPROVED"}
        http_req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": f"session={self.admin_a_token}"}
        )

        with urllib.request.urlopen(http_req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "success")
            self.assertIn("user_id", data)
            self.assertEqual(data.get("request", {}).get("status"), "APPROVED")

        # 1. Verify datastore AccessRequest state
        updated_req = self.ds.access_requests[access_req.request_id]
        self.assertEqual(updated_req.status, AccessRequestStatus.APPROVED)
        self.assertIsNotNone(updated_req.reviewed_at)
        self.assertEqual(updated_req.reviewed_by, "usr_admin_org_a")

        # 2. Verify user was provisioned in Org ABC
        user_org_res = self.ds.resolve_user_organization(requester_email)
        self.assertIsNotNone(user_org_res, "User should now be resolvable in datastore")
        user, org = user_org_res
        self.assertEqual(org.organization_id, "org_abc_001")
        self.assertEqual(user.email, requester_email)
        self.assertFalse(user.must_change_password, "Entra user must NOT be forced to change password")

        # 3. Verify user has VIEWER role and company ACLs
        roles = self.ds.user_roles.get(f"{user.user_id}:{org.organization_id}")
        self.assertEqual(roles, {"VIEWER"})
        acls = self.ds.user_company_acls.get(f"{user.user_id}:{org.organization_id}")
        self.assertTrue(len(acls) > 0, "User should have organization companies assigned")

        # 4. Verify Entra login immediately produces a fully provisioned session
        entra_token = self.auth_mgr.login_entra_user(
            email=requester_email,
            display_name=requester_name
        )
        session = self.auth_mgr.get_session(entra_token)
        self.assertIsNotNone(session)
        self.assertTrue(session.provisioned)
        self.assertEqual(session.organization_id, "org_abc_001")
        self.assertEqual(session.roles, ["VIEWER"])
        self.assertFalse(session.must_change_password)

    def test_reject_request_updates_status_without_provisioning_user(self):
        """Task B: Rejecting request sets status to REJECTED and creates no user."""
        requester_email = "david@external.com"
        access_req = self.ds.create_access_request(
            organization_id="org_abc_001",
            user_id="usr_unprov_david",
            email=requester_email,
            display_name="David Requester"
        )

        url = f"{self.base_url}/api/admin/access-requests/decision"
        payload = {"request_id": access_req.request_id, "decision": "REJECTED"}
        http_req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": f"session={self.admin_a_token}"}
        )

        with urllib.request.urlopen(http_req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "success")
            self.assertEqual(data.get("request", {}).get("status"), "REJECTED")

        # Verify datastore request state
        updated_req = self.ds.access_requests[access_req.request_id]
        self.assertEqual(updated_req.status, AccessRequestStatus.REJECTED)
        self.assertIsNotNone(updated_req.reviewed_at)
        self.assertEqual(updated_req.reviewed_by, "usr_admin_org_a")

        # Verify user was NOT provisioned
        user_org_res = self.ds.resolve_user_organization(requester_email)
        self.assertIsNone(user_org_res, "Rejected requester should not be provisioned")

    def test_redeciding_already_resolved_request_returns_400(self):
        """Task B: Attempting to decide on an already resolved request returns 400 Bad Request."""
        access_req = self.ds.create_access_request(
            organization_id="org_abc_001",
            user_id="usr_once_only",
            email="once@abc.com",
            display_name="Once Only"
        )

        url = f"{self.base_url}/api/admin/access-requests/decision"
        payload = {"request_id": access_req.request_id, "decision": "APPROVED"}
        http_req1 = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": f"session={self.admin_a_token}"}
        )
        with urllib.request.urlopen(http_req1) as resp:
            self.assertEqual(resp.status, 200)

        # Attempt to decide again (e.g. Reject)
        http_req2 = urllib.request.Request(
            url,
            data=json.dumps({"request_id": access_req.request_id, "decision": "REJECTED"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": f"session={self.admin_a_token}"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(http_req2)
        self.assertEqual(ctx.exception.code, 400)
        err_body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("already APPROVED", err_body.get("error", ""))

    def test_enterprise_admin_can_decide_any_request(self):
        """Task B: ENTERPRISE_ADMIN can approve or reject requests for any organization."""
        access_req = self.ds.create_access_request(
            organization_id="org_xyz_002",
            user_id="usr_super_approve",
            email="super_approved@xyz.com",
            display_name="Super Approved"
        )

        url = f"{self.base_url}/api/admin/access-requests/decision"
        payload = {"request_id": access_req.request_id, "decision": "APPROVED"}
        http_req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": f"session={self.enterprise_admin_token}"}
        )

        with urllib.request.urlopen(http_req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "success")

        updated_req = self.ds.access_requests[access_req.request_id]
        self.assertEqual(updated_req.status, AccessRequestStatus.APPROVED)
        self.assertEqual(updated_req.reviewed_by, "usr_enterprise_admin")


if __name__ == "__main__":
    unittest.main()
