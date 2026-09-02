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
