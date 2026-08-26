"""
Rule Pack 2 — Generic Subledger Bypass Rule implementation.
Detects direct G/L journal entries posted to control accounts outside permitted source codes.
"""
from typing import Optional, Dict, Any
from modules.data_trust_engine.rule_contract import DataTrustRule
from modules.data_trust_engine.candidate import CandidateTransaction
from modules.data_trust_engine.models import DataTrustFinding


class SubledgerBypassRule(DataTrustRule):
    rule_id = "subledger_bypass"
    rule_version = "1.0"
    rule_pack = "Subledger Bypass"
    enabled = True

    def assess_eligibility(self, context: Dict[str, Any]) -> str:
        return "ELIGIBLE"

    def evaluate_transaction(self, tx: Dict[str, Any], config: Dict[str, Any]) -> Optional[DataTrustFinding]:
        control_accounts = config.get("subledger_control_accounts", [])
        if not control_accounts:
            return None

        account_no = str(tx.get("account_no") or tx.get("account_id") or tx.get("gl_account_no") or tx.get("G_L_Account_No") or "")
        if not account_no:
            return None

        matched_ctrl = None
        for ctrl in control_accounts:
            if str(ctrl.get("account_no")) == account_no:
                matched_ctrl = ctrl
                break

        if not matched_ctrl:
            return None

        source_code = str(tx.get("source_code") or tx.get("source") or tx.get("Source_Code") or tx.get("document_type") or "GENJNL")
        expected_sources = matched_ctrl.get("expected_posting_sources", [])
        direct_allowed = matched_ctrl.get("direct_posting_allowed", False)

        source_matched = any(exp.lower() in source_code.lower() for exp in expected_sources)

        if not source_matched and not direct_allowed:
            subledger_type = matched_ctrl.get("subledger_type", "OTHER")
            account_name = matched_ctrl.get("account_name", f"Account {account_no}")
            amount = tx.get("amount") or tx.get("amount_lcy") or 0.0
            user = tx.get("user") or tx.get("user_id") or "UNKNOWN"
            doc_no = tx.get("document_no") or tx.get("doc_no") or "N/A"
            tx_date = tx.get("posting_date") or tx.get("date") or "N/A"
            tx_id = tx.get('id') or doc_no

            evidence = [
                f"G/L Account {account_no} ({account_name}) is a mapped {subledger_type} Subledger Control Account.",
                f"Transaction posting source '{source_code}' is outside Expected Posting Sources: {expected_sources}.",
                f"Direct Posting Allowed flag is set to False for Account {account_no}.",
                f"Transaction context: Document '{doc_no}', Amount ${float(amount):,.2f}, Posted by User '{user}' on Date '{tx_date}'."
            ]

            reconcil_impact = (
                f"Direct G/L bypass on Control Account {account_no} creates a subledger-to-GL mismatch for {subledger_type} subledger. "
                f"Subledger reports will fail to reconcile with General Ledger balance by ${float(amount):,.2f}."
            )

            return DataTrustFinding(
                id=f"DT-BYPASS-{tx_id}",
                dedup_key=f"Subledger Bypass:{account_no}:{tx_id}",
                rule_pack="Subledger Bypass",
                classification="Policy Violation",
                evidence_strength="HIGH",
                severity="HIGH",
                signals_fired_count=len(evidence),
                evidence_chain=evidence,
                transaction_details=tx,
                business_impact=reconcil_impact,
                recommended_action="Human review required (never auto-corrected)"
            )

        return None

    def evaluate(self, context: Dict[str, Any], config: Dict[str, Any]) -> Optional[CandidateTransaction]:
        finding = self.evaluate_transaction(context, config)
        if finding:
            return CandidateTransaction(
                candidate_id=f"CAND-{finding.id}",
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tenant=config.get("tenant_id", "default_tenant"),
                company=config.get("company_name") or context.get("company_id") or "default_company",
                source_record=context,
                eligibility="ELIGIBLE",
                evidence_strength=finding.evidence_strength,
                classification=finding.classification,
                severity=finding.severity,
                dedup_key=finding.dedup_key,
                signals=[{"signal": "subledger_bypass", "fired": True}],
                evidence=[{"evidence": item} for item in finding.evidence_chain],
                requires_llm=False
            )
        return None

    def requires_llm(self, candidate: CandidateTransaction) -> bool:
        return False
