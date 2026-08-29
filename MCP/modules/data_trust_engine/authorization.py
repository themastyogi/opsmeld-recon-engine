"""
Opsmeld Data Trust - Server-Side Company Authorization and Discovery Module.
Enforces that Data Trust never exposes Business Central data outside the authorized company scope.
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
        """Retrieves company list from Business Central REST API /companies endpoint."""
        if not client:
            return []
        resp = client._execute_bc_rest("companies")
        if isinstance(resp, dict) and isinstance(resp.get("value"), list):
            return [
                {
                    "id": c.get("id"),
                    "name": str(c.get("name") or c.get("id")),
                    "displayName": str(c.get("displayName") or c.get("name") or c.get("id"))
                }
                for c in resp["value"] if isinstance(c, dict) and c.get("id")
            ]
        return []

    def validate_company_access(
        self,
        client: Optional[BCMCPClient],
        requested_company: Optional[str] = None,
        session_info: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        mode: str = "AUTO"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Server-side company authorization gate.
        P0 rules:
        1. TEST/DEMO mode: fixture bypass only.
        2. No client: fail closed with AUTHENTICATION_UNAVAILABLE.
        3. default_company/unspecified_company: reject with CONFIGURATION_MISSING (400).
        4. No matching company in discovered list: ACCESS_DENIED (403).
        5. Step B company-scoped GL probe: fail closed on 401/403/404/500.
        """
        # Rule 1: TEST/DEMO mode bypass only
        if mode in ("TEST_FIXTURE", "DEMO_FIXTURE"):
            target_comp = requested_company or "FIXTURE_COMPANY"
            return True, DataTrustState.SUCCESS, {
                "company_id": target_comp,
                "company_name": target_comp,
                "is_offline_preview": True
            }

        # Rule 2: No client -> fail closed
        if not client:
            msg = build_user_message(DataTrustState.AUTHENTICATION_UNAVAILABLE, run_id=run_id)
            return False, DataTrustState.AUTHENTICATION_UNAVAILABLE, {"message": msg, "http_status": 401}

        token = client.get_access_token()
        if not token:
            msg = build_user_message(DataTrustState.AUTHENTICATION_UNAVAILABLE, run_id=run_id)
            return False, DataTrustState.AUTHENTICATION_UNAVAILABLE, {"message": msg, "http_status": 401}

        # Rule 3: P0 - Synthetic placeholder names must NEVER be resolved as live company IDs
        if requested_company in ("default_company", "unspecified_company"):
            return False, DataTrustState.CONFIGURATION_MISSING, {
                "message": "Missing or invalid company_id. Please provide a valid Business Central company GUID.",
                "http_status": 400
            }

        # Step A: Candidate Discovery via GET /companies
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

        target_comp_guid = None
        target_comp_name = None

        if not requested_company:
            # Only valid if exactly one company in tenant
            if len(discovered) == 1:
                target_comp_guid = discovered[0]["id"]
                target_comp_name = discovered[0]["name"]
            elif len(discovered) > 1:
                return False, DataTrustState.CONFIGURATION_MISSING, {
                    "message": "Multiple companies detected. Please select an explicit company for analysis.",
                    "http_status": 400
                }
            else:
                msg = build_user_message(DataTrustState.ACCESS_DENIED, run_id=run_id)
                return False, DataTrustState.ACCESS_DENIED, {"message": msg, "http_status": 403}
        else:
            # Match requested company GUID or name against discovered list
            matched = [
                c for c in discovered
                if c["id"] == requested_company
                or c["name"].lower() == requested_company.lower()
                or c["displayName"].lower() == requested_company.lower()
            ]
            if len(matched) == 1:
                target_comp_guid = matched[0]["id"]
                target_comp_name = matched[0]["name"]
            elif len(matched) > 1:
                return False, DataTrustState.COMPANY_NOT_FOUND, {"message": "Ambiguous company match.", "http_status": 404}
            else:
                # Forged/unauthorized company request
                msg = build_user_message(DataTrustState.ACCESS_DENIED, run_id=run_id)
                return False, DataTrustState.ACCESS_DENIED, {"message": msg, "http_status": 403}

        # Step B: Final Real Company-Scoped BC Access Verification Gate
        scope_test_resp = client._execute_bc_rest(f"companies({target_comp_guid})/generalLedgerEntries?$top=1")
        if isinstance(scope_test_resp, dict) and (scope_test_resp.get("is_error") or "error" in scope_test_resp):
            status_code = scope_test_resp.get("http_status", 500)
            if status_code == 403:
                msg = build_user_message(DataTrustState.ACCESS_DENIED, run_id=run_id)
                return False, DataTrustState.ACCESS_DENIED, {"message": msg, "http_status": 403}
            elif status_code == 401:
                msg = build_user_message(DataTrustState.AUTHENTICATION_UNAVAILABLE, run_id=run_id)
                return False, DataTrustState.AUTHENTICATION_UNAVAILABLE, {"message": msg, "http_status": 401}
            elif status_code == 404:
                err_mapped = map_http_error(404, is_company_resolution=False, endpoint="generalLedgerEntries", run_id=run_id)
                return False, DataTrustState.DATA_REQUEST_INVALID, {"message": err_mapped["message"], "http_status": 404}
            else:
                err_mapped = map_http_error(status_code, is_company_resolution=False, endpoint="generalLedgerEntries", run_id=run_id)
                return False, err_mapped["status"], {"message": err_mapped["message"], "http_status": status_code}

        return True, DataTrustState.SUCCESS, {
            "company_id": target_comp_guid,
            "company_name": target_comp_name,
            "is_offline_preview": False
        }
