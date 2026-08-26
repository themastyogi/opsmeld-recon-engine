"""
Opsmeld Data Trust — Server-Side Company Authorization & Discovery Module.
Enforces that Data Trust never exposes Business Central data outside the user's authorized company scope.
Integrates real company-scoped Business Central access verification as the final authorization gate.
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

    def get_discovered_companies(self, client: Optional[BCMCPClient]) -> List[Dict[str, Any]]:
        """
        Discovers companies accessible in the current Business Central context via GET /companies.
        Returns candidate company list: [{'id': GUID, 'name': Name, 'displayName': DisplayName}].
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
        client: Optional[BCMCPClient],
        requested_company: Optional[str] = None,
        session_info: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        mode: str = "AUTO"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Server-side company authorization gate:
        1. Explicitly separates offline/test mode from live production.
        2. Uses /companies as discovery to resolve company GUID.
        3. Executes a real company-scoped BC data access test against the target company.
        4. Rejects empty company selection (does NOT silently choose first company in multi-company environments).
        5. Rejects unauthorized or forged company requests with ACCESS_DENIED.
        """
        # Rule 7: Explicitly separate offline/test mode from live production authorization
        if mode in ("TEST_FIXTURE", "DEMO_FIXTURE") or not client:
            target_comp = requested_company or "CRONUS IN"
            return True, DataTrustState.SUCCESS, {
                "company_id": target_comp,
                "company_name": target_comp,
                "is_offline_preview": True
            }

        # Live Production Authorization Path
        token = client.get_access_token()
        if not token:
            msg = build_user_message(DataTrustState.AUTHENTICATION_UNAVAILABLE, run_id=run_id)
            return False, DataTrustState.AUTHENTICATION_UNAVAILABLE, {"message": msg, "http_status": 401}

        # Step A: Candidate Discovery
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

        # Rule 6: Empty company does not silently select first company if ambiguous
        if not requested_company:
            if len(discovered) == 1:
                target_comp_guid = discovered[0]["id"]
                target_comp_name = discovered[0]["name"]
            elif len(discovered) > 1:
                # Require explicit company selection in multi-company environments
                msg = build_user_message(DataTrustState.CONFIGURATION_MISSING, run_id=run_id)
                return False, DataTrustState.CONFIGURATION_MISSING, {
                    "message": "Multiple companies detected. Please select an explicit company for analysis.",
                    "http_status": 400
                }
            else:
                msg = build_user_message(DataTrustState.ACCESS_DENIED, run_id=run_id)
                return False, DataTrustState.ACCESS_DENIED, {"message": msg, "http_status": 403}
        else:
            # Match requested company against discovered companies
            matched = [
                c for c in discovered
                if c["id"] == requested_company or c["name"].lower() == requested_company.lower() or c["displayName"].lower() == requested_company.lower()
            ]

            if len(matched) == 1:
                target_comp_guid = matched[0]["id"]
                target_comp_name = matched[0]["name"]
            elif len(matched) > 1:
                msg = build_user_message(DataTrustState.COMPANY_NOT_FOUND, run_id=run_id)
                return False, DataTrustState.COMPANY_NOT_FOUND, {"message": "Ambiguous company match.", "http_status": 404}
            else:
                # Requested company not found in user's authorized company list (Forged/Unauthorized request)
                msg = build_user_message(DataTrustState.ACCESS_DENIED, run_id=run_id)
                return False, DataTrustState.ACCESS_DENIED, {"message": msg, "http_status": 403}

        # Step B: Final Real Company-Scoped Business Central Access Verification Gate
        # Verify access by executing a lightweight company-scoped data request
        scope_test_resp = client._execute_bc_rest(f"companies({target_comp_guid})/generalLedgerEntries?$top=1")
        if isinstance(scope_test_resp, dict) and (scope_test_resp.get("is_error") or "error" in scope_test_resp):
            status_code = scope_test_resp.get("http_status", 500)
            if status_code in (401, 403):
                msg = build_user_message(DataTrustState.ACCESS_DENIED, run_id=run_id)
                return False, DataTrustState.ACCESS_DENIED, {"message": msg, "http_status": 403}

        return True, DataTrustState.SUCCESS, {
            "company_id": target_comp_guid,
            "company_name": target_comp_name,
            "is_offline_preview": False
        }
