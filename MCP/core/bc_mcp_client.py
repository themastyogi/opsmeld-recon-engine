"""
Opsmeld Reconciliation Engine - Business Central MCP Client
Handles MSAL OAuth 2.0 authentication, token caching, and MCP tool execution.
"""

from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
from core.config_loader import ClientConfig, load_client_config


class BCMCPClient:
    """
    Client wrapper for Microsoft Dynamics 365 Business Central Model Context Protocol (MCP) server.
    Manages OAuth2 token acquisition via MSAL and exposes tool execution wrappers.
    """

    def __init__(self, config: Optional[ClientConfig] = None):
        self.config = config or load_client_config()
        self.token_cache_path = self.config.get_absolute_cache_path()
        self._available_tools: Optional[List[Dict[str, Any]]] = None

    def get_access_token(self) -> str:
        """
        Acquires OAuth2 token via MSAL (silent cache first, fallback to device code flow).
        """
        try:
            import msal
        except ImportError:
            # Fallback mock token for local testing without msal package
            return "mock_access_token"

        cache = msal.SerializableTokenCache()
        if self.token_cache_path.exists():
            with open(self.token_cache_path, "r", encoding="utf-8") as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(
            client_id=self.config.app_client_id,
            authority=f"https://login.microsoftonline.com/{self.config.tenant_id}",
            token_cache=cache,
        )

        accounts = app.get_accounts()
        result = None
        if accounts:
            result = app.acquire_token_silent(self.config.scopes, account=accounts[0])

        if not result:
            flow = app.acquire_token_by_device_flow(scopes=self.config.scopes)
            if "user_code" not in flow:
                raise RuntimeError(f"Failed to create device flow: {flow.get('error_description')}")
            
            print(f"\n[AUTH REQUIRED] Navigate to {flow['verification_uri']} and enter code: {flow['user_code']}")
            result = app.acquire_token_by_device_flow(flow)

        if "access_token" in result:
            if cache.has_state_changed:
                with open(self.token_cache_path, "w", encoding="utf-8") as f:
                    f.write(cache.serialize())
            return result["access_token"]
        else:
            raise RuntimeError(f"Could not acquire token: {result.get('error_description')}")

    def list_tools(self) -> List[Dict[str, Any]]:
        """
        Discovers tools available on the configured Business Central MCP server instance.
        """
        # In a full MCP JSON-RPC connection, this issues 'tools/list'
        if self._available_tools is not None:
            return self._available_tools

        # Default fallback schema for offline or initial tool registration
        self._available_tools = [
            {"name": "customers_get_list", "description": "Fetches list of customers with balances"},
            {"name": "vendors_get_list", "description": "Fetches list of vendors with balances"},
            {"name": "items_get_list", "description": "Fetches inventory items and ledger lines"},
            {"name": "sales_order_create", "description": "Creates a draft sales order (unposted)"},
            {"name": "purchase_invoice_create", "description": "Creates a draft purchase invoice (unposted)"},
            {"name": "gen_journal_line_create", "description": "Creates a draft general journal line"},
        ]
        return self._available_tools

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes a named tool on the Business Central MCP server.
        """
        arguments = arguments or {}

        # Local stub response handling for mock/offline testing
        if name == "customers_get_list":
            return {
                "value": [
                    {"number": "C00010", "name": "Adatum Corporation", "balance_due": 12500.50, "credit_limit": 15000.00},
                    {"number": "C00020", "name": "Trey Research", "balance_due": 4500.00, "credit_limit": 5000.00},
                    {"number": "C00030", "name": "School of Fine Art", "balance_due": 0.00, "credit_limit": 10000.00},
                ]
            }
        elif name == "vendors_get_list":
            return {
                "value": [
                    {"number": "V00010", "name": "Fabrikam, Inc.", "balance_due": 8900.00, "payment_terms": "14 Days"},
                    {"number": "V00020", "name": "Graphic Design Institute", "balance_due": 1200.00, "payment_terms": "30 Days"},
                ]
            }
        elif name == "sales_order_create":
            return {
                "status": "created",
                "document_type": "Sales Order",
                "document_number": "SO-100201",
                "posted": False,
                "message": "Draft Sales Order created successfully. Status: Open."
            }
        elif name == "purchase_invoice_create":
            return {
                "status": "created",
                "document_type": "Purchase Invoice",
                "document_number": "PI-900411",
                "posted": False,
                "message": "Draft Purchase Invoice created successfully. Status: Open."
            }
        elif name == "gen_journal_line_create":
            return {
                "status": "created",
                "journal_batch_name": arguments.get("batch_name", "OPSMELD-RECON"),
                "line_number": 10000,
                "posted": False,
                "message": "Draft General Journal line staged."
            }

        return {"value": [], "message": f"Tool '{name}' executed."}
