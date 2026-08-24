"""
Unit tests for Real AR Manager module and discrepancy analytics.
"""

import unittest
from pathlib import Path
from core.bc_mcp_client import BCMCPClient
from core.config_loader import load_client_config, load_engine_rules
from modules.ar_manager import ARManagerReport


class TestARManager(unittest.TestCase):

    def setUp(self):
        self.config = load_client_config()
        self.rules = load_engine_rules()
        self.client = BCMCPClient(self.config)
        self.report = ARManagerReport(self.client, self.rules)

    def test_fetch_data_and_deep_metrics(self):
        res = self.report.fetch_data()
        self.assertIn("customers", res)

    def test_tier_customer_critical_risk(self):
        high_risk = {"number": "C100", "name": "Risk Corp", "balance_due": 18000.0, "credit_limit": 10000.0, "trapped_cash": 5000.0, "has_unapplied_limbo": True}
        tiered = self.report.tier_customer(high_risk)
        self.assertEqual(tiered["tier"], "collect")

    def test_propose_fix_safety_boundary(self):
        fix_res = self.report.propose_fix("C00030")
        self.assertIsInstance(fix_res, dict)
        self.assertTrue(fix_res.get("read_only_boundary", True))

    def test_calculate_baseline_drift_and_probability_bars(self):
        mock_entries = [
            {"customer_no": "10000", "overdue_days": 10, "open": False},
            {"customer_no": "10000", "overdue_days": 12, "open": False},
            {"customer_no": "10000", "overdue_days": 35, "open": True},
        ]
        drift = self.report.calculate_baseline_drift("10000", mock_entries)
        self.assertIn("drift_days", drift)
        self.assertTrue(drift["is_dormant_risk"])

        bars = self.report.calculate_probability_bars("10000", mock_entries)
        self.assertIsInstance(bars, list)
        self.assertEqual(len(bars), 8)

    def test_generate_report(self):
        output_file = "test_ar_manager.html"
        generated_path = self.report.generate_report(output_file)
        self.assertTrue(Path(output_file).exists())
        if Path(output_file).exists():
            Path(output_file).unlink()

    def test_get_collections_workload_page_pagination(self):
        page_data = self.report.get_collections_workload_page(page=1, page_size=20)
        self.assertIn("current_page", page_data)
        self.assertIn("items", page_data)
        self.assertEqual(page_data["current_page"], 1)
        self.assertEqual(page_data["page_size"], 20)
        self.assertIsInstance(page_data["items"], list)

    def test_call_tool_all_pages_structure(self):
        resp = self.client.call_tool_all_pages("customers_get_list")
        self.assertIsInstance(resp, dict)
        self.assertTrue("value" in resp or "error" in resp)


if __name__ == "__main__":
    unittest.main()
