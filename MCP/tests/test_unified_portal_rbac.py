"""
Opsmeld Application Portal & Unified RBAC Automated Test Suite.
Verifies all 16 security acceptance criteria across session authentication,
two-dimensional permission boundaries (Module Permissions + Explicit Company Entitlements),
standardized portal endpoints, logout, session expiry, and dynamic module registration.
"""

import json
import time
import unittest
from unittest.mock import MagicMock, patch
from core.auth import get_auth_manager, AuthManager, OpsmeldUserSession
from core.rbac import get_module_registry, RBACResolver
from web.app import OpsmeldWebHandler


class MockRequest:
    def __init__(self, headers=None, path="/"):
        self.headers = headers or {}
        self.path = path

    def makefile(self, *args, **kwargs):
        return None


class TestUnifiedPortalRBAC(unittest.TestCase):
    def setUp(self):
        self.auth_mgr = get_auth_manager()
        self.test_guid_a = "ac6b97ba-bc8f-f111-832d-7c1e5233db45"
        self.test_guid_b = "c37ac1c0-bc8f-f111-832d-7c1e5233db45"
        self.unauthorized_guid = "99999999-9999-9999-9999-999999999999"

    def _create_test_handler(self, path, method="GET", headers=None, body=None):
        handler = OpsmeldWebHandler.__new__(OpsmeldWebHandler)
        handler.path = path
        handler.headers = headers or {}
        handler.rfile = MagicMock()
        if body:
            handler.rfile.read.return_value = body.encode("utf-8") if isinstance(body, str) else body
        
        handler.response_code = None
        handler.response_headers = {}
        handler.written_data = b""

        def send_response(code):
            handler.response_code = code

        def send_header(keyword, value):
            handler.response_headers[keyword] = value

        def end_headers():
            pass

        def write(data):
            handler.written_data += data

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = end_headers
        handler.wfile = MagicMock()
        handler.wfile.write = write
        return handler

    # Case 1: No session -> 401
    def test_case_01_no_session_returns_401(self):
        handler = self._create_test_handler("/api/portal/modules")
        handler.do_GET()
        self.assertEqual(handler.response_code, 401)
        resp = json.loads(handler.written_data.decode("utf-8"))
        self.assertIn("error", resp)

    # Case 2: Valid session -> /api/auth/me returns 200
    def test_case_02_valid_session_auth_me_returns_200(self):
        token = self.auth_mgr.create_session(
            user_id="usr_dt_001",
            email="auditor@opsmeld.com",
            display_name="Auditor User",
            roles=["DATA_TRUST_ANALYST"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a}
        )
        handler = self._create_test_handler("/api/auth/me", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 200)
        resp = json.loads(handler.written_data.decode("utf-8"))
        self.assertTrue(resp["authenticated"])
        self.assertEqual(resp["user"]["email"], "auditor@opsmeld.com")
        self.assertIn("data_trust:read", resp["permissions"])

    # Case 3: No DT permission -> 403 on DT API
    def test_case_03_no_dt_permission_returns_403(self):
        token = self.auth_mgr.create_session(
            user_id="usr_ar_001",
            email="ar@opsmeld.com",
            display_name="AR Analyst",
            roles=["AR_ANALYST"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a}
        )
        handler = self._create_test_handler(f"/api/data-trust/findings?company_id={self.test_guid_a}", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 403)
        resp = json.loads(handler.written_data.decode("utf-8"))
        self.assertIn("lacks required module permission", resp["error"])

    # Case 4: DT read permission -> findings allowed (mocked data layer)
    @patch("web.app.CompanyAccessManager")
    @patch("web.app.DataTrustEngine")
    def test_case_04_dt_read_permission_returns_200(self, mock_dt_cls, mock_cam_cls):
        mock_cam_inst = MagicMock()
        mock_cam_inst.validate_company_access.return_value = (True, "SUCCESS", {})
        mock_cam_cls.return_value = mock_cam_inst

        mock_instance = MagicMock()
        mock_instance.load_stored_findings.return_value = []
        mock_instance.get_summary_metrics.return_value = {"total_findings": 0}
        mock_dt_cls.return_value = mock_instance

        token = self.auth_mgr.create_session(
            user_id="usr_dt_002",
            email="dt@opsmeld.com",
            display_name="DT User",
            roles=["DATA_TRUST_ANALYST"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a}
        )
        handler = self._create_test_handler(f"/api/data-trust/findings?company_id={self.test_guid_a}", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 200)

    # Case 5: DT read but no write -> run-recon returns 403
    def test_case_05_dt_read_without_write_returns_403_on_run_recon(self):
        token = self.auth_mgr.create_session(
            user_id="usr_auditor_001",
            email="auditor_read@opsmeld.com",
            display_name="Read Only Auditor",
            roles=["DATA_TRUST_AUDITOR"], # data_trust:read only
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a}
        )
        handler = self._create_test_handler(f"/api/data-trust/run-recon?company_id={self.test_guid_a}", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 403)
        resp = json.loads(handler.written_data.decode("utf-8"))
        self.assertIn("lacks required module permission 'data_trust:write'", resp["error"])

    # Case 6: DT permission + unauthorized company GUID -> 403
    def test_case_06_unauthorized_company_guid_returns_403(self):
        token = self.auth_mgr.create_session(
            user_id="usr_dt_003",
            email="dt_scoped@opsmeld.com",
            display_name="Scoped User",
            roles=["DATA_TRUST_ANALYST"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a} # Only company A allowed
        )
        # Attempt to access company B
        handler = self._create_test_handler(f"/api/data-trust/findings?company_id={self.test_guid_b}", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 403)
        resp = json.loads(handler.written_data.decode("utf-8"))
        self.assertIn("not authorized to access company", resp["error"])

    # Case 7: DT permission + authorized company GUID -> allowed
    @patch("web.app.CompanyAccessManager")
    @patch("web.app.DataTrustEngine")
    def test_case_07_authorized_company_guid_allowed(self, mock_dt_cls, mock_cam_cls):
        mock_cam_inst = MagicMock()
        mock_cam_inst.validate_company_access.return_value = (True, "SUCCESS", {})
        mock_cam_cls.return_value = mock_cam_inst

        mock_instance = MagicMock()
        mock_instance.load_stored_findings.return_value = []
        mock_instance.get_summary_metrics.return_value = {"total_findings": 0}
        mock_dt_cls.return_value = mock_instance

        token = self.auth_mgr.create_session(
            user_id="usr_dt_004",
            email="dt_multi@opsmeld.com",
            display_name="Multi Company User",
            roles=["DATA_TRUST_ANALYST"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a, self.test_guid_b}
        )
        handler = self._create_test_handler(f"/api/data-trust/findings?company_id={self.test_guid_b}", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 200)

    # Case 8: AR-only user -> DT API returns 403
    def test_case_08_ar_only_user_accessing_dt_returns_403(self):
        token = self.auth_mgr.create_session(
            user_id="usr_ar_only",
            email="ar_only@opsmeld.com",
            display_name="AR Analyst Only",
            roles=["AR_ANALYST"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a}
        )
        handler = self._create_test_handler("/api/data-trust/authorized-companies", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 403)

    # Case 9: DT-only user -> AR Control Tower API returns 403
    def test_case_09_dt_only_user_accessing_ar_returns_403(self):
        token = self.auth_mgr.create_session(
            user_id="usr_dt_only",
            email="dt_only@opsmeld.com",
            display_name="DT Analyst Only",
            roles=["DATA_TRUST_ANALYST"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a}
        )
        handler = self._create_test_handler("/api/ar-manager/data", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 403)

    # Case 10: Multi-module user -> both available
    @patch("web.app.ARManagerReport")
    def test_case_10_multi_module_user_accesses_both(self, mock_ar_cls):
        mock_ar_inst = MagicMock()
        mock_ar_inst.fetch_data.return_value = {"customers": [], "autopilot": []}
        mock_ar_cls.return_value = mock_ar_inst

        token = self.auth_mgr.create_session(
            user_id="usr_admin_multi",
            email="admin_multi@opsmeld.com",
            display_name="Enterprise Admin User",
            roles=["ENTERPRISE_ADMIN"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a}
        )
        # AR access check
        handler_ar = self._create_test_handler("/api/ar-manager/data", headers={"Cookie": f"session={token}"})
        handler_ar.do_GET()
        self.assertEqual(handler_ar.response_code, 200)

        # Portal modules check
        handler_portal = self._create_test_handler("/api/portal/modules", headers={"Cookie": f"session={token}"})
        handler_portal.do_GET()
        self.assertEqual(handler_portal.response_code, 200)
        res = json.loads(handler_portal.written_data.decode("utf-8"))
        modules = {m["id"]: m["enabled"] for m in res["modules"]}
        self.assertTrue(modules["ar_control_tower"])
        self.assertTrue(modules["data_trust"])

    # Case 11: Logout -> protected API returns 401
    def test_case_11_logout_revokes_session(self):
        token = self.auth_mgr.create_session(
            user_id="usr_logout",
            email="logout@opsmeld.com",
            display_name="Logout Test",
            roles=["ENTERPRISE_ADMIN"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a}
        )
        # Verify valid before logout
        handler_me = self._create_test_handler("/api/auth/me", headers={"Cookie": f"session={token}"})
        handler_me.do_GET()
        self.assertEqual(handler_me.response_code, 200)

        # Perform logout
        handler_logout = self._create_test_handler("/api/auth/logout", method="POST", headers={"Cookie": f"session={token}"})
        handler_logout.do_GET()

        # Verify revoked
        handler_post = self._create_test_handler("/api/portal/modules", headers={"Cookie": f"session={token}"})
        handler_post.do_GET()
        self.assertEqual(handler_post.response_code, 401)

    # Case 12: Session expiry -> 401
    def test_case_12_expired_session_returns_401(self):
        token = self.auth_mgr.create_session(
            user_id="usr_expired",
            email="expired@opsmeld.com",
            display_name="Expired User",
            roles=["ENTERPRISE_ADMIN"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a}
        )
        # Manually expire session timestamp
        session = self.auth_mgr.get_session(token)
        session.expires_at = time.time() - 3600

        handler = self._create_test_handler("/api/portal/modules", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 401)

    # Case 13: Invalid company name string -> 400
    def test_case_13_invalid_company_name_returns_400(self):
        token = self.auth_mgr.create_session(
            user_id="usr_invalid_comp",
            email="invalid_comp@opsmeld.com",
            display_name="Test User",
            roles=["DATA_TRUST_ANALYST"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a}
        )
        handler = self._create_test_handler("/api/data-trust/findings?company_id=CRONUS_IN_NAME", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 400)
        resp = json.loads(handler.written_data.decode("utf-8"))
        self.assertEqual(resp["status"], "CONFIGURATION_MISSING")

    # Case 14: Unauthorized GUID -> 403
    def test_case_14_unauthorized_guid_returns_403(self):
        token = self.auth_mgr.create_session(
            user_id="usr_unauth_guid",
            email="unauth_guid@opsmeld.com",
            display_name="Test User",
            roles=["DATA_TRUST_ANALYST"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a}
        )
        handler = self._create_test_handler(f"/api/data-trust/findings?company_id={self.unauthorized_guid}", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 403)

    # Case 15: BC unavailable / fail closed
    @patch("web.app.CompanyAccessManager")
    def test_case_15_bc_unavailable_fails_closed(self, mock_mgr_cls):
        mock_mgr_inst = MagicMock()
        mock_mgr_inst.get_discovered_companies_with_provenance.return_value = ([], "DATA_UNAVAILABLE")
        mock_mgr_cls.return_value = mock_mgr_inst

        token = self.auth_mgr.create_session(
            user_id="usr_bc_off",
            email="bcoff@opsmeld.com",
            display_name="Test User",
            roles=["DATA_TRUST_ANALYST"],
            organization_id="org_abc_001",
            allowed_companies={self.test_guid_a}
        )
        handler = self._create_test_handler("/api/data-trust/authorized-companies", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 200)
        resp = json.loads(handler.written_data.decode("utf-8"))
        self.assertEqual(resp["status"], "DATA_UNAVAILABLE")
        self.assertEqual(len(resp["companies"]), 0)

    # Case 16: Dynamic Future Module Permission Registration
    def test_case_16_future_module_registration(self):
        registry = get_module_registry()
        # Dynamically register Layer 4
        registry.register_module(
            module_id="layer_4",
            name="Treasury & Cashflow Forecasting",
            description="Continuous liquidity modeling and bank reconciliation audit",
            permissions=["layer_4:read", "layer_4:write"]
        )
        from core.models import get_datastore
        get_datastore().org_modules["org_abc_001"].add("layer_4")

        token = self.auth_mgr.create_session(
            user_id="usr_treasury",
            email="treasury@opsmeld.com",
            display_name="Treasury Officer",
            roles=[],
            organization_id="org_abc_001",
            direct_permissions=["layer_4:read"]
        )

        handler = self._create_test_handler("/api/portal/modules", headers={"Cookie": f"session={token}"})
        handler.do_GET()
        self.assertEqual(handler.response_code, 200)
        resp = json.loads(handler.written_data.decode("utf-8"))
        modules = {m["id"]: m for m in resp["modules"]}
        self.assertIn("layer_4", modules)
        self.assertTrue(modules["layer_4"]["enabled"])
        self.assertFalse(modules["data_trust"]["enabled"])
        self.assertFalse(modules["ar_control_tower"]["enabled"])


if __name__ == "__main__":
    unittest.main()
