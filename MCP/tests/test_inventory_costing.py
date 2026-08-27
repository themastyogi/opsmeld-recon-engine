"""
Opsmeld Data Trust — Dedicated Test Suite for Phase 3 Inventory Costing & Valuation Integrity.
Verifies CostBaselineResolver, DataAcquirer inventory endpoints, population routing,
company isolation, C1–C10 signals, cost driver analysis, peer attenuation, and End-to-End Scenarios A-D.
"""

import unittest
from unittest.mock import MagicMock
from modules.data_trust_engine.baseline_resolver import CostBaselineResolver, calculate_mad, calculate_median
from modules.data_trust_engine.acquisition import DataAcquirer
from modules.data_trust_engine.rules.inventory_costing import InventoryCostingRule
from modules.data_trust_engine.engine import DataTrustEngineOrchestrator


class TestInventoryCostingPhase3(unittest.TestCase):
    def setUp(self):
        self.resolver = CostBaselineResolver(minimum_history=20)
        self.rule = InventoryCostingRule(minimum_history=20)

    # -------------------------------------------------------------------------
    # 1. CostBaselineResolver Direct Unit Tests
    # -------------------------------------------------------------------------
    def test_mad_and_median_calculation(self):
        vals = [10.0, 12.0, 15.0, 18.0, 20.0]
        self.assertEqual(calculate_median(vals), 15.0)
        self.assertEqual(calculate_mad(vals, 15.0), 3.0)

    def test_baseline_hierarchy_vendor_item_selected(self):
        tx = {
            "id": "CURR-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 150.0, "currency_code": "INR"
        }
        history = [
            {
                "id": f"HIST-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 100.0, "currency_code": "INR"
            }
            for i in range(25)
        ]
        res = self.resolver.resolve_baseline(tx, history)
        self.assertEqual(res["status"], "ELIGIBLE")
        self.assertEqual(res["primary"]["level"], "VENDOR_ITEM")
        self.assertEqual(res["primary"]["count"], 25)
        self.assertEqual(res["primary"]["median"], 100.0)

    def test_baseline_hierarchy_fallback_to_item_location(self):
        tx = {
            "id": "CURR-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 150.0, "currency_code": "INR"
        }
        # Vendor-specific history: only 7 (< 20)
        history = [
            {
                "id": f"HIST-V-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 100.0, "currency_code": "INR"
            }
            for i in range(7)
        ]
        # Broader Item + Location history: 25 (>= 20)
        history.extend([
            {
                "id": f"HIST-L-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": f"VEND-OTHER-{i}", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 105.0, "currency_code": "INR"
            }
            for i in range(25)
        ])

        res = self.resolver.resolve_baseline(tx, history)
        self.assertEqual(res["status"], "ELIGIBLE")
        self.assertEqual(res["primary"]["level"], "ITEM_LOCATION")
        self.assertEqual(res["counts"]["vendor_item_count"], 7)

    def test_baseline_current_transaction_exclusion(self):
        tx = {
            "id": "TX-SAME-ID", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 500.0, "currency_code": "INR"
        }
        history = [
            {
                "id": "TX-SAME-ID", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 500.0, "currency_code": "INR"
            }
        ]
        for i in range(20):
            history.append({
                "id": f"HIST-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 100.0, "currency_code": "INR"
            })

        res = self.resolver.resolve_baseline(tx, history)
        self.assertEqual(res["primary"]["count"], 20)
        self.assertEqual(res["primary"]["median"], 100.0)

    def test_baseline_poisoning_protection(self):
        tx = {
            "id": "CURR-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 150.0, "currency_code": "INR"
        }
        history = [
            {
                "id": f"HIST-NORMAL-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 100.0, "currency_code": "INR"
            }
            for i in range(20)
        ]
        # Add 5 unresolved anomaly records with extreme costs
        history.extend([
            {
                "id": f"HIST-ANOMALY-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 999.0, "currency_code": "INR",
                "is_unresolved_anomaly": True, "finding_status": "UNRESOLVED"
            }
            for i in range(5)
        ])

        res = self.resolver.resolve_baseline(tx, history)
        self.assertEqual(res["primary"]["count"], 20)
        self.assertEqual(res["primary"]["median"], 100.0)

    def test_currency_basis_isolation(self):
        tx = {
            "id": "CURR-USD", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 110.0, "currency_code": "USD"
        }
        history = [
            {
                "id": f"HIST-INR-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 105.0, "currency_code": "INR"
            }
            for i in range(25)
        ]

        res = self.resolver.resolve_baseline(tx, history)
        self.assertEqual(res["status"], "INSUFFICIENT_EVIDENCE")

    def test_explicit_baseline_resolver_company_isolation(self):
        tx = {
            "id": "CURR-COMP-A", "company_id": "COMPANY_A", "tenant_id": "TEN1",
            "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
            "variant_code": "VAR-1", "cost_per_unit": 105.0, "currency_code": "INR"
        }
        history = [
            {
                "id": f"HIST-COMP-A-{i}", "company_id": "COMPANY_A", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 101.0, "currency_code": "INR"
            }
            for i in range(25)
        ]
        # Add Company B records with 510 median
        history.extend([
            {
                "id": f"HIST-COMP-B-{i}", "company_id": "COMPANY_B", "tenant_id": "TEN1",
                "item_no": "ITEM-100", "vendor_no": "VEND-A", "location_code": "MAIN",
                "variant_code": "VAR-1", "cost_per_unit": 510.0, "currency_code": "INR"
            }
            for i in range(25)
        ])

        res = self.resolver.resolve_baseline(tx, history)
        self.assertEqual(res["primary"]["median"], 101.0)
        self.assertEqual(res["primary"]["count"], 25)

    # -------------------------------------------------------------------------
    # 2. Acquisition Contract & Fail-Closed Tests
    # -------------------------------------------------------------------------
    def test_partial_acquisition_fail_closed(self):
        mock_client = MagicMock()
        mock_client.get_access_token.return_value = "mock_token"

        # Item Ledger succeeds, Value Entry fails
        mock_client._execute_bc_rest.side_effect = [
            {"value": [{"id": "ILE-1", "quantity": 10, "costAmountActual": 100}]},
            {"is_error": True, "error": "Value Entry OData Error"}
        ]

        acquirer = DataAcquirer(mcp_client=mock_client)
        txs, provenance = acquirer.acquire_inventory_cost_transactions(company_id="COMP_GUID")
        self.assertEqual(provenance, "DATA_UNAVAILABLE")
        self.assertEqual(len(txs), 0)

    def test_auto_mode_no_client_returns_data_unavailable_inventory(self):
        acquirer = DataAcquirer(mcp_client=None, mode="AUTO")
        txs, provenance = acquirer.acquire_inventory_cost_transactions()
        self.assertEqual(provenance, "DATA_UNAVAILABLE")
        self.assertEqual(len(txs), 0)

    def test_explicit_test_and_demo_fixture_modes(self):
        acquirer_test = DataAcquirer(mcp_client=None, mode="TEST_FIXTURE")
        txs_test, prov_test = acquirer_test.acquire_inventory_cost_transactions()
        self.assertEqual(prov_test, "SNAPSHOT_SEED")
        self.assertTrue(len(txs_test) > 0)

        acquirer_demo = DataAcquirer(mcp_client=None, mode="DEMO_FIXTURE")
        txs_demo, prov_demo = acquirer_demo.acquire_inventory_cost_transactions()
        self.assertEqual(prov_demo, "SNAPSHOT_SEED")
        self.assertTrue(len(txs_demo) > 0)

    # -------------------------------------------------------------------------
    # 3. Population Routing Tests
    # -------------------------------------------------------------------------
    def test_population_routing_inventory_costing_only(self):
        orch = DataTrustEngineOrchestrator(mcp_client=None)
        res = orch.run_recon(mode="TEST_FIXTURE")
        self.assertIn("INVENTORY_COSTING", res["rule_status"])

    # -------------------------------------------------------------------------
    # 4. Mandatory End-to-End Pipeline Scenarios (A - D)
    # -------------------------------------------------------------------------
    def test_scenario_a_unexplained_spike(self):
        """Scenario A: Vendor A historical = 105, Current = 145 (+38%), Peers = 105, No Driver -> Potential Data Error."""
        tx = {
            "id": "SPIKE-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
            "variant_code": "DEFAULT", "cost_per_unit": 145.0, "quantity": 10.0,
            "cost_amount_actual": 1450.0, "cost_amount_expected": 1450.0, "currency_code": "INR"
        }
        history = [
            {
                "id": f"HIST-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
                "variant_code": "DEFAULT", "cost_per_unit": 105.0, "quantity": 10.0, "currency_code": "INR"
            }
            for i in range(25)
        ]
        tx["historical_transactions"] = history
        config = {"inventory_costing": {"enabled": True, "historical_pattern": {"relative_change_percent": 25.0}}}

        finding = self.rule.evaluate_candidate(tx, history, config)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.classification, "Potential Data Error")
        self.assertEqual(finding.evidence_strength, "HIGH")

        fired_codes = [s["signal_code"] for s in finding.signals if s["fired"]]
        self.assertIn("C1", fired_codes)
        self.assertIn("C7", fired_codes)
        self.assertIn("C8", fired_codes)

    def test_scenario_b_legitimate_item_charge(self):
        """Scenario B: Landed cost item charge -> C6 fired, Informational / Explained Cost Movement."""
        tx = {
            "id": "LANDED-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
            "variant_code": "DEFAULT", "cost_per_unit": 135.0, "quantity": 10.0,
            "cost_amount_actual": 1350.0, "cost_amount_expected": 1350.0,
            "item_charge_no": "FREIGHT-01", "currency_code": "INR"
        }
        history = [
            {
                "id": f"HIST-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
                "variant_code": "DEFAULT", "cost_per_unit": 105.0, "quantity": 10.0, "currency_code": "INR"
            }
            for i in range(25)
        ]
        config = {"inventory_costing": {"enabled": True, "historical_pattern": {"relative_change_percent": 25.0}}}

        finding = self.rule.evaluate_candidate(tx, history, config)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.classification, "Informational")
        fired_codes = [s["signal_code"] for s in finding.signals if s["fired"]]
        self.assertIn("C6", fired_codes)
        self.assertNotIn("C8", fired_codes)

    def test_scenario_c_vendor_history_sparse(self):
        """Scenario C: Vendor history = 7 (<20), Item/Location history = 80 -> Primary baseline = ITEM_LOCATION."""
        tx = {
            "id": "SPARSE-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-SPARSE", "location_code": "DELHI",
            "variant_code": "DEFAULT", "cost_per_unit": 125.0, "quantity": 10.0, "currency_code": "INR"
        }
        # 7 vendor-specific history
        history = [
            {
                "id": f"HIST-V-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-SPARSE", "location_code": "DELHI",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "quantity": 10.0, "currency_code": "INR"
            }
            for i in range(7)
        ]
        # 80 item/location history
        history.extend([
            {
                "id": f"HIST-L-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-OTHER-{i}", "location_code": "DELHI",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "quantity": 10.0, "currency_code": "INR"
            }
            for i in range(80)
        ])
        config = {"inventory_costing": {"enabled": True, "historical_pattern": {"relative_change_percent": 20.0}}}

        res = self.resolver.resolve_baseline(tx, history)
        self.assertEqual(res["primary"]["level"], "ITEM_LOCATION")
        self.assertEqual(res["counts"]["vendor_item_count"], 7)

    def test_scenario_d_whole_market_movement_attenuation(self):
        """Scenario D: Vendor deviation = +30%, Peer movement = +23.5% >= 20% -> Attenuated to Anomaly / Medium evidence."""
        tx = {
            "id": "MARKET-1", "company_id": "COMP1", "tenant_id": "TEN1",
            "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
            "variant_code": "DEFAULT", "cost_per_unit": 130.0, "quantity": 10.0, "currency_code": "INR"
        }
        # Vendor-specific baseline median = 100.0
        history = [
            {
                "id": f"HIST-V-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": "VENDOR-A", "location_code": "DELHI",
                "variant_code": "DEFAULT", "cost_per_unit": 100.0, "quantity": 10.0, "currency_code": "INR"
            }
            for i in range(25)
        ]
        # Broader item peer baseline median = 125.0 (25% shift)
        history.extend([
            {
                "id": f"HIST-PEER-{i}", "company_id": "COMP1", "tenant_id": "TEN1",
                "item_no": "ITEM-X", "vendor_no": f"VENDOR-OTHER-{i}", "location_code": "OTHER",
                "variant_code": "DEFAULT", "cost_per_unit": 125.0, "quantity": 10.0, "currency_code": "INR"
            }
            for i in range(80)
        ])
        config = {"inventory_costing": {"enabled": True, "historical_pattern": {"relative_change_percent": 25.0}}}

        finding = self.rule.evaluate_candidate(tx, history, config)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.classification, "Anomaly")
        self.assertEqual(finding.evidence_strength, "MEDIUM")


if __name__ == "__main__":
    unittest.main()
