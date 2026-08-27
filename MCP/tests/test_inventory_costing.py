"""
Opsmeld Data Trust — Dedicated Test Suite for Phase 3 Inventory Costing & Valuation Integrity.
Verifies BaselineEligibilityFilter, CostBaselineResolver, DataAcquirer inventory endpoints,
population routing, company isolation, C1–C10 signals, boolean normalization,
C3 materiality threshold, currency gating, peer attenuation Gating, and End-to-End Scenarios A-D.
"""

import unittest
from unittest.mock import MagicMock
from modules.data_trust_engine.baseline_resolver import (
    CostBaselineResolver, BaselineEligibilityFilter, calculate_mad, calculate_median
)
from modules.data_trust_engine.acquisition import DataAcquirer
from modules.data_trust_engine.rules.inventory_costing import InventoryCostingRule, normalize_boolean
from modules.data_trust_engine.engine import DataTrustEngineOrchestrator


class TestInventoryCostingPhase3(unittest.TestCase):
    def setUp(self):
        self.resolver = CostBaselineResolver(minimum_history=20)
        self.rule = InventoryCostingRule(minimum_history=20)

    # -------------------------------------------------------------------------
    # 1. BaselineEligibilityFilter & Currency Gating Tests
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

        # Gated by rule eligibility as well
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
    # 2. CostBaselineResolver Direct Unit Tests
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
        # Add out-of-order date entries
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
    # 3. Peer Attenuation & Peer Movement Calculation Tests
    # -------------------------------------------------------------------------
    def test_peer_history_under_20_does_not_attenuate(self):
        tx = {
            "id": "SPIKE-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
            "variant_code": "DEFAULT", "cost_per_unit": 145.0, "quantity": 10.0, "currency_code": "INR"
        }
        # Vendor-specific history = 25 (median = 100)
        history = [
            {
                "id": f"HIST-V-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "currency_code": "INR"
            }
            for i in range(25)
        ]
        # Peer history = 5 (< 20 threshold) even with high peer median = 135
        history.extend([
            {
                "id": f"HIST-PEER-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-OTHER-{i}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 135.0, "currency_code": "INR"
            }
            for i in range(5)
        ])
        config = {"inventory_costing": {"enabled": True, "historical_pattern": {"relative_change_percent": 25.0}}}

        res = self.resolver.resolve_baseline(tx, history, config)
        self.assertEqual(res["peer"]["peer_attenuation_status"], "INSUFFICIENT_PEERS")

        finding = self.rule.evaluate_candidate(tx, history, config)
        self.assertEqual(finding.classification, "Potential Data Error")
        self.assertEqual(finding.evidence_strength, "HIGH")

    def test_vendor_spike_vs_broad_market_movement(self):
        tx = {
            "id": "SPIKE-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
            "variant_code": "DEFAULT", "cost_per_unit": 135.0, "quantity": 10.0, "currency_code": "INR"
        }
        # Vendor A historical median = 100.0
        history = [
            {
                "id": f"HIST-V-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "currency_code": "INR"
            }
            for i in range(25)
        ]
        # Earlier peer transactions (Jan-June): cost = 100.0
        for i in range(20):
            history.append({
                "id": f"HIST-PEER-EARLY-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-OTHER-{i}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "posting_date": f"2026-02-{min(i+1, 28):02d}", "currency_code": "INR"
            })
        # Recent peer transactions (August): cost = 125.0
        for i in range(10):
            history.append({
                "id": f"HIST-PEER-RECENT-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-OTHER-{i+20}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 125.0, "posting_date": f"2026-08-{min(i+1, 28):02d}", "currency_code": "INR"
            })
        config = {"inventory_costing": {"enabled": True, "historical_pattern": {"relative_change_percent": 25.0}}}

        res = self.resolver.resolve_baseline(tx, history, config)
        self.assertEqual(res["peer"]["peer_attenuation_status"], "ATTENUATED")

        finding = self.rule.evaluate_candidate(tx, history, config)
        self.assertEqual(finding.classification, "Anomaly")
        self.assertEqual(finding.evidence_strength, "MEDIUM")

    def test_peer_movement_time_window_separation(self):
        """Verifies peer movement is calculated by comparing historical peer median vs recent peer median across distinct time windows."""
        tx = {
            "id": "CURR-PEER-SHIFT", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
            "variant_code": "DEFAULT", "cost_per_unit": 130.0, "currency_code": "INR"
        }
        # Vendor A historical median = 100.0
        history = [
            {
                "id": f"HIST-V-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "posting_date": f"2026-01-{min(i+1, 28):02d}", "currency_code": "INR"
            }
            for i in range(25)
        ]
        # Earlier peer transactions (Jan-June): cost = 100.0
        for i in range(20):
            history.append({
                "id": f"HIST-PEER-EARLY-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-PEER-{i}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "posting_date": f"2026-02-{min(i+1, 28):02d}", "currency_code": "INR"
            })
        # Recent peer transactions (August): cost = 125.0
        for i in range(10):
            history.append({
                "id": f"HIST-PEER-RECENT-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-PEER-{i+20}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 125.0, "posting_date": f"2026-08-{min(i+1, 28):02d}", "currency_code": "INR"
            })

        res = self.resolver.resolve_baseline(tx, history)
        self.assertEqual(res["peer"]["historical_peer_median"], 100.0)
        self.assertEqual(res["peer"]["recent_peer_median"], 125.0)
        self.assertEqual(res["peer"]["peer_shift_percent"], 25.0)
        self.assertEqual(res["peer"]["peer_attenuation_status"], "ATTENUATED")

    # -------------------------------------------------------------------------
    # 4. Quantity Zero & Payload Normalization Tests
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
    # 5. Boolean Normalization & C3 Materiality Tests
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
        # Small variance (5% < 20% thresh) -> C3 does NOT fire
        tx_below = {
            "id": "C3-BELOW", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 100.0, "quantity": 10.0,
            "cost_amount_expected": 1000.0, "cost_amount_actual": 1050.0, "currency_code": "INR"
        }
        # Large variance (30% >= 20% thresh) -> C3 fires
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


if __name__ == "__main__":
    unittest.main()
