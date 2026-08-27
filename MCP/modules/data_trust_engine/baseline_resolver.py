"""
Opsmeld Data Trust — Phase 3 Cost Baseline Resolver
Implements hierarchical baseline selection, minimum-history gating, currency isolation,
baseline-poisoning protection, median/MAD statistics, and peer dispersion analysis.
"""

import math
from typing import Any, Dict, List, Optional, Tuple


def calculate_median(values: List[float]) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


def calculate_mad(values: List[float], median: Optional[float] = None) -> float:
    """Calculates Median Absolute Deviation (MAD)."""
    if not values:
        return 0.0
    if median is None:
        median = calculate_median(values)
    abs_devs = [abs(x - median) for x in values]
    return calculate_median(abs_devs)


class CostBaselineResolver:
    """
    Hierarchical baseline resolver for inventory costing analysis.
    Evaluates levels in priority order:
    1. VENDOR_ITEM (Company + Item + Vendor + Location + Variant)
    2. ITEM_LOCATION (Company + Item + Location + Variant)
    3. ITEM_VARIANT (Company + Item + Variant)
    4. ITEM (Company + Item)
    """

    def __init__(self, minimum_history: int = 20):
        self.minimum_history = minimum_history

    def resolve_baseline(
        self,
        current_tx: Dict[str, Any],
        historical_txs: List[Dict[str, Any]],
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Resolves the primary baseline and supporting peer statistics for a current transaction.
        Enforces:
        - Excludes current transaction by ID/item_ledger_entry_no
        - Company & tenant isolation
        - Baseline-poisoning protection (excludes unresolved anomalies)
        - Currency-basis isolation
        - Gating at minimum_history threshold
        """
        curr_id = str(current_tx.get("id") or current_tx.get("item_ledger_entry_no") or current_tx.get("value_entry_no") or "")
        curr_comp = str(current_tx.get("company_id") or current_tx.get("company_name") or "default_company")
        curr_tenant = str(current_tx.get("tenant_id") or "default_tenant")
        curr_item = str(current_tx.get("item_no") or "")
        curr_vendor = str(current_tx.get("vendor_no") or "")
        curr_loc = str(current_tx.get("location_code") or "")
        curr_variant = str(current_tx.get("variant_code") or "")
        curr_curr = str(current_tx.get("currency_code") or "INR").upper()

        # Step 1: Filter historical records by tenant & company isolation, excluding current transaction
        eligible_history: List[Dict[str, Any]] = []
        for h in historical_txs:
            h_id = str(h.get("id") or h.get("item_ledger_entry_no") or h.get("value_entry_no") or "")
            if curr_id and h_id == curr_id:
                continue

            h_comp = str(h.get("company_id") or h.get("company_name") or "default_company")
            h_tenant = str(h.get("tenant_id") or "default_tenant")
            if h_comp != curr_comp or h_tenant != curr_tenant:
                continue

            # Baseline-poisoning protection: exclude unresolved Data Trust anomalies
            if h.get("is_unresolved_anomaly") is True or str(h.get("finding_status") or "").upper() == "UNRESOLVED":
                continue

            # Currency-basis isolation check
            h_curr = str(h.get("currency_code") or "INR").upper()
            if curr_curr and h_curr and curr_curr != h_curr:
                continue

            eligible_history.append(h)

        # Step 2: Build population pools for baseline hierarchy levels
        vendor_item_pool = [
            h for h in eligible_history
            if str(h.get("item_no") or "") == curr_item and
               str(h.get("vendor_no") or "") == curr_vendor and
               str(h.get("location_code") or "") == curr_loc and
               str(h.get("variant_code") or "") == curr_variant and
               curr_vendor != ""
        ]

        item_loc_pool = [
            h for h in eligible_history
            if str(h.get("item_no") or "") == curr_item and
               str(h.get("location_code") or "") == curr_loc and
               str(h.get("variant_code") or "") == curr_variant
        ]

        item_variant_pool = [
            h for h in eligible_history
            if str(h.get("item_no") or "") == curr_item and
               str(h.get("variant_code") or "") == curr_variant
        ]

        item_pool = [
            h for h in eligible_history
            if str(h.get("item_no") or "") == curr_item
        ]

        # Step 3: Determine primary baseline level by hierarchy priority
        primary_level = "INSUFFICIENT_EVIDENCE"
        selected_pool: List[Dict[str, Any]] = []

        if len(vendor_item_pool) >= self.minimum_history:
            primary_level = "VENDOR_ITEM"
            selected_pool = vendor_item_pool
        elif len(item_loc_pool) >= self.minimum_history:
            primary_level = "ITEM_LOCATION"
            selected_pool = item_loc_pool
        elif len(item_variant_pool) >= self.minimum_history:
            primary_level = "ITEM_VARIANT"
            selected_pool = item_variant_pool
        elif len(item_pool) >= self.minimum_history:
            primary_level = "ITEM"
            selected_pool = item_pool

        # Step 4: Calculate statistics for primary baseline
        if primary_level == "INSUFFICIENT_EVIDENCE" or not selected_pool:
            primary_stats = {
                "level": "INSUFFICIENT_EVIDENCE",
                "count": len(selected_pool),
                "median": None,
                "average": None,
                "mad": None,
                "min": None,
                "max": None,
                "most_recent_cost": None
            }
        else:
            costs = [float(h.get("cost_per_unit") or 0.0) for h in selected_pool if float(h.get("cost_per_unit") or 0.0) > 0]
            if len(costs) < self.minimum_history:
                primary_stats = {
                    "level": "INSUFFICIENT_EVIDENCE",
                    "count": len(costs),
                    "median": None,
                    "average": None,
                    "mad": None,
                    "min": None,
                    "max": None,
                    "most_recent_cost": None
                }
            else:
                med = calculate_median(costs)
                avg = sum(costs) / len(costs)
                mad_val = calculate_mad(costs, med)
                rec = costs[-1] if costs else med

                primary_stats = {
                    "level": primary_level,
                    "count": len(costs),
                    "median": med,
                    "average": avg,
                    "mad": mad_val,
                    "min": min(costs),
                    "max": max(costs),
                    "most_recent_cost": rec
                }

        # Step 5: Compute supporting broader peer statistics & dispersion
        peer_costs = [float(h.get("cost_per_unit") or 0.0) for h in item_pool if float(h.get("cost_per_unit") or 0.0) > 0]
        if peer_costs:
            p_med = calculate_median(peer_costs)
            p_avg = sum(peer_costs) / len(peer_costs)
            p_mad = calculate_mad(peer_costs, p_med)
            peer_stats = {
                "peer_count": len(peer_costs),
                "peer_median": p_med,
                "peer_average": p_avg,
                "peer_mad": p_mad,
                "peer_min": min(peer_costs),
                "peer_max": max(peer_costs),
                "peer_dispersion": "LOW" if p_mad / max(p_med, 1.0) < 0.1 else ("MEDIUM" if p_mad / max(p_med, 1.0) < 0.25 else "HIGH")
            }
        else:
            peer_stats = {
                "peer_count": 0,
                "peer_median": None,
                "peer_average": None,
                "peer_mad": None,
                "peer_min": None,
                "peer_max": None,
                "peer_dispersion": "INSUFFICIENT"
            }

        # Supporting baselines list for finding inspection
        supporting_baselines = []
        for name, pool in [
            ("VENDOR_ITEM", vendor_item_pool),
            ("ITEM_LOCATION", item_loc_pool),
            ("ITEM_VARIANT", item_variant_pool),
            ("ITEM", item_pool)
        ]:
            if name != primary_level:
                p_costs = [float(h.get("cost_per_unit") or 0.0) for h in pool if float(h.get("cost_per_unit") or 0.0) > 0]
                if p_costs:
                    p_med = calculate_median(p_costs)
                    curr_cost = float(current_tx.get("cost_per_unit") or 0.0)
                    dev_pct = ((curr_cost - p_med) / p_med * 100.0) if p_med > 0 else 0.0
                    supporting_baselines.append({
                        "level": name,
                        "count": len(p_costs),
                        "median": round(p_med, 2),
                        "deviation_percent": round(dev_pct, 1)
                    })

        return {
            "status": "ELIGIBLE" if primary_stats.get("median") is not None else "INSUFFICIENT_EVIDENCE",
            "primary": primary_stats,
            "peer": peer_stats,
            "supporting": supporting_baselines,
            "counts": {
                "vendor_item_count": len(vendor_item_pool),
                "item_location_count": len(item_loc_pool),
                "item_variant_count": len(item_variant_pool),
                "item_count": len(item_pool),
            }
        }
