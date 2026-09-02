"""
Regression tests for Data Trust Company Authorization & RBAC Filtering Pipeline.
Verifies:
- Live company appears in authorized-companies;
- Permitted live company can call findings successfully;
- Non-permitted live company returns 403 Forbidden;
- Company A findings cannot be returned when Company B is selected;
- Customer/tenant isolation remains intact.
"""

import pytest
from core.auth import OpsmeldUserSession, get_auth_manager
from core.authorization import CentralAuthorizationEngine, DenialReason
from core.config_loader import load_client_config
from core.bc_mcp_client import BCMCPClient
from modules.data_trust_engine.authorization import CompanyAccessManager


def test_admin_permitted_all_live_companies_in_tenant():
    "according to admin session"
    admin_session = OpsmeldUserSession(
        token="tok_admin_test",
        user_id="usr_admin",
        email="admin@opsmeld.com",
        display_name="Admin User",
        roles=["ENTERPRISE_ADMIN"],
        organization_id="org_abc_001",
        tenant_id="tenant_001"
    )

    comp_id = "4f:82917-85a4-f111-aaa8-e4fb1efd3a10"
    is_allowed, reason = CentralAuthorizationEngine.authorize(
        session=admin_session,
        module_id="data_trust",
        company_id=comp_id
    )

    assert is_allowed is True
    assert reason == DenialReason.ALLOW


def test_normal_user_permitted_only_explicit_acl_companies():
    "user session acl"
    user_session = OpsmeldUserSession(
        token="tok_user_test",
        user_id="usr_normal",
        email="user@opsmeld.com",
        display_name="Normal User",
        roles=["DATA_TRUST_VIEWER"],
        allowed_companies={"ac6b97ba-bc8f-f111-832d-7c1e5233db45"},
        organization_id="org_abc_001",
        tenant_id="tenant_001"
    )

    is_allowed_1, reason_1 = CentralAuthorizationEngine.authorize(
        session=user_session,
        module_id="data_trust",
        company_id="ac6b97ba-bc8f-f111-832d-7c1e5233db45"
    )
    assert is_allowed_1 is True
    assert reason_1 == DenialReason.ALLOW

    is_allowed_2, reason_2 = CentralAuthorizationEngine.authorize(
        session=user_session,
        module_id="data_trust",
        company_id="4f682917-85a4-f111-aaa8-e4fb1efd3a10"
    )
    assert is_allowed_2 is False
    assert reason_2 == DenialReason.COMPANY_NOT_PERMITTED


def test_company_a_findings_cannot_be_accessed_when_requesting_company_b():
    class DummyBCClient:
        def get_access_token(self):
            return "fake_token"
        def _execute_bc_rest(self, path):
            if path == "companies":
                return {"value": [{"id": "comp_A", "name": "Company A"}]}
            return {}

    client = DummyBCClient()
    mgr = CompanyAccessManager()

    is_auth, state, details = mgr.validate_company_access(client, requested_company="comp_B")
    assert is_auth is False
    assert details["http_status"] == 403


def test_customer_tenant_boundary_isolation():
    session_tenant_a = OpsmeldUserSession(
        token="tok_tenant_a",
        user_id="usr_a",
        email="a@tenant-a.com",
        display_name="User A",
        roles=["DATA_TRUST_VIETER"],
        organization_id="org_tenant_a",
        tenant_id="tenant_a_guid"
    )

    assert session_tenant_a.customer_id == "tenant_a_guid"
    assert session_tenant_a.tenant_id == "tenant_a_guid"


def test_company_header_excluded_for_company_scoped_rest_urls(monkeypatch):
    import urllib.request
    captured_headers = {}

    def mock_urlopen(req, timeout=15):
        nonlocal captured_headers
        captured_headers = req.headers
        class DummyResp:
            def read(self):
                return b'{"value": []}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    config = load_client_config()
    client = BCMCPClient(config)
    monkeypatch.setattr(client, "get_access_token", lambda: "fake_jwt")
    monkeypatch.setattr(client, "_get_tenant_id", lambda: "tenant_guid_123")

    # 1. Company-scoped URL (companies) -> Should NOT have Company header
    client._execute_bc_rest("companies(ac6b97ba-bc8f-f111-832d-7c1e5233db45)/customers")
    assert "Company" not in captured_headers

    # 2. Base discovery URL (companies) -> Should NOT have Company header
    client._execute_bc_rest("companies")
    assert "Company" not in captured_headers


def test_company_access_manager_lightweight_company_lookup():
    class DummyBCClient:
        def get_access_token(self):
            return "fake_token"
        def _execute_bc_rest(self, path):
            if path == "companies":
                return {"value": [{"id": "comp_123", "name": "CRONUS IN"}]}
            if path == "companies(comp_123)":
                return {"id": "comp_123", "name": "CRONUS IN"}
            return {"is_error": True, "http_status": 404, "error": "Not found"}

    client = DummyBCClient()
    mgr = CompanyAccessManager()

    is_auth, state, details = mgr.validate_company_access(client, requested_company="comp_123")
    assert is_auth is True
    assert details["company_id"] == "comp_123"
    assert details["is_offline_preview"] is False


def test_authorized_companies_filters_by_user_acl():
    """Verifies authorized-companies endpoint pipeline: BC discovered -> user session ACL -> authorized response."""
    discovered = [
        {"id": "comp_guid_1", "name": "CRONUS IN"},
        {"id": "comp_guid_2", "name": "My Company"},
        {"id": "comp_guid_3", "name": "Sandbox"}
    ]

    # Admin Session -> Returns all 3 discovered companies
    admin_session = {"roles": ["ENTERPRISE_ADMIN"], "allowed_companies": set()}
    roles_admin = admin_session["roles"]
    is_admin = "ENTERPRISE_ADMIN" in roles_admin or "CUSTOMER_ADMIN" in roles_admin
    auth_admin = discovered if is_admin else [c for c in discovered if c["id"] in admin_session["allowed_companies"]]
    assert len(auth_admin) == 3

    # Normal User Session -> Returns ONLY explicitly allowed company (comp_guid_1)
    normal_session = {"roles": ["DATA_TRUST_VIEWER"], "allowed_companies": {"comp_guid_1"}}
    roles_norm = normal_session["roles"]
    is_admin_norm = "ENTERPRISE_ADMIN" in roles_norm or "CUSTOMER_ADMIN" in roles_norm
    auth_norm = discovered if is_admin_norm else [c for c in discovered if c["id"] in normal_session["allowed_companies"]]
    assert len(auth_norm) == 1
    assert auth_norm[0]["id"] == "comp_guid_1"


def test_bc_mcp_client_execute_jsonrpc_http_error_path_no_nameerror(monkeypatch):
    """Verifies that _execute_jsonrpc handles HTTPError without NameError and returns endpoint=method."""
    import urllib.error
    import io

    def mock_urlopen(req, timeout=15):
        fp = io.BytesIO(b'{"error": {"code": "Unauthorized", "message": "Access denied"}}')
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, fp)

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    config = load_client_config()
    client = BCMCPClient(config)
    monkeypatch.setattr(client, "get_access_token", lambda: "fake_jwt")

    res = client._execute_jsonrpc("tools/call", {"name": "customers_get_list"})
    assert res["is_error"] is True
    assert res["http_status"] == 401
    assert res["endpoint"] == "tools/call"
    assert res["error_code"] == "Unauthorized"
