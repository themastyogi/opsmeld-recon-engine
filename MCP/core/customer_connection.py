"""
Opsmeld Reconciliation Engine - Customer Connection Module
Provides persistent CustomerConnection abstraction and isolated multi-tenant Business Central profile resolution.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


@dataclass
class CustomerConnection:
    customer_id: str
    entra_tenant_id: str
    bc_environment: str = "Production"
    bc_base_url: str = ""
    oauth_client_id: str = ""
    credential_ref: str = ""  # Environment variable name or secure vault reference
    connection_status: str = "ACTIVE"
    scopes: List[str] = field(default_factory=lambda: ["https://api.businesscentral.dynamics.com/.default"])

    def get_isolated_cache_path(self) -> Path:
        """Resolves isolated token cache path for customer & tenant boundary isolation."""
        safe_cust = self.customer_id.replace("/", "_").replace("\\", "_")
        safe_tenant = self.entra_tenant_id.replace("/", "_").replace("\\", "_")
        cache_dir = BASE_DIR / "token_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{safe_cust}_{safe_tenant}.bin"

    def get_resolved_secret(self) -> str:
        """Resolves secret from environment using credential_ref or BC_CLIENT_SECRET fallback. Never stores secrets in plain config."""
        if self.credential_ref and self.credential_ref in os.environ:
            return os.environ[self.credential_ref]
        return os.environ.get("BC_CLIENT_SECRET", "")

    def to_dict(self) -> Dict[str, Any]:
        """Returns non-sensitive metadata dictionary for diagnostic logging."""
        return {
            "customer_id": self.customer_id,
            "entra_tenant_id": self.entra_tenant_id,
            "bc_environment": self.bc_environment,
            "bc_base_url": self.bc_base_url or f"https://api.businesscentral.dynamics.com/v2.0/{self.entra_tenant_id}/{self.bc_environment}",
            "oauth_client_id": self.oauth_client_id,
            "credential_ref": self.credential_ref or "BC_CLIENT_SECRET",
            "connection_status": self.connection_status,
            "has_secret": bool(self.get_resolved_secret())
        }

class CustomerConnectionRepository:
    """Manages persistent CustomerConnection store. Prevents using clients.json as customer database."""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or (DATA_DIR / "customer_connections.json")
        self._connections: Dict[str, CustomerConnection] = {}
        self._load()

    def _load(self):
        """Loads connections from json store if present."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for cid, cdata in data.items():
                        self._connections[cid] = CustomerConnection(
                            customer_id=cdata.get("customer_id", cid),
                            entra_tenant_id=cdata.get("entra_tenant_id", ""),
                            bc_environment=cdata.get("bc_environment", "Production"),
                            bc_base_url=cdata.get("bc_base_url", ""),
                            oauth_client_id=cdata.get("oauth_client_id", ""),
                            credential_ref=cdata.get("credential_ref", ""),
                            connection_status=cdata.get("connection_status", "ACTIVE"),
                            scopes=cdata.get("scopes", ["https://api.businesscentral.dynamics.com/.default"])
                        )
            except Exception:
                self._connections = {}

    def save_connection(self, conn: CustomerConnection):
        """Saves or updates a CustomerConnection dynamically without modifying source code."""
        self._connections[conn.customer_id] = conn
        self.storage_path.parent.mkdir( parents=True, exist_ok=True)
        serialized = {cid: c.to_dict() for cid, c in self._connections.items()}
        for cdict in serialized.values():
            cdict.pop("has_secret", None)
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(serialized, f, indent=2)

    def get_connection(self, customer_id: str) -> Optional[CustomerConnection]:
        """Resolves connection by customer_id."""
        return self._connections.get(customer_id)

    def get_connection_by_tenant(self, tenant_id: str) -> Optional[CustomerConnection]:
        """Resolves connection by Azure Entra tenant_id."""
        for conn in self._connections.values():
            if conn.entra_tenant_id == tenant_id:
                return conn
        return None

_REPO_INSTANCE: Optional[CustomerConnectionRepository] = None


def get_customer_connection_repo() -> CustomerConnectionRepository:
    global _REPO_INSTANCE
    if _REPO_INSTANCE is None:
        _REPO_INSTANCE = CustomerConnectionRepository()
    return _REPO_INSTANCE
