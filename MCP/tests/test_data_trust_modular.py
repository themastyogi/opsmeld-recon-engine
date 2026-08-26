"""
Unit tests for modular Data Trust Engine package (MCP/modules/data_trust_engine/).
Verifies import stability, supporting models, rule contracts, fail-closed live acquisition,
N1-N5 signal structures, LLM failover metadata, and end-to-end run_recon orchestration.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import MagicMock
from modules.data_trust import DataTrustEngine, DataTrustFinding, DataTrustConfigManager
from modules.data_trust_engine.models import StructuredEvidence, SourceMetadata, LLMMetadata
from modules.data_trust_engine.candidate import CandidateTransaction
from modules.data_trust_engine.acquisition import DataAcquirer
from modules.data_trust_engine.llm_interpreter import LLMInterpreter
from modules.data_trust_engine.engine import DataTrustEngineOrchestrator
from modules.data_trust_engine.rules.posting_date import PostingDatePolicyRule
from modules.data_trust_engine.rules.subledger_bypass import SubledgerBypassRule
from modules.data_trust_engine.rules.narration_context import NarrationContextRule


class TestDataTrustModularFramework(unittest.TestCase):

    def test_import_compatibility_facade(self):
        """Verify stable imports from MCP/modules/data_trust.py facade."""
        self.assertIsNotNone(DataTrustEngine)
        self.assertIsNotNone(DataTrustFinding)
        self.assertIsNotNone(DataTrustConfigManager)

    def test_supporting_models(self):
        """Verify additive supporting models in data_trust_engine/models.py."""
        ev = StructuredEvidence(evidence_id="EV-1", entity_table="G/L Entry", field_name="Posting Date")
        self.assertEqual(ev.evidence_id, "EV-1")
        self.assertEqual(ev.source_system, "Business Central")

        meta = SourceMetadata(provenance_state="LIVE_BUSINESS_CENTRAL")
        self.assertEqual(meta.provenance_state, "LIVE_BUSINESS_CENTRAL")

        llm_meta = LLMMetadata(model="claude-haiku-4-5-20251001", status="SUCCESS")
        self.assertEqual(llm_meta.model, "claude-haiku-4-5-20251001")

    def test_candidate_explicit_n1_n5_signals(self):
        """Verify candidate stores explicit N1-N5 signal dictionary objects."""
        rule = NarrationContextRule()
        sample_context = {
            "id": "TX-1001",
            "account_no": "50100",
            "narration": "Suspicious manual entry",
            "peer_history": [{"narration": "Normal"} for _ in range(25)]
        }
        cand = rule.evaluate(sample_context, {})
        self.assertIsNotNone(cand)
        self.assertTrue(isinstance(cand.signals, list))
        self.assertTrue(len(cand.signals) >= 5)
        self.assertEqual(cand.signals[0]["signal_code"], "N1")

    def test_canonical_finding_additive_metadata_wiring(self):
        """Verify DataTrustFinding receives additive structured_evidence, signals, source/llm metadata."""
        finding = DataTrustFinding(
            id="DT-TEST-1",
            dedup_key="DEDUP-TEST-1",
            rule_pack="Subledger Bypass",
            classification="Policy Violation",
            evidence_strength="MEDIUM",
            severity="HIGH",
            signals_fired_count=1,
            evidence_chain=["Subledger bypass detected"],
            transaction_details={"id": "TX-1001", "posting_date": "2026-08-20"},
            business_impact="Reconciliation risk",
            recommended_action="Human review required",
            data_source="LIVE_BUSINESS_CENTRAL",
            structured_evidence=[{"evidence_id": "EV-1"}],
            signals=[{"signal_code": "N1", "fired": True}],
            source_metadata={"provenance_state": "LIVE_BUSINESS_CENTRAL"},
            llm_metadata={"status": "SUCCESS"},
            rule_version="1.0"
        )
        dict_rep = finding.to_dict()
        self.assertIn("structured_evidence", dict_rep)
        self.assertIn("signals", dict_rep)
        self.assertIn("source_metadata", dict_rep)
        self.assertIn("llm_metadata", dict_rep)
        self.assertEqual(dict_rep["rule_version"], "1.0")

    def test_live_data_failure_returns_data_unavailable(self):
        """Verify live BC failure returns DATA_UNAVAILABLE with zero findings (no synthetic fallback)."""
        mock_client = MagicMock()
        mock_client.get_access_token.return_value = None  # Auth failure
        acquirer = DataAcquirer(mcp_client=mock_client)
        txs, provenance = acquirer.acquire_transactions()
        self.assertEqual(provenance, "DATA_UNAVAILABLE")
        self.assertEqual(len(txs), 0)

    def test_llm_provider_failover_metadata(self):
        """Verify LLMInterpreter returns valid LLMMetadata with Tuple import intact."""
        interpreter = LLMInterpreter()
        interp, meta = interpreter.interpret_candidate("Summary", "System")
        self.assertEqual(meta.status, "UNINTERPRETED")
        self.assertIn("Fallback", meta.provider)

    def test_orchestrator_pipeline_execution(self):
        """Verify end-to-end pipeline: rule -> candidate -> optional LLM -> finding."""
        orchestrator = DataTrustEngineOrchestrator(mcp_client=None)
        res = orchestrator.run_recon()
        self.assertEqual(res["status"], "success")
        self.assertIn("findings", res)
        self.assertTrue(len(res["findings"]) > 0)
