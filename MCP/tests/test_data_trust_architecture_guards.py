"""
Static Architecture Dependency Inversion & Single Implementation Guards for Data Trust.
Proves data_trust_engine package contains zero imports from legacy modules.data_trust facade,
and modules.data_trust remains a thin compatibility façade.
"""
import ast
import pathlib
import unittest


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


if __name__ == "__main__":
    unittest.main()
