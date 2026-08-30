import os
import sys
import time
import threading
import wsgiref.simple_server
from pathlib import Path

# Add MCP to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MCP"))

from http.server import HTTPServer
from web.app import OpsmeldWebHandler
from playwright.sync_api import sync_playwright
from core.auth import get_auth_manager

def run_server():
    server = HTTPServer(('127.0.0.1', 8899), OpsmeldWebHandler)
    server.serve_forever()

def run_browser_verification():
    print("=== STARTING FRONTEND USER JOURNEY VERIFICATION (A-D) ===")
    
    # Start local WSGI test server
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(1)
    
    base_url = "http://127.0.0.1:8899"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        # ---------------------------------------------------------------------
        # TEST A: Incognito / New User Journey
        # ---------------------------------------------------------------------
        print("\n[TEST A] Incognito / New User Journey...")
        context_a = browser.new_context()
        page_a = context_a.new_page()
        page_a.goto(base_url)
        
        landing_visible_a = page_a.is_visible("#view-public-landing")
        app_shell_visible_a = page_a.is_visible("#view-app-shell")
        print(f"  Initial Load -> Public Landing: {landing_visible_a}, App Shell: {app_shell_visible_a}")
        assert landing_visible_a and not app_shell_visible_a, "Test A: Must load public landing page without app shell"
        
        page_a.click("button:has-text('Sign In')")
        page_a.wait_for_selector("#signin-unauth-container", state="visible")
        unauth_visible = page_a.is_visible("#signin-unauth-container")
        welcome_visible = page_a.is_visible("#signin-welcome-container")
        print(f"  After Sign In Click -> Unauth Container: {unauth_visible}, Welcome Container: {welcome_visible}")
        assert unauth_visible and not welcome_visible, "Test A: Must render canonical login screen with Continue with Microsoft"
        
        page_a.click("#signin-unauth-container button")
        page_a.wait_for_selector("#login-modal", state="visible")
        user_code_text = page_a.text_content("#login-user-code")
        print(f"  After Entra Click -> Modal Visible: True, User Code: {user_code_text.strip()}")
        assert page_a.is_visible("#login-modal"), "Test A: Must display device authorization modal"
        context_a.close()

        # ---------------------------------------------------------------------
        # TEST B: Existing Session (Returning User)
        # ---------------------------------------------------------------------
        print("\n[TEST B] Returning User with Active Session...")
        context_b = browser.new_context()
        auth_mgr = get_auth_manager()
        admin_companies = getattr(auth_mgr, "default_admin_companies", set())
        token = auth_mgr.create_session(
            user_id="usr_admin_001",
            email="admin@opsmeld.com",
            display_name="Vikas Kumar (CRONUS IN)",
            roles=["ENTERPRISE_ADMIN"],
            organization_id="org_abc_001",
            allowed_companies=admin_companies
        )
        context_b.add_cookies([{"name": "session", "value": token, "domain": "127.0.0.1", "path": "/"}])
        page_b = context_b.new_page()
        
        page_b.goto(base_url)
        page_b.evaluate(f"localStorage.setItem('opsmeld_token', '{token}')")
        page_b.goto(base_url)
        
        landing_visible_b = page_b.is_visible("#view-public-landing")
        app_shell_visible_b = page_b.is_visible("#view-app-shell")
        print(f"  Returning Load -> Public Landing: {landing_visible_b}, App Shell: {app_shell_visible_b}")
        assert landing_visible_b and not app_shell_visible_b, "Test B: Returning user MUST load landing page without auto-entering dashboard"
        
        page_b.click("button:has-text('Sign In')")
        page_b.wait_for_selector("#signin-welcome-container", state="visible")
        welcome_visible_b = page_b.is_visible("#signin-welcome-container")
        welcome_email_b = page_b.text_content("#welcome-user-email")
        app_shell_after_signin = page_b.is_visible("#view-app-shell")
        print(f"  After Sign In Click -> Welcome Back Visible: {welcome_visible_b}, Email: {welcome_email_b.strip()}, App Shell: {app_shell_after_signin}")
        assert welcome_visible_b and not app_shell_after_signin, "Test B: Must display Welcome Back container and NOT auto-enter dashboard"
        
        page_b.click("button:has-text('Continue to Opsmeld Portal')")
        page_b.wait_for_selector("#view-app-shell", state="visible")
        app_shell_final = page_b.is_visible("#view-app-shell")
        print(f"  After Continue Click -> App Shell Visible: {app_shell_final}")
        assert app_shell_final, "Test B: App Shell must render after explicit Continue click"

        # ---------------------------------------------------------------------
        # TEST C: Sign In With Another Account
        # ---------------------------------------------------------------------
        print("\n[TEST C] Sign In With Another Account...")
        page_c = context_b.new_page()
        page_c.goto(base_url)
        page_c.click("button:has-text('Sign In')")
        page_c.wait_for_selector("#signin-welcome-container", state="visible")
        
        page_c.click("button:has-text('Sign in with another account')")
        page_c.wait_for_selector("#login-modal", state="visible")
        token_after_switch = page_c.evaluate("localStorage.getItem('opsmeld_token')")
        print(f"  After Another Account Click -> Modal Visible: True, Token Cleared: {token_after_switch is None}")
        assert token_after_switch is None, "Test C: Session token must be cleared upon account switch"

        # ---------------------------------------------------------------------
        # TEST D: Sign Out Journey
        # ---------------------------------------------------------------------
        print("\n[TEST D] Sign Out Journey...")
        page_d = context_b.new_page()
        page_d.goto(base_url)
        page_d.click("button:has-text('Sign In')")
        page_d.wait_for_selector("#signin-welcome-container", state="visible")
        page_d.click("button:has-text('Continue to Opsmeld Portal')")
        page_d.wait_for_selector("#view-app-shell", state="visible")
        
        page_d.click("button:has-text('Sign Out')")
        page_d.wait_for_selector("#view-public-landing", state="visible")
        landing_d = page_d.is_visible("#view-public-landing")
        token_d = page_d.evaluate("localStorage.getItem('opsmeld_token')")
        print(f"  After Sign Out Click -> Public Landing: {landing_d}, Token Cleared: {token_d is None}")
        assert landing_d and token_d is None, "Test D: Sign out must clear session and return to public landing"
        
        browser.close()
        print("\n=== ALL FRONTEND USER JOURNEY TESTS (A-D) PASSED 100% CLEANLY! ===")

if __name__ == "__main__":
    run_browser_verification()
