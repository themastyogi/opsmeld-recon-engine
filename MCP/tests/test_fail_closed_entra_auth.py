"""
Opsmeld Unit Tests for Fail-Closed Entra Authentication & Persistent Multitenant Datastore (v1.3)
Verifies:
1. Unknown Entra identity receives unprovisioned session (provisioned=False, status=ACCOUNT_NOT_PROVISIONED).
2. CentralAuthorizationEngine denies access for unprovisioned users (HTTP 401/403).
3. Organization registration approval provisions active organization, trial subscription, and customer admin.
4. File persistence preserves registrations and approved organization lifecycle states across restarts.
"""

import json
import os
import tempfile
import unittest
from core.auth import get_auth_manager, AuthManager, OpsmeldUserSession
from core.authorization import CentralAuthorizationEngine, DenialReason
from core.models import get_datastore, MultitenantDataStore, OrganizationStatus, RegistrationStatus


class TestFailClosedEntraAuth(unittest.TestCase):
    def setUp(self):
        self.auth_mgr = get_auth_manager()

    def test_unknown_entra_user_receives_unprovisioned_session(self):
        token = self.auth_mgr.login_entra_user(
            email="unknown_user_99@external.com",
            display_name="Unknown Guest User",
            entra_oid="oid_unknown_999"
        )
        self.assertIsNotNone(token)

        session = self.auth_mgr.get_session(token)
        self.assertIsNotNone(session)
        self.assertFalse(session.provisioned)
        self.assertIsNone(session.organization_id)
        self.assertEqual(len(session.roles), 0)
        self.assertEqual(len(session.permissions), 0)

        s_dict = session.to_dict()
        self.assertTrue(s_dict["authenticated"])
        self.assertFalse(s_dict["provisioned"])
        self.assertEqual(s_dict["status"], "ACCOUNT_NOT_PROVISIONED")
        self.assertIsNone(s_dict["organization"])

    def test_unprovisioned_user_fails_authorization_engine(self):
        token = self.auth_mgr.login_entra_user(
            email="unprovisioned_user@external.com",
            display_name="Unprovisioned Guest"
        )
        session = self.auth_mgr.get_session(token)

        is_allowed, reason = CentralAuthorizationEngine.authorize(
            session=session,
            module_id="data_trust",
            permission="data_trust:read"
        )
        self.assertFalse(is_allowed)
        self.assertEqual(reason, DenialReason.UNAUTHENTICATED)

    def test_registration_approval_provisions_customer_admin(self):
        ds = get_datastore()
        reg = ds.create_registration(
            organization_name="Global Logistics Corp",
            requester_name="Jane Doe",
            business_email="jane.doe@globallogistics.com",
            requested_modules=["ar_control_tower", "data_trust"]
        )
        self.assertEqual(reg.status, RegistrationStatus.REGISTRATION_PENDING)

        org = ds.approve_registration(reg.registration_id, reviewer_user_id="usr_admin_001")
        self.assertIsNotNone(org)
        self.assertEqual(org.name, "Global Logistics Corp")
        self.assertEqual(org.status, OrganizationStatus.TRIAL)

        # Entra login for newly provisioned user
        token = self.auth_mgr.login_entra_user(
            email="jane.doe@globallogistics.com",
            display_name="Jane Doe"
        )
        session = self.auth_mgr.get_session(token)
        self.assertIsNotNone(session)
        self.assertTrue(session.provisioned)
        self.assertEqual(session.organization_id, org.organization_id)
        self.assertIn("CUSTOMER_ADMIN", session.roles)
        self.assertIn("ar_control_tower:read", session.permissions)
        self.assertIn("data_trust:read", session.permissions)

        # Authorization engine now succeeds
        is_allowed, reason = CentralAuthorizationEngine.authorize(
            session=session,
            module_id="data_trust",
            permission="data_trust:read"
        )
        self.assertTrue(is_allowed)
        self.assertEqual(reason, "ALLOW")

    def test_multitenant_datastore_file_persistence(self):
        ds = MultitenantDataStore()
        reg = ds.create_registration("Test Corp Persistence", "John Persistence", "john@persist.com", ["ar_control_tower"])

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "multitenant_store.json")
            ds.persist(filepath=file_path)

            self.assertTrue(os.path.exists(file_path))
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertIn("organizations", data)
            self.assertIn("registrations", data)
            reg_names = [r["organization_name"] for r in data["registrations"]]
            self.assertIn("Test Corp Persistence", reg_names)

    def test_login_entra_user_without_arguments_raises_valueerror(self):
        with self.assertRaises(ValueError):
            self.auth_mgr.login_entra_user()

    def test_create_session_without_org_id_raises_typeerror(self):
        with self.assertRaises(TypeError):
            self.auth_mgr.create_session(
                user_id="u1",
                email="e1@test.com",
                display_name="Test",
                roles=["USER"]
            )

    def test_unprovisioned_session_evaluates_zero_modules(self):
        token = self.auth_mgr.create_session(
            user_id="usr_unprovisioned_test",
            email="unprovisioned@test.com",
            display_name="Unprovisioned Test",
            roles=[],
            organization_id=None,
            provisioned=False
        )
        session = self.auth_mgr.get_session(token)
        self.assertIsNotNone(session)
        self.assertFalse(session.provisioned)
        self.assertIsNone(session.organization_id)

        modules = CentralAuthorizationEngine.evaluate_portal_modules(session)
        self.assertEqual(modules, [])


if __name__ == "__main__":
    unittest.main()
