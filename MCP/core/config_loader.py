"""
Opsmeld Reconciliation Engine - Configuration Loader Module
Provides safe multi-tenant client profile parsing and operational rule loading.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"


@dataclass
class ClientConfig:
    client_key: str
    name: str
    tenant_id: str
    app_client_id: str
    client_secret: str = ""
    environment: str = "Production"
    company_name: str = ""
    mcp_server_url: str = ""
    scopes: list[str] = field(default_factory=lambda: ["https://api.businesscentral.dynamics.com/.default"])
    cache_path: str = "./token_cache/default.bin"

    def get_absolute_cache_path(self) -> Path:
        """Resolves cache path relative to project root with safe directory creation."""
        path = Path(self.cache_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


@dataclass
class EngineRules:
    safety_mode: str = "staged"
    allow_write_operations: bool = True
    default_do_not_post: bool = True
    max_query_records: int = 500
    raw_rules: Dict[str, Any] = field(default_factory=dict)


def load_client_config(client_key: Optional[str] = None) -> ClientConfig:
    """
    Loads client configuration by key from clients.json (or clients.json.example fallback).
    Environment variables (BC_TENANT_ID, BC_CLIENT_ID) override config files if set.
    """
    clients_file = CONFIG_DIR / "clients.json"
    if not clients_file.exists():
        clients_file = CONFIG_DIR / "clients.json.example"

    if not clients_file.exists():
        raise FileNotFoundError(f"Configuration file not found in {CONFIG_DIR}")

    with open(clients_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    target_key = client_key or data.get("active_client") or "contoso_us"
    clients_map = data.get("clients", {})

    if target_key not in clients_map:
        # Fallback to first available client key if specific key not found
        if clients_map:
            target_key = next(iter(clients_map.keys()))
        else:
            raise KeyError(f"Client key '{target_key}' not defined in {clients_file.name}")

    client_data = clients_map[target_key]

    # Environment variable overrides for production deployment security
    tenant_id = os.environ.get("BC_TENANT_ID", client_data.get("tenant_id", ""))
    app_client_id = os.environ.get("BC_CLIENT_ID", client_data.get("app_client_id", ""))
    client_secret = os.environ.get("BC_CLIENT_SECRET", client_data.get("client_secret", ""))

    return ClientConfig(
        client_key=target_key,
        name=client_data.get("name", target_key),
        tenant_id=tenant_id,
        app_client_id=app_client_id,
        client_secret=client_secret,
        environment=client_data.get("environment", "Production"),
        company_name=client_data.get("company_name", ""),
        mcp_server_url=client_data.get("mcp_server_url", ""),
        scopes=client_data.get("scopes", ["https://api.businesscentral.dynamics.com/.default"]),
        cache_path=client_data.get("cache_path", f"./token_cache/{target_key}.bin"),
    )


def load_engine_rules() -> EngineRules:
    """Loads operational thresholds and safety policies from config/rules.json."""
    rules_file = CONFIG_DIR / "rules.json"
    if not rules_file.exists():
        return EngineRules()

    with open(rules_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    general = data.get("general", {})
    return EngineRules(
        safety_mode=general.get("safety_mode", "staged"),
        allow_write_operations=general.get("allow_write_operations", True),
        default_do_not_post=general.get("default_do_not_post", True),
        max_query_records=general.get("max_query_records", 500),
        raw_rules=data,
    )
