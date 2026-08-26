"""
Rule Pack 1 - Posting-Date Policy Rule implementation.
"""
from typing import Optional, Dict, Any
from modules.data_trust_engine.rule_contract import DataTrustRule
from modules.data_trust_engine.candidate import CandidateTransaction


class PostingDatePolicyRule(DataTrustRule):
    rule_id = "posting_date_policy"
    rule_version = "1.0"
    rule_pack = "Posting-Date Policy"
    enabled = True

    def assess_eligibility(self, context: Dict[str, Any]) -> str:
        return "ELIGIBLE"

    def evaluate(self, context: Dict[str, Any], config: Dict[str, Any]) -> Optional[CandidateTransaction]:
        from modules.data_trust import PostingDateRulePack
        finding = PostingDateRulePack.evaluate_transaction(context, config)
        if finding:
            return CandidateTransaction(
                candidate_id=f"CAND-{finding.id}",
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tenant=config.get("tenant_id", "default_tenant"),
                company=config.get("company_name", "CRONUS IN"),
                source_record=context,
                eligibility="ELIGIBLE",
                signals=[{"signal": "posting_date_policy", "fired": True}],
                evidence=[{"evidence": item} for item in finding.evidence_chain],
                requires_llm=False
            )
        return None

    def requires_llm(self, candidate: CandidateTransaction) -> bool:
        return False
