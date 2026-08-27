"""
Opsmeld Data Trust — Phase 3 Inventory Costing & Valuation Integrity Rule
Implements deterministic, read-only evaluation of inventory cost entries (C1–C10 signals),
cost driver analysis, boolean normalization, materiality gating,
and authoritative configuration integration.
"""

from typing import Any, Dict, List, Optional
from modules.data_trust_engine.models import DataTrustFinding
from modules.data_trust_engine.baseline_resolver import CostBaselineResolver
from modules.data_trust_engine.candidate import CandidateTransaction
from core.bc_mcp_client import BCMCPClient


def normalize_boolean(val: Any) -> bool:
    """Normalizes raw Business Central boolean representations."""
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("true", "1", "yes")


class InventoryCostingRule:
    rule_id = "inventory_costing"
    name = "Inventory Costing & Valuation Integrity"
    required_data_source = "INVENTORY_COST_TRANSACTIONS"

    def __init__(self, minimum_history: int = 20):
        self.minimum_history = minimum_history
        self.resolver = CostBaselineResolver(minimum_history=minimum_history)
        self.enabled = True

    def requires_llm(self, candidate: CandidateTransaction) -> bool:
        return False

    def assess_eligibility(self, context: Dict[str, Any]) -> str:
        cost = float(context.get("cost_per_unit") or context.get("cost_amount_actual") or 0.0)
        qty = float(context.get("quantity") or 0.0)
        curr = context.get("currency_code")
        if not curr:
            return "INSUFFICIENT_EVIDENCE"
        if cost <= 0 and qty <= 0:
            return "INSUFFICIENT_EVIDENCE"
        return "ELIGIBLE"

    def evaluate(self, context: Dict[str, Any], config: Dict[str, Any]) -> Optional[DataTrustFinding]:
        cost_config = config.get("inventory_costing", {})
        if not cost_config.get("enabled", True):
            return None

        min_hist = int(cost_config.get("historical_pattern", {}).get("minimum_history", self.minimum_history))
        self.resolver = CostBaselineResolver(minimum_history=min_hist)

        historical_txs = context.get("historical_transactions", [])
        return self.evaluate_candidate(context, historical_txs, config)

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

        min_hist = int(cost_config.get("historical_pattern", {}).get("minimum_history", self.minimum_history))
        self.resolver = CostBaselineResolver(minimum_history=min_hist)

        # Step 1: Use CostBaselineResolver once per candidate
        res = self.resolver.resolve_baseline(tx, historical_txs, config)
        primary = res.get("primary", {})
        peer = res.get("peer", {})
        supporting = res.get("supporting", [])

        if res.get("status") == "INSUFFICIENT_EVIDENCE" or primary.get("median") is None:
            return None

        curr_cost = float(tx.get("cost_per_unit") or 0.0)
        base_median = float(primary.get("median") or 1.0)
        dev_pct = ((curr_cost - base_median) / base_median) * 100.0 if base_median > 0 else 0.0

        signals_fired = []
        evidence_chain = []
        signals_list = []
        known_drivers = []

        rel_thresh = float(cost_config.get("historical_pattern", {}).get("relative_change_percent", 25.0))

        # C1 — Sudden Unit Cost Movement
        c1_fired = abs(dev_pct) >= rel_thresh

        signals_list.append({"signal_code": "C1", "name": "Sudden Unit Cost Movement", "fired": c1_fired})
        if c1_fired:
            signals_fired.append("C1 (Sudden Unit Cost Movement)")
            evidence_chain.append(
                f"[C1 Sudden Unit Cost Movement] Fired: Unit cost ${curr_cost:,.2f} deviates by {dev_pct:+.1f}% from selected {primary['level']} baseline median (${base_median:,.2f})."
            )

        # C2 — Unusual Purchase Cost Variance (Requires authoritative purchase evidence)
        purch_act_raw = tx.get("purchase_amount_actual")
        purch_exp_raw = tx.get("purchase_amount_expected")
        purch_thresh_pct = float(cost_config.get("expected_actual", {}).get("relative_variance_percent", 20.0))
        c2_fired = False
        if purch_act_raw is not None and purch_exp_raw is not None:
            purch_act = float(purch_act_raw)
            purch_exp = float(purch_exp_raw)
            if purch_exp > 0:
                var_pct = (abs(purch_act - purch_exp) / purch_exp) * 100.0
                if var_pct >= purch_thresh_pct:
                    c2_fired = True
                    evidence_chain.append(
                        f"[C2 Purchase Cost Variance] Fired: Purchase actual ${purch_act:,.2f} vs expected ${purch_exp:,.2f} variance ({var_pct:.1f}% >= {purch_thresh_pct:.0f}%)."
                    )
        signals_list.append({"signal_code": "C2", "name": "Unusual Purchase Cost Variance", "fired": c2_fired})
        if c2_fired:
            signals_fired.append("C2 (Unusual Purchase Cost Variance)")

        # C3 — Expected-to-Actual Cost Change (Known Costing Driver)
        exp_act_thresh = float(cost_config.get("expected_actual", {}).get("relative_variance_percent", 20.0))
        act_cost_raw = tx.get("cost_amount_actual")
        exp_cost_raw = tx.get("cost_amount_expected")
        c3_fired = False
        if act_cost_raw is not None and exp_cost_raw is not None:
            act_cost = float(act_cost_raw)
            exp_cost = float(exp_cost_raw)
            if exp_cost > 0:
                c3_variance_pct = (abs(act_cost - exp_cost) / exp_cost) * 100.0
                if c3_variance_pct >= exp_act_thresh:
                    c3_fired = True
                    known_drivers.append("EXPECTED_TO_ACTUAL")
                    evidence_chain.append(
                        f"[C3 Expected-to-Actual] Fired: Expected cost ${exp_cost:,.2f} transitioned to actual cost ${act_cost:,.2f} (variance {c3_variance_pct:.1f}% >= {exp_act_thresh:.0f}%)."
                    )
        signals_list.append({"signal_code": "C3", "name": "Expected-to-Actual Cost Change", "fired": c3_fired})
        if c3_fired:
            signals_fired.append("C3 (Expected-to-Actual Cost Change)")

        # C4 — Cost Adjustment Event (Known Costing Driver)
        c4_fired = normalize_boolean(tx.get("adjustment"))
        signals_list.append({"signal_code": "C4", "name": "Cost Adjustment Event", "fired": c4_fired})
        if c4_fired:
            known_drivers.append("COST_ADJUSTMENT")
            signals_fired.append("C4 (Cost Adjustment Event)")
            evidence_chain.append(
                "[C4 Cost Adjustment] Fired: Transaction represents an authoritative Business Central cost adjustment entry."
            )

        # C5 — Revaluation Event (Known Costing Driver)
        c5_fired = normalize_boolean(tx.get("partial_revaluation")) or normalize_boolean(tx.get("revaluation"))
        signals_list.append({"signal_code": "C5", "name": "Revaluation Event", "fired": c5_fired})
        if c5_fired:
            known_drivers.append("REVALUATION")
            signals_fired.append("C5 (Revaluation Event)")
            evidence_chain.append(
                "[C5 Revaluation] Fired: Transaction contains authoritative partial or full inventory revaluation."
            )

        # C6 — Item Charge / Landed Cost Impact (Known Costing Driver)
        item_charge = str(tx.get("item_charge_no") or "").strip()
        c6_fired = bool(item_charge)
        signals_list.append({"signal_code": "C6", "name": "Item Charge Landed Cost Impact", "fired": c6_fired})
        if c6_fired:
            known_drivers.append(f"ITEM_CHARGE({item_charge})")
            signals_fired.append("C6 (Item Charge Impact)")
            evidence_chain.append(
                f"[C6 Item Charge] Fired: Cost movement associated with landed item charge '{item_charge}'."
            )

        # C7 — Historical Cost Pattern Break (Measures recent 5-observation distribution shift vs baseline median)
        c7_fired = False
        selected_pool = res.get("selected_pool", historical_txs)
        if len(selected_pool) >= 5:
            sorted_recent = sorted(
                selected_pool,
                key=lambda h: str(h.get("posting_date") or h.get("document_date") or h.get("valuation_date") or "")
            )[-5:]
            recent_costs = [float(h.get("cost_per_unit") or 0.0) for h in sorted_recent if float(h.get("cost_per_unit") or 0.0) > 0]
            if len(recent_costs) >= 5:
                recent_median = sorted(recent_costs)[len(recent_costs) // 2]
                shift_pct = ((recent_median - base_median) / base_median) * 100.0 if base_median > 0 else 0.0
                if abs(shift_pct) >= rel_thresh:
                    c7_fired = True
                    evidence_chain.append(
                        f"[C7 Pattern Break] Fired: Recent 5-observation median (${recent_median:,.2f}) shifted by {shift_pct:+.1f}% from historical baseline median (${base_median:,.2f})."
                    )

        signals_list.append({"signal_code": "C7", "name": "Historical Cost Pattern Break", "fired": c7_fired})
        if c7_fired:
            signals_fired.append("C7 (Historical Cost Pattern Break)")

        # C8 — Unexplained Cost Movement (Fires ONLY when material movement exists AND zero known drivers explain it)
        material_movement = c1_fired or c7_fired
        c8_fired = material_movement and (len(known_drivers) == 0)
        signals_list.append({"signal_code": "C8", "name": "Unexplained Cost Movement", "fired": c8_fired})
        if c8_fired:
            signals_fired.append("C8 (Unexplained Cost Movement)")
            evidence_chain.append(
                f"[C8 Unexplained Movement] Fired: Material unit cost deviation ({dev_pct:+.1f}%) is unsupported by authoritative Business Central costing drivers."
            )

        # C9 — Cost / Quantity Inconsistency (Strict null & zero quantity semantics)
        c9_fired = False
        qty_raw = tx.get("quantity")
        if qty_raw is not None and act_cost_raw is not None:
            qty = float(qty_raw)
            act_cost = float(act_cost_raw)
            tol_pct = float(cost_config.get("quantity_cost", {}).get("relative_tolerance_percent", 5.0))
            if qty == 0.0 and act_cost != 0.0:
                c9_fired = True
                evidence_chain.append(
                    f"[C9 Inconsistency] Fired: Transaction quantity is 0.0 while actual cost is ${act_cost:,.2f}."
                )
            elif qty > 0 and curr_cost > 0:
                derived_cost = act_cost / qty
                discrepancy_pct = (abs(derived_cost - curr_cost) / curr_cost) * 100.0
                if discrepancy_pct >= tol_pct:
                    c9_fired = True
                    evidence_chain.append(
                        f"[C9 Inconsistency] Fired: Derived unit cost (${derived_cost:,.2f}) deviates by {discrepancy_pct:.1f}% from reported unit cost (${curr_cost:,.2f})."
                    )

        signals_list.append({"signal_code": "C9", "name": "Cost/Quantity Inconsistency", "fired": c9_fired})
        if c9_fired:
            signals_fired.append("C9 (Cost/Quantity Inconsistency)")

        # C10 — Cost-to-G/L Posting Difference (Strict Fail-Closed: Never substitutes inventory cost for missing G/L cost)
        c10_fired = False
        cost_gl_raw = tx.get("cost_posted_to_gl")
        if cost_gl_raw is not None and act_cost_raw is not None:
            cost_gl = float(cost_gl_raw)
            act_cost = float(act_cost_raw)
            if abs(act_cost - cost_gl) > 0.01:
                c10_fired = True
                evidence_chain.append(
                    f"[C10 G/L Difference] Fired: Value entry actual cost (${act_cost:,.2f}) differs from posted G/L amount (${cost_gl:,.2f})."
                )

        signals_list.append({"signal_code": "C10", "name": "Cost-to-G/L Posting Difference", "fired": c10_fired})
        if c10_fired:
            signals_fired.append("C10 (Cost-to-G/L Difference)")

        if not any(s["fired"] for s in signals_list):
            return None

        # Step 6: Peer Movement Attenuation Status Check
        peer_attenuation_status = peer.get("peer_attenuation_status", "UNATTENUATED")
        is_peer_attenuated = (peer_attenuation_status == "ATTENUATED")
        if is_peer_attenuated:
            evidence_chain.append(
                "[Peer Attenuation] Broad market/item movement detected (peer shift >= 20%). Anomaly severity attenuated to MEDIUM."
            )

        # Evidence Strength & Classification Determination
        if c8_fired or c9_fired or c10_fired:
            classification = "Potential Data Error"
            evidence_strength = "MEDIUM" if is_peer_attenuated else "HIGH"
        elif len(known_drivers) > 0:
            classification = "Explained Anomaly Candidate"
            evidence_strength = "MEDIUM"
        else:
            classification = "Anomaly"
            evidence_strength = "LOW" if is_peer_attenuated else "MEDIUM"

        tx_id = str(tx.get("id") or tx.get("item_ledger_entry_no") or tx.get("value_entry_no") or "UNKNOWN")
        comp = str(tx.get("company_id") or tx.get("company_name") or "DEFAULT")
        item_no = str(tx.get("item_no") or "UNKNOWN")

        tx_clean = {k: v for k, v in tx.items() if k != "historical_transactions"}

        finding = DataTrustFinding(
            id=f"FINDING-{tx_id}",
            dedup_key=f"INVENTORY_COSTING_{comp}_{tx_id}",
            rule_pack="Inventory Costing & Valuation Integrity",
            classification=classification,
            evidence_strength=evidence_strength,
            severity="HIGH" if evidence_strength == "HIGH" else ("MEDIUM" if evidence_strength == "MEDIUM" else "INFORMATIONAL"),
            signals_fired_count=len(signals_fired),
            evidence_chain=evidence_chain,
            transaction_details=tx_clean,
            business_impact=f"Unit cost deviation from {primary.get('level')} baseline median (${base_median:,.2f})",
            recommended_action="Human review required for inventory cost entry adjustment",
            signals=signals_list,
            data_source=tx.get("data_provenance") or "SNAPSHOT_SEED"
        )
        return finding
