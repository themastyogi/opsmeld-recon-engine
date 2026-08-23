"""
example_list_customers.py

Smallest possible end-to-end example: acquire a token (device-code flow
the first time, silent after), open an MCP session against one client's
Business Central environment, and pull back a few customers.

Run:
    python example_list_customers.py

First run: it will print a device-code sign-in URL + code — open it in
any browser, sign in as the CLIENT's BC admin, approve once.
Every run after that: silent, no browser, no clicking.
"""

from bc_mcp_client import BCClientConfig, BCMCPClient

# --- one entry per client, in a real engine this comes from a database ---
CLIENTS = [
    BCClientConfig(
        client_name="opsmeld-dev",              # internal label -> cache file name
        tenant_id="db961cfa-b4ab-42c5-9ab4-90b82e0da387",
        environment_name="Production",
        company="CRONUS IN",
        configuration_name="Reconciliation Engine",
        # Replace with YOUR multi-tenant Entra app's client ID once created.
        # For now this can be the same "Opsmeld BC MCP Inspector" app ID,
        # since it's already registered as a trusted client in BC.
        app_client_id="5accae97-5fc5-4a13-9600-2cbe0065d83a",
    ),
]


def main() -> None:
    for cfg in CLIENTS:
        print(f"\n=== {cfg.client_name} ===")
        client = BCMCPClient(cfg)
        client.initialize()

        tools = client.list_tools()
        print(f"Available tools: {[t['name'] for t in tools]}")

        customers = client.call_tool(
            "List_Customers_PAG30009",
            {"top": 5, "select": "number,displayName,balanceDue,creditLimit"},
        )
        print(json.dumps(customers, indent=2) if not isinstance(customers, str) else customers)


if __name__ == "__main__":
    import json
    main()
