"""
Rule Pack 1 — Posting-Date Policy Rule implementation.
Evaluates transaction posting dates against scope policies, backdating/future-dating thresholds, and close windows.
"""
from datetime import datetime, date
from typing import Optional, Dict, Any
from modules.data_trust_engine.rule_contract import DataTrustRule
from modules.data_trust_engine.candidate import CandidateTransaction
from modules.data_trust_engine.models import DataTrustFinding


class PostingDatePolicyRule(DataTrustRule):
    rule_id = "posting_date_policy"
    rule_version = "1.0"
    rule_pack = "Posting-Date Policy"
    enabled = True

    def assess_eligibility(self, context: Dict[str, Any]) -> str:
        return "ELIGIBLE"

    def evaluate_transaction(self, tx: Dict[str, Any], config: Dict[str, Any], ref_date: Optional[date] = None) -> Optional[DataTrustFinding]:
        policies = config.get("posting_date_policy", {})
        tx_id = tx.get('id') or tx.get('document_no') or '000'

        if not policies:
            return DataTrustFinding(
                id=f"DT-PD-{tx_id}",
                dedup_key=f"Posting-Date Policy:{tx_id}:Insufficient Evidence",
                rule_pack="Posting-Date Policy",
                classification="Insufficient Evidence",
                evidence_strength="INSUFFICIENT",
                severity="INFORMATIONAL",
                signals_fired_count=0,
                evidence_chain=[
                    "Deterministic Rule: PostingDatePolicy scope matching",
                    "Result: Applicable posting-date policy has not been configured for this scope"
                ],
                transaction_details=tx,
                business_impact="Posting date cannot be verified against company policy until policy configuration is defined.",
                recommended_action="Human review required (Configure Posting-Date Policy in Settings)"
            )

        posting_date_str = tx.get("posting_date") or tx.get("date") or tx.get("postingDate")
        if not posting_date_str:
            return DataTrustFinding(
                id=f"DT-PD-{tx_id}",
                dedup_key=f"Posting-Date Policy:{tx_id}:Missing Date",
                rule_pack="Posting-Date Policy",
                classification="Insufficient Evidence",
                evidence_strength="INSUFFICIENT",
                severity="INFORMATIONAL",
                signals_fired_count=0,
                evidence_chain=["Transaction object is missing posting_date field."],
                transaction_details=tx,
                business_impact="Transaction posting date is missing; policy compliance cannot be assessed.",
                recommended_action="Human review required"
            )

        try:
            tx_date = datetime.strptime(str(posting_date_str)[:10], "%Y-%m-%d").date()
        except ValueError:
            return DataTrustFinding(
                id=f"DT-PD-{tx_id}",
                dedup_key=f"Posting-Date Policy:{tx_id}:Invalid Date",
                rule_pack="Posting-Date Policy",
                classification="Insufficient Evidence",
                evidence_strength="INSUFFICIENT",
                severity="INFORMATIONAL",
                signals_fired_count=0,
                evidence_chain=[f"Unparseable date format: '{posting_date_str}'."],
                transaction_details=tx,
                business_impact="Invalid posting date string format.",
                recommended_action="Human review required"
            )

        today = ref_date or date.today()

        user = tx.get("user") or tx.get("user_id") or ""
        doc_type = tx.get("document_type") or ""

        matched_policy = None
        for key, p in policies.items():
            stype = p.get("scope_type", "")
            sval = p.get("scope_value", "")
            if stype == "User" and sval and sval.lower() == user.lower():
                matched_policy = p
                break
            elif stype == "Document Type" and sval and sval.lower() == doc_type.lower():
                matched_policy = p
                break

        if not matched_policy:
            matched_policy = policies.get("company_default") or list(policies.values())[0]

        backdating = matched_policy.get("backdating", {})
        future_dating = matched_policy.get("future_dating", {})
        month_close = matched_policy.get("month_close", {})
        year_close = matched_policy.get("year_close", {})

        diff_days = (tx_date - today).days

        evidence = []
        is_violation = False
        is_approval_required = False
        severity = "INFORMATIONAL"
        classification = "Informational"

        # Backdating check
        if diff_days < 0:
            back_days = abs(diff_days)
            max_back = backdating.get("maximum_days", 7)
            appr_above = backdating.get("approval_required_above_days", 3)
            allowed = backdating.get("allowed", True)

            if not allowed or back_days > max_back:
                is_violation = True
                classification = "Policy Violation"
                severity = "HIGH"
                evidence.append(f"Backdated by {back_days} days (Policy Max Allowed: {max_back} days, Allowed: {allowed}).")
            elif back_days > appr_above:
                is_approval_required = True
                classification = "Policy Violation"
                severity = "MEDIUM"
                evidence.append(f"Backdated by {back_days} days (exceeds approval threshold of {appr_above} days; approval required).")
            else:
                evidence.append(f"Backdated by {back_days} days (within policy allowance of {max_back} days).")

        # Future-dating check
        elif diff_days > 0:
            fut_days = diff_days
            max_fut = future_dating.get("maximum_days", 2)
            allowed = future_dating.get("allowed", True)

            if not allowed or fut_days > max_fut:
                is_violation = True
                classification = "Policy Violation"
                severity = "HIGH"
                evidence.append(f"Future-dated by {fut_days} days (Policy Max Allowed: {max_fut} days, Allowed: {allowed}).")
            else:
                evidence.append(f"Future-dated by {fut_days} days (within policy allowance of {max_fut} days).")

        # Close window check (Month/Year Close)
        for close_cfg, label in [(month_close, "Month Close"), (year_close, "Year Close")]:
            c_date_str = close_cfg.get("close_date")
            if c_date_str:
                try:
                    c_date = datetime.strptime(str(c_date_str)[:10], "%Y-%m-%d").date()
                    adj_window = close_cfg.get("adjustment_window_days", 5)
                    needs_appr = close_cfg.get("approval_required", True)
                    if tx_date <= c_date and 0 <= (today - c_date).days <= adj_window and needs_appr:
                        is_approval_required = True
                        evidence.append(f"Posted into closed period ({label} {c_date_str}) within adjustment window of {adj_window} days. Approval required.")
                except ValueError:
                    pass

        if not is_violation and not is_approval_required:
            return None

        evidence_strength = "HIGH" if is_violation else "MEDIUM"
        impact = f"Posting date date-variance detected ({tx_date} vs reference {today}). Financial reporting period alignment or audit compliance may be impacted."

        return DataTrustFinding(
            id=f"DT-PD-{tx_id}",
            dedup_key=f"Posting-Date Policy:{tx_id}:{classification}",
            rule_pack="Posting-Date Policy",
            classification=classification,
            evidence_strength=evidence_strength,
            severity=severity,
            signals_fired_count=len(evidence),
            evidence_chain=evidence,
            transaction_details=tx,
            business_impact=impact,
            recommended_action="Human review required (never auto-corrected)"
        )

    def evaluate(self, context: Dict[str, Any], config: Dict[str, Any]) -> Optional[CandidateTransaction]:
        finding = self.evaluate_transaction(context, config)
        if finding:
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
                signals=[{"signal": "posting_date_policy", "fired": True}],
                evidence=[{"evidence": item} for item in finding.evidence_chain],
                requires_llm=False
            )
        return None

    def requires_llm(self, candidate: CandidateTransaction) -> bool:
        return False
