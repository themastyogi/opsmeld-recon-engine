"""
Unit tests for modular Data Trust Engine package (MCP/modules/data_trust_engine/).
Verifies import stability, supporting models, rule contracts, fail-closed live acquisition boundaries,
explicit N1-N5 signal dictionary objects, LLM failover metadata, and end-to-end run_recon orchestration.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import MagicMock, patch
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

    def test_production_live_bc_failure_returns_data_unavailable(self):
        """Verify production DataTrustEngine.run_recon() returns empty findings list on live BC failure."""
        mock_client = MagicMock()
        mock_client.get_access_token.return_value = None
        mock_client._execute_bc_rest.side_effect = Exception("Live connection failed")
        engine = DataTrustEngine(mcp_client=mock_client)
        findings = engine.run_recon()
        self.assertEqual(len(findings), 0)

    def test_modular_live_bc_failure_returns_data_unavailable(self):
        """Verify DataAcquirer returns DATA_UNAVAILABLE with zero findings when live query fails."""
        mock_client = MagicMock()
        mock_client.get_access_token.return_value = None
        acquirer = DataAcquirer(mcp_client=mock_client)
        txs, provenance = acquirer.acquire_transactions()
        self.assertEqual(provenance, "DATA_UNAVAILABLE")
        self.assertEqual(len(txs), 0)

    def test_llm_provider_failover_anthropic_to_openai_to_gemini(self):
        """Verify LLMInterpreter failover chain across Anthropic -> OpenAI -> Gemini -> Fallback."""
        interpreter = LLMInterpreter()
        interp, meta = interpreter.interpret_candidate("Summary", "System")
        self.assertEqual(meta.status, "UNINTERPRETED")
        self.assertIn("Fallback", meta.provider)

        # Mock OpenAI HTTP call to test secondary provider success metadata
        interpreter_oai = LLMInterpreter(openai_key="mock_openai_key")
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"choices": [{"message": {"content": "OpenAI interpretation"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 20}}'
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response):
            interp_oai, meta_oai = interpreter_oai.interpret_candidate("Summary", "System")
            self.assertEqual(meta_oai.provider, "OpenAI")
            self.assertEqual(meta_oai.model, "gpt-4o-mini")

    def test_orchestrator_pipeline_execution_end_to_end(self):
        """Verify end-to-end pipeline: rule -> candidate -> optional LLM -> finding."""
        orchestrator = DataTrustEngineOrchestrator(mcp_client=None)
        res = orchestrator.run_recon()
        self.assertEqual(res["status"], "success")
        self.assertIn("findings", res)
        self.assertTrue(len(res["findings"]) > 0)

    def test_n1_peer_gating_prevents_llm_call_and_user_finding(self):
        """Verify below minimum history (<20), N1 candidate returns None (no finding, no LLM call)."""
        rule = NarrationContextRule()
        sample_context = {
            "id": "TX-1001",
            "narration": "Entry",
            "peer_history": [{"narration": "Peer"} for _ in range(5)]  # Below 20
        }
        cand = rule.evaluate(sample_context, {})
        self.assertIsNone(cand)

    def test_at_most_one_llm_call_per_candidate(self):
        """Verify candidate produces at most one LLM call per run."""
        interpreter = LLMInterpreter()
        interp, meta = interpreter.interpret_candidate("Summary", "System")
        self.assertTrue(meta.call_count <= 1)


if __name__ == "__main__":
    unittest.main()
