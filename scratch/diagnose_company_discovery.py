# Live Business Central Company Discovery Diagnostic Tool
import sys
import json
import logging
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name in ("scratch", "tests") else SCRIPT_DIR
sys.path.insert(0, str(PROJECT_ROOT / "MCP"))
sys.path.insert(0, str(PROJECT_ROOT))

from core.config_loader import load_client_config
from core.bc_mcp_client import BCMCPClient
from modules.data_trust_engine.authorization import CompanyAccessManager

logging.basicConfig(level=logging.INFO)

def run_diagnostic():
    print("=" * 80)
    print("OPSMELD DATA TRUST - BC COMPANY DISCOVERY DIAGNOSTIC")
    print("=" * 80)

    cfg = load_client_config()
    print(f"Tenant ID: {cfg.tenant_id}")
    print(f"Environment: {cfg.environment}")

    client = BCMCPClient(cfg)
    token = client.get_access_token()
    print(f"Access Token Acquired: {bool(token)}")

    if not token:
        print("ERROR: Access token could not be acquired. Check session or device code flow.")
        return

    raw = client._execute_bc_rest("companies")
    print("\n===== STEP 1: RAW BC /companies RESPONSE =====")
    if isinstance(raw, dict) and not raw.get("is_error") and "error" not in raw:
        companies = raw.get("value", [])
        raw_count = len(companies)
        print(f"RAW COMPANY COUNT: {raw_count}")
        for c in companies:
            print(f"  GUID: {c.get('id')} | Name: {c.get('name')} | DisplayName: {c.get('displayName')}")
    else:
        print(f"RAW RESPONSE ERROR: {raw}")
        companies = []
        raw_count = 0

    print("\n===== STEP 2: PER-COMPANY GL AUTHORIZATION PROBES =====")
    probe_results = []
    for c in companies:
        comp_id = c.get("id")
        comp_name = c.get("name")
        probe = client._execute_bc_rest(f"companies({comp_id})/generalLedgerEntries?=1")
        if isinstance(probe, dict) and (probe.get("is_error") or "error" in probe):
            status = probe.get("http_status", "?")
            err = probe.get("error", "Unknown error")
            print(f"  [REJECTED] {comp_name} ({comp_id}) -> GL probe HTTP {status}: {err}")
            probe_results.append((comp_id, comp_name, status, "REJECTED", err))
        else:
            val_len = len(probe.get("value", [])) if isinstance(probe, dict) else 0
            print(f"  [AUTHORIZED] {comp_name} ({comp_id}) -> GL probe HTTP 200 (records={val_len})")
            probe_results.append((comp_id, comp_name, 200, "AUTHORIZED", "OK"))

    print("\n===== STEP 3: OPSMELD AUTHORIZED COMPANIES PIPELINE =====")
    mgr = CompanyAccessManager()
    authorized, ds = mgr.get_discovered_companies_with_provenance(client)
    auth_count = len(authorized)
    print(f"DATA SOURCE              : {ds}")
    print(f"AUTHORIZED COMPANY COUNT : {auth_count}")
    for c in authorized:
        print(f"  GUID: {c.get('id')} | Name: {c.get('name')} | DisplayName: {c.get('displayName')}")

    print("\n" + "=" * 80)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 80)
    print(f"BC RAW COMPANY COUNT      : {raw_count}")
    print(f"AUTHORIZED COMPANY COUNT  : {auth_count}")
    print(f"DATA SOURCE               : {ds}")

    if raw_count == 1 and auth_count == 1:
        print("\nCLASSIFICATION: [CASE A] Business Central returns only 1 company to this tenant/session context.")
        print("CONCLUSION: Opsmeld is NOT hiding companies. The BC environment itself contains only 1 company.")
    elif raw_count > 1 and auth_count == 1:
        print("\nCLASSIFICATION: [CASE B] Business Central returns multiple companies, but Opsmeld GL probe filters them down to 1.")
        print("CONCLUSION: Server-side GL authorization probe rejected the other companies.")
    elif raw_count > 1 and auth_count == raw_count:
        print("\nCLASSIFICATION: [CASE C/D] Server-side discovery returns all companies. Issue is frontend/cache rendering.")
    else:
        print(f"\nCLASSIFICATION: RAW={raw_count}, AUTHORIZED={auth_count}")

if __name__ == "__main__":
    run_diagnostic()