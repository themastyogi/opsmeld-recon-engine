"""
Unit and Integration Tests for Environment-Variable-Driven Bootstrap Provisioning
Verifies:
1. Resolution of bootstrapped Entra admin account into new Organization with role CUSTOMER_ADMIN.
2. Entra login creates provisioned session with AUTHENTICATED_PROVISIONED and must_change_password=False.
3. CUSTOMER_ADMIN can access authorized BC companies and modules.
4. CUSTOMER_ADMIN can provision other users into their own organization via /api/admin/viewers.
5. Bootstrap is strictly idempotent across multiple calls and server restarts (no duplicates).
6. ENTERPRISE_ADMIN permissions are NOT granted (fail-closed security boundary).
7. Seeded demo fixture org_abc_001 (ABC Manufacturing) remains completely untouched.
"""

import os
import json
import unittest
from unittest.mock import patch

from core.models import get_datastore, MultitenantDataStore, OrganizationStatus
from core.auth import get_auth_manager
from web.app import create_server


class TestBootstrapProvisioning(unittest.TestCase):

    def setUp(self):
        self.test_org_name = "Acme Global Dynamics"
        self.test_admin_email = "bootstrap_test_admin@acmeglobal.com"
        self.test_admin_name = "Acme Admin User"

        self.env_patcher = patch.dict(os.environ, {
            "OPSMELD_BOOTSTRAP_ORG_NAME": self.test_org_name,
            "OPSMELD_BOOTSTRAP_ADMIN_EMAIL": self.test_admin_email,
            "OPSMELD_BOOTSTRAP_ADMIN_NAME": self.test_admin_name
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_1_resolve_user_organization_returns_customer_admin_in_new_org(self):
        """Requirement 1: Read back ds.resolve_user_organization directly and confirm new user, new org, role CUSTOMER_ADMIN."""
        ds = MultitenantDataStore()  # creates fresh store which runs bootstrap_from_env()
        
        resolved = ds.resolve_user_organization(self.test_admin_email)
        self.assertIsNotNone(resolved, f"User {self.test_admin_email} must resolve to an organization")
        user, org = resolved

        # Organization assertions
        self.assertEqual(org.name, self.test_org_name)
        self.assertEqual(org.status, OrganizationStatus.ACTIVE)
        self.assertNotEqual(org.organization_id, "org_abc_001", "Must NOT reuse org_abc_001")
        self.assertTrue(ds.is_organization_active(org.organization_id))
        self.assertTrue(ds.is_module_subscribed(org.organization_id, "ar_control_tower"))
        self.assertTrue(ds.is_module_subscribed(org.organization_id, "data_trust"))

        # User assertions
        self.assertEqual(user.email, self.test_admin_email)
        self.assertEqual(user.display_name, self.test_admin_name)
        self.assertFalse(user.must_change_password, "Entra account must NOT have must_change_password=True")

        # Role and permission assertions
        roles = ds.user_roles.get(f"{user.user_id}:{org.organization_id}", set())
        self.assertIn("CUSTOMER_ADMIN", roles)
        self.assertNotIn("ENTERPRISE_ADMIN", roles, "Must NOT grant ENTERPRISE_ADMIN")

        perms = ds.get_user_permissions(user.user_id, org.organization_id)
        self.assertIn("org:users:manage", perms)
        self.assertIn("ar_control_tower:read", perms)
        self.assertIn("data_trust:read", perms)

    def test_2_entra_login_creates_authenticated_provisioned_session(self):
        """Requirement 2: Real live Entra login creates session with provisioned=True, status=AUTHENTICATED_PROVISIONED."""
        ds = get_datastore()
        ds.bootstrap_from_env()

        auth_mgr = get_auth_manager()
        token = auth_mgr.login_entra_user(
            email=self.test_admin_email,
            display_name=self.test_admin_name
        )
        self.assertIsNotNone(token)

        session = auth_mgr.get_session(token)
        self.assertIsNotNone(session)
        self.assertTrue(session.provisioned, "Session must be marked provisioned: True")
        self.assertEqual(session.email, self.test_admin_email)
        self.assertIn("CUSTOMER_ADMIN", session.roles)
        self.assertNotIn("ENTERPRISE_ADMIN", session.roles)
        self.assertFalse(session.must_change_password, "Entra session must NOT require password change")

        # Session dictionary matches frontend expectation
        sdict = session.to_dict()
        self.assertEqual(sdict.get("status"), "ACTIVE")
        self.assertTrue(sdict.get("authenticated"))
        self.assertTrue(sdict.get("provisioned"))

    def test_3_customer_admin_has_authorized_bc_companies(self):
        """Requirement 3: Confirm this account has access to the org's real discoverable companies."""
        ds = get_datastore()
        ds.bootstrap_from_env()

        resolved = ds.resolve_user_organization(self.test_admin_email)
        self.assertIsNotNone(resolved)
        user, org = resolved

        allowed = ds.get_user_allowed_companies(user.user_id, org.organization_id)
        self.assertIn("ac6b97ba-bc8f-f111-832d-7c1e5233db45", allowed)  # CRONUS IN
        self.assertIn("c37ac1c0-bc8f-f111-832d-7c1e5233db45", allowed)  # My Company
        self.assertIn("c4e0106b-159e-f111-8072-7ced8d9f80ff", allowed)  # Sandbox

        org_comps = ds.org_companies.get(org.organization_id, [])
        comp_names = [c.name for c in org_comps]
        self.assertIn("CRONUS IN", comp_names)
        self.assertIn("My Company", comp_names)
        self.assertIn("Sandbox", comp_names)

    def test_4_customer_admin_can_provision_users_in_own_org(self):
        """Requirement 4: Confirm account can use /api/admin/viewers endpoint to provision users into their own org."""
        ds = get_datastore()
        ds.bootstrap_from_env()
        auth_mgr = get_auth_manager()

        # Generate active session for the bootstrapped CUSTOMER_ADMIN
        admin_token = auth_mgr.login_entra_user(
            email=self.test_admin_email,
            display_name=self.test_admin_name
        )
        session = auth_mgr.get_session(admin_token)
        org_id = session.organization_id

        # Use test client / handler simulation
        from web.app import OpsmeldWebHandler
        from unittest.mock import MagicMock
        import io

        handler = OpsmeldWebHandler.__new__(OpsmeldWebHandler)
        handler.headers = {"Cookie": f"session={admin_token}", "Content-Length": "0"}
        handler.command = "POST"
        handler.path = "/api/admin/viewers"
        handler.rfile = io.BytesIO(json.dumps({
            "email": "finance_viewer@acmeglobal.com",
            "display_name": "Finance Viewer",
            "organization_id": org_id,
            "allowed_companies": ["ac6b97ba-bc8f-f111-832d-7c1e5233db45"],
            "role": "VIEWER"
        }).encode("utf-8"))
        handler.headers["Content-Length"] = str(len(handler.rfile.getvalue()))
        handler.wfile = io.BytesIO()
        handler._set_headers = MagicMock()

        handler.do_POST()

        # Confirm 201 Created or 200 OK
        handler._set_headers.assert_called_with("application/json", 201)
        resp_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(resp_data.get("status"), "success")
        self.assertEqual(resp_data.get("role"), "VIEWER")
        self.assertEqual(resp_data.get("organization_id"), org_id)

        # Confirm user was created in datastore under the bootstrap org
        resolved_viewer = ds.resolve_user_organization("finance_viewer@acmeglobal.com")
        self.assertIsNotNone(resolved_viewer)
        v_user, v_org = resolved_viewer
        self.assertEqual(v_org.organization_id, org_id)

    def test_5_idempotency_restart_does_not_create_duplicate(self):
        """Requirement 5: Restart / multiple runs with same environment variables does NOT create duplicate organizations."""
        ds = MultitenantDataStore()
        
        # First bootstrap
        org1 = ds.bootstrap_from_env()
        self.assertIsNotNone(org1)
        initial_org_count = len(ds.organizations)
        initial_user_count = len(ds.users)

        # Second bootstrap simulation (e.g. server restart or create_server call)
        org2 = ds.bootstrap_from_env()
        self.assertEqual(org1.organization_id, org2.organization_id)
        self.assertEqual(len(ds.organizations), initial_org_count, "Organization count must not increase")
        self.assertEqual(len(ds.users), initial_user_count, "User count must not increase")

        # Third run via create_server
        server = create_server("127.0.0.1", 8099)
        server.server_close()
        
        matching_orgs = [o for o in ds.organizations.values() if o.name.strip().lower() == self.test_org_name.lower()]
        self.assertEqual(len(matching_orgs), 1, "Exactly one organization must exist for this bootstrap name")

    def test_6_enterprise_admin_boundaries_are_enforced(self):
        """Open Question Boundary: CUSTOMER_ADMIN must NOT hold ENTERPRISE_ADMIN rights."""
        ds = get_datastore()
        ds.bootstrap_from_env()
        auth_mgr = get_auth_manager()

        admin_token = auth_mgr.login_entra_user(
            email=self.test_admin_email,
            display_name=self.test_admin_name
        )

        from web.app import OpsmeldWebHandler
        from unittest.mock import MagicMock
        import io

        # Attempt to call ENTERPRISE_ADMIN-only endpoint: POST /api/admin/registrations/approve
        handler = OpsmeldWebHandler.__new__(OpsmeldWebHandler)
        handler.headers = {"Cookie": f"session={admin_token}", "Content-Length": "0"}
        handler.command = "POST"
        handler.path = "/api/admin/registrations/approve"
        handler.rfile = io.BytesIO(json.dumps({
            "registration_id": "reg_dummy"
        }).encode("utf-8"))
        handler.headers["Content-Length"] = str(len(handler.rfile.getvalue()))
        handler.wfile = io.BytesIO()
        handler._set_headers = MagicMock()

        handler.do_POST()

        # Must be rejected with 403 Forbidden
        handler._set_headers.assert_called_with("application/json", 403)
        resp_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("Platform Admin required", resp_data.get("error", ""))

    def test_7_seeded_demo_org_abc_remains_untouched(self):
        """Integrity Guard: org_abc_001 (ABC Manufacturing) fixture remains completely intact."""
        ds = get_datastore()
        ds.bootstrap_from_env()

        abc = ds.get_organization("org_abc_001")
        self.assertIsNotNone(abc)
        self.assertEqual(abc.name, "ABC Manufacturing")
        self.assertEqual(abc.status, OrganizationStatus.ACTIVE)
        self.assertIn("usr_admin_001", ds.org_users.get("org_abc_001", set()))


if __name__ == "__main__":
    unittest.main()
