"""
Opsmeld Data Trust — Configuration Manager Service Module.
Manages loading, persisting, and auditing client-specific Data Trust configuration.
"""
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from core.config_loader import load_client_config, CONFIG_DIR, BASE_DIR


class DataTrustConfigManager:
    """Manages loading, persisting, and auditing client-specific Data Trust configuration."""

    def __init__(self, client_key: Optional[str] = None):
        self.client_key = client_key or load_client_config().client_key
        self.config_path = CONFIG_DIR / f"data_trust_config_{self.client_key}.json"
        self.default_config_path = CONFIG_DIR / "data_trust_config.json"
        self.audit_log_path = BASE_DIR / "data" / "snapshots" / f"data_trust_config_audit_{self.client_key}.json"

    def load_config(self) -> Dict[str, Any]:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        if self.default_config_path.exists():
            try:
                with open(self.default_config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return self._default_config()

    def save_config(self, config_data: Dict[str, Any], user: str = "admin@opsmeld.com") -> bool:
        try:
            old_config = self.load_config()
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)

            self._log_audit_trail(old_config, config_data, user)
            return True
        except Exception:
            return False

    def load_audit_trail(self) -> List[Dict[str, Any]]:
        if self.audit_log_path.exists():
            try:
                with open(self.audit_log_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _log_audit_trail(self, old_cfg: Dict[str, Any], new_cfg: Dict[str, Any], user: str):
        try:
            audit_records = self.load_audit_trail()
            audit_records.append({
                "timestamp": datetime.now().isoformat(),
                "user": user,
                "client_key": self.client_key,
                "changes_summary": "Configuration updated via Admin Console",
                "old_config": old_cfg,
                "new_config": new_cfg
            })
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.audit_log_path, "w", encoding="utf-8") as f:
                json.dump(audit_records, f, indent=2)
        except Exception:
            pass

    def _default_config(self) -> Dict[str, Any]:
        return {
            "posting_date_policy": {
                "company_default": {
                    "scope_type": "Company",
                    "scope_value": "DEFAULT",
                    "allowed_posting_mode": "CURRENT_MONTH",
                    "backdating": {
                        "allowed": True,
                        "maximum_days": 7,
                        "approval_required_above_days": 3
                    },
                    "future_dating": {
                        "allowed": True,
                        "maximum_days": 2
                    },
                    "month_close": {
                        "close_date": "2026-08-31",
                        "adjustment_window_days": 5,
                        "approval_required": True
                    },
                    "year_close": {
                        "close_date": "2026-12-31",
                        "adjustment_window_days": 10,
                        "approval_required": True
                    }
                }
            },
            "subledger_control_accounts": [
                {
                    "account_no": "10200",
                    "account_name": "Accounts Payable Control",
                    "subledger_type": "VENDOR",
                    "expected_posting_sources": ["Purchase", "Payables", "Purchases", "VendorLedger"],
                    "direct_posting_allowed": False
                },
                {
                    "account_no": "10100",
                    "account_name": "Accounts Receivable Control",
                    "subledger_type": "CUSTOMER",
                    "expected_posting_sources": ["Sales", "Receivables", "CustLedger"],
                    "direct_posting_allowed": False
                },
                {
                    "account_no": "10500",
                    "account_name": "Inventory Control Account",
                    "subledger_type": "ITEM",
                    "expected_posting_sources": ["Inventory", "Purchase", "Sales", "ItemLedger"],
                    "direct_posting_allowed": False
                },
                {
                    "account_no": "20100",
                    "account_name": "Bank Account Control",
                    "subledger_type": "BANK",
                    "expected_posting_sources": ["Bank", "Cash Receipt", "Payment"],
                    "direct_posting_allowed": False
                }
            ],
            "narration_context": {
                "minimum_peer_transactions": 20,
                "taxonomy_level_2": {
                    "Office Supplies": ["stationery", "printer", "paper", "toner", "furniture", "desk", "chair", "pen", "office"],
                    "Raw Materials": ["steel", "aluminium", "aluminum", "plastic", "metal", "sheet", "resin", "copper", "raw material"],
                    "Professional Fees": ["legal", "audit", "consulting", "advisory", "tax", "accounting", "attorney", "retainer"],
                    "IT Hardware & Software": ["laptop", "monitor", "keyboard", "server", "cable", "memory", "storage", "software", "license"],
                    "Travel & Entertainment": ["flight", "hotel", "taxi", "meal", "travel", "lodging", "uber", "airline"]
                }
            }
        }
