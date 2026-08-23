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
        customers = self.report.fetch_data()
        self.assertGreater(len(customers), 0)
        c30 = next((c for c in customers if c.get("number") == "C00030"), None)
        self.assertIsNotNone(c30)
        self.assertTrue(c30["has_unapplied_limbo"])
        self.assertGreater(c30["trapped_cash"], 0)

    def test_tier_customer_critical_risk(self):
        high_risk = {"number": "C100", "name": "Risk Corp", "balance_due": 18000.0, "credit_limit": 10000.0, "trapped_cash": 5000.0, "has_unapplied_limbo": True}
        tiered = self.report.tier_customer(high_risk)
        self.assertEqual(tiered["tier"], "collect")

    def test_propose_fix_staging(self):
        fix_res = self.report.propose_fix("C00030")
        self.assertIn("status", fix_res)
        self.assertEqual(fix_res.get("status"), "staged")
        self.assertEqual(fix_res.get("journal_batch_name"), "OPSMELD-RECON")

    def test_generate_report(self):
        output_file = "test_ar_manager.html"
        generated_path = self.report.generate_report(output_file)
        self.assertTrue(Path(output_file).exists())
        if Path(output_file).exists():
            Path(output_file).unlink()


if __name__ == "__main__":
    unittest.main()
