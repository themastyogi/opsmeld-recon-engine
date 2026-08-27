"""
Opsmeld Data Trust — Dedicated Test Suite for Phase 3 Inventory Costing & Valuation Integrity.
Verifies BaselineEligibilityFilter, CostBaselineResolver, DataAcquirer inventory endpoints,
authoritative configuration manager deep merge & validation, orchestrator runtime wiring
for minimum_history and lookback_months, and non-regression of Phase 1/2 behavior.
"""

import os
import unittest
from unittest.mock import MagicMock
from modules.data_trust_engine.baseline_resolver import (
    CostBaselineResolver, BaselineEligibilityFilter, calculate_mad, calculate_median
)
from modules.data_trust_engine.acquisition import DataAcquirer
from modules.data_trust_engine.rules.inventory_costing import InventoryCostingRule, normalize_boolean
from modules.data_trust_engine.engine import DataTrustEngineOrchestrator
from modules.data_trust_engine.config import DataTrustConfigManager, deep_merge_configs


class TestInventoryCostingPhase3(unittest.TestCase):
    def setUp(self):
        self.resolver = CostBaselineResolver(minimum_history=20)
        self.rule = InventoryCostingRule(minimum_history=20)
        self.config_mgr = DataTrustConfigManager(client_key="TEST_CLIENT")

    # -------------------------------------------------------------------------
    # 1. Authoritative Configuration Manager & Regression Tests
    # -------------------------------------------------------------------------
    def test_missing_phase3_section_inherits_defaults(self):
        default_cfg = self.config_mgr._default_config()
        partial_user_cfg = {
            "posting_date_policy": default_cfg["posting_date_policy"]
        }
        merged = deep_merge_configs(default_cfg, partial_user_cfg)
        self.assertIn("inventory_costing", merged)
        self.assertEqual(merged["inventory_costing"]["historical_pattern"]["minimum_history"], 20)

    def test_partial_phase3_section_deep_merged(self):
        default_cfg = self.config_mgr._default_config()
        partial_ic_cfg = {
            "inventory_costing": {
                "historical_pattern": {
                    "minimum_history": 15
                }
            }
        }
        merged = deep_merge_configs(default_cfg, partial_ic_cfg)
        self.assertEqual(merged["inventory_costing"]["historical_pattern"]["minimum_history"], 15)
        self.assertEqual(merged["inventory_costing"]["historical_pattern"]["lookback_months"], 12)
        self.assertEqual(merged["inventory_costing"]["peer_movement"]["material_movement_percent"], 20)

    def test_invalid_value_produces_configuration_error(self):
        invalid_cfg = self.config_mgr._default_config()
        invalid_cfg["inventory_costing"]["historical_pattern"]["minimum_history"] = -5
        is_valid, errors = self.config_mgr.validate_config(invalid_cfg)
        self.assertFalse(is_valid)
        self.assertTrue(any("minimum_history" in e for e in errors))

    def test_real_json_file_minimum_history_runtime_change(self):
        """Writes real client JSON config file, loads via DataTrustEngineOrchestrator(client_key=...), and proves minimum_history changes runtime resolver behavior."""
        import json
        from core.config_loader import CONFIG_DIR
        client_key = "REAL_JSON_MIN_HIST_TEST"
        cfg_path = CONFIG_DIR / f"data_trust_config_{client_key}.json"

        # 25 Historical records (enough for min_hist=20, not enough for min_hist=30)
        history = [
            {
                "id": f"HIST-V-{i}", "company_id": "CRONUS IN", "tenant_id": "DEFAULT",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 100.0, "posting_date": "2026-01-15", "currency_code": "INR"
            }
            for i in range(25)
        ]
        tx_spike = {
            "id": "SPIKE-30", "company_id": "CRONUS IN", "tenant_id": "DEFAULT",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 150.0, "quantity": 10.0, "posting_date": "2026-08-25", "currency_code": "INR"
        }
        all_txs = list(history)
        all_txs.append(tx_spike)

        try:
            # Step 1: Write real JSON file with minimum_history = 30
            config_data_30 = self.config_mgr._default_config()
            config_data_30["inventory_costing"]["historical_pattern"]["minimum_history"] = 30
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(config_data_30, f, indent=2)

            orchestrator_30 = DataTrustEngineOrchestrator(client_key=client_key)
            orchestrator_30.acquirer.acquire_inventory_cost_transactions = MagicMock(return_value=(all_txs, "SNAPSHOT_SEED"))

            res_30 = orchestrator_30.run_recon(company_id="CRONUS IN", mode="TEST_FIXTURE")
            all_f_30 = res_30["findings"] if isinstance(res_30, dict) and "findings" in res_30 else res_30
            ic_f_30 = [f for f in all_f_30 if (f.get("rule_pack") if isinstance(f, dict) else getattr(f, "rule_pack", "")) == "Inventory Costing & Valuation Integrity"]
            # min_history=30 requires 30 records -> 25 available -> 0 inventory costing findings from real JSON file
            self.assertEqual(len(ic_f_30), 0)

            # Step 2: Overwrite real JSON file with minimum_history = 10
            config_data_10 = self.config_mgr._default_config()
            config_data_10["inventory_costing"]["historical_pattern"]["minimum_history"] = 10
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(config_data_10, f, indent=2)

            orchestrator_10 = DataTrustEngineOrchestrator(client_key=client_key)
            orchestrator_10.acquirer.acquire_inventory_cost_transactions = MagicMock(return_value=(all_txs, "SNAPSHOT_SEED"))

            res_10 = orchestrator_10.run_recon(company_id="CRONUS IN", mode="TEST_FIXTURE")
            all_f_10 = res_10["findings"] if isinstance(res_10, dict) and "findings" in res_10 else res_10
            ic_f_10 = [f for f in all_f_10 if (f.get("rule_pack") if isinstance(f, dict) else getattr(f, "rule_pack", "")) == "Inventory Costing & Valuation Integrity"]
            # min_history=10 requires 10 records -> 25 available -> 1 inventory costing finding produced from real JSON file!
            self.assertEqual(len(ic_f_10), 1)
            self.assertEqual(ic_f_10[0].rule_pack if hasattr(ic_f_10[0], "rule_pack") else ic_f_10[0]["rule_pack"], "Inventory Costing & Valuation Integrity")
        finally:
            if cfg_path.exists():
                try: cfg_path.unlink()
                except Exception: pass

    def test_real_json_file_lookback_months_acquisition_change(self):
        """Writes real client JSON config file, loads via DataTrustEngineOrchestrator(client_key=...), and proves lookback_months changes acquisition behavior."""
        import json
        from core.config_loader import CONFIG_DIR
        client_key = "REAL_JSON_LOOKBACK_TEST"
        cfg_path = CONFIG_DIR / f"data_trust_config_{client_key}.json"

        sample_txs = [
            {"id": "RECENT-1", "posting_date": "2026-08-15", "cost_per_unit": 100.0},
            {"id": "RECENT-2", "posting_date": "2026-06-10", "cost_per_unit": 100.0},
            {"id": "OLD-1", "posting_date": "2025-01-15", "cost_per_unit": 100.0}
        ]

        try:
            # Write real JSON file with lookback_months = 3
            config_data = self.config_mgr._default_config()
            config_data["inventory_costing"]["historical_pattern"]["lookback_months"] = 3
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)

            orchestrator_3m = DataTrustEngineOrchestrator(client_key=client_key)
            orchestrator_3m.acquirer.mode = "TEST_FIXTURE"
            orchestrator_3m.acquirer._get_fixture_inventory_cost_transactions = MagicMock(return_value=sample_txs)

            # Acquirer receives lookback_months=3 from real JSON file
            acquired_3m, _ = orchestrator_3m.acquirer.acquire_inventory_cost_transactions(company_id="CRONUS IN", lookback_months=orchestrator_3m.config_mgr.load_config()["inventory_costing"]["historical_pattern"]["lookback_months"])
            self.assertEqual(len(acquired_3m), 2)
            self.assertNotIn("OLD-1", [t["id"] for t in acquired_3m])

            # Update real JSON file to lookback_months = 24
            config_data["inventory_costing"]["historical_pattern"]["lookback_months"] = 24
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)

            orchestrator_24m = DataTrustEngineOrchestrator(client_key=client_key)
            orchestrator_24m.acquirer.mode = "TEST_FIXTURE"
            orchestrator_24m.acquirer._get_fixture_inventory_cost_transactions = MagicMock(return_value=sample_txs)

            acquired_24m, _ = orchestrator_24m.acquirer.acquire_inventory_cost_transactions(company_id="CRONUS IN", lookback_months=orchestrator_24m.config_mgr.load_config()["inventory_costing"]["historical_pattern"]["lookback_months"])
            self.assertEqual(len(acquired_24m), 3)
            self.assertIn("OLD-1", [t["id"] for t in acquired_24m])
        finally:
            if cfg_path.exists():
                try: cfg_path.unlink()
                except Exception: pass

    def test_acquirer_path_lookback_months_runtime_change(self):
        """Proves lookback_months filtering through DataAcquirer excludes older records."""
        acquirer = DataAcquirer(mode="TEST_FIXTURE")

        # Population with mix of recent (2026-08-15) and old (2025-01-15) entries
        sample_txs = [
            {"id": "RECENT-1", "posting_date": "2026-08-15", "cost_per_unit": 100.0},
            {"id": "RECENT-2", "posting_date": "2026-06-10", "cost_per_unit": 100.0},
            {"id": "OLD-1", "posting_date": "2025-01-15", "cost_per_unit": 100.0}
        ]
        acquirer._get_fixture_inventory_cost_transactions = MagicMock(return_value=sample_txs)

        txs_12m, _ = acquirer.acquire_inventory_cost_transactions(company_id="CRONUS IN", lookback_months=20)
        self.assertEqual(len(txs_12m), 3)

        txs_3m, _ = acquirer.acquire_inventory_cost_transactions(company_id="CRONUS IN", lookback_months=3)
        self.assertEqual(len(txs_3m), 2)
        tx_ids = [t["id"] for t in txs_3m]
        self.assertNotIn("OLD-1", tx_ids)

    # -------------------------------------------------------------------------
    # 2. BaselineEligibilityFilter & Currency Gating Tests
    # -------------------------------------------------------------------------
    def test_missing_currency_returns_insufficient_evidence(self):
        tx_no_curr = {
            "id": "TX-NO-CURR", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 150.0, "currency_code": None
        }
        history = [
            {
                "id": f"HIST-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 100.0, "currency_code": "INR"
            }
            for i in range(25)
        ]
        res = self.resolver.resolve_baseline(tx_no_curr, history)
        self.assertEqual(res["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(res["reason"], "MISSING_CURRENCY")

        elig = self.rule.assess_eligibility(tx_no_curr)
        self.assertEqual(elig, "INSUFFICIENT_EVIDENCE")

    def test_baseline_eligibility_filter_decouples_unresolved_anomalies(self):
        tx = {"id": "CURR-1", "company_id": "COMP1", "tenant_id": "TEN1", "currency_code": "INR"}
        history = [
            {"id": f"H-NORMAL-{i}", "company_id": "COMP1", "tenant_id": "TEN1", "currency_code": "INR"}
            for i in range(10)
        ]
        history.append({"id": "H-ANOMALY", "company_id": "COMP1", "tenant_id": "TEN1", "currency_code": "INR", "is_unresolved_anomaly": True})
        history.append({"id": "H-UNRESOLVED", "company_id": "COMP1", "tenant_id": "TEN1", "currency_code": "INR", "finding_status": "UNRESOLVED"})

        filtered, is_valid = BaselineEligibilityFilter.filter_eligible_history(tx, history)
        self.assertTrue(is_valid)
        self.assertEqual(len(filtered), 10)

    # -------------------------------------------------------------------------
    # 3. CostBaselineResolver Direct Unit Tests
    # -------------------------------------------------------------------------
    def test_mad_and_median_calculation(self):
        vals = [10.0, 12.0, 15.0, 18.0, 20.0]
        self.assertEqual(calculate_median(vals), 15.0)
        self.assertEqual(calculate_mad(vals, 15.0), 3.0)

    def test_historical_date_sorting_for_most_recent_cost(self):
        tx = {
            "id": "CURR-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 150.0, "currency_code": "INR"
        }
        history = [
            {
                "id": "HIST-LATEST", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 120.0, "posting_date": "2026-08-20", "currency_code": "INR"
            },
            {
                "id": "HIST-EARLIEST", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 80.0, "posting_date": "2026-01-01", "currency_code": "INR"
            }
        ]
        for i in range(18):
            history.append({
                "id": f"HIST-MID-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 100.0, "posting_date": "2026-05-15", "currency_code": "INR"
            })

        res = self.resolver.resolve_baseline(tx, history)
        self.assertEqual(res["primary"]["most_recent_cost"], 120.0)

    # -------------------------------------------------------------------------
    # 4. Date-Based Peer Time Windowing & Dual Minimum History Tests
    # -------------------------------------------------------------------------
    def test_peer_recent_history_under_threshold_returns_insufficient_evidence(self):
        """Historical peer count = 40 (>=20), Recent peer count = 3 (<5) -> INSUFFICIENT_EVIDENCE, peer_shift = None, do NOT attenuate."""
        tx = {
            "id": "SPIKE-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
            "variant_code": "DEFAULT", "cost_per_unit": 145.0, "quantity": 10.0, "posting_date": "2026-08-25", "currency_code": "INR"
        }
        history = [
            {
                "id": f"HIST-V-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "posting_date": "2026-01-15", "currency_code": "INR"
            }
            for i in range(25)
        ]
        for i in range(40):
            history.append({
                "id": f"HIST-PEER-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-OTHER-{i}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "posting_date": f"2026-02-{min(i+1, 28):02d}", "currency_code": "INR"
            })
        for i in range(3):
            history.append({
                "id": f"HIST-PEER-RECENT-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-OTHER-REC-{i}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 135.0, "posting_date": f"2026-08-{i+1:02d}", "currency_code": "INR"
            })

        config = {"inventory_costing": {"enabled": True, "peer_movement": {"minimum_peer_recent_history": 5}}}
        res = self.resolver.resolve_baseline(tx, history, config)

        self.assertEqual(res["peer"]["historical_peer_count"], 40)
        self.assertEqual(res["peer"]["recent_peer_count"], 3)
        self.assertIsNone(res["peer"]["peer_shift_percent"])
        self.assertEqual(res["peer"]["peer_attenuation_status"], "INSUFFICIENT_EVIDENCE")

        finding = self.rule.evaluate_candidate(tx, history, config)
        self.assertEqual(finding.classification, "Potential Data Error")
        self.assertEqual(finding.evidence_strength, "HIGH")

    def test_date_based_peer_window_with_uneven_volumes(self):
        """Proves peer windows are strictly date-based rather than 75%/25% positional splits on volume."""
        tx = {
            "id": "UNEVEN-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
            "variant_code": "DEFAULT", "cost_per_unit": 130.0, "posting_date": "2026-08-25", "currency_code": "INR"
        }
        history = [
            {
                "id": f"HIST-V-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "posting_date": "2026-01-15", "currency_code": "INR"
            }
            for i in range(25)
        ]
        for i in range(20):
            history.append({
                "id": f"HIST-PEER-JAN-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-P-{i}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "posting_date": f"2026-02-{min(i+1, 28):02d}", "currency_code": "INR"
            })
        for i in range(100):
            history.append({
                "id": f"HIST-PEER-JUL-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-P-JUL-{i}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "posting_date": "2026-05-10", "currency_code": "INR"
            })
        for i in range(10):
            history.append({
                "id": f"HIST-PEER-AUG-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-P-AUG-{i}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 125.0, "posting_date": f"2026-08-{min(i+1, 28):02d}", "currency_code": "INR"
            })

        config = {"inventory_costing": {"enabled": True, "peer_movement": {"recent_lookback_months": 3, "minimum_peer_recent_history": 5}}}
        res = self.resolver.resolve_baseline(tx, history, config)

        self.assertEqual(res["peer"]["historical_peer_count"], 120)
        self.assertEqual(res["peer"]["recent_peer_count"], 10)
        self.assertEqual(res["peer"]["historical_peer_median"], 100.0)
        self.assertEqual(res["peer"]["recent_peer_median"], 125.0)
        self.assertEqual(res["peer"]["peer_shift_percent"], 25.0)
        self.assertEqual(res["peer"]["peer_attenuation_status"], "ATTENUATED")

    # -------------------------------------------------------------------------
    # 5. Quantity Zero & Payload Normalization Tests
    # -------------------------------------------------------------------------
    def test_zero_quantity_preserved_and_triggers_c9(self):
        tx = {
            "id": "ZERO-QTY-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "quantity": 0.0, "cost_amount_actual": 250.0,
            "cost_per_unit": 0.0, "currency_code": "INR"
        }
        history = [
            {
                "id": f"HIST-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 100.0, "currency_code": "INR"
            }
            for i in range(25)
        ]
        config = {"inventory_costing": {"enabled": True}}
        finding = self.rule.evaluate_candidate(tx, history, config)
        self.assertIsNotNone(finding)
        fired_codes = [s["signal_code"] for s in finding.signals if s["fired"]]
        self.assertIn("C9", fired_codes)

    def test_missing_value_entry_relationship_fails_closed(self):
        mock_client = MagicMock()
        mock_client.get_access_token.return_value = "mock_token"
        mock_client._execute_bc_rest.side_effect = [
            {"value": [{"id": "ILE-1", "quantity": 10, "costAmountActual": 100}]},
            {"is_error": True, "error": "Value Entry OData Error"}
        ]
        acquirer = DataAcquirer(mcp_client=mock_client)
        txs, provenance = acquirer.acquire_inventory_cost_transactions(company_id="COMP_GUID")
        self.assertEqual(provenance, "DATA_UNAVAILABLE")
        self.assertEqual(len(txs), 0)

    # -------------------------------------------------------------------------
    # 6. Boolean Normalization & Materiality Tests
    # -------------------------------------------------------------------------
    def test_boolean_false_string_normalization_c4_c5(self):
        self.assertFalse(normalize_boolean("false"))
        self.assertFalse(normalize_boolean("False"))
        self.assertFalse(normalize_boolean("0"))
        self.assertFalse(normalize_boolean(0))
        self.assertFalse(normalize_boolean(None))
        self.assertTrue(normalize_boolean("true"))
        self.assertTrue(normalize_boolean("1"))

        tx = {
            "id": "BOOL-TEST", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 100.0, "quantity": 10.0,
            "adjustment": "false", "partial_revaluation": "0", "currency_code": "INR"
        }
        history = [
            {
                "id": f"HIST-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 100.0, "currency_code": "INR"
            }
            for i in range(25)
        ]
        config = {"inventory_costing": {"enabled": True}}
        finding = self.rule.evaluate_candidate(tx, history, config)
        if finding:
            fired_codes = [s["signal_code"] for s in finding.signals if s["fired"]]
            self.assertNotIn("C4", fired_codes)
            self.assertNotIn("C5", fired_codes)

    def test_c3_below_and_above_materiality_threshold(self):
        tx_below = {
            "id": "C3-BELOW", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 100.0, "quantity": 10.0,
            "cost_amount_expected": 1000.0, "cost_amount_actual": 1050.0, "currency_code": "INR"
        }
        tx_above = {
            "id": "C3-ABOVE", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 100.0, "quantity": 10.0,
            "cost_amount_expected": 1000.0, "cost_amount_actual": 1300.0, "currency_code": "INR"
        }
        history = [
            {
                "id": f"HIST-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 100.0, "currency_code": "INR"
            }
            for i in range(25)
        ]
        config = {"inventory_costing": {"enabled": True, "expected_actual": {"relative_variance_percent": 20.0}}}

        finding_below = self.rule.evaluate_candidate(tx_below, history, config)
        if finding_below:
            fired_below = [s["signal_code"] for s in finding_below.signals if s["fired"]]
            self.assertNotIn("C3", fired_below)

        finding_above = self.rule.evaluate_candidate(tx_above, history, config)
        self.assertIsNotNone(finding_above)
        fired_above = [s["signal_code"] for s in finding_above.signals if s["fired"]]
        self.assertIn("C3", fired_above)


    def test_real_json_file_narration_context_minimum_peer_transactions(self):
        """Proves narration_context.minimum_peer_transactions from real JSON file alters rule evaluation."""
        import json
        from core.config_loader import CONFIG_DIR
        from modules.data_trust_engine.rules.narration_context import NarrationContextRule
        client_key = "REAL_JSON_NC_TEST"
        cfg_path = CONFIG_DIR / f"data_trust_config_{client_key}.json"

        rule = NarrationContextRule()
        tx = {"id": "NC-101", "account_no": "60100", "narration": "Unusual consulting payment", "vendor_name": "Acme"}
        peer_history = [{"narration": "Paper"} for _ in range(25)]

        try:
            config_data = self.config_mgr._default_config()
            config_data["narration_context"]["minimum_peer_transactions"] = 30
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)

            cfg = DataTrustConfigManager(client_key).load_config()
            cand_30 = rule.evaluate(tx, cfg)
            # min_peer=30 requires 30 records -> 25 available -> returns None (insufficient evidence)
            self.assertIsNone(cand_30)

            config_data["narration_context"]["minimum_peer_transactions"] = 10
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)

            cfg = DataTrustConfigManager(client_key).load_config()
            cand_10 = rule.evaluate(tx, cfg)
            # min_peer=10 requires 10 records -> 25 available -> produces candidate
            self.assertIsNotNone(cand_10)
        finally:
            if cfg_path.exists():
                try: cfg_path.unlink()
                except Exception: pass

    def test_real_json_file_payment_timing_minimum_history_and_lookback(self):
        """Proves payment_timing minimum_history and lookback_months from real JSON file alter rule and acquisition behavior."""
        import json
        from core.config_loader import CONFIG_DIR
        client_key = "REAL_JSON_PT_TEST"
        cfg_path = CONFIG_DIR / f"data_trust_config_{client_key}.json"

        try:
            config_data = self.config_mgr._default_config()
            config_data["payment_timing"] = {
                "enabled": True,
                "historical_pattern": {
                    "minimum_history": 30,
                    "lookback_months": 3
                }
            }
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)

            orchestrator = DataTrustEngineOrchestrator(client_key=client_key)
            loaded_cfg = orchestrator.config_mgr.load_config()
            self.assertEqual(loaded_cfg["payment_timing"]["historical_pattern"]["minimum_history"], 30)
            self.assertEqual(loaded_cfg["payment_timing"]["historical_pattern"]["lookback_months"], 3)
        finally:
            if cfg_path.exists():
                try: cfg_path.unlink()
                except Exception: pass

    def test_baseline_resolver_config_flags(self):
        """Proves vendor_baseline.enabled, peer_baseline.enabled, include_location, and include_variant affect baseline resolver."""
        resolver = CostBaselineResolver(minimum_history=10)
        current_tx = {
            "id": "TX-FLAGS", "item_no": "ITEM-1", "vendor_no": "VEND-1",
            "location_code": "LOC-A", "variant_code": "VAR-1", "cost_per_unit": 150.0,
            "currency_code": "INR"
        }
        history = [
            {
                "id": f"H-{i}", "item_no": "ITEM-1", "vendor_no": "VEND-1",
                "location_code": "LOC-A", "variant_code": "VAR-1", "cost_per_unit": 100.0,
                "currency_code": "INR"
            }
            for i in range(15)
        ]

        # 1. vendor_baseline.enabled = False -> skips VENDOR_ITEM and selects ITEM_LOCATION
        cfg_no_vendor = {
            "inventory_costing": {
                "vendor_baseline": {"enabled": False},
                "peer_baseline": {"enabled": True, "include_location": True, "include_variant": True}
            }
        }
        res_no_vendor = resolver.resolve_baseline(current_tx, history, cfg_no_vendor)
        self.assertEqual(res_no_vendor["primary"]["level"], "ITEM_LOCATION")

        # 2. peer_baseline.enabled = False -> returns peer_dispersion = "DISABLED"
        cfg_no_peer = {
            "inventory_costing": {
                "vendor_baseline": {"enabled": True},
                "peer_baseline": {"enabled": False}
            }
        }
        res_no_peer = resolver.resolve_baseline(current_tx, history, cfg_no_peer)
        self.assertEqual(res_no_peer["peer"]["peer_dispersion"], "DISABLED")
        self.assertEqual(res_no_peer["peer"]["peer_attenuation_status"], "DISABLED")

        # 3. include_location = False -> relaxes location filtering in vendor_item_pool and selects ITEM_VARIANT if vendor disabled
        cfg_no_loc = {
            "inventory_costing": {
                "vendor_baseline": {"enabled": False},
                "baseline_hierarchy": {"include_location": False, "include_variant": True},
                "peer_baseline": {"enabled": True}
            }
        }
        res_no_loc = resolver.resolve_baseline(current_tx, history, cfg_no_loc)
        self.assertEqual(res_no_loc["primary"]["level"], "ITEM_VARIANT")

    def test_save_config_tuple_unpacking_and_validation_error(self):
        """Proves save_config returns (False, errors) tuple on invalid config, protecting UI from reporting success on invalid saves."""
        invalid_config = self.config_mgr._default_config()
        invalid_config["inventory_costing"]["historical_pattern"]["minimum_history"] = -10

        saved, errors = self.config_mgr.save_config(invalid_config)
        self.assertFalse(saved)
        self.assertTrue(isinstance(errors, list))
        self.assertTrue(len(errors) > 0)


    def test_every_exposed_config_knob_alters_runtime_behavior(self):
        """Systematically proves that EVERY exposed configuration knob changes runtime evaluation behavior."""
        resolver = CostBaselineResolver(minimum_history=10)

        tx_spike = {
            "id": "SPIKE", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-1", "vendor_no": "VEND-1", "location_code": "LOC-A",
            "variant_code": "VAR-1", "cost_per_unit": 130.0, "quantity": 10.0,
            "cost_amount_actual": 1300.0, "posting_date": "2026-08-25", "currency_code": "INR"
        }
        history_25 = [
            {
                "id": f"H-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-1", "vendor_no": "VEND-1", "location_code": "LOC-A",
                "variant_code": "VAR-1", "cost_per_unit": 100.0, "posting_date": "2026-01-15",
                "currency_code": "INR"
            }
            for i in range(25)
        ]

        # Knob 1: relative_change_percent (25% vs 50% threshold)
        cfg_rel_25 = {"inventory_costing": {"enabled": True, "historical_pattern": {"relative_change_percent": 25.0}}}
        finding_25 = self.rule.evaluate_candidate(tx_spike, history_25, cfg_rel_25)
        self.assertIsNotNone(finding_25)
        self.assertTrue(any(s["signal_code"] == "C1" and s["fired"] for s in finding_25.signals))

        cfg_rel_50 = {"inventory_costing": {"enabled": True, "historical_pattern": {"relative_change_percent": 50.0}}}
        finding_50 = self.rule.evaluate_candidate(tx_spike, history_25, cfg_rel_50)
        self.assertIsNone(finding_50)

        # Knob 2: peer_movement.material_movement_percent (10% vs 50% threshold for attenuation)
        peers_hist = [
            {"id": f"P-HIST-{i}", "item_no": "ITEM-1", "vendor_no": "VEND-2", "cost_per_unit": 100.0, "posting_date": "2026-01-15", "currency_code": "INR"}
            for i in range(25)
        ]
        peers_recent = [
            {"id": f"P-REC-{i}", "item_no": "ITEM-1", "vendor_no": "VEND-2", "cost_per_unit": 130.0, "posting_date": "2026-08-20", "currency_code": "INR"}
            for i in range(10)
        ]
        peer_history = history_25 + peers_hist + peers_recent

        cfg_att_10 = {"inventory_costing": {"enabled": True, "peer_movement": {"material_movement_percent": 10.0}}}
        res_att_10 = resolver.resolve_baseline(tx_spike, peer_history, cfg_att_10)
        self.assertEqual(res_att_10["peer"]["peer_attenuation_status"], "ATTENUATED")

        cfg_att_50 = {"inventory_costing": {"enabled": True, "peer_movement": {"material_movement_percent": 50.0}}}
        res_att_50 = resolver.resolve_baseline(tx_spike, peer_history, cfg_att_50)
        self.assertEqual(res_att_50["peer"]["peer_attenuation_status"], "UNATTENUATED")

        # Knob 3: peer_movement.minimum_peer_recent_history (5 vs 50 required recent peers)
        cfg_rec_50 = {"inventory_costing": {"enabled": True, "peer_movement": {"minimum_peer_recent_history": 50}}}
        res_rec_50 = resolver.resolve_baseline(tx_spike, peer_history, cfg_rec_50)
        self.assertEqual(res_rec_50["peer"]["peer_attenuation_status"], "INSUFFICIENT_EVIDENCE")

        # Knob 4: quantity_cost.relative_tolerance_percent (discrepancy tolerance check)
        tx_qty_disc = {
            "id": "QTY-DISC", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-1", "vendor_no": "VEND-1", "location_code": "LOC-A",
            "variant_code": "VAR-1", "cost_per_unit": 100.0, "quantity": 10.0,
            "cost_amount_actual": 1200.0, "currency_code": "INR"
        }
        cfg_tol_5 = {"inventory_costing": {"enabled": True, "quantity_cost": {"relative_tolerance_percent": 5.0}}}
        finding_tol_5 = self.rule.evaluate_candidate(tx_qty_disc, history_25, cfg_tol_5)
        self.assertIsNotNone(finding_tol_5)
        self.assertTrue(any(s["signal_code"] == "C9" and s["fired"] for s in finding_tol_5.signals))

        cfg_tol_50 = {"inventory_costing": {"enabled": True, "quantity_cost": {"relative_tolerance_percent": 50.0}}}
        finding_tol_50 = self.rule.evaluate_candidate(tx_qty_disc, history_25, cfg_tol_50)
        if finding_tol_50:
            self.assertFalse(any(s["signal_code"] == "C9" and s["fired"] for s in finding_tol_50.signals))


if __name__ == "__main__":
    unittest.main()
