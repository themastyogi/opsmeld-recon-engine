"""
Opsmeld Data Trust — Configuration Manager Service Module.
Manages loading, persisting, deep merging, and auditing client-specific Data Trust configuration.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from core.config_loader import load_client_config, CONFIG_DIR, BASE_DIR


def deep_merge_configs(default_cfg: Dict[str, Any], override_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merges override_cfg into default_cfg without shallow key erasure."""
    merged = dict(default_cfg)
    for k, v in override_cfg.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = deep_merge_configs(merged[k], v)
        else:
            merged[k] = v
    return merged


class DataTrustConfigManager:
    """Manages loading, persisting, deep merging, and auditing client-specific Data Trust configuration."""

    def __init__(self, client_key: Optional[str] = None):
        self.client_key = client_key or load_client_config().client_key
        self.config_path = CONFIG_DIR / f"data_trust_config_{self.client_key}.json"
        self.default_config_path = CONFIG_DIR / "data_trust_config.json"
        self.audit_log_path = BASE_DIR / "data" / "snapshots" / f"data_trust_config_audit_{self.client_key}.json"

    def load_config(self) -> Dict[str, Any]:
        raw_config = None
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    raw_config = json.load(f)
            except Exception:
                pass
        elif self.default_config_path.exists():
            try:
                with open(self.default_config_path, "r", encoding="utf-8") as f:
                    raw_config = json.load(f)
            except Exception:
                pass

        default_cfg = self._default_config()
        if raw_config is not None:
            effective = deep_merge_configs(default_cfg, raw_config)
        else:
            effective = default_cfg

        is_valid, errors = self.validate_config(effective)
        if not is_valid:
            effective["_validation_errors"] = errors
            effective["_is_valid"] = False

        return effective

    def validate_config(self, config_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Generic validation for Data Trust configuration across all rule packs."""
        errors = []

        ic_cfg = config_data.get("inventory_costing", {})
        if ic_cfg.get("enabled", True):
            hist_pat = ic_cfg.get("historical_pattern", {})
            min_hist = hist_pat.get("minimum_history")
            if min_hist is not None and (not isinstance(min_hist, int) or min_hist <= 0):
                errors.append("inventory_costing.historical_pattern.minimum_history must be an integer > 0")

            lb_months = hist_pat.get("lookback_months")
            if lb_months is not None and (not isinstance(lb_months, (int, float)) or lb_months <= 0):
                errors.append("inventory_costing.historical_pattern.lookback_months must be > 0")

            rel_change = hist_pat.get("relative_change_percent")
            if rel_change is not None and (not isinstance(rel_change, (int, float)) or rel_change <= 0):
                errors.append("inventory_costing.historical_pattern.relative_change_percent must be > 0")

            peer_mov = ic_cfg.get("peer_movement", {})
            min_rec = peer_mov.get("minimum_peer_recent_history")
            if min_rec is not None and (not isinstance(min_rec, int) or min_rec < 0):
                errors.append("inventory_costing.peer_movement.minimum_peer_recent_history must be >= 0")

        nc_cfg = config_data.get("narration_context", {})
        min_peer = nc_cfg.get("minimum_peer_transactions")
        if min_peer is not None and (not isinstance(min_peer, int) or min_peer <= 0):
            errors.append("narration_context.minimum_peer_transactions must be an integer > 0")

        pt_cfg = config_data.get("payment_timing", {})
        pt_hist = pt_cfg.get("historical_pattern", {})
        pt_min_hist = pt_hist.get("minimum_history")
        if pt_min_hist is not None and (not isinstance(pt_min_hist, int) or pt_min_hist <= 0):
            errors.append("payment_timing.historical_pattern.minimum_history must be an integer > 0")

        pt_lb = pt_hist.get("lookback_months")
        if pt_lb is not None and (not isinstance(pt_lb, (int, float)) or pt_lb <= 0):
            errors.append("payment_timing.historical_pattern.lookback_months must be > 0")

        return len(errors) == 0, errors

    def save_config(self, config_data: Dict[str, Any], user: str = "admin@opsmeld.com") -> Tuple[bool, List[str]]:
        is_valid, errors = self.validate_config(config_data)
        if not is_valid:
            return False, errors

        try:
            old_config = self.load_config()
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)

            self._log_audit_trail(old_config, config_data, user)
            return True, []
        except Exception as e:
            return False, [str(e)]

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
            },
            "payment_timing": {
                "enabled": True,
                "historical_pattern": {
                    "minimum_history": 20,
                    "lookback_months": 12,
                    "unusual_deviation_days": 7
                }
            },
            "inventory_costing": {
                "enabled": True,
                "minimum_amount": 0,
                "minimum_quantity": 1,
                "historical_pattern": {
                    "enabled": True,
                    "minimum_history": 20,
                    "lookback_months": 12,
                    "relative_change_percent": 25
                },
                "vendor_baseline": {
                    "enabled": True
                },
                "peer_baseline": {
                    "enabled": True,
                    "include_location": True,
                    "include_variant": True
                },
                "peer_movement": {
                    "enabled": True,
                    "material_movement_percent": 20,
                    "recent_lookback_months": 3,
                    "minimum_peer_recent_history": 5
                },
                "expected_actual": {
                    "enabled": True,
                    "relative_variance_percent": 20
                },
                "quantity_cost": {
                    "enabled": True,
                    "relative_tolerance_percent": 5
                },
                "revaluation": {
                    "enabled": True
                },
                "cost_adjustment": {
                    "enabled": True
                }
            }
        }
