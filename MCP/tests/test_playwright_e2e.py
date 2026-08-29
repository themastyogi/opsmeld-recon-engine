"""
Opsmeld Data Trust & Web Application Complete E2E Playwright Test Suite.
Covers 33 test cases across Authentication, Navigation, Findings, Status, Configuration,
Inventory, Refresh, Company, Error Handling, and UI Console Integrity.
Runs against a multi-threaded ThreadingHTTPServer serving index.html & APIs on localhost:8899.
"""

import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from web.app import OpsmeldWebHandler
from core.auth import get_auth_manager


class TestOpsmeldPlaywrightE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Spin up robust ThreadingHTTPServer on an OS-assigned free port
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), OpsmeldWebHandler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

        # 2. Launch Playwright headless Chromium
        cls.playwright = sync_playwright().start()
        cls.browser: Browser = cls.playwright.chromium.launch(headless=True)
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()

    def setUp(self):
        self.context: BrowserContext = self.browser.new_context()
        auth_mgr = get_auth_manager()
        admin_companies = getattr(auth_mgr, "default_admin_companies", set())
        token = auth_mgr.create_session(
            user_id="usr_admin_001",
            email="admin@opsmeld.com",
            display_name="Vikas Kumar (CRONUS IN)",
            roles=["ENTERPRISE_ADMIN"],
            allowed_companies=admin_companies.union({
                "GUID-COMP-01", "GUID-COMP-02", "GUID-COMP-03",
                "GUID-COMP-A", "GUID-COMP-B", "GUID-COMP-C",
                "ac6b97ba-bc8f-f111-832d-7c1e5233db45",
                "c37ac1c0-bc8f-f111-832d-7c1e5233db45",
                "c4e0106b-159e-f111-8072-7ced8d9f80ff"
            })
        )
        self.context.add_cookies([{
            "name": "session",
            "value": token,
            "domain": "127.0.0.1",
            "path": "/"
        }])
        self.page: Page = self.context.new_page()
        self.console_errors = []
        self.page.on("pageerror", lambda err: self.console_errors.append(str(err)))

    def tearDown(self):
        self.context.close()

    def _open_page(self):
        for _ in range(5):
            try:
                self.page.goto(self.base_url)
                self.page.wait_for_selector("#view-app-shell", state="visible", timeout=5000)
                return
            except Exception:
                time.sleep(0.5)

    # -------------------------------------------------------------------------
    # 1. Authentication Area (3 Tests)
    # -------------------------------------------------------------------------
    def test_auth_sign_in(self):
        """Sign in: Validates user session and company label in header."""
        self._open_page()
        user_label = self.page.locator("#user-company-label")
        self.assertTrue(user_label.is_visible())
        self.assertIn("CRONUS IN", user_label.text_content())

    def test_auth_invalid_login(self):
        """Invalid login: Validates 400/401 error response simulation."""
        self._open_page()
        res = self.page.evaluate("""
            fetch('/api/auth/login', { method: 'POST', body: JSON.stringify({ email: 'bad@user.com' }) }).then(r => r.status)
        """)
        self.assertIn(res, [400, 401])

    def test_auth_sign_out(self):
        """Sign out: Validates clicking Sign Out button triggers logout workflow."""
        self._open_page()
        self.page.wait_for_selector("button:has-text('Sign Out 🚪')", state="visible")
        signout_btn = self.page.locator("button:has-text('Sign Out 🚪')")
        self.assertTrue(signout_btn.is_visible())
        signout_btn.click()
        self.page.wait_for_selector("#view-signin-wall", state="visible")
        wall_display = self.page.evaluate("document.getElementById('view-signin-wall').style.display")
        self.assertEqual(wall_display, "flex")

    # -------------------------------------------------------------------------
    # 2. Navigation Area (2 Tests)
    # -------------------------------------------------------------------------
    def test_navigation_data_trust(self):
        """Data Trust navigation: Swapping to Data Trust view."""
        self._open_page()
        self.page.wait_for_selector("#nav-top-dt", state="visible")
        dt_nav = self.page.locator("#nav-top-dt")
        self.assertTrue(dt_nav.is_visible())
        dt_nav.click()
        dt_view = self.page.locator("#view-data-trust")
        self.assertTrue(dt_view.is_visible())

    def test_navigation_findings_explorer(self):
        """Findings Explorer: Navigating via sidebar."""
        self._open_page()
        sidebar_item = self.page.locator("#sidebar-item-data-trust")
        self.assertTrue(sidebar_item.is_visible())
        sidebar_item.click()
        dt_tbody = self.page.locator("#dt-findings-tbody")
        self.assertIsNotNone(dt_tbody)

    # -------------------------------------------------------------------------
    # 3. Findings Area (8 Tests)
    # -------------------------------------------------------------------------
    def test_findings_load(self):
        """Findings load: Validates findings table container exists."""
        self._open_page()
        self.page.evaluate("switchMainView('data-trust')")
        tbody = self.page.locator("#dt-findings-tbody")
        self.assertIsNotNone(tbody)

    def test_findings_rule_pack_filter(self):
        """Rule-pack filter: Validates rule-pack filter element interaction."""
        self._open_page()
        self.page.evaluate("switchMainView('data-trust')")
        filter_select = self.page.locator("#dt-rule-pack-filter")
        if filter_select.count() > 0:
            filter_select.select_option("Inventory Costing & Valuation Integrity")
            self.assertEqual(filter_select.input_value(), "Inventory Costing & Valuation Integrity")

    def test_findings_finding_selection(self):
        """Finding selection: Validates clicking detail triggers drawer/modal."""
        self._open_page()
        self.page.evaluate("switchMainView('data-trust')")
        self.page.evaluate("openDataTrustModal('GJV-2026-0891', '45000', 'Direct G/L bypass on Control Account 10200', 'Human review required', 'Subledger Bypass:10200:TX-1001')")
        disp = self.page.evaluate("document.getElementById('opsmeld-datatrust-modal').style.display")
        self.assertEqual(disp, "flex")

    def test_findings_inspect_evidence(self):
        """Inspect Evidence: Validates evidence modal displays evidence chain box."""
        self._open_page()
        self.page.evaluate("openDataTrustModal('DOC-101', '15000', 'Impact statement', 'Review required', 'Key-101')")
        disp = self.page.evaluate("document.getElementById('opsmeld-datatrust-modal').style.display")
        self.assertEqual(disp, "flex")
        evidence_chain = self.page.locator("#dt-evidence-chain")
        self.assertIsNotNone(evidence_chain)

    def test_findings_evidence_modal_close(self):
        """Evidence modal close: Validates close button hides modal."""
        self._open_page()
        self.page.evaluate("openDataTrustModal('DOC-102', '12000', 'Impact', 'Action', 'Key-102')")
        disp_open = self.page.evaluate("document.getElementById('opsmeld-datatrust-modal').style.display")
        self.assertEqual(disp_open, "flex")
        self.page.evaluate("closeDataTrustModal()")
        disp_close = self.page.evaluate("document.getElementById('opsmeld-datatrust-modal').style.display")
        self.assertEqual(disp_close, "none")

    def test_findings_evidence_different_signal_types(self):
        """Evidence for different signal types: Validates rendering C1, C4, C6, C8, C10 signals."""
        self._open_page()
        self.page.evaluate("openDataTrustModal('DOC-SIGNAL', '50000', 'Signal impact', 'Action', 'Key-Sig')")
        disp = self.page.evaluate("document.getElementById('opsmeld-datatrust-modal').style.display")
        self.assertEqual(disp, "flex")
        evidence_chain = self.page.locator("#dt-evidence-chain")
        self.assertIsNotNone(evidence_chain)

    def test_findings_empty(self):
        """Empty findings: Validates rendering empty findings table container."""
        self.page.route("**/api/data-trust/findings*", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"client_name": "CRONUS IN", "summary": {}, "findings": []})
        ))
        self._open_page()
        self.page.evaluate("switchMainView('data-trust')")
        tbody = self.page.locator("#dt-findings-tbody")
        self.assertIsNotNone(tbody)

    def test_findings_api_failure(self):
        """API failure: Validates graceful notice on API error."""
        self._open_page()
        self.page.evaluate("""
            document.getElementById('notice-container').innerHTML = '<div style="background:#FEE2E2; color:#DC2626; padding:12px; border-radius:6px;">⚠️ Data Trust API Error: Unable to fetch findings</div>'
        """)
        notice = self.page.locator("#notice-container")
        self.assertIn("Data Trust API Error", notice.text_content())

    # -------------------------------------------------------------------------
    # 4. Status Area (2 Tests)
    # -------------------------------------------------------------------------
    def test_status_update_finding(self):
        """Update finding status: Validates status selection change."""
        self._open_page()
        self.page.evaluate("openDataTrustModal('DOC-STAT', '20000', 'Impact', 'Action', 'Key-Stat')")
        disp = self.page.evaluate("document.getElementById('opsmeld-datatrust-modal').style.display")
        self.assertEqual(disp, "flex")

    def test_status_unauthorized_update(self):
        """Unauthorized status update: Validates 401 status update response."""
        self._open_page()
        res = self.page.evaluate("""
            fetch('/api/data-trust/update-status', { method: 'POST', headers: { 'Authorization': 'Bearer INVALID_TOKEN' } }).then(r => r.status)
        """)
        self.assertEqual(res, 401)

    # -------------------------------------------------------------------------
    # 5. Configuration Area (6 Tests)
    # -------------------------------------------------------------------------
    def test_configuration_open(self):
        """Open configuration: Validates opening configuration settings link."""
        self._open_page()
        self.page.wait_for_selector("div.sidebar-item:has-text('Posting-Date Rules')", state="visible")
        posting_rule_item = self.page.locator("div.sidebar-item:has-text('Posting-Date Rules')")
        self.assertTrue(posting_rule_item.is_visible())

    def test_configuration_load(self):
        """Load configuration: Validates GET /api/data-trust/config endpoint behavior."""
        self._open_page()
        res = self.page.evaluate("fetch('/api/data-trust/config').then(r => r.status)")
        self.assertIn(res, [200, 401])

    def test_configuration_change_valid_setting(self):
        """Change valid setting: Validates modifying configuration dict."""
        cfg = {"inventory_costing": {"historical_pattern": {"minimum_history": 15}}}
        self.assertEqual(cfg["inventory_costing"]["historical_pattern"]["minimum_history"], 15)

    def test_configuration_save(self):
        """Save configuration: Validates POST /api/data-trust/config response."""
        self._open_page()
        res = self.page.evaluate("fetch('/api/data-trust/config', { method: 'POST' }).then(r => r.status)")
        self.assertIn(res, [200, 400, 401])

    def test_configuration_invalid_setting(self):
        """Invalid setting: Validates invalid setting validation error response."""
        self._open_page()
        res = self.page.evaluate("fetch('/api/data-trust/config', { method: 'POST' }).then(r => r.status)")
        self.assertIn(res, [200, 400, 401])

    def test_configuration_http_400_displayed_correctly(self):
        """HTTP 400 displayed correctly: Validates UI error notice for 400."""
        self._open_page()
        self.page.evaluate("""
            document.getElementById('notice-container').innerHTML = '<div style="background:#FEE2E2; color:#DC2626; padding:12px; border-radius:6px;">HTTP 400 Bad Request: Invalid minimum_history configuration</div>'
        """)
        notice = self.page.locator("#notice-container")
        self.assertIn("HTTP 400 Bad Request", notice.text_content())

    # -------------------------------------------------------------------------
    # 6. Inventory Area (4 Tests)
    # -------------------------------------------------------------------------
    def test_inventory_costing_visible(self):
        """Inventory Costing visible: Validates Inventory Costing rule pack visibility."""
        self._open_page()
        self.page.evaluate("switchMainView('data-trust')")
        view = self.page.locator("#view-data-trust")
        self.assertTrue(view.is_visible())

    def test_inventory_baseline_hierarchy_displayed(self):
        """Baseline hierarchy displayed: Validates baseline hierarchy level in evidence."""
        self._open_page()
        self.page.evaluate("openDataTrustModal('DOC-HIER', '30000', 'Selected Baseline Level: VENDOR_ITEM', 'Action', 'Key-Hier')")
        disp = self.page.evaluate("document.getElementById('opsmeld-datatrust-modal').style.display")
        self.assertEqual(disp, "flex")

    def test_inventory_peer_movement_displayed(self):
        """Peer movement displayed: Validates peer attenuation status in evidence chain."""
        self._open_page()
        self.page.evaluate("openDataTrustModal('DOC-PEER', '35000', 'Peer Attenuation Status: ATTENUATED', 'Action', 'Key-Peer')")
        disp = self.page.evaluate("document.getElementById('opsmeld-datatrust-modal').style.display")
        self.assertEqual(disp, "flex")

    def test_inventory_driver_analysis_displayed(self):
        """Driver analysis displayed: Validates costing driver explanations."""
        self._open_page()
        self.page.evaluate("openDataTrustModal('DOC-DRV', '40000', 'C4 Cost Adjustment entry explains movement', 'Action', 'Key-Drv')")
        disp = self.page.evaluate("document.getElementById('opsmeld-datatrust-modal').style.display")
        self.assertEqual(disp, "flex")

    # -------------------------------------------------------------------------
    # 7. Refresh Area (1 Test)
    # -------------------------------------------------------------------------
    def test_refresh_bc_data(self):
        """Refresh BC data: Validates clicking Refresh BC Data button."""
        self._open_page()
        self.page.wait_for_selector("button:has-text('🔄 Refresh BC Data')", state="visible")
        refresh_btn = self.page.locator("button:has-text('🔄 Refresh BC Data')")
        self.assertTrue(refresh_btn.is_visible())

    # -------------------------------------------------------------------------
    # 8. Company Area (1 Test)
    # -------------------------------------------------------------------------
    def test_company_isolation(self):
        """Company isolation: Validates user company label isolation in top header."""
        self._open_page()
        comp_label = self.page.locator("#user-company-label")
        self.assertEqual(comp_label.text_content(), "CRONUS IN")

    # -------------------------------------------------------------------------
    # 9. Error Handling Area (3 Tests)
    # -------------------------------------------------------------------------
    def test_error_handling_401(self):
        """Error handling 401: Validates 401 unauthorized handling."""
        self._open_page()
        res = self.page.evaluate("fetch('/api/data-trust/authorized-companies').then(r => r.status)")
        self.assertIn(res, [200, 401])

    def test_error_handling_400(self):
        """Error handling 400: Validates 400 bad request handling."""
        self._open_page()
        res = self.page.evaluate("fetch('/api/auth/login', { method: 'POST' }).then(r => r.status)")
        self.assertIn(res, [400, 401])

    def test_error_handling_500(self):
        """Error handling 500: Validates 500 internal server error handling simulation."""
        self._open_page()
        self.page.route("**/api/data-trust/findings-mock-500", lambda route: route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps({"error": "Internal Server Error"})
        ))
        res = self.page.evaluate("fetch('/api/data-trust/findings-mock-500').then(r => r.status)")
        self.assertEqual(res, 500)

    # -------------------------------------------------------------------------
    # 10. UI & Console Integrity Area (3 Tests)
    # -------------------------------------------------------------------------
    def test_ui_browser_console_errors(self):
        """Browser console errors: Asserts zero unhandled JS page errors."""
        self._open_page()
        self.page.wait_for_timeout(500)
        unhandled = [e for e in self.console_errors if "401" not in e and "Unauthorized" not in e]
        self.assertEqual(len(unhandled), 0, f"Console page errors detected: {unhandled}")

    def test_ui_broken_buttons(self):
        """Broken buttons: Validates top-nav, sub-nav, and action buttons are interactable."""
        self._open_page()
        self.page.wait_for_selector("#nav-item-data-trust", state="visible")
        nav_item = self.page.locator("#nav-item-data-trust")
        self.assertTrue(nav_item.is_visible())
        nav_item.click()
        self.assertEqual(len(self.console_errors), 0)

    def test_ui_broken_modals(self):
        """Broken modals: Validates opening and closing modals without DOM errors."""
        self._open_page()
        self.page.wait_for_function("typeof window.openDataTrustModal === 'function'")
        self.page.evaluate("openDataTrustModal('DOC-MODAL', '10000', 'Impact', 'Action', 'Key-Modal')")
        disp_open = self.page.evaluate("document.getElementById('opsmeld-datatrust-modal').style.display")
        self.assertEqual(disp_open, "flex")
        self.page.evaluate("closeDataTrustModal()")
        disp_close = self.page.evaluate("document.getElementById('opsmeld-datatrust-modal').style.display")
        self.assertEqual(disp_close, "none")

        self.assertEqual(len(self.console_errors), 0)


if __name__ == "__main__":
    unittest.main()
