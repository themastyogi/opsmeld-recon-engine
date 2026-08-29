"""
Opsmeld Multitenant Core Models - Hierarchy & Entitlement Entities
Defines the canonical multi-tenant data structures:
Opsmeld Platform -> Customer Organization -> Subscription -> Module -> Customer User -> Role -> Permission -> BC Company
"""

import time
from typing import Dict, List, Set, Optional, Any


class OrganizationStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TRIAL = "TRIAL"
    EXPIRED = "EXPIRED"


class ModuleStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Organization:
    def __init__(self, organization_id: str, name: str, status: str = OrganizationStatus.ACTIVE, created_at: Optional[float] = None):
        self.organization_id = organization_id
        self.name = name
        self.status = status
        self.created_at = created_at or time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at
        }


class User:
    def __init__(self, user_id: str, entra_oid: str, email: str, display_name: str, status: str = "ACTIVE"):
        self.user_id = user_id
        self.entra_oid = entra_oid
        self.email = email
        self.display_name = display_name
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "entra_oid": self.entra_oid,
            "email": self.email,
            "display_name": self.display_name,
            "status": self.status
        }


class Subscription:
    def __init__(self, subscription_id: str, organization_id: str, plan_id: str, status: str = "ACTIVE"):
        self.subscription_id = subscription_id
        self.organization_id = organization_id
        self.plan_id = plan_id
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subscription_id": self.subscription_id,
            "organization_id": self.organization_id,
            "plan_id": self.plan_id,
            "status": self.status
        }


class OrganizationCompany:
    def __init__(self, organization_company_id: str, organization_id: str, bc_company_guid: str, name: str, status: str = "ACTIVE"):
        self.organization_company_id = organization_company_id
        self.organization_id = organization_id
        self.bc_company_guid = bc_company_guid
        self.name = name
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "organization_company_id": self.organization_company_id,
            "organization_id": self.organization_id,
            "bc_company_guid": self.bc_company_guid,
            "name": self.name,
            "status": self.status
        }


class MultitenantDataStore:
    """
    In-memory / Persistent Multitenant Data Store for Opsmeld Platform.
    Stores Organizations, Subscriptions, Module Subscriptions, Roles, Users, and Company ACLs.
    """
    def __init__(self):
        self.organizations: Dict[str, Organization] = {}
        self.subscriptions: Dict[str, Subscription] = {}
        self.org_modules: Dict[str, Set[str]] = {}  # org_id -> set of subscribed module_ids
        self.users: Dict[str, User] = {}
        self.org_users: Dict[str, Set[str]] = {}  # org_id -> set of user_ids
        self.user_org: Dict[str, str] = {}  # user_id -> org_id
        self.user_roles: Dict[str, Set[str]] = {}  # (user_id, org_id) -> set of role_ids
        self.org_roles: Dict[str, Dict[str, Set[str]]] = {}  # org_id -> {role_id -> set of permissions}
        self.org_companies: Dict[str, List[OrganizationCompany]] = {}  # org_id -> list of OrganizationCompany
        self.user_company_acls: Dict[str, Set[str]] = {}  # (user_id, org_id) -> set of bc_company_guids

        self._seed_default_tenants()

    def _seed_default_tenants(self):
        """Seeds default multi-tenant baseline for production and testing."""
        # Customer A: ABC Manufacturing
        org_abc = Organization("org_abc_001", "ABC Manufacturing", OrganizationStatus.ACTIVE)
        self.organizations[org_abc.organization_id] = org_abc
        self.subscriptions[org_abc.organization_id] = Subscription("sub_abc", org_abc.organization_id, "Enterprise")
        self.org_modules[org_abc.organization_id] = {"ar_control_tower", "data_trust"}

        # Customer B: XYZ Industries
        org_xyz = Organization("org_xyz_002", "XYZ Industries", OrganizationStatus.ACTIVE)
        self.organizations[org_xyz.organization_id] = org_xyz
        self.subscriptions[org_xyz.organization_id] = Subscription("sub_xyz", org_xyz.organization_id, "Standard")
        self.org_modules[org_xyz.organization_id] = {"ar_control_tower"}

        # Customer C: Suspended Demo Corp
        org_demo = Organization("org_demo_003", "Demo Corporation", OrganizationStatus.SUSPENDED)
        self.organizations[org_demo.organization_id] = org_demo
        self.subscriptions[org_demo.organization_id] = Subscription("sub_demo", org_demo.organization_id, "Trial")
        self.org_modules[org_demo.organization_id] = {"ar_control_tower", "data_trust"}

        # Production Default Customer Admin User
        admin_user = User("usr_admin_001", "oid_admin_001", "admin@opsmeld.com", "Vikas Kumar (CRONUS IN)")
        self.users[admin_user.user_id] = admin_user
        self.org_users[org_abc.organization_id] = {admin_user.user_id}
        self.user_org[admin_user.user_id] = org_abc.organization_id

        # Roles for ABC Manufacturing
        self.org_roles[org_abc.organization_id] = {
            "CUSTOMER_ADMIN": {
                "ar_control_tower:read", "ar_control_tower:write",
                "data_trust:read", "data_trust:write",
                "layer_3:read", "layer_3:write",
                "org:users:manage", "org:roles:manage", "org:companies:manage"
            },
            "AR_ANALYST": {"ar_control_tower:read", "ar_control_tower:write"},
            "DATA_TRUST_AUDITOR": {"data_trust:read"}
        }
        self.user_roles[f"{admin_user.user_id}:{org_abc.organization_id}"] = {"CUSTOMER_ADMIN"}

        # Companies for ABC Manufacturing
        comp_cronus = OrganizationCompany("org_comp_1", org_abc.organization_id, "ac6b97ba-bc8f-f111-832d-7c1e5233db45", "CRONUS IN")
        comp_mycompany = OrganizationCompany("org_comp_2", org_abc.organization_id, "c37ac1c0-bc8f-f111-832d-7c1e5233db45", "My Company")
        comp_sandbox = OrganizationCompany("org_comp_3", org_abc.organization_id, "c4e0106b-159e-f111-8072-7ced8d9f80ff", "Sandbox")

        self.org_companies[org_abc.organization_id] = [comp_cronus, comp_mycompany, comp_sandbox]

        # Explicit Company ACL for Admin User
        self.user_company_acls[f"{admin_user.user_id}:{org_abc.organization_id}"] = {
            comp_cronus.bc_company_guid,
            comp_mycompany.bc_company_guid,
            comp_sandbox.bc_company_guid,
            "GUID-COMP-01", "GUID-COMP-02", "GUID-COMP-A", "GUID-COMP-B"
        }

    def get_organization(self, org_id: str) -> Optional[Organization]:
        return self.organizations.get(org_id)

    def is_organization_active(self, org_id: str) -> bool:
        org = self.get_organization(org_id)
        return org is not None and org.status == OrganizationStatus.ACTIVE

    def is_module_subscribed(self, org_id: str, module_id: str) -> bool:
        if not self.is_organization_active(org_id):
            return False
        subscribed = self.org_modules.get(org_id, set())
        return module_id in subscribed

    def get_user_permissions(self, user_id: str, org_id: str) -> Set[str]:
        role_ids = self.user_roles.get(f"{user_id}:{org_id}", set())
        roles_dict = self.org_roles.get(org_id, {})
        perms: Set[str] = set()
        for r_id in role_ids:
            perms.update(roles_dict.get(r_id, set()))
        return perms

    def get_user_allowed_companies(self, user_id: str, org_id: str) -> Set[str]:
        return self.user_company_acls.get(f"{user_id}:{org_id}", set())

    def resolve_user_organization(self, email: str, entra_oid: Optional[str] = None) -> Optional[Tuple[User, Organization]]:
        """
        Resolves Entra OID / email -> User -> OrganizationUser -> Organization.
        Returns (User, Organization) or None if user is not assigned to an organization.
        """
        email_clean = (email or "").strip().lower()
        matched_user = None
        for u in self.users.values():
            if u.email.strip().lower() == email_clean or (entra_oid and u.entra_oid == entra_oid):
                matched_user = u
                break
        if not matched_user:
            return None

        org_id = self.user_org.get(matched_user.user_id)
        if not org_id:
            return None

        org = self.get_organization(org_id)
        if not org:
            return None

        return matched_user, org


_GLOBAL_DATASTORE = MultitenantDataStore()


def get_datastore() -> MultitenantDataStore:
    return _GLOBAL_DATASTORE
