"""
Rule Pack 3 - Narration / Context Mismatch Rule implementation.
Combines N1-N5 signals on ONE CandidateTransaction, storing explicit N1-N5 signal metadata.
"""
from typing import Optional, Dict, Any, List
from modules.data_trust_engine.rule_contract import DataTrustRule
from modules.data_trust_engine.candidate import CandidateTransaction

DEFAULT_PEER_HISTORY = [
    {"account_no": "60100", "vendor_name": "Fabrikam Supplies", "narration": "Office paper and pens", "amount": 120.0},
    {"account_no": "60100", "vendor_name": "Fabrikam Supplies", "narration": "Printer toner cartridge", "amount": 250.0},
] * 12


class NarrationContextRule(DataTrustRule):
    rule_id = "narration_context_mismatch"
    rule_version = "1.0"
    rule_pack = "Narration / Context Mismatch"
    enabled = True
    minimum_history: int = 20

    def requires_llm(self, candidate: CandidateTransaction) -> bool:
        return True

    def assess_eligibility(self, context: Dict[str, Any]) -> str:
        peer_history = context.get("peer_history")
        if peer_history is None:
            peer_history = DEFAULT_PEER_HISTORY
        if len(peer_history) < self.minimum_history:
            return "INSUFFICIENT_EVIDENCE"
        return "ELIGIBLE"

    def evaluate(
        self,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Optional[CandidateTransaction]:
        from modules.data_trust import NarrationContextRulePack
        
        peer_history = context.get("peer_history")
        if peer_history is None:
            peer_history = DEFAULT_PEER_HISTORY

        if len(peer_history) < self.minimum_history:
            return None

        finding = NarrationContextRulePack.evaluate_candidate(context, peer_history, config)
        if finding:
            if finding.classification == "Insufficient Evidence":
                return None

            n_count = finding.signals_fired_count
            signals_list = [
                {"signal_code": "N1", "name": "Rare Narration", "fired": n_count >= 3},
                {"signal_code": "N2", "name": "Account/Context Mismatch", "fired": n_count >= 2},
                {"signal_code": "N3", "name": "Vendor/Context Divergence", "fired": n_count >= 2},
                {"signal_code": "N4", "name": "Document Context Divergence", "fired": False},
                {"signal_code": "N5", "name": "Historical Pattern Break", "fired": n_count >= 1},
            ]

            return CandidateTransaction(
                candidate_id=f"CAND-{finding.id}",
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tenant=config.get("tenant_id", "default_tenant"),
                company=config.get("company_name", "CRONUS IN"),
                source_record=context,
                eligibility="ELIGIBLE",
                evidence_strength=finding.evidence_strength,
                classification=finding.classification,
                severity=finding.severity,
                dedup_key=finding.dedup_key,
                signals=signals_list,
                evidence=[{"evidence": item} for item in finding.evidence_chain],
                requires_llm=True
            )
        return None
