"""
Rule Pack 4 — Inventory Costing & Valuation Integrity Rule Implementation.
Evaluates Candidate Transactions carrying signals C1–C10.
Uses CostBaselineResolver for deterministic hierarchical baseline selection and cost driver analysis.
"""

from typing import Any, Dict, List, Optional
from core.bc_mcp_client import BCMCPClient
from modules.data_trust_engine.rule_contract import DataTrustRule
from modules.data_trust_engine.candidate import CandidateTransaction
from modules.data_trust_engine.models import DataTrustFinding
from modules.data_trust_engine.baseline_resolver import CostBaselineResolver


def normalize_boolean(val: Any) -> bool:
    """Normalizes string 'false', '0', 0, False, None to boolean False."""
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val != 0)
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "y", "t")


class InventoryCostingRule(DataTrustRule):
    rule_id = "INVENTORY_COSTING"
    rule_version = "1.0"
    rule_pack = "Inventory Costing"
    required_data_source = "INVENTORY_COST_TRANSACTIONS"
    enabled = True
    requires_llm = False

    def __init__(self, minimum_history: int = 20):
        self.minimum_history = minimum_history
        self.resolver = CostBaselineResolver(minimum_history=minimum_history)

    def assess_eligibility(self, context: Dict[str, Any]) -> str:
        cost = float(context.get("cost_per_unit") or context.get("cost_amount_actual") or 0.0)
        qty = float(context.get("quantity") or 0.0)
        curr = context.get("currency_code")
        if not curr:
            return "INSUFFICIENT_EVIDENCE"
        if cost <= 0 and qty <= 0:
            return "INSUFFICIENT_EVIDENCE"
        return "ELIGIBLE"

    def evaluate_candidate(
        self,
        tx: Dict[str, Any],
        historical_txs: List[Dict[str, Any]],
        config: Dict[str, Any],
        mcp_client: Optional[BCMCPClient] = None
    ) -> Optional[DataTrustFinding]:
        cost_config = config.get("inventory_costing", {})
        if not cost_config.get("enabled", True):
            return None

        # Step 1: Use CostBaselineResolver once per candidate
        res = self.resolver.resolve_baseline(tx, historical_txs, config)
        primary = res.get("primary", {})
        peer = res.get("peer", {})
        supporting = res.get("supporting", [])

        if res.get("status") == "INSUFFICIENT_EVIDENCE" or primary.get("median") is None:
            # Baseline insufficient to form a finding
            return None

        curr_cost = float(tx.get("cost_per_unit") or 0.0)
        base_median = float(primary.get("median") or 1.0)
        dev_pct = ((curr_cost - base_median) / base_median) * 100.0 if base_median > 0 else 0.0

        signals_fired = []
        evidence_chain = []
        signals_list = []

        rel_thresh = float(cost_config.get("historical_pattern", {}).get("relative_change_percent", 25.0))

        # C1 — Sudden Unit Cost Movement
        c1_fired = abs(dev_pct) >= rel_thresh
        signals_list.append({"signal_code": "C1", "name": "Sudden Unit Cost Movement", "fired": c1_fired})
        if c1_fired:
            signals_fired.append("C1 (Sudden Unit Cost Movement)")
            evidence_chain.append(
                f"[C1 Sudden Unit Cost Movement] Fired: Unit cost ${curr_cost:,.2f} deviates by {dev_pct:+.1f}% from selected {primary['level']} baseline median (${base_median:,.2f})."
            )

        # C2 — Unusual Purchase Cost Variance
        purch_act = float(tx.get("purchase_amount_actual") or 0.0)
        purch_exp = float(tx.get("purchase_amount_expected") or 0.0)
        purch_thresh = float(cost_config.get("expected_actual", {}).get("relative_variance_percent", 20.0)) / 100.0
        c2_fired = (purch_act > 0 and purch_exp > 0 and abs(purch_act - purch_exp) / max(purch_exp, 1.0) >= purch_thresh)
        signals_list.append({"signal_code": "C2", "name": "Unusual Purchase Cost Variance", "fired": c2_fired})
        if c2_fired:
            signals_fired.append("C2 (Unusual Purchase Cost Variance)")
            evidence_chain.append(
                f"[C2 Purchase Cost Variance] Fired: Purchase actual ${purch_act:,.2f} vs expected ${purch_exp:,.2f} variance >= {int(purch_thresh*100)}%."
            )

        # C3 — Expected-to-Actual Cost Change (Gated by Materiality Threshold)
        exp_act_thresh = float(cost_config.get("expected_actual", {}).get("relative_variance_percent", 20.0))
        act_cost = float(tx.get("cost_amount_actual") or 0.0)
        exp_cost = float(tx.get("cost_amount_expected") or 0.0)
        c3_variance_pct = (abs(act_cost - exp_cost) / max(exp_cost, 1.0) * 100.0) if exp_cost > 0 else 0.0
        c3_fired = (exp_cost > 0 and act_cost > 0 and c3_variance_pct >= exp_act_thresh)
        signals_list.append({"signal_code": "C3", "name": "Expected-to-Actual Cost Change", "fired": c3_fired})
        if c3_fired:
            signals_fired.append("C3 (Expected-to-Actual Cost Change)")
            evidence_chain.append(
                f"[C3 Expected-to-Actual] Fired: Expected cost ${exp_cost:,.2f} transitioned to actual cost ${act_cost:,.2f} (variance {c3_variance_pct:.1f}% >= {exp_act_thresh:.0f}%)."
            )

        # C4 — Cost Adjustment Event (Boolean Normalized)
        c4_fired = normalize_boolean(tx.get("adjustment"))
        signals_list.append({"signal_code": "C4", "name": "Cost Adjustment Event", "fired": c4_fired})
        if c4_fired:
            signals_fired.append("C4 (Cost Adjustment Event)")
            evidence_chain.append(
                "[C4 Cost Adjustment] Fired: Transaction represents a Business Central cost adjustment entry."
            )

        # C5 — Revaluation / Partial Revaluation (Boolean Normalized)
        c5_fired = normalize_boolean(tx.get("partial_revaluation"))
        signals_list.append({"signal_code": "C5", "name": "Revaluation Event", "fired": c5_fired})
        if c5_fired:
            signals_fired.append("C5 (Revaluation Event)")
            evidence_chain.append(
                "[C5 Revaluation] Fired: Transaction contains partial or full inventory revaluation."
            )

        # C6 — Item Charge / Landed Cost Impact
        item_charge = str(tx.get("item_charge_no") or "")
        c6_fired = bool(item_charge)
        signals_list.append({"signal_code": "C6", "name": "Item Charge Landed Cost Impact", "fired": c6_fired})
        if c6_fired:
            signals_fired.append("C6 (Item Charge Impact)")
            evidence_chain.append(
                f"[C6 Item Charge] Fired: Cost movement associated with landed item charge '{item_charge}'."
            )

        # C7 — Historical Cost Pattern Break
        c7_fired = abs(dev_pct) >= rel_thresh
        signals_list.append({"signal_code": "C7", "name": "Historical Cost Pattern Break", "fired": c7_fired})
        if c7_fired:
            signals_fired.append("C7 (Historical Cost Pattern Break)")
            evidence_chain.append(
                f"[C7 Pattern Break] Fired: Current unit cost ${curr_cost:,.2f} materially deviates ({dev_pct:+.1f}%) from historical baseline."
            )

        # Cost Driver Analysis: Deterministic Evaluation
        known_driver = "No identified driver"
        driver_explained = False

        if c6_fired:
            known_driver = f"Item Charge ({item_charge})"
            driver_explained = True
        elif c4_fired:
            known_driver = "Cost Adjustment"
            driver_explained = True
        elif c5_fired:
            known_driver = "Inventory Revaluation"
            driver_explained = True
        elif c2_fired:
            known_driver = "Purchase Price Change"
            driver_explained = True
        elif c3_fired and not c1_fired:
            known_driver = "Expected-to-Actual Transition"
            driver_explained = True

        # C8 — Unexplained Cost Movement
        c8_fired = (abs(dev_pct) >= rel_thresh) and not driver_explained
        signals_list.append({"signal_code": "C8", "name": "Unexplained Cost Movement", "fired": c8_fired})
        if c8_fired:
            signals_fired.append("C8 (Unexplained Cost Movement)")
            evidence_chain.append(
                f"[C8 Unexplained Movement] Fired: Unit cost deviation ({dev_pct:+.1f}%) is material and unsupported by identified Business Central costing drivers."
            )

        # C9 — Cost / Quantity Inconsistency
        qty = float(tx.get("quantity") if tx.get("quantity") is not None else 0.0)
        c9_fired = (qty == 0.0 and act_cost > 0.0)
        signals_list.append({"signal_code": "C9", "name": "Cost/Quantity Inconsistency", "fired": c9_fired})
        if c9_fired:
            signals_fired.append("C9 (Cost/Quantity Inconsistency)")
            evidence_chain.append(
                "[C9 Inconsistency] Fired: Zero quantity with positive actual cost amount detected."
            )

        # C10 — Cost-to-G/L Posting Difference
        cost_gl = float(tx.get("cost_posted_to_gl") or act_cost)
        c10_fired = (act_cost > 0 and cost_gl != act_cost)
        signals_list.append({"signal_code": "C10", "name": "Cost-to-G/L Posting Difference", "fired": c10_fired})
        if c10_fired:
            signals_fired.append("C10 (Cost-to-G/L Difference)")
            evidence_chain.append(
                f"[C10 G/L Difference] Fired: Value entry cost (${act_cost:,.2f}) differs from posted G/L amount (${cost_gl:,.2f})."
            )

        if not any(s["fired"] for s in signals_list):
            return None

        # Step 6: Peer Movement Attenuation Status Check
        peer_attenuation_status = peer.get("peer_attenuation_status", "UNATTENUATED")
        is_peer_attenuated = (peer_attenuation_status == "ATTENUATED")
        if is_peer_attenuated:
            evidence_chain.append(
                "[Peer Attenuation] Broad market/item movement detected (peer shift >= 20%). Anomaly severity attenuated to MEDIUM."
            )

        # Classification & Evidence Strength Selection
        if c8_fired and not is_peer_attenuated:
            classification = "Potential Data Error"
            evidence_strength = "HIGH"
            severity = "HIGH"
        elif c8_fired and is_peer_attenuated:
            classification = "Anomaly"
            evidence_strength = "MEDIUM"
            severity = "MEDIUM"
        elif driver_explained:
            classification = "Informational"
            evidence_strength = "LOW"
            severity = "INFORMATIONAL"
        elif c1_fired or c7_fired:
            classification = "Anomaly"
            evidence_strength = "MEDIUM"
            severity = "MEDIUM"
        else:
            classification = "Informational"
            evidence_strength = "LOW"
            severity = "INFORMATIONAL"

        item_no = str(tx.get("item_no") or "ITEM")
        tx_id = str(tx.get("id") or tx.get("item_ledger_entry_no") or "000")

        impact = f"Inventory costing movement ({dev_pct:+.1f}%) detected for Item '{item_no}'. Identified driver: {known_driver}."

        clean_tx = {k: v for k, v in tx.items() if k != "historical_transactions"}
        return DataTrustFinding(
            id=f"DT-COST-{tx_id}",
            dedup_key=f"Inventory Costing:{item_no}:{tx_id}",
            rule_pack="Inventory Costing",
            classification=classification,
            evidence_strength=evidence_strength,
            severity=severity,
            signals_fired_count=len(signals_fired),
            evidence_chain=evidence_chain,
            transaction_details=clean_tx,
            business_impact=impact,
            recommended_action="Human review required (never auto-corrected)",
            data_source=tx.get("provenance_state", "LIVE_BUSINESS_CENTRAL"),
            structured_evidence=[{"evidence": e} for e in evidence_chain],
            signals=signals_list,
            source_metadata={"tenant_id": tx.get("tenant_id", "default_tenant"), "company": tx.get("company_name", "default_company")},
            rule_version=self.rule_version
        )

    def evaluate(
        self,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Optional[CandidateTransaction]:
        clean_context = {k: v for k, v in context.items() if k != "historical_transactions"}
        historical_txs = context.get("historical_transactions") or []
        finding = self.evaluate_candidate(clean_context, historical_txs, config)
        if finding:
            return CandidateTransaction(
                candidate_id=f"CAND-{finding.id}",
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tenant=config.get("tenant_id", "default_tenant"),
                company=config.get("company_name", "default_company"),
                source_record=clean_context,
                eligibility="ELIGIBLE",
                evidence_strength=finding.evidence_strength,
                classification=finding.classification,
                severity=finding.severity,
                dedup_key=finding.dedup_key,
                signals=finding.signals,
                evidence=finding.structured_evidence,
                requires_llm=False
            )
        return None

    def requires_llm(self, candidate: CandidateTransaction) -> bool:
        return False
