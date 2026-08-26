"""
Rule Pack 4 - Payment Timing & Due-Date Compliance Rule implementation.
Evaluates customer and vendor settled invoice transactions deterministically (no LLM, no BC writes).
Computes settlement timing, discount windows, sequence anomalies, and company-scoped prior baselines.
"""
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from modules.data_trust_engine.rule_contract import DataTrustRule
from modules.data_trust_engine.candidate import CandidateTransaction


class PaymentTimingRule(DataTrustRule):
    rule_id = "PAYMENT_TIMING"
    rule_version = "1.0"
    rule_pack = "Payment Timing"
    enabled = True

    def _parse_date(self, val: Any) -> Optional[date]:
        if not val:
            return None
        if isinstance(val, date):
            return val
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
            except Exception:
                try:
                    return datetime.strptime(val[:10], "%Y-%m-%d").date()
                except Exception:
                    return None
        return None

    def assess_eligibility(self, context: Dict[str, Any]) -> str:
        doc_type = str(context.get("document_type") or context.get("dvleDocumentType") or context.get("dcleDocumentType") or "Invoice")
        if "Invoice" not in doc_type:
            return "INELIGIBLE"

        # Check application resolution (single application event MVP requirement)
        app_resolved = context.get("application_resolved", True)
        app_count = context.get("application_count", 1)
        if not app_resolved or app_count > 1:
            return "INSUFFICIENT_EVIDENCE"

        due_dt = self._parse_date(context.get("due_date") or context.get("vleDueDate") or context.get("cleDueDate"))
        pay_dt = self._parse_date(context.get("payment_date") or context.get("dvlePostingDate") or context.get("dclePostingDate"))

        if not due_dt or not pay_dt:
            return "INSUFFICIENT_EVIDENCE"

        return "ELIGIBLE"

    def evaluate(
        self,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Optional[CandidateTransaction]:
        eligibility = self.assess_eligibility(context)
        if eligibility == "INELIGIBLE":
            return None

        tenant = str(context.get("environment_id") or config.get("tenant_id") or "default_tenant")
        company = str(context.get("company_id") or config.get("company_name") or "CRONUS IN")
        ledger_type = str(context.get("ledger_type") or "VENDOR").upper()
        account_no = str(context.get("account_no") or context.get("vendor_no") or context.get("customer_no") or "UNKNOWN")

        if eligibility == "INSUFFICIENT_EVIDENCE":
            # Return INSUFFICIENT_EVIDENCE diagnostic candidate
            return CandidateTransaction(
                candidate_id=f"CAND-PT-INSUFF-{context.get('id', 'TX')}",
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tenant=tenant,
                company=company,
                source_record=context,
                eligibility="INSUFFICIENT_EVIDENCE",
                signals=[{"signal_code": "INSUFFICIENT_EVIDENCE", "name": "Required Settlement Evidence Missing", "fired": True}],
                evidence=[{"evidence": "Settlement application relationship is unresolved, multi-part, or required dates are missing."}],
                requires_llm=False
            )

        due_dt = self._parse_date(context.get("due_date") or context.get("vleDueDate") or context.get("cleDueDate"))
        pay_dt = self._parse_date(context.get("payment_date") or context.get("dvlePostingDate") or context.get("dclePostingDate"))
        doc_dt = self._parse_date(context.get("document_date") or context.get("posting_date") or context.get("vleDocumentDate"))
        disc_dt = self._parse_date(context.get("payment_discount_date"))

        days_to_payment = (pay_dt - due_dt).days

        pt_cfg = config.get("payment_timing", {})
        early_cfg = pt_cfg.get("early_payment", {})
        late_cfg = pt_cfg.get("late_payment", {})
        disc_cfg = pt_cfg.get("discount", {})
        hist_cfg = pt_cfg.get("historical_pattern", {})

        min_history = hist_cfg.get("minimum_history", 20)
        unusual_dev_days = hist_cfg.get("unusual_deviation_days", 7)

        # Calculate Company + Ledger Type + Account scoped historical baseline (CURRENT TRANSACTION EXCLUDED)
        peer_history = context.get("peer_history", [])
        qualifying_prior_days: List[int] = []

        for prior in peer_history:
            p_due = self._parse_date(prior.get("due_date"))
            p_pay = self._parse_date(prior.get("payment_date"))
            if p_due and p_pay:
                qualifying_prior_days.append((p_pay - p_due).days)

        prior_count = len(qualifying_prior_days)
        has_adequate_history = (prior_count >= min_history)
        hist_avg_days = (sum(qualifying_prior_days) / prior_count) if has_adequate_history else 0.0

        signals: List[Dict[str, Any]] = []
        evidence_chain: List[Dict[str, Any]] = []

        # Signal P1: Early Payment
        p1_fired = (days_to_payment < 0)
        signals.append({
            "signal_code": "P1",
            "name": "Early Payment",
            "fired": p1_fired,
            "days_early": abs(days_to_payment) if p1_fired else 0
        })
        if p1_fired:
            evidence_chain.append({"evidence": f"[P1 Early Payment] Payment occurred {abs(days_to_payment)} days prior to contractual due date ({due_dt.isoformat()})."})

        # Signal P2: Late Payment
        p2_fired = (days_to_payment > 0)
        signals.append({
            "signal_code": "P2",
            "name": "Late Payment",
            "fired": p2_fired,
            "days_late": days_to_payment if p2_fired else 0
        })
        if p2_fired:
            evidence_chain.append({"evidence": f"[P2 Late Payment] Settlement occurred {days_to_payment} days after contractual due date ({due_dt.isoformat()})."})

        # Signal P3: Missed Payment Discount
        p3_fired = False
        if disc_cfg.get("enabled", True) and disc_dt:
            if pay_dt > disc_dt:
                p3_fired = True
                evidence_chain.append({"evidence": f"[P3 Missed Payment Discount] Payment date ({pay_dt.isoformat()}) occurred after configured discount date ({disc_dt.isoformat()}); potential discount opportunity may have been missed."})
        signals.append({
            "signal_code": "P3",
            "name": "Payment Discount Missed",
            "fired": p3_fired
        })

        # Signal P4: Repeated Early Behavioral Pattern
        p4_fired = (days_to_payment < 0 and has_adequate_history and hist_avg_days < 0)
        signals.append({
            "signal_code": "P4",
            "name": "Repeated Early Payment Pattern",
            "fired": p4_fired,
            "historical_avg_days": round(hist_avg_days, 1) if has_adequate_history else None
        })

        # Signal P5: Repeated Late Behavioral Pattern
        p5_fired = (days_to_payment > 0 and has_adequate_history and hist_avg_days > 0)
        signals.append({
            "signal_code": "P5",
            "name": "Repeated Late Payment Pattern",
            "fired": p5_fired,
            "historical_avg_days": round(hist_avg_days, 1) if has_adequate_history else None
        })

        # Signal P6: Settlement Date Sequence Anomaly
        p6_fired = False
        if doc_dt and pay_dt < doc_dt:
            p6_fired = True
            evidence_chain.append({"evidence": f"[P6 Sequence Anomaly] Settlement posting date ({pay_dt.isoformat()}) precedes invoice document date ({doc_dt.isoformat()})."})
        signals.append({
            "signal_code": "P6",
            "name": "Settlement Date Sequence Anomaly",
            "fired": p6_fired
        })

        # Signal P7: Unusual Timing Deviation
        p7_fired = False
        if has_adequate_history:
            dev = abs(days_to_payment - hist_avg_days)
            if dev >= unusual_dev_days:
                p7_fired = True
                evidence_chain.append({"evidence": f"[P7 Unusual Timing Deviation] Settlement timing ({days_to_payment} days) deviates by {round(dev, 1)} days from prior company baseline average ({round(hist_avg_days, 1)} days across {prior_count} prior settlements)."})
        signals.append({
            "signal_code": "P7",
            "name": "Unusual Payment Timing",
            "fired": p7_fired,
            "baseline_avg": round(hist_avg_days, 1) if has_adequate_history else None,
            "observed_days": days_to_payment
        })

        # Classification Determination
        classification = "Informational"
        late_policy_days = late_cfg.get("policy_violation_threshold_days")
        
        if late_policy_days and days_to_payment >= late_policy_days:
            classification = "Policy Violation"
        elif p6_fired:
            classification = "Potential Data Error"
        elif p7_fired:
            classification = "Anomaly"
        elif p1_fired or p2_fired or p3_fired:
            classification = "Informational"

        baseline_ref = {
            "company_id": company,
            "ledger_type": ledger_type,
            "account_no": account_no,
            "prior_qualifying_count": prior_count,
            "historical_average_days": round(hist_avg_days, 1) if has_adequate_history else None
        }

        cand_id = f"CAND-PT-{context.get('id', 'TX')}"
        return CandidateTransaction(
            candidate_id=cand_id,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            tenant=tenant,
            company=company,
            source_record=context,
            eligibility="ELIGIBLE",
            baseline_reference=baseline_ref,
            signals=signals,
            evidence=evidence_chain,
            requires_llm=False
        )

    def requires_llm(self, candidate: CandidateTransaction) -> bool:
        # 100% Deterministic Rule Pack — Zero LLM calls
        return False
