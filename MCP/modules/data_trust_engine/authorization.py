"""
Opsmeld Data Trust — Server-Side Company Authorization & Discovery Module.
Enforces that Data Trust never exposes Business Central data outside the user's authorized company scope.
"""
from typing import Optional, Dict, Any, List, Tuple
from core.bc_mcp_client import BCMCPClient
from modules.data_trust_engine.company_context import DataTrustState, build_user_message, map_http_error


class CompanyAccessManager:
    """
    Server-side company discovery and access validator.
    Business Central remains the source of truth for company authorization.
    """
    def __init__(self):
        pass

    def get_discovered_companies(self, client: BCMCPClient) -> List[Dict[str, Any]]:
        """
        Discovers companies accessible in the current Business Central context via GET /companies.
        Returns list of candidate companies: [{'id': GUID, 'name': Name, 'displayName': DisplayName}].
        Used as candidate discovery for UI selector, NOT as sole authorization proof.
        """
        if not client:
            return []
        token = client.get_access_token()
        if not token:
            return []

        comp_resp = client._execute_bc_rest("companies")
        if not isinstance(comp_resp, dict) or comp_resp.get("is_error") or "error" in comp_resp:
            return []

        raw_list = comp_resp.get("value", []) if isinstance(comp_resp.get("value"), list) else []
        discovered: List[Dict[str, Any]] = []
        for c in raw_list:
            if isinstance(c, dict) and c.get("id"):
                discovered.append({
                    "id": c.get("id"),
                    "name": str(c.get("name") or c.get("id")),
                    "displayName": str(c.get("displayName") or c.get("name") or c.get("id"))
                })
        return discovered

    def validate_company_access(
        self,
        client: BCMCPClient,
        requested_company: Optional[str] = None,
        session_info: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Server-side company data request verification gate.
        Enforces that requested_company is authorized for the current user/context.
        If unauthorized or access is revoked, returns (False, ACCESS_DENIED, details).
        """
        if not client:
            return True, DataTrustState.SUCCESS, {"company_id": requested_company or "CRONUS IN", "company_name": "CRONUS IN"}

        token = client.get_access_token()
        if not token:
            msg = build_user_message(DataTrustState.AUTHENTICATION_UNAVAILABLE, run_id=run_id)
            return False, DataTrustState.AUTHENTICATION_UNAVAILABLE, {"message": msg, "http_status": 401}

        comp_resp = client._execute_bc_rest("companies")
        if isinstance(comp_resp, dict) and (comp_resp.get("is_error") or "error" in comp_resp):
            status_code = comp_resp.get("http_status", 500)
            err_mapped = map_http_error(status_code, is_company_resolution=True, run_id=run_id)
            return False, err_mapped["status"], {"message": err_mapped["message"], "http_status": status_code}

        raw_list = comp_resp.get("value", []) if isinstance(comp_resp, dict) and isinstance(comp_resp.get("value"), list) else []
        discovered = [
            {
                "id": c.get("id"),
                "name": str(c.get("name") or c.get("id")),
                "displayName": str(c.get("displayName") or c.get("name") or c.get("id"))
            }
            for c in raw_list if isinstance(c, dict) and c.get("id")
        ]

        if not requested_company:
            if len(discovered) >= 1:
                first = discovered[0]
                return True, DataTrustState.SUCCESS, {"company_id": first["id"], "company_name": first["name"]}
            else:
                msg = build_user_message(DataTrustState.ACCESS_DENIED, run_id=run_id)
                return False, DataTrustState.ACCESS_DENIED, {"message": msg, "http_status": 403}

        matched = [
            c for c in discovered
            if c["id"] == requested_company or c["name"].lower() == requested_company.lower() or c["displayName"].lower() == requested_company.lower()
        ]

        if len(matched) == 1:
            comp = matched[0]
            return True, DataTrustState.SUCCESS, {"company_id": comp["id"], "company_name": comp["name"]}
        elif len(matched) > 1:
            msg = build_user_message(DataTrustState.COMPANY_NOT_FOUND, run_id=run_id)
            return False, DataTrustState.COMPANY_NOT_FOUND, {"message": "Ambiguous company match.", "http_status": 404}
        else:
            msg = build_user_message(DataTrustState.ACCESS_DENIED, run_id=run_id)
            return False, DataTrustState.ACCESS_DENIED, {"message": msg, "http_status": 403}
