"""
Opsmeld Multitenant Core Models - Hierarchy & Entitlement Entities (v1.2)
Defines multi-tenant data structures, organization lifecycle state machine, registrations, and access requests:
Opsmeld Platform -> Registration / Prospect -> Approval -> Customer Organization -> Subscription -> Module -> User -> Role -> Permission -> BC Company
"""

import os
import time
from typing import Dict, List, Set, Optional, Any, Tuple

BOOTSTRAP_ORG_NAME = os.environ.get("OPSMELD_BOOTSTRAP_ORG_NAME")
BOOTSTRAP_ADMIN_EMAIL = os.environ.get("OPSMELD_BOOTSTRAP_ADMIN_EMAIL")
BOOTSTRAP_ADMIN_NAME = os.environ.get("OPSMELD_BOOTSTRAP_ADMIN_NAME")


class OrganizationStatus:
    PROSPECT = "PROSPECT"
    REGISTRATION_PENDING = "REGISTRATION_PENDING"
    REJECTED = "REJECTED"
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class RegistrationStatus:
    REGISTRATION_PENDING = "REGISTRATION_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AccessRequestStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class OrganizationRegistration:
    def __init__(
        self,
        registration_id: str,
        organization_name: str,
        requester_name: str,
        business_email: str,
        requested_modules: List[str],
        status: str = RegistrationStatus.REGISTRATION_PENDING,
        created_at: Optional[float] = None
    ):
        self.registration_id = registration_id
        self.organization_name = organization_name
        self.requester_name = requester_name
        self.business_email = business_email
        self.requested_modules = requested_modules or ["ar_control_tower", "data_trust"]
        self.status = status
        self.created_at = created_at or time.time()
        self.reviewed_at: Optional[float] = None
        self.reviewed_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "registration_id": self.registration_id,
            "organization_name": self.organization_name,
            "requester_name": self.requester_name,
            "business_email": self.business_email,
            "requested_modules": self.requested_modules,
            "status": self.status,
            "created_at": self.created_at,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by
        }


class AccessRequest:
    def __init__(
        self,
        request_id: str,
        organization_id: str,
        user_id: str,
        email: str,
        display_name: str,
        status: str = AccessRequestStatus.PENDING,
        created_at: Optional[float] = None
    ):
        self.request_id = request_id
        self.organization_id = organization_id
        self.user_id = user_id
        self.email = email
        self.display_name = display_name
        self.status = status
        self.created_at = created_at or time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "organization_id": self.organization_id,
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "status": self.status,
            "created_at": self.created_at
        }


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
    def __init__(self, user_id: str, entra_oid: str, email: str, display_name: str, status: str = "ACTIVE", must_change_password: bool = False):
        self.user_id = user_id
        self.entra_oid = entra_oid
        self.email = email
        self.display_name = display_name
        self.status = status
        self.must_change_password = must_change_password

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "entra_oid": self.entra_oid,
            "email": self.email,
            "display_name": self.display_name,
            "status": self.status,
            "must_change_password": self.must_change_password
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
    Stores Organizations, Subscriptions, Module Subscriptions, Roles, Users, Company ACLs, Registrations & Access Requests.
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

        self.registrations: Dict[str, OrganizationRegistration] = {}
        self.access_requests: Dict[str, AccessRequest] = {}

        self._seed_default_tenants()
        self.bootstrap_from_env()

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
            "DATA_TRUST_AUDITOR": {"data_trust:read"},
            "VIEWER": {
                "ar_control_tower:read",
                "data_trust:read",
                "layer_3:read"
            }
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
        return org is not None and org.status in (OrganizationStatus.ACTIVE, OrganizationStatus.TRIAL)

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
            if r_id in roles_dict:
                perms.update(roles_dict[r_id])
            else:
                from core.rbac import ROLE_PERMISSIONS
                perms.update(ROLE_PERMISSIONS.get(r_id, set()))
        return perms

    def get_user_allowed_companies(self, user_id: str, org_id: str) -> Set[str]:
        return self.user_company_acls.get(f"{user_id}:{org_id}", set())

    def resolve_user_organization(self, email: str, entra_oid: Optional[str] = None) -> Optional[Tuple[User, Organization]]:
        """
        Resolves Entra OID / email -> User -> OrganizationUser -> Organization.
        Returns (User, Organization) or None if user is not assigned to an organization.
        """
        email_clean = (email or "").strip().lower()
        if not email_clean and not entra_oid:
            return None  # Fail closed: missing identity must never resolve to any user or tenant

        if email_clean in ("admin", "admin@opsmeld.com"):
            matched_user = self.users.get("usr_admin_001")
        else:
            matched_user = None
            for u in self.users.values():
                if (email_clean and u.email.strip().lower() == email_clean) or (entra_oid and u.entra_oid == entra_oid):
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

    def create_registration(self, organization_name: str, requester_name: str, business_email: str, requested_modules: List[str]) -> OrganizationRegistration:
        reg_id = f"reg_{len(self.registrations) + 101}"
        reg = OrganizationRegistration(reg_id, organization_name, requester_name, business_email, requested_modules)
        self.registrations[reg_id] = reg
        return reg

    def approve_registration(self, registration_id: str, reviewer_user_id: str) -> Optional[Organization]:
        reg = self.registrations.get(registration_id)
        if not reg or reg.status != RegistrationStatus.REGISTRATION_PENDING:
            return None

        reg.status = RegistrationStatus.APPROVED
        reg.reviewed_at = time.time()
        reg.reviewed_by = reviewer_user_id

        # Provision new Organization (TRIAL mode)
        org_id = f"org_{len(self.organizations) + 101}"
        org = Organization(org_id, reg.organization_name, OrganizationStatus.TRIAL)
        self.organizations[org_id] = org

        # Provision Subscription & Subscribed Modules
        self.subscriptions[org_id] = Subscription(f"sub_{org_id}", org_id, "Trial")
        self.org_modules[org_id] = set(reg.requested_modules)

        # Provision Registering Customer Admin User
        user_id = f"usr_{len(self.users) + 101}"
        user = User(user_id, f"oid_{user_id}", reg.business_email, reg.requester_name)
        self.users[user_id] = user
        self.org_users[org_id] = {user_id}
        self.user_org[user_id] = org_id

        # Roles for new Organization
        self.org_roles[org_id] = {
            "CUSTOMER_ADMIN": {
                "ar_control_tower:read", "ar_control_tower:write",
                "data_trust:read", "data_trust:write",
                "layer_3:read", "layer_3:write",
                "org:users:manage", "org:roles:manage", "org:companies:manage"
            },
            "VIEWER": {
                "ar_control_tower:read",
                "data_trust:read",
                "layer_3:read"
            }
        }
        self.user_roles[f"{user_id}:{org_id}"] = {"CUSTOMER_ADMIN"}
        self.org_companies[org_id] = []
        self.user_company_acls[f"{user_id}:{org_id}"] = set()

        return org

    def provision_org_user(self, org_id: str, email: str, display_name: str, allowed_companies: set, role: str = "VIEWER") -> str:
        """Admin-provisioned, password-login user (VIEWER or CUSTOMER_ADMIN).
        Adds to an EXISTING organization with strict role and company ACL boundaries."""
        org = self.get_organization(org_id)
        if not org:
            raise ValueError(f"Organization '{org_id}' does not exist.")

        role_clean = (role or "VIEWER").strip().upper()
        if role_clean not in ("VIEWER", "CUSTOMER_ADMIN"):
            raise ValueError(f"Unsupported role '{role}'. Only VIEWER and CUSTOMER_ADMIN can be provisioned.")

        org_roles = self.org_roles.setdefault(org_id, {})
        if role_clean == "CUSTOMER_ADMIN":
            if "CUSTOMER_ADMIN" not in org_roles:
                org_roles["CUSTOMER_ADMIN"] = {
                    "ar_control_tower:read", "ar_control_tower:write",
                    "data_trust:read", "data_trust:write",
                    "layer_3:read", "layer_3:write",
                    "org:users:manage", "org:roles:manage", "org:companies:manage"
                }
        elif role_clean == "VIEWER":
            if "VIEWER" not in org_roles:
                from core.rbac import ROLE_PERMISSIONS
                org_roles["VIEWER"] = set(ROLE_PERMISSIONS.get("VIEWER", set()))

        email_clean = (email or "").strip().lower()
        existing_user = None
        for u in self.users.values():
            if u.email.strip().lower() == email_clean:
                existing_user = u
                break

        if existing_user:
            user_id = existing_user.user_id
            if display_name:
                existing_user.display_name = display_name
            existing_user.must_change_password = True
        else:
            user_id = f"usr_{len(self.users) + 101}"
            user = User(user_id, f"oid_{user_id}", email, display_name, must_change_password=True)
            self.users[user_id] = user

        self.org_users.setdefault(org_id, set()).add(user_id)
        self.user_org[user_id] = org_id
        self.user_roles[f"{user_id}:{org_id}"] = {role_clean}
        self.user_company_acls[f"{user_id}:{org_id}"] = set(allowed_companies)
        return user_id

    def provision_viewer_user(self, org_id: str, email: str, display_name: str, allowed_companies: set) -> str:
        """Backwards-compatible wrapper for provision_org_user with role='VIEWER'."""
        return self.provision_org_user(org_id, email, display_name, allowed_companies, role="VIEWER")

    def create_access_request(self, organization_id: str, user_id: str, email: str, display_name: str) -> AccessRequest:
        req_id = f"req_{len(self.access_requests) + 101}"
        req = AccessRequest(req_id, organization_id, user_id, email, display_name)
        self.access_requests[req_id] = req
        return req

    def persist(self, filepath: Optional[str] = None):
        """Persists current multitenant data store to JSON file."""
        import json, os
        target = filepath or os.path.join(os.path.dirname(__file__), "..", "data", "multitenant_store.json")
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            data = {
                "organizations": [o.to_dict() for o in self.organizations.values()],
                "subscriptions": [s.to_dict() for s in self.subscriptions.values()],
                "org_modules": {k: list(v) for k, v in self.org_modules.items()},
                "users": [u.to_dict() for u in self.users.values()],
                "user_org": self.user_org,
                "user_roles": {k: list(v) for k, v in self.user_roles.items()},
                "user_company_acls": {k: list(v) for k, v in self.user_company_acls.items()},
                "registrations": [r.to_dict() for r in self.registrations.values()],
                "access_requests": [req.to_dict() for req in self.access_requests.values()]
            }
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def bootstrap_from_env(self) -> Optional[Organization]:
        """
        Environment-variable-driven bootstrap logic for real customer organization and admin.
        Safe and idempotent: runs once only when environment variables are configured
        and the organization does not already exist.
        """
        org_name = (os.environ.get("OPSMELD_BOOTSTRAP_ORG_NAME") or "").strip()
        admin_email = (os.environ.get("OPSMELD_BOOTSTRAP_ADMIN_EMAIL") or "").strip()
        admin_name = (os.environ.get("OPSMELD_BOOTSTRAP_ADMIN_NAME") or "").strip()

        if not org_name or not admin_email:
            return None

        existing = next((o for o in self.organizations.values() if o.name.strip().lower() == org_name.lower()), None)
        if existing:
            return existing

        org_id = f"org_{len(self.organizations) + 101}"
        org = Organization(org_id, org_name, OrganizationStatus.ACTIVE)
        self.organizations[org_id] = org
        self.subscriptions[org_id] = Subscription(f"sub_{org_id}", org_id, "Enterprise")
        self.org_modules[org_id] = {"ar_control_tower", "data_trust"}

        # Roles for new Organization
        self.org_roles[org_id] = {
            "CUSTOMER_ADMIN": {
                "ar_control_tower:read", "ar_control_tower:write",
                "data_trust:read", "data_trust:write",
                "layer_3:read", "layer_3:write",
                "org:users:manage", "org:roles:manage", "org:companies:manage"
            },
            "VIEWER": {
                "ar_control_tower:read",
                "data_trust:read",
                "layer_3:read"
            }
        }

        # Seeded demo company GUIDs (matches BC demo baseline)
        comp_cronus = OrganizationCompany(f"comp_{org_id}_1", org_id, "ac6b97ba-bc8f-f111-832d-7c1e5233db45", "CRONUS IN")
        comp_mycompany = OrganizationCompany(f"comp_{org_id}_2", org_id, "c37ac1c0-bc8f-f111-832d-7c1e5233db45", "My Company")
        comp_sandbox = OrganizationCompany(f"comp_{org_id}_3", org_id, "c4e0106b-159e-f111-8072-7ced8d9f80ff", "Sandbox")
        self.org_companies[org_id] = [comp_cronus, comp_mycompany, comp_sandbox]

        allowed_companies = {
            comp_cronus.bc_company_guid,
            comp_mycompany.bc_company_guid,
            comp_sandbox.bc_company_guid,
            "GUID-COMP-01", "GUID-COMP-02", "GUID-COMP-A", "GUID-COMP-B"
        }

        user_id = self.provision_org_user(
            org_id=org_id,
            email=admin_email,
            display_name=admin_name or admin_email,
            allowed_companies=allowed_companies,
            role="CUSTOMER_ADMIN"
        )
        if user_id in self.users:
            self.users[user_id].must_change_password = False

        self.persist()
        return org



_GLOBAL_DATASTORE = MultitenantDataStore()


def get_datastore() -> MultitenantDataStore:
    return _GLOBAL_DATASTORE
