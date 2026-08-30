"""
Opsmeld Unit Tests for Specification v2.0 Acceptance Criteria (Section 25)
Verifies:
- Scenario A: Existing customer sign-in -> Entra -> Customer resolved -> Portal -> Module available.
- Scenario B: New user of existing customer (no role assigned) -> Portal -> Module state NOT_PERMITTED.
- Scenario C: New company registration -> REGISTRATION_PENDING -> No application access.
- Scenario D: Opsmeld Admin approves company -> Subscriptions configured -> Customer Admin provisioned.
- Scenario E: Customer Admin provisions employee with role + company ACL -> Employee sees module AVAILABLE & company visible.
- Scenario F: Customer Admin tries to grant permission for unpurchased module -> Evaluates NOT_SUBSCRIBED (403 MODULE_NOT_SUBSCRIBED).
- Scenario G: Opsmeld Admin suspends customer -> Immediate 403 ORGANIZATION_SUSPENDED on protected APIs.
"""

import json
import unittest
from core.auth import get_auth_manager
from core.authorization import CentralAuthorizationEngine, DenialReason, ModulePortalState
from core.models import get_datastore, MultitenantDataStore, OrganizationStatus, RegistrationStatus


class TestSpecV2Acceptance(unittest.TestCase):
    def setUp(self):
        self.auth_mgr = get_auth_manager()
        self.ds = get_datastore()

    def test_scenario_a_existing_customer_signin(self):
        # Entra sign in for seeded admin Vikas Kumar
        token = self.auth_mgr.login_entra_user("admin@opsmeld.com", "Vikas Kumar (CRONUS IN)")
        session = self.auth_mgr.get_session(token)
        self.assertIsNotNone(session)
        self.assertTrue(session.provisioned)
        self.assertEqual(session.organization_id, "org_abc_001")

        # Portal module evaluation
        modules = CentralAuthorizationEngine.evaluate_portal_modules(session)
        mod_dict = {m["id"]: m for m in modules}
        self.assertIn("ar_control_tower", mod_dict)
        self.assertEqual(mod_dict["ar_control_tower"]["state"], ModulePortalState.AVAILABLE)
        self.assertTrue(mod_dict["ar_control_tower"]["organization_subscribed"])
        self.assertTrue(mod_dict["ar_control_tower"]["user_permitted"])

    def test_scenario_b_new_user_unpermitted(self):
        # Register user under org_abc_001 without permissions
        user_id = "usr_unpermitted_99"
        self.ds.users[user_id] = User(user_id, "oid_unperm", "unperm@opsmeld.com", "Unpermitted User")
        self.ds.user_org[user_id] = "org_abc_001"
        self.ds.org_users["org_abc_001"].add(user_id)
        self.ds.user_roles[f"{user_id}:org_abc_001"] = set() # No roles assigned

        token = self.auth_mgr.login_entra_user("unperm@opsmeld.com", "Unpermitted User")
        session = self.auth_mgr.get_session(token)
        self.assertTrue(session.provisioned)

        modules = CentralAuthorizationEngine.evaluate_portal_modules(session)
        mod_dict = {m["id"]: m for m in modules}
        self.assertEqual(mod_dict["data_trust"]["state"], ModulePortalState.NOT_PERMITTED)
        self.assertTrue(mod_dict["data_trust"]["organization_subscribed"])
        self.assertFalse(mod_dict["data_trust"]["user_permitted"])
        self.assertTrue(mod_dict["data_trust"]["can_request_access"])

    def test_scenario_c_new_company_registration_pending(self):
        reg = self.ds.create_registration(
            organization_name="Quantum Financials",
            requester_name="Alex Smith",
            business_email="alex@quantum.com",
            requested_modules=["ar_control_tower"]
        )
        self.assertEqual(reg.status, RegistrationStatus.REGISTRATION_PENDING)

        # External user login before approval -> Fails closed to unprovisioned
        token = self.auth_mgr.login_entra_user("alex@quantum.com", "Alex Smith")
        session = self.auth_mgr.get_session(token)
        self.assertFalse(session.provisioned)
        self.assertEqual(session.to_dict()["status"], "ACCOUNT_NOT_PROVISIONED")

        is_allowed, reason = CentralAuthorizationEngine.authorize(session, "ar_control_tower")
        self.assertFalse(is_allowed)
        self.assertEqual(reason, DenialReason.UNAUTHENTICATED)

    def test_scenario_d_opsmeld_admin_approves_company(self):
        reg = self.ds.create_registration(
            organization_name="Apex Logistics",
            requester_name="Robert Vance",
            business_email="robert@apex.com",
            requested_modules=["ar_control_tower", "data_trust"]
        )
        org = self.ds.approve_registration(reg.registration_id, "usr_admin_001")
        self.assertIsNotNone(org)
        self.assertEqual(org.status, OrganizationStatus.TRIAL)

        # Robert Vance signs in after approval
        token = self.auth_mgr.login_entra_user("robert@apex.com", "Robert Vance")
        session = self.auth_mgr.get_session(token)
        self.assertTrue(session.provisioned)
        self.assertEqual(session.organization_id, org.organization_id)
        self.assertIn("CUSTOMER_ADMIN", session.roles)

    def test_scenario_e_customer_admin_provisions_employee(self):
        # Create Org and Customer Admin
        org_id = "org_test_e"
        org = Organization(org_id, "Test E Corp", OrganizationStatus.ACTIVE)
        self.ds.organizations[org_id] = org
        self.ds.subscriptions[org_id] = Subscription(f"sub_{org_id}", org_id, "Enterprise")
        self.ds.org_modules[org_id] = {"ar_control_tower"}

        # Provision employee with role & company ACL
        user_id = "usr_emp_e"
        user = User(user_id, f"oid_{user_id}", "employee@test-e.com", "Test Employee")
        self.ds.users[user_id] = user
        self.ds.user_org[user_id] = org_id
        self.ds.org_users[org_id] = {user_id}
        self.ds.org_roles[org_id] = {
            "AR_ANALYST": {"ar_control_tower:read"}
        }
        self.ds.user_roles[f"{user_id}:{org_id}"] = {"AR_ANALYST"}
        self.ds.user_company_acls[f"{user_id}:{org_id}"] = {"GUID-COMP-01"}

        token = self.auth_mgr.login_entra_user("employee@test-e.com", "Test Employee")
        session = self.auth_mgr.get_session(token)
        self.assertTrue(session.provisioned)

        is_allowed, reason = CentralAuthorizationEngine.authorize(
            session=session,
            module_id="ar_control_tower",
            permission="ar_control_tower:read",
            company_id="GUID-COMP-01"
        )
        self.assertTrue(is_allowed)
        self.assertEqual(reason, "ALLOW")

    def test_scenario_f_unpurchased_module_evaluated_not_subscribed(self):
        # Org has ONLY ar_control_tower, NOT layer_3
        token = self.auth_mgr.login_entra_user("admin@opsmeld.com", "Vikas Kumar")
        session = self.auth_mgr.get_session(token)

        # Attempt to authorize layer_3
        is_allowed, reason = CentralAuthorizationEngine.authorize(
            session=session,
            module_id="layer_3",
            permission="layer_3:read"
        )
        self.assertFalse(is_allowed)
        self.assertEqual(reason, DenialReason.MODULE_NOT_SUBSCRIBED)

        modules = CentralAuthorizationEngine.evaluate_portal_modules(session)
        mod_dict = {m["id"]: m for m in modules}
        self.assertEqual(mod_dict["layer_3"]["state"], ModulePortalState.NOT_SUBSCRIBED)
        self.assertFalse(mod_dict["layer_3"]["organization_subscribed"])
        self.assertFalse(mod_dict["layer_3"]["can_request_access"])

    def test_scenario_g_suspended_organization_denied(self):
        # Suspend Demo Corp
        token = self.auth_mgr.create_session(
            user_id="usr_demo_user",
            email="demo@democorp.com",
            display_name="Demo User",
            roles=["CUSTOMER_ADMIN"],
            organization_id="org_demo_003" # Suspended Org
        )
        session = self.auth_mgr.get_session(token)

        is_allowed, reason = CentralAuthorizationEngine.authorize(
            session=session,
            module_id="ar_control_tower",
            permission="ar_control_tower:read"
        )
        self.assertFalse(is_allowed)
        self.assertEqual(reason, DenialReason.ORGANIZATION_SUSPENDED)


from core.models import User, Organization, Subscription

if __name__ == "__main__":
    unittest.main()
