"""
Opsmeld Unit Tests: Read-Only Viewer Accounts & Security Boundary (Task A, B, C, D)
Verifies:
1. Admin provisioning of VIEWER accounts via POST /api/admin/viewers.
2. Non-admin rejection (HTTP 403) and invalid company GUID rejection (HTTP 400).
3. Viewer password login via POST /api/auth/login.
4. VIEWER can access read endpoints for allowed companies.
5. VIEWER is rejected with HTTP 403 on write endpoints (e.g. data_trust:write / run-recon).
6. VIEWER is rejected with HTTP 403 when accessing unassigned companies.
7. Entra-provisioned users without password hashes are rejected on password login (HTTP 401).
"""

import json
import threading
import unittest
import urllib.request
import urllib.error
from web.app import create_server
from core.auth import get_auth_manager
from core.models import get_datastore


class TestViewerRoleAndSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 8095
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
        self.comp_a = "ac6b97ba-bc8f-f111-832d-7c1e5233db45"
        self.comp_b = "c37ac1c0-bc8f-f111-832d-7c1e5233db45"

        # Create admin session
        self.admin_token = self.auth_mgr.create_session(
            user_id="usr_admin_viewer_test",
            email="admin_vt@opsmeld.com",
            display_name="Admin Viewer Test",
            roles=["CUSTOMER_ADMIN"],
            organization_id="org_abc_001",
            permissions={"org:users:manage", "data_trust:read", "data_trust:write"},
            allowed_companies={self.comp_a, self.comp_b}
        )

    def test_admin_provisions_viewer_and_receives_password(self):
        """Task B: Admin can provision a VIEWER user and receives a one-time temporary password."""
        url = f"{self.base_url}/api/admin/viewers"
        payload = {
            "email": "readonly_user_1@opsmeld.com",
            "display_name": "Read Only User One",
            "allowed_companies": [self.comp_a]
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.admin_token}"
            }
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("role"), "VIEWER")
        self.assertEqual(data.get("email"), "readonly_user_1@opsmeld.com")
        self.assertIn("temporary_password", data)
        self.assertTrue(len(data["temporary_password"]) >= 16)

    def test_non_admin_cannot_provision_viewer(self):
        """Task B: Non-admin users (e.g. standard viewer) are rejected with HTTP 403."""
        viewer_token = self.auth_mgr.create_session(
            user_id="usr_viewer_nonadmin",
            email="viewer_nonadmin@opsmeld.com",
            display_name="Non Admin Viewer",
            roles=["VIEWER"],
            organization_id="org_abc_001",
            permissions={"data_trust:read"},
            allowed_companies={self.comp_a}
        )
        url = f"{self.base_url}/api/admin/viewers"
        req = urllib.request.Request(
            url,
            data=json.dumps({
                "email": "unauthorized_viewer@opsmeld.com",
                "allowed_companies": [self.comp_a]
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {viewer_token}"
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)

    def test_provision_viewer_rejects_arbitrary_unauthorized_company_guid(self):
        """Task B: Provisioning endpoint rejects arbitrary, unauthorized company GUIDs with HTTP 400."""
        url = f"{self.base_url}/api/admin/viewers"
        req = urllib.request.Request(
            url,
            data=json.dumps({
                "email": "invalid_company_viewer@opsmeld.com",
                "allowed_companies": ["arbitrary_fake_guid_999"]
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.admin_token}"
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_viewer_password_login_and_read_success(self):
        """Task D (1): VIEWER logs in with provisioned password and can reach read endpoints."""
        email = "viewer_auth_test@opsmeld.com"
        url_prov = f"{self.base_url}/api/admin/viewers"
        req_prov = urllib.request.Request(
            url_prov,
            data=json.dumps({
                "email": email,
                "display_name": "Viewer Auth Test",
                "allowed_companies": [self.comp_a]
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.admin_token}"
            }
        )
        with urllib.request.urlopen(req_prov) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            temp_password = data["temporary_password"]

        req_login = urllib.request.Request(
            f"{self.base_url}/api/auth/login",
            data=json.dumps({"email": email, "password": temp_password}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_login) as resp_login:
            self.assertEqual(resp_login.status, 200)
            login_data = json.loads(resp_login.read().decode("utf-8"))
            viewer_token = login_data["token"]

        req_read = urllib.request.Request(
            f"{self.base_url}/api/data-trust/findings?company_id={self.comp_a}",
            headers={"Authorization": f"Bearer {viewer_token}"}
        )
        with urllib.request.urlopen(req_read) as resp_read:
            self.assertEqual(resp_read.status, 200)

    def test_viewer_denied_write_endpoints(self):
        """Task D (1): VIEWER session gets HTTP 403 on write endpoints (e.g. run-recon)."""
        viewer_token = self.auth_mgr.create_session(
            user_id="usr_viewer_write_test",
            email="viewer_write_test@opsmeld.com",
            display_name="Viewer Write Test",
            roles=["VIEWER"],
            organization_id="org_abc_001",
            permissions={"data_trust:read", "ar_control_tower:read", "layer_3:read"},
            allowed_companies={self.comp_a}
        )
        req_recon = urllib.request.Request(
            f"{self.base_url}/api/data-trust/run-recon?company_id={self.comp_a}",
            headers={"Authorization": f"Bearer {viewer_token}"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_recon)
        self.assertEqual(ctx.exception.code, 403)

        req_status = urllib.request.Request(
            f"{self.base_url}/api/admin/organizations/status",
            data=json.dumps({"organization_id": "org_abc_001", "status": "ACTIVE"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {viewer_token}"
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx2:
            urllib.request.urlopen(req_status)
        self.assertEqual(ctx2.exception.code, 403)

    def test_viewer_company_isolation(self):
        """Task D (2): VIEWER with allowed_companies = {comp_a} gets HTTP 403 when requesting comp_b."""
        viewer_token = self.auth_mgr.create_session(
            user_id="usr_viewer_iso_test",
            email="viewer_iso@opsmeld.com",
            display_name="Viewer Isolation Test",
            roles=["VIEWER"],
            organization_id="org_abc_001",
            permissions={"data_trust:read", "ar_control_tower:read"},
            allowed_companies={self.comp_a}
        )
        req_unassigned = urllib.request.Request(
            f"{self.base_url}/api/data-trust/findings?company_id={self.comp_b}",
            headers={"Authorization": f"Bearer {viewer_token}"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_unassigned)
        self.assertEqual(ctx.exception.code, 403)

    def test_entra_user_without_password_hash_fails_password_login(self):
        """Task D (3): Standard Entra user with no password hash fails password login with HTTP 401."""
        entra_email = "entra_only_employee@opsmeld.com"
        self.ds.provision_viewer_user("org_abc_001", entra_email, "Entra Employee", {self.comp_a})
        self.auth_mgr._user_passwords.pop(entra_email, None)

        req = urllib.request.Request(
            f"{self.base_url}/api/auth/login",
            data=json.dumps({"email": entra_email, "password": "AttemptPassword999!"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 401)

    def test_customer_admin_cannot_create_user_in_other_org_lands_in_own_org(self):
        """Task A: CUSTOMER_ADMIN for org A attempts to pass organization_id: 'org-B'.
        Confirms the created user strictly lands in org A, not org B."""
        from core.models import Organization, OrganizationStatus
        # Setup Org B
        org_b_id = "org_xyz_999"
        if not self.ds.get_organization(org_b_id):
            self.ds.organizations[org_b_id] = Organization(org_b_id, "Organization B", OrganizationStatus.ACTIVE)
            self.ds.org_users[org_b_id] = set()

        target_email = "scope_tamper_user@opsmeld.com"
        url = f"{self.base_url}/api/admin/users"
        payload = {
            "email": target_email,
            "display_name": "Scope Tamper User",
            "organization_id": org_b_id,  # Adversarial attempt to create in Org B
            "role": "VIEWER",
            "allowed_companies": [self.comp_a]
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.admin_token}"
            }
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))

        user_id = data["user_id"]
        # Response must show caller's org_abc_001, NOT org_b_id
        self.assertEqual(data["organization_id"], "org_abc_001")

        # Datastore verification: User MUST land in org_abc_001, never in org_b_id
        self.assertEqual(self.ds.user_org.get(user_id), "org_abc_001")
        self.assertIn(user_id, self.ds.org_users.get("org_abc_001", set()))
        self.assertNotIn(user_id, self.ds.org_users.get(org_b_id, set()))

        # Resolution verification: Resolving identity points to org_abc_001
        resolved = self.ds.resolve_user_organization(target_email)
        self.assertIsNotNone(resolved)
        user_obj, org_obj = resolved
        self.assertEqual(org_obj.organization_id, "org_abc_001")

    def test_customer_admin_can_create_customer_admin_in_own_org(self):
        """Task A: CUSTOMER_ADMIN can create another CUSTOMER_ADMIN user in their own org."""
        target_email = "new_co_admin@opsmeld.com"
        url = f"{self.base_url}/api/admin/users"
        payload = {
            "email": target_email,
            "display_name": "New Company Admin",
            "role": "CUSTOMER_ADMIN",
            "allowed_companies": [self.comp_a]
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.admin_token}"
            }
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(data["role"], "CUSTOMER_ADMIN")
        self.assertEqual(data["organization_id"], "org_abc_001")
        temp_pass = data["temporary_password"]

        # Log in as newly created CUSTOMER_ADMIN
        req_login = urllib.request.Request(
            f"{self.base_url}/api/auth/login",
            data=json.dumps({"email": target_email, "password": temp_pass}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_login) as resp_login:
            self.assertEqual(resp_login.status, 200)
            login_data = json.loads(resp_login.read().decode("utf-8"))
            new_admin_token = login_data["token"]

        new_session = self.auth_mgr.get_session(new_admin_token)
        self.assertIn("CUSTOMER_ADMIN", new_session.roles)
        self.assertTrue(new_session.has_permission("org:users:manage"))
        self.assertTrue(new_session.has_permission("data_trust:write"))

    def test_enterprise_admin_can_create_users_in_any_org(self):
        """Task A: ENTERPRISE_ADMIN can create users in any org by specifying organization_id."""
        enterprise_token = self.auth_mgr.create_session(
            user_id="usr_enterprise_tester",
            email="platform_boss@opsmeld.com",
            display_name="Enterprise Admin Tester",
            roles=["ENTERPRISE_ADMIN"],
            organization_id=None,
            provisioned=True
        )

        url = f"{self.base_url}/api/admin/users"
        # 1. Success with organization_id
        payload_ok = {
            "email": "enterprise_created_user@opsmeld.com",
            "display_name": "Enterprise Created User",
            "organization_id": "org_abc_001",
            "role": "VIEWER",
            "allowed_companies": [self.comp_a]
        }
        req_ok = urllib.request.Request(
            url,
            data=json.dumps(payload_ok).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {enterprise_token}"
            }
        )
        with urllib.request.urlopen(req_ok) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["organization_id"], "org_abc_001")

        # 2. Rejection (400) if ENTERPRISE_ADMIN caller omits organization_id
        payload_no_org = {
            "email": "enterprise_no_org@opsmeld.com",
            "role": "VIEWER",
            "allowed_companies": [self.comp_a]
        }
        req_no_org = urllib.request.Request(
            url,
            data=json.dumps(payload_no_org).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {enterprise_token}"
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_no_org)
        self.assertEqual(ctx.exception.code, 400)

    def test_cannot_provision_enterprise_admin_via_api(self):
        """Task B: API strictly rejects any attempt to create ENTERPRISE_ADMIN with HTTP 400."""
        url = f"{self.base_url}/api/admin/users"
        payload = {
            "email": "malicious_admin_attempt@opsmeld.com",
            "role": "ENTERPRISE_ADMIN",
            "allowed_companies": [self.comp_a]
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.admin_token}"
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        data = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("Cannot provision ENTERPRISE_ADMIN", data.get("error", ""))

    def test_organizations_status_tightening_rejects_invalid_module_id(self):
        """Task C: /api/admin/organizations/status rejects invalid module IDs with HTTP 400."""
        enterprise_token = self.auth_mgr.create_session(
            user_id="usr_enterprise_mod_tester",
            email="platform_modules@opsmeld.com",
            display_name="Enterprise Mod Tester",
            roles=["ENTERPRISE_ADMIN"],
            organization_id=None,
            provisioned=True
        )
        url = f"{self.base_url}/api/admin/organizations/status"

        # 1. Invalid module ID returns 400
        req_invalid = urllib.request.Request(
            url,
            data=json.dumps({
                "organization_id": "org_abc_001",
                "modules": ["data_trust", "totally_fake_module_xyz"]
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {enterprise_token}"
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_invalid)
        self.assertEqual(ctx.exception.code, 400)
        err_data = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("Invalid module ID", err_data.get("error", ""))

        # 2. Valid modules return 200 and persist
        req_valid = urllib.request.Request(
            url,
            data=json.dumps({
                "organization_id": "org_abc_001",
                "modules": ["data_trust", "ar_control_tower"]
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {enterprise_token}"
            }
        )
        with urllib.request.urlopen(req_valid) as resp:
            self.assertEqual(resp.status, 200)

        self.assertEqual(self.ds.org_modules.get("org_abc_001"), {"data_trust", "ar_control_tower"})


if __name__ == "__main__":
    unittest.main()
