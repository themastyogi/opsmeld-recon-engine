"""
Unit tests for Opsmeld Configuration Loader and Core Client Modules.
"""

import os
import unittest
from pathlib import Path
from core.config_loader import load_client_config, load_engine_rules, ClientConfig, EngineRules
from core.bc_mcp_client import BCMCPClient
from core.ledger_theme import escape_html, LEDGER_CSS


class TestConfigLoader(unittest.TestCase):

    def test_load_client_config_default(self):
        config = load_client_config()
        self.assertIsInstance(config, ClientConfig)
        self.assertTrue(len(config.client_key) > 0)
        self.assertTrue(config.get_absolute_cache_path().name.endswith(".bin"))

    def test_load_engine_rules(self):
        rules = load_engine_rules()
        self.assertIsInstance(rules, EngineRules)
        self.assertTrue(rules.default_do_not_post)
        self.assertTrue(rules.allow_write_operations)

    def test_escape_html_safety(self):
        unsafe_input = "<script>alert('xss')</script>"
        safe_output = escape_html(unsafe_input)
        self.assertNotIn("<script>", safe_output)
        self.assertIn("&lt;script&gt;", safe_output)

    def test_bc_mcp_client_tool_call(self):
        client = BCMCPClient()
        tools = client.list_tools()
        self.assertTrue(len(tools) > 0)
        
        customers = client.call_tool("customers_get_list")
        self.assertIn("value", customers)
        self.assertGreater(len(customers["value"]), 0)


if __name__ == "__main__":
    unittest.main()
