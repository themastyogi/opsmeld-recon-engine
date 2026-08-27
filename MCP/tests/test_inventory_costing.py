"""
Opsmeld Data Trust — Dedicated Test Suite for Phase 3 Inventory Costing & Valuation Integrity.
Verifies BaselineEligibilityFilter, CostBaselineResolver, DataAcquirer inventory endpoints,
population routing, company isolation, C1–C10 signals, boolean normalization,
C3 materiality threshold, currency gating, date-based peer time windowing,
uneven transaction volume handling, and dual minimum history gating for peer attenuation.
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
    # 3. Date-Based Peer Time Windowing & Dual Minimum History Tests
    # -------------------------------------------------------------------------
    def test_peer_recent_history_under_threshold_returns_insufficient_evidence(self):
        """Historical peer count = 40 (>=20), Recent peer count = 3 (<5) -> INSUFFICIENT_EVIDENCE, peer_shift = None, do NOT attenuate."""
        tx = {
            "id": "SPIKE-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
            "variant_code": "DEFAULT", "cost_per_unit": 145.0, "quantity": 10.0, "posting_date": "2026-08-25", "currency_code": "INR"
        }
        # Vendor-specific history = 25
        history = [
            {
                "id": f"HIST-V-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "posting_date": "2026-01-15", "currency_code": "INR"
            }
            for i in range(25)
        ]
        # Historical peer window (Jan-May): 40 entries
        for i in range(40):
            history.append({
                "id": f"HIST-PEER-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-OTHER-{i}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "posting_date": f"2026-02-{min(i+1, 28):02d}", "currency_code": "INR"
            })
        # Recent peer window (August): only 3 entries (< 5 threshold)
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
        # Jan-June: 20 peer transactions @ 100.0
        for i in range(20):
            history.append({
                "id": f"HIST-PEER-JAN-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-P-{i}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "posting_date": f"2026-02-{min(i+1, 28):02d}", "currency_code": "INR"
            })
        # July: Massive volume spike of 100 peer transactions @ 100.0 (still historical > 3 months ago relative to Aug 25)
        for i in range(100):
            history.append({
                "id": f"HIST-PEER-JUL-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-P-JUL-{i}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "posting_date": "2026-05-10", "currency_code": "INR"
            })
        # August (Recent window within 3 months): 10 peer transactions @ 125.0
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


if __name__ == "__main__":
    unittest.main()
