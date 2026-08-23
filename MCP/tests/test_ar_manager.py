"""
Unit tests for AR Manager module.
"""

import unittest
from pathlib import Path
from core.bc_mcp_client import BCMCPClient
from core.config_loader import load_client_config, load_engine_rules
from modules.ar_manager import ARManagerReport


class TestARManager(unittest.TestCase):

    def setUp(self):
        self.config = load_client_config("contoso_us")
        self.rules = load_engine_rules()
        self.client = BCMCPClient(self.config)
        self.report = ARManagerReport(self.client, self.rules)

    def test_tier_customer(self):
        high_risk = {"number": "C100", "name": "Risk Corp", "balance_due": 15000.0, "credit_limit": 10000.0}
        tiered = self.report.tier_customer(high_risk)
        self.assertEqual(tiered["tier"], "collect")

        clear = {"number": "C200", "name": "Safe Inc", "balance_due": 100.0, "credit_limit": 50000.0}
        tiered_clear = self.report.tier_customer(clear)
        self.assertEqual(tiered_clear["tier"], "clear")

    def test_generate_report(self):
        output_file = "test_ar_manager.html"
        generated_path = self.report.generate_report(output_file)
        self.assertTrue(Path(output_file).exists())
        
        # Cleanup
        if Path(output_file).exists():
            Path(output_file).unlink()


if __name__ == "__main__":
    unittest.main()
