import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""
Unit tests for modular Data Trust Engine package (MCP/modules/data_trust_engine/).
Verifies import stability, supporting models, rule contracts, and acquisition state handling.
"""
import unittest
from modules.data_trust import DataTrustEngine, DataTrustFinding, DataTrustConfigManager
from modules.data_trust_engine.models import StructuredEvidence, SourceMetadata, LLMMetadata
from modules.data_trust_engine.candidate import CandidateTransaction
from modules.data_trust_engine.acquisition import DataAcquirer
from modules.data_trust_engine.rules.posting_date import PostingDatePolicyRule
from modules.data_trust_engine.rules.subledger_bypass import SubledgerBypassRule
from modules.data_trust_engine.rules.narration_context import NarrationContextRule


class TestDataTrustModularFramework(unittest.TestCase):

    def test_import_compatibility_façade(self):
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

    def test_candidate_transaction_model(self):
        """Verify CandidateTransaction model produced by rule evaluation."""
        cand = CandidateTransaction(
            candidate_id="CAND-1",
            rule_id="posting_date_policy",
            rule_version="1.0",
            tenant="default_tenant",
            company="CRONUS IN",
            source_record={"id": "TX-1"}
        )
        self.assertEqual(cand.candidate_id, "CAND-1")
        self.assertFalse(cand.requires_llm)

    def test_rule_contracts(self):
        """Verify rule contract instantiation and eligibility assessment."""
        pd_rule = PostingDatePolicyRule()
        self.assertEqual(pd_rule.rule_id, "posting_date_policy")
        self.assertEqual(pd_rule.assess_eligibility({}), "ELIGIBLE")

        sb_rule = SubledgerBypassRule()
        self.assertEqual(sb_rule.rule_id, "subledger_bypass")
        self.assertEqual(sb_rule.assess_eligibility({}), "ELIGIBLE")

        narr_rule = NarrationContextRule()
        self.assertEqual(narr_rule.rule_id, "narration_context_mismatch")
        self.assertEqual(narr_rule.assess_eligibility({"peer_history": []}), "INSUFFICIENT_EVIDENCE")

    def test_data_acquirer_provenance_states(self):
        """Verify acquisition layer mode handling."""
        acquirer = DataAcquirer(mcp_client=None, mode="AUTO")
        txs, state = acquirer.acquire_transactions()
        self.assertEqual(state, "SNAPSHOT_SEED")
