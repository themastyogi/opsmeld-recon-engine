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
    print(f"Client Key: {getattr(cfg, 'client_key', 'default_client')}")
    cache_path = cfg.get_absolute_cache_path()
    print(f"Token Cache Path: {cache_path} (Exists: {cache_path.exists()})")

    client = BCMCPClient(cfg)
    token = client.get_access_token()
    print(f"Access Token Acquired: {bool(token)}")

    if not token:
        print("\n===== MSAL AUTHENTICATION & TOKEN CACHE DIAGNOSTIC =====")
        try:
            import msal
            print("MSAL module imported: OK")
            cache = msal.SerializableTokenCache()
            if cache_path.exists():
                print(f"Token Cache File Size: {cache_path.stat().st_size} bytes")
                with open(cache_path, "r", encoding="utf-8") as f:
                    raw_data = f.read()
                    cache.deserialize(raw_data)
                    app = msal.PublicClientApplication(
                        client_id=cfg.app_client_id,
                        authority=f"https://login.microsoftonline.com/{cfg.tenant_id}",
                        token_cache=cache,
                    )
                    accounts = app.get_accounts()
                    print(f"Accounts found in token cache: {len(accounts)}")
                    for i, acc in enumerate(accounts):
                        print(f"  Account [{i}]: username={acc.get('username')}")

                    if accounts:
                        res_default = app.acquire_token_silent(cfg.scopes, account=accounts[0])
                        if res_default and "access_token" in res_default:
                            print("  acquire_token_silent(cfg.scopes): SUCCESS")
                        else:
                            err_name = res_default.get('error') if res_default else 'None'
                            err_desc = res_default.get('error_description') if res_default else 'No result'
                            print(f"  acquire_token_silent(cfg.scopes): FAILED -> {err_name}: {err_desc}")

                        res_user = app.acquire_token_silent(["https://api.businesscentral.dynamics.com/user_impersonation"], account=accounts[0])
                        if res_user and "access_token" in res_user:
                            print("  acquire_token_silent(user_impersonation): SUCCESS")
                        else:
                            err_name = res_user.get('error') if res_user else 'None'
                            err_desc = res_user.get('error_description') if res_user else 'No result'
                            print(f"  acquire_token_silent(user_impersonation): FAILED -> {err_name}: {err_desc}")
            else:
                print("Token cache file does NOT exist at path.")

            client_secret = getattr(cfg, "client_secret", None) or os.environ.get("BC_CLIENT_SECRET")
            print(f"Client Secret configured: {bool(client_secret)}")
        except ImportError as ie:
            print(f"MSAL ImportError: {ie}")
            print("HINT: Run the script using the project virtualenv Python: `./venv/bin/python scratch/diagnose_company_discovery.py`")
        except Exception as ex:
            print(f"MSAL Diagnostic Exception: {ex}")

        print("\nERROR: Access token could not be acquired. Check session or device code flow.")
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