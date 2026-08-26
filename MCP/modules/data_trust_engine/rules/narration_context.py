"""
Rule Pack 3 - Narration / Context Mismatch Rule implementation.
Combines N1-N5 signals on ONE CandidateTransaction, storing explicit N1-N5 signal metadata.
"""
from typing import Optional, Dict, Any, List
from modules.data_trust_engine.rule_contract import DataTrustRule
from modules.data_trust_engine.candidate import CandidateTransaction


class NarrationContextRule(DataTrustRule):
    rule_id = "narration_context_mismatch"
    rule_version = "1.0"
    rule_pack = "Narration / Context Mismatch"
    enabled = True
    minimum_history: int = 20

    def assess_eligibility(self, context: Dict[str, Any]) -> str:
        peer_history = context.get("peer_history", [])
        if len(peer_history) < self.minimum_history:
            return "INSUFFICIENT_EVIDENCE"
        return "ELIGIBLE"

    def evaluate(
        self,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Optional[CandidateTransaction]:
        from modules.data_trust import NarrationContextRulePack
        peer_history = context.get("peer_history", [])
        
        # N1 peer gating check: if peer history < 20, N1 is not eligible
        finding = NarrationContextRulePack.evaluate_candidate(context, peer_history, config)
        if finding:
            if finding.classification == "Insufficient Evidence":
                # Do NOT produce a noisy user-facing business finding for small peer population
                return None

            # Construct explicit N1-N5 signal dictionary list
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
                signals=signals_list,
                evidence=[{"evidence": item} for item in finding.evidence_chain],
                requires_llm=True
            )
        return None

    def requires_llm(self, candidate: CandidateTransaction) -> bool:
        return candidate.eligibility == "ELIGIBLE" and len(candidate.signals) > 0
