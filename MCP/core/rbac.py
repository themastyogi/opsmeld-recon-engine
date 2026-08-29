"""
Opsmeld Centralized RBAC Engine and Module Registry.
Provides extensible module permission registration and two-dimensional authorization resolution:
- Dimension 1: Module permissions (data_trust:read, data_trust:write, ar_control_tower:read, layer_3:read, etc.)
- Dimension 2: Explicit company entitlements set (Set[str] of BC company GUIDs).
"""

import logging
from typing import Dict, Set, List, Any, Optional

logger = logging.getLogger("Opsmeld.RBAC")


class ModuleDefinition:
    def __init__(self, module_id: str, name: str, description: str, permissions: List[str]):
        self.module_id = module_id
        self.name = name
        self.description = description
        self.permissions = set(permissions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.module_id,
            "name": self.name,
            "description": self.description,
            "permissions": sorted(list(self.permissions))
        }


class ModuleRegistry:
    """
    Extensible Module Registry for Opsmeld Platform (Layers 1 to N).
    Future modules (Layer 3, Layer 4, etc.) register permissions here without altering core auth code.
    """
    def __init__(self):
        self._modules: Dict[str, ModuleDefinition] = {}
        self._register_default_modules()

    def _register_default_modules(self):
        self.register_module(
            module_id="ar_control_tower",
            name="AR Control Tower",
            description="Receivables workload management, collections, and cash recovery automation",
            permissions=["ar_control_tower:read", "ar_control_tower:write"]
        )
        self.register_module(
            module_id="data_trust",
            name="Data Trust Expert",
            description="Continuous Business Central transaction audit and subledger bypass detection",
            permissions=["data_trust:read", "data_trust:write"]
        )
        self.register_module(
            module_id="layer_3",
            name="Financial Compliance",
            description="Posting-date compliance, subledger controls and GAAP narration interpretation",
            permissions=["layer_3:read", "layer_3:write"]
        )

    def register_module(self, module_id: str, name: str, description: str, permissions: List[str]):
        """Registers a new module definition into the platform registry."""
        mod = ModuleDefinition(module_id, name, description, permissions)
        self._modules[module_id] = mod
        logger.info(f"Registered Opsmeld Module: '{module_id}' ({name}) with permissions: {permissions}")

    def get_module(self, module_id: str) -> Optional[ModuleDefinition]:
        return self._modules.get(module_id)

    def list_modules(self) -> List[ModuleDefinition]:
        return list(self._modules.values())

    def get_all_permissions(self) -> Set[str]:
        all_perms: Set[str] = set()
        for mod in self._modules.values():
            all_perms.update(mod.permissions)
        return all_perms


# Global Module Registry Instance
_GLOBAL_MODULE_REGISTRY = ModuleRegistry()


def get_module_registry() -> ModuleRegistry:
    return _GLOBAL_MODULE_REGISTRY


# Pre-defined Role Definitions
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "ENTERPRISE_ADMIN": {
        "ar_control_tower:read", "ar_control_tower:write",
        "data_trust:read", "data_trust:write",
        "layer_3:read", "layer_3:write"
    },
    "DATA_TRUST_ANALYST": {
        "data_trust:read", "data_trust:write"
    },
    "DATA_TRUST_AUDITOR": {
        "data_trust:read"
    },
    "AR_ANALYST": {
        "ar_control_tower:read", "ar_control_tower:write"
    },
    "COMPLIANCE_AUDITOR": {
        "layer_3:read"
    }
}


class RBACResolver:
    """
    Resolves user roles, identity claims, and explicit company entitlements.
    """

    @staticmethod
    def resolve_permissions(roles: List[str], direct_permissions: Optional[List[str]] = None) -> Set[str]:
        """Resolves the set of module permissions granted to a user."""
        perms: Set[str] = set()
        for role in roles:
            role_upper = (role or "").strip().upper()
            if role_upper in ROLE_PERMISSIONS:
                perms.update(ROLE_PERMISSIONS[role_upper])
        if direct_permissions:
            perms.update(direct_permissions)
        return perms

    @staticmethod
    def get_module_status_for_user(user_permissions: Set[str]) -> List[Dict[str, Any]]:
        """
        Generates module availability payload for GET /api/portal/modules.
        Frontend uses this payload for card/navigation rendering.
        """
        registry = get_module_registry()
        modules_status = []
        for mod in registry.list_modules():
            granted = sorted(list(user_permissions.intersection(mod.permissions)))
            enabled = len(granted) > 0
            mod_dict = mod.to_dict()
            mod_dict["enabled"] = enabled
            mod_dict["user_permissions"] = granted
            modules_status.append(mod_dict)
        return modules_status
