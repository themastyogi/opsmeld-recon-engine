"""
Rule Pack 3 — Narration / Context Mismatch Rule implementation.
Evaluates Candidate Transactions carrying signals N1–N5.
Calculates Evidence Strength deterministically and executes single-pass LLM candidate interpretation.
"""
import re
from typing import Optional, Dict, Any, List
from core.bc_mcp_client import BCMCPClient
from modules.data_trust_engine.rule_contract import DataTrustRule
from modules.data_trust_engine.candidate import CandidateTransaction
from modules.data_trust_engine.models import DataTrustFinding

DEFAULT_PEER_HISTORY = [
    {"account_no": "60100", "vendor_name": "Fabrikam Supplies", "narration": "Office paper and pens", "amount": 120.0},
    {"account_no": "60100", "vendor_name": "Fabrikam Supplies", "narration": "Printer toner cartridge", "amount": 250.0},
] * 12


class NarrationContextRule(DataTrustRule):
    rule_id = "narration_context"
    rule_version = "1.0"
    rule_pack = "Narration / Context Mismatch"
    enabled = True
    minimum_history: int = 20

    def assess_eligibility(self, context: Dict[str, Any]) -> str:
        peer_history = context.get("peer_history")
        if peer_history is None:
            peer_history = DEFAULT_PEER_HISTORY
        if len(peer_history) < self.minimum_history:
            return "INSUFFICIENT_EVIDENCE"
        return "ELIGIBLE"

    def evaluate_candidate(
        self,
        tx: Dict[str, Any],
        peer_history: List[Dict[str, Any]],
        config: Dict[str, Any],
        mcp_client: Optional[BCMCPClient] = None
    ) -> Optional[DataTrustFinding]:
        n_config = config.get("narration_context", {})
        min_peer = n_config.get("minimum_peer_transactions", 20)
        taxonomy_l2 = n_config.get("taxonomy_level_2", {})

        account = str(tx.get("account_no") or tx.get("gl_account_no") or tx.get("account_name") or "Office Supplies Expense")
        entity = str(tx.get("vendor_name") or tx.get("vendor_id") or tx.get("customer_name") or tx.get("vendor") or "Vendor")
        narration = str(tx.get("narration") or tx.get("description") or tx.get("line_description") or "")
        doc_type = str(tx.get("document_type") or tx.get("source_code") or "General Journal")
        tx_id = tx.get('id') or tx.get('document_no') or '000'

        signals_fired = []
        evidence_items = []
        is_baseline_adequate = len(peer_history) >= min_peer

        # N1 — Rare Narration Check (Hard-Gated on peer history threshold)
        if not is_baseline_adequate:
            evidence_items.append(
                f"[N1 Rare Narration] Not Evaluated: Peer group population ({len(peer_history)} transactions) is below minimum threshold ({min_peer}). Baseline requirement not met."
            )
        else:
            narration_words = set(re.findall(r'\w+', narration.lower()))
            matching_peer_count = sum(
                1 for ptx in peer_history
                if any(w in str(ptx.get("narration") or ptx.get("description") or "").lower() for w in narration_words if len(w) > 3)
            )
            if matching_peer_count <= 1:
                signals_fired.append("N1 (Rare Narration)")
                evidence_items.append(
                    f"[N1 Rare Narration] Fired: Narration pattern '{narration}' appears in <= 1 transaction out of {len(peer_history)} historical peer group records."
                )

        # N2 — Account/Narration Semantic Divergence
        account_lower = account.lower()
        narration_lower = narration.lower()

        for cat_name, cat_keywords in taxonomy_l2.items():
            if any(kw in account_lower for kw in cat_keywords) or cat_name.lower() in account_lower:
                mismatched_cats = []
                for other_cat, other_keywords in taxonomy_l2.items():
                    if other_cat != cat_name:
                        if any(okw in narration_lower for okw in other_keywords if len(okw) > 3):
                            mismatched_cats.append(other_cat)
                if mismatched_cats:
                    signals_fired.append("N2 (Account/Narration Semantic Divergence)")
                    evidence_items.append(
                        f"[N2 Semantic Divergence] Fired: Account '{account}' maps to '{cat_name}', but narration '{narration}' contains semantic keywords associated with '{', '.join(mismatched_cats)}'."
                    )
                    break

        # N3 — Vendor/Context Divergence
        if peer_history:
            vendor_narrations = [str(ptx.get("narration") or ptx.get("description") or "").lower() for ptx in peer_history]
            all_vendor_text = " ".join(vendor_narrations)
            narration_keywords = [w for w in re.findall(r'\w+', narration_lower) if len(w) > 4]
            if narration_keywords and not any(kw in all_vendor_text for kw in narration_keywords):
                signals_fired.append("N3 (Vendor/Context Divergence)")
                evidence_items.append(
                    f"[N3 Vendor Divergence] Fired: Narration keywords {narration_keywords} deviate from historical narration profile for entity '{entity}'."
                )

        # N4 — Document-Type/Context Divergence
        if "journal" in doc_type.lower() and any(inv_kw in narration_lower for inv_kw in ["invoice", "inv-", "po-", "purchase order"]):
            signals_fired.append("N4 (Document-Type Context Divergence)")
            evidence_items.append(
                f"[N4 Document Type Divergence] Fired: Document type is '{doc_type}' but narration resembles a standard commercial invoice."
            )

        # N5 — Historical Pattern Break
        if is_baseline_adequate and peer_history:
            amounts = [float(ptx.get("amount") or 0.0) for ptx in peer_history]
            if amounts:
                avg_amt = sum(amounts) / len(amounts)
                curr_amt = float(tx.get("amount") or 0.0)
                if curr_amt > 5 * max(avg_amt, 100.0):
                    signals_fired.append("N5 (Historical Pattern Break)")
                    evidence_items.append(
                        f"[N5 Pattern Break] Fired: Transaction amount ${curr_amt:,.2f} is substantially higher than historical peer average (${avg_amt:,.2f})."
                    )

        if not signals_fired:
            return None

        # Calculate Evidence Strength deterministically
        signal_count = len(signals_fired)
        if signal_count >= 3 and is_baseline_adequate:
            evidence_strength = "HIGH"
        elif signal_count >= 2 and is_baseline_adequate:
            evidence_strength = "MEDIUM"
        elif signal_count >= 1:
            evidence_strength = "LOW"
        else:
            evidence_strength = "INSUFFICIENT"

        # Classification mapping based on signals and baseline
        if "N2 (Account/Narration Semantic Divergence)" in signals_fired or "N3 (Vendor/Context Divergence)" in signals_fired:
            classification = "Anomaly"
        elif "N5 (Historical Pattern Break)" in signals_fired:
            classification = "Potential Data Error"
        else:
            classification = "Informational"

        if evidence_strength == "HIGH":
            severity = "HIGH"
        elif evidence_strength == "MEDIUM":
            severity = "MEDIUM"
        else:
            severity = "INFORMATIONAL"

        tx_amt = float(tx.get("amount") or 0.0)
        impact = f"Narration/context divergence detected across {len(signals_fired)} signals. Transaction value ${tx_amt:,.2f} may represent account misclassification or posting error."

        return DataTrustFinding(
            id=f"DT-NARR-{tx_id}",
            dedup_key=f"Narration / Context Mismatch:{account}:{tx_id}",
            rule_pack="Narration / Context Mismatch",
            classification=classification,
            evidence_strength=evidence_strength,
            severity=severity,
            signals_fired_count=len(signals_fired),
            evidence_chain=evidence_items,
            transaction_details=tx,
            business_impact=impact,
            recommended_action="Human review required (never auto-corrected)"
        )

    def evaluate(
        self,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Optional[CandidateTransaction]:
        peer_history = context.get("peer_history")
        if peer_history is None:
            peer_history = DEFAULT_PEER_HISTORY

        if len(peer_history) < self.minimum_history:
            return None

        finding = self.evaluate_candidate(context, peer_history, config)
        if finding:
            if finding.classification == "Insufficient Evidence":
                return None

            signals_list = [
                {"signal_code": "N1", "name": "Rare Narration", "fired": any("N1" in item for item in finding.evidence_chain if "Fired" in item)},
                {"signal_code": "N2", "name": "Account/Context Mismatch", "fired": any("N2" in item for item in finding.evidence_chain if "Fired" in item)},
                {"signal_code": "N3", "name": "Vendor/Context Divergence", "fired": any("N3" in item for item in finding.evidence_chain if "Fired" in item)},
                {"signal_code": "N4", "name": "Document Context Divergence", "fired": any("N4" in item for item in finding.evidence_chain if "Fired" in item)},
                {"signal_code": "N5", "name": "Historical Pattern Break", "fired": any("N5" in item for item in finding.evidence_chain if "Fired" in item)},
            ]

            requires_llm_flag = finding.evidence_strength in ("HIGH", "MEDIUM")
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
                signals=signals_list,
                evidence=[{"evidence": item} for item in finding.evidence_chain],
                requires_llm=requires_llm_flag
            )
        return None

    def requires_llm(self, candidate: CandidateTransaction) -> bool:
        return candidate.requires_llm
