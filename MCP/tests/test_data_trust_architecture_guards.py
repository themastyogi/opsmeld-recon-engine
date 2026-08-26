"""
Static Architecture Dependency Inversion & Single Implementation Guards for Data Trust.
Proves data_trust_engine package contains zero imports from legacy modules.data_trust facade,
and modules.data_trust remains a thin compatibility façade with zero duplicate active rule logic.
"""
import ast
import pathlib
import unittest
from unittest.mock import MagicMock


class TestDataTrustArchitectureGuards(unittest.TestCase):
    def setUp(self):
        self.repo_root = pathlib.Path(__file__).parent.parent
        self.modular_engine_dir = self.repo_root / "modules" / "data_trust_engine"
        self.facade_file = self.repo_root / "modules" / "data_trust.py"

    def test_no_forbidden_imports_in_modular_engine(self):
        """data_trust_engine package MUST NOT import from modules.data_trust."""
        forbidden_matches = []
        for py_file in self.modular_engine_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module == "modules.data_trust":
                        rel_path = py_file.relative_to(self.repo_root)
                        forbidden_matches.append(f"{rel_path}:{node.lineno} imports from modules.data_trust")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "modules.data_trust":
                            rel_path = py_file.relative_to(self.repo_root)
                            forbidden_matches.append(f"{rel_path}:{node.lineno} imports modules.data_trust")

        self.assertEqual(
            forbidden_matches,
            [],
            f"Dependency inversion violation! Found forbidden legacy imports inside data_trust_engine: {forbidden_matches}"
        )

    def test_compatibility_facade_imports_exist(self):
        """modules.data_trust MUST successfully export DataTrustEngine, DataTrustFinding, DataTrustConfigManager."""
        from modules.data_trust import DataTrustEngine, DataTrustFinding, DataTrustConfigManager
        self.assertIsNotNone(DataTrustEngine)
        self.assertIsNotNone(DataTrustFinding)
        self.assertIsNotNone(DataTrustConfigManager)

    def test_single_active_rule_implementation_path(self):
        """modules.data_trust RulePacks MUST be thin shims delegating to data_trust_engine rules."""
        from modules.data_trust import PostingDateRulePack, SubledgerBypassRulePack, NarrationContextRulePack
        from modules.data_trust_engine.rules.posting_date import PostingDatePolicyRule
        from modules.data_trust_engine.rules.subledger_bypass import SubledgerBypassRule
        from modules.data_trust_engine.rules.narration_context import NarrationContextRule

        self.assertTrue(hasattr(PostingDateRulePack, "evaluate_transaction"))
        self.assertTrue(hasattr(SubledgerBypassRulePack, "evaluate_transaction"))
        self.assertTrue(hasattr(NarrationContextRulePack, "evaluate_candidate"))

        # AST inspection: Verify facade classes are thin delegation shims (<5 body statements each)
        tree = ast.parse(self.facade_file.read_text(encoding="utf-8"), filename=str(self.facade_file))
        rule_pack_classes = ["PostingDateRulePack", "SubledgerBypassRulePack", "NarrationContextRulePack"]
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in rule_pack_classes:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        statement_count = len(item.body)
                        self.assertLessEqual(
                            statement_count,
                            5,
                            f"Duplicate active rule logic found in legacy façade class {node.name}.{item.name} ({statement_count} statements)."
                        )

    def test_orchestrator_no_cronus_in_hardcoded_fallback(self):
        """DataTrustEngineOrchestrator run_recon MUST NOT contain hardcoded 'CRONUS IN' fallback."""
        orchestrator_file = self.modular_engine_dir / "engine.py"
        content = orchestrator_file.read_text(encoding="utf-8")
        self.assertNotIn('or "CRONUS IN"', content, "Orchestrator must not hardcode 'CRONUS IN' fallback")

    def test_auto_mode_no_client_returns_data_unavailable(self):
        """Production AUTO mode without a BC client MUST return DATA_UNAVAILABLE (no silent SNAPSHOT_SEED fallback)."""
        from modules.data_trust_engine.acquisition import DataAcquirer
        acquirer = DataAcquirer(mcp_client=None, mode="AUTO")
        txs, provenance = acquirer.acquire_transactions()
        self.assertEqual(provenance, "DATA_UNAVAILABLE")
        self.assertEqual(len(txs), 0)

    def test_payment_timing_uses_dynamic_environment_id(self):
        """Payment Timing transaction normalization MUST use client.config.environment instead of 'production_env'."""
        from modules.data_trust_engine.acquisition import DataAcquirer
        mock_client = MagicMock()
        mock_client.config.environment = "Sandbox_EU"
        acquirer = DataAcquirer(mcp_client=mock_client)
        
        resolved = acquirer._resolve_bc_payment_entries(
            ledger_entries=[{"id": "INV-1", "accountNo": "V1", "dueDate": "2026-08-01", "documentType": "Invoice"}],
            detailed_entries=[{"appliedVendLedgerEntryNo": "INV-1", "documentType": "Payment", "postingDate": "2026-07-25"}],
            ledger_type="VENDOR",
            company_id="COMP_GUID"
        )
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["environment_id"], "Sandbox_EU")

    def test_facade_fetch_live_bc_transactions_delegates_to_acquirer(self):
        """DataTrustEngine.fetch_live_bc_transactions MUST delegate to DataAcquirer."""
        from modules.data_trust import DataTrustEngine
        engine = DataTrustEngine(mcp_client=None)
        txs = engine.fetch_live_bc_transactions()
        self.assertIsInstance(txs, list)
        self.assertEqual(len(txs), 0)


if __name__ == "__main__":
    unittest.main()
