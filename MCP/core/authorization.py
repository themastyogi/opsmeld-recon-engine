"""
Opsmeld Centralized Authorization Engine
Evaluates every protected request through the canonical 6-stage policy gate:
Session (1) -> Organization Status (2) -> Subscription (3) -> User Permission (4) -> Company ACL (5) -> BC Probe (6) -> ALLOW
"""

import logging
from typing import Tuple, Dict, Any, Optional, Set, List
from core.models import get_datastore, OrganizationStatus

logger = logging.getLogger("Opsmeld.AuthorizationEngine")


class DenialReason:
    ALLOW = "ALLOW"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    ORGANIZATION_SUSPENDED = "ORGANIZATION_SUSPENDED"
    MODULE_NOT_SUBSCRIBED = "MODULE_NOT_SUBSCRIBED"
    USER_NOT_PERMITTED = "USER_NOT_PERMITTED"
    COMPANY_NOT_PERMITTED = "COMPANY_NOT_PERMITTED"
    BC_ACCESS_DENIED = "BC_ACCESS_DENIED"
    BC_UNAVAILABLE = "BC_UNAVAILABLE"


class ModulePortalState:
    AVAILABLE = "AVAILABLE"
    NOT_PERMITTED = "NOT_PERMITTED"
    NOT_SUBSCRIBED = "NOT_SUBSCRIBED"


class CentralAuthorizationEngine:
    """
    Authoritative Centralized Authorization Engine for Opsmeld Platform.
    Evaluates multitenant policy server-side. Zero frontend-only authorization decisions.
    """
    @staticmethod
    def authorize(
        session: Optional[Any],
        module_id: str,
        permission: Optional[str] = None,
        company_id: Optional[str] = None,
        bc_client: Optional[Any] = None
    ) -> Tuple[bool, str]:
        """
        Evaluates a request against the 6 policy gates.
        Returns (True, "ALLOW") or (False, DenialReason).
        """
        # Gate 1: Who is the user? (Opsmeld Session)
        if not session or not getattr(session, "user_id", None):
            return False, DenialReason.UNAUTHENTICATED

        if getattr(session, "is_expired", lambda: False)():
            return False, DenialReason.UNAUTHENTICATED

        if not getattr(session, "provisioned", True):
            logger.warning(f"Authorization Denied: User '{session.user_id}' account is not provisioned.")
            return False, DenialReason.UNAUTHENTICATED

        datastore = get_datastore()
        org_id = getattr(session, "organization_id", None)
        if not org_id:
            logger.warning(f"Authorization Denied: User '{session.user_id}' is not assigned to an organization.")
            return False, DenialReason.ORGANIZATION_SUSPENDED

        # Gate 2: Is organization active?
        if not datastore.is_organization_active(org_id):
            logger.warning(f"Authorization Denied: Organization '{org_id}' is not ACTIVE/TRIAL")
            return False, DenialReason.ORGANIZATION_SUSPENDED

        # Gate 3: Is module subscribed for organization?
        alt_module_id = module_id.replace("-", "_") if "-" in module_id else module_id.replace("_", "-")
        if not datastore.is_module_subscribed(org_id, module_id) and not datastore.is_module_subscribed(org_id, alt_module_id):
            logger.warning(f"Authorization Denied: Module '{module_id}' is NOT SUBSCRIBED for org '{org_id}'")
            return False, DenialReason.MODULE_NOT_SUBSCRIBED

        # Gate 4: User permission
        if permission:
            user_perms = session.permissions if hasattr(session, "permissions") else datastore.get_user_permissions(session.user_id, org_id)
            alt_permission = permission.replace("-", "_") if "-" in permission else permission.replace("_", "-")
            roles = getattr(session, "roles", [])
            is_enterprise_admin = "ENTERPRISE_ADMIN" in roles or "CUSTOMER_ADMIN" in roles
            if not is_enterprise_admin and permission not in user_perms and alt_permission not in user_perms and "*" not in user_perms:
                logger.warning(f"Authorization Denied: User '{session.user_id}' lacks permission '{permission}' for module '{module_id}'")
                return False, DenialReason.USER_NOT_PERMITTED

        # Gate 5: User Company ACL
        if company_id:
            user_companies = session.allowed_companies if hasattr(session, "allowed_companies") else datastore.get_user_allowed_companies(session.user_id, org_id)
            if company_id not in user_companies:
                logger.warning(f"Authorization Denied: User '{session.user_id}' ACL does not grant access to company GUID '{company_id}'")
                return False, DenialReason.COMPANY_NOT_PERMITTED

        # Gate 6: Business Central backend authorization probe
        if bc_client and company_id:
            try:
                # Execute probe
                probe_res = bc_client._execute_bc_rest(f"companies({company_id})/generalLedgerEntries?$top=1")
                if isinstance(probe_res, dict) and probe_res.get("is_error"):
                    http_status = probe_res.get("http_status")
                    if http_status == 403 or probe_res.get("error") == "Access Denied":
                        return False, DenialReason.BC_ACCESS_DENIED
                    return False, DenialReason.BC_UNAVAILABLE
            except Exception as e:
                logger.error(f"BC Authorization probe failed for company '{company_id}': {e}")
                return False, DenialReason.BC_UNAVAILABLE

        return True, DenialReason.ALLOW

    @staticmethod
    def evaluate_portal_modules(session: Optional[Any]) -> List[Dict[str, Any]]:
        """
        Evaluates explicit product availability states for authenticated portal cards:
        - AVAILABLE: Subscribed by company AND permitted for user
        - NOT_PERMITTED: Subscribed by company BUT user lacks permission
        - NOT_SUBSCRIBED: Not included in company subscription
        """
        from core.rbac import get_module_registry
        datastore = get_datastore()

        if not session:
            return []

        org_id = getattr(session, "organization_id", None)
        if not org_id or not getattr(session, "provisioned", False):
            return []

        user_perms = session.permissions if hasattr(session, "permissions") else datastore.get_user_permissions(session.user_id, org_id)
        modules = get_module_registry().list_modules()

        results = []
        for mod in modules:
            is_subscribed = datastore.is_module_subscribed(org_id, mod.module_id)
            has_permission = any(p in user_perms for p in mod.permissions)

            if not is_subscribed:
                state = ModulePortalState.NOT_SUBSCRIBED
                message = "Not included in your organization's current plan."
                can_request = False
            elif not has_permission:
                state = ModulePortalState.NOT_PERMITTED
                message = "Available to your organization. You don't currently have access."
                can_request = True
            else:
                state = ModulePortalState.AVAILABLE
                message = "Available for your account."
                can_request = False

            results.append({
                "id": mod.module_id,
                "module_id": mod.module_id,
                "name": mod.name,
                "description": mod.description,
                "state": state,
                "message": message,
                "enabled": state == ModulePortalState.AVAILABLE,
                "is_available": state == ModulePortalState.AVAILABLE,
                "organization_subscribed": is_subscribed,
                "user_permitted": has_permission,
                "can_request_access": can_request
            })

        return results
