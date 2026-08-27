"""
Opsmeld Data Trust — Phase 3 Cost Baseline Resolver
Implements hierarchical baseline selection, minimum-history gating, currency isolation,
baseline-poisoning protection via BaselineEligibilityFilter, median/MAD statistics,
and date-based peer dispersion/attenuation analysis with dual minimum history gating.
"""

from datetime import datetime, date, timedelta
import math
from typing import Any, Dict, List, Optional, Tuple


def parse_date(val: Any) -> Optional[date]:
    """Parses date string or object into datetime.date."""
    if not val:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val).strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


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


class BaselineEligibilityFilter:
    """
    Upstream filter for baseline history eligibility.
    Decouples findings-store/status semantics from CostBaselineResolver.
    Strips out unresolved Data Trust anomalies, records with missing required fields,
    and non-eligible currency records before passing the population to CostBaselineResolver.
    """

    @staticmethod
    def filter_eligible_history(
        current_tx: Dict[str, Any],
        historical_txs: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Filters historical transactions for baseline calculation.
        Returns (eligible_history, is_currency_valid).
        """
        curr_id = str(current_tx.get("id") or current_tx.get("item_ledger_entry_no") or current_tx.get("value_entry_no") or "")
        curr_comp = str(current_tx.get("company_id") or current_tx.get("company_name") or "")
        curr_tenant = str(current_tx.get("tenant_id") or "")
        curr_curr = current_tx.get("currency_code")

        # Strict Currency Gating: If current transaction currency is missing/unknown, currency cannot be verified
        if not curr_curr:
            return [], False

        curr_curr_str = str(curr_curr).strip().upper()
        if not curr_curr_str:
            return [], False

        eligible = []
        for h in historical_txs:
            h_id = str(h.get("id") or h.get("item_ledger_entry_no") or h.get("value_entry_no") or "")
            if curr_id and h_id == curr_id:
                continue

            h_comp = str(h.get("company_id") or h.get("company_name") or "")
            h_tenant = str(h.get("tenant_id") or "")
            if curr_comp and h_comp and h_comp != curr_comp:
                continue
            if curr_tenant and h_tenant and h_tenant != curr_tenant:
                continue

            # Baseline-poisoning protection: filter out unresolved Data Trust anomalies
            if h.get("is_unresolved_anomaly") is True or str(h.get("finding_status") or "").upper() == "UNRESOLVED":
                continue

            # Strict Currency Gating: missing currency or currency mismatch returns ineligible
            h_curr = h.get("currency_code")
            if not h_curr:
                continue
            if str(h_curr).strip().upper() != curr_curr_str:
                continue

            eligible.append(h)

        return eligible, True


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
        - BaselineEligibilityFilter upstream Gating
        - Strict Currency Gating (missing/unknown currency -> INSUFFICIENT_EVIDENCE)
        - Hierarchical Baseline selection
        - Historical Business Date sorting for most_recent_cost
        - Date-Based Peer Time Window splitting and Dual Minimum History Gating for Peer Attenuation
        """
        eligible_history, is_curr_valid = BaselineEligibilityFilter.filter_eligible_history(current_tx, historical_txs)

        if not is_curr_valid:
            return {
                "status": "INSUFFICIENT_EVIDENCE",
                "reason": "MISSING_CURRENCY",
                "primary": {"level": "INSUFFICIENT_EVIDENCE", "count": 0, "median": None, "average": None, "mad": None, "min": None, "max": None, "most_recent_cost": None},
                "peer": {"peer_count": 0, "historical_peer_count": 0, "recent_peer_count": 0, "peer_median": None, "historical_peer_median": None, "recent_peer_median": None, "peer_shift_percent": None, "peer_average": None, "peer_mad": None, "peer_min": None, "peer_max": None, "peer_dispersion": "INSUFFICIENT", "peer_attenuation_status": "INSUFFICIENT_EVIDENCE"},
                "supporting": [],
                "counts": {"vendor_item_count": 0, "item_location_count": 0, "item_variant_count": 0, "item_count": 0}
            }

        cost_cfg = config.get("inventory_costing", {}) if config else {}
        vendor_baseline_enabled = cost_cfg.get("vendor_baseline", {}).get("enabled", True)
        peer_cfg = cost_cfg.get("peer_baseline", {})
        peer_baseline_enabled = peer_cfg.get("enabled", True)
        include_location = peer_cfg.get("include_location", cost_cfg.get("baseline_hierarchy", {}).get("include_location", True))
        include_variant = peer_cfg.get("include_variant", cost_cfg.get("baseline_hierarchy", {}).get("include_variant", True))

        curr_item = str(current_tx.get("item_no") or "")
        curr_vendor = str(current_tx.get("vendor_no") or "")
        curr_loc = str(current_tx.get("location_code") or "")
        curr_variant = str(current_tx.get("variant_code") or "")

        # Build population pools for baseline hierarchy levels
        vendor_item_pool = [
            h for h in eligible_history
            if str(h.get("item_no") or "") == curr_item and
               str(h.get("vendor_no") or "") == curr_vendor and
               (not include_location or str(h.get("location_code") or "") == curr_loc) and
               (not include_variant or str(h.get("variant_code") or "") == curr_variant) and
               curr_vendor != ""
        ]

        item_loc_pool = [
            h for h in eligible_history
            if str(h.get("item_no") or "") == curr_item and
               str(h.get("location_code") or "") == curr_loc and
               (not include_variant or str(h.get("variant_code") or "") == curr_variant)
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

        # Determine primary baseline level by hierarchy priority
        primary_level = "INSUFFICIENT_EVIDENCE"
        selected_pool: List[Dict[str, Any]] = []

        if vendor_baseline_enabled and len(vendor_item_pool) >= self.minimum_history:
            primary_level = "VENDOR_ITEM"
            selected_pool = vendor_item_pool
        elif include_location and len(item_loc_pool) >= self.minimum_history:
            primary_level = "ITEM_LOCATION"
            selected_pool = item_loc_pool
        elif include_variant and len(item_variant_pool) >= self.minimum_history:
            primary_level = "ITEM_VARIANT"
            selected_pool = item_variant_pool
        elif len(item_pool) >= self.minimum_history:
            primary_level = "ITEM"
            selected_pool = item_pool

        # Calculate statistics for primary baseline
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
            # Sort selected pool by verified business date before finding most_recent_cost
            sorted_selected = sorted(
                selected_pool,
                key=lambda h: str(h.get("posting_date") or h.get("document_date") or h.get("valuation_date") or "")
            )
            costs = [float(h.get("cost_per_unit") or 0.0) for h in sorted_selected if float(h.get("cost_per_unit") or 0.0) > 0]
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

                # Date-sorted most_recent_cost
                most_recent_cost = float(sorted_selected[-1].get("cost_per_unit") or 0.0) if sorted_selected else med

                primary_stats = {
                    "level": primary_level,
                    "count": len(costs),
                    "median": med,
                    "average": avg,
                    "mad": mad_val,
                    "min": min(costs),
                    "max": max(costs),
                    "most_recent_cost": most_recent_cost
                }

        # Compute supporting broader peer statistics & Date-Based Peer Time Window Attenuation
        if not peer_baseline_enabled:
            peer_stats = {
                "peer_count": 0,
                "historical_peer_count": 0,
                "recent_peer_count": 0,
                "peer_median": None,
                "historical_peer_median": None,
                "recent_peer_median": None,
                "peer_shift_percent": None,
                "peer_average": None,
                "peer_mad": None,
                "peer_min": None,
                "peer_max": None,
                "peer_dispersion": "DISABLED",
                "peer_attenuation_status": "DISABLED"
            }
        else:
            peer_pool = [h for h in item_pool if str(h.get("vendor_no") or "") != curr_vendor]
            peer_costs = [float(h.get("cost_per_unit") or 0.0) for h in peer_pool if float(h.get("cost_per_unit") or 0.0) > 0]

            # Determine reference date for date-based windowing
            ref_date = parse_date(current_tx.get("posting_date") or current_tx.get("document_date") or current_tx.get("valuation_date"))
            if not ref_date and peer_pool:
                dates = [parse_date(h.get("posting_date") or h.get("document_date") or h.get("valuation_date")) for h in peer_pool]
                valid_dates = [d for d in dates if d]
                if valid_dates:
                    ref_date = max(valid_dates)

            if not ref_date:
                ref_date = date.today()

            recent_months = int(cost_cfg.get("peer_movement", {}).get("recent_lookback_months", 3))
            recent_cutoff_date = ref_date - timedelta(days=int(recent_months * 30.4375))

            hist_peer_pool = []
            recent_peer_pool = []

            for h in peer_pool:
                d = parse_date(h.get("posting_date") or h.get("document_date") or h.get("valuation_date"))
                if d and d >= recent_cutoff_date:
                    recent_peer_pool.append(h)
                else:
                    hist_peer_pool.append(h)

            hist_peer_costs = [float(h.get("cost_per_unit") or 0.0) for h in hist_peer_pool if float(h.get("cost_per_unit") or 0.0) > 0]
            recent_peer_costs = [float(h.get("cost_per_unit") or 0.0) for h in recent_peer_pool if float(h.get("cost_per_unit") or 0.0) > 0]

            min_peer_hist = self.minimum_history # 20
            min_peer_recent = int(cost_cfg.get("peer_movement", {}).get("minimum_peer_recent_history", 5))

            # Dual Minimum History Gating for Peer Attenuation
            if len(hist_peer_costs) < min_peer_hist or len(recent_peer_costs) < min_peer_recent:
                peer_stats = {
                    "peer_count": len(peer_costs),
                    "historical_peer_count": len(hist_peer_costs),
                    "recent_peer_count": len(recent_peer_costs),
                    "peer_median": calculate_median(peer_costs) if peer_costs else None,
                    "historical_peer_median": calculate_median(hist_peer_costs) if hist_peer_costs else None,
                    "recent_peer_median": calculate_median(recent_peer_costs) if recent_peer_costs else None,
                    "peer_shift_percent": None,
                    "peer_average": (sum(peer_costs) / len(peer_costs)) if peer_costs else None,
                    "peer_mad": calculate_mad(peer_costs) if peer_costs else None,
                    "peer_min": min(peer_costs) if peer_costs else None,
                    "peer_max": max(peer_costs) if peer_costs else None,
                    "peer_dispersion": "INSUFFICIENT" if not peer_costs else ("LOW" if calculate_mad(peer_costs) / max(calculate_median(peer_costs), 1.0) < 0.1 else "MEDIUM"),
                    "peer_attenuation_status": "INSUFFICIENT_EVIDENCE"
                }
            else:
                p_med = calculate_median(peer_costs)
                p_avg = sum(peer_costs) / len(peer_costs)
                p_mad = calculate_mad(peer_costs, p_med)

                hist_p_med = calculate_median(hist_peer_costs)
                recent_p_med = calculate_median(recent_peer_costs)

                peer_shift_pct = abs(recent_p_med - hist_p_med) / max(hist_p_med, 1.0) * 100.0

                base_med = primary_stats.get("median")
                peer_attenuation_status = "UNATTENUATED"
                if base_med and base_med > 0:
                    curr_cost = float(current_tx.get("cost_per_unit") or 0.0)
                    vendor_dev_pct = abs(curr_cost - base_med) / base_med * 100.0
                    mat_thresh = float(cost_cfg.get("peer_movement", {}).get("material_movement_percent", 20.0))

                    if vendor_dev_pct >= mat_thresh and peer_shift_pct >= mat_thresh:
                        peer_attenuation_status = "ATTENUATED"

                peer_stats = {
                    "peer_count": len(peer_costs),
                    "historical_peer_count": len(hist_peer_costs),
                    "recent_peer_count": len(recent_peer_costs),
                    "peer_median": p_med,
                    "historical_peer_median": hist_p_med,
                    "recent_peer_median": recent_p_med,
                    "peer_shift_percent": round(peer_shift_pct, 1),
                    "peer_average": p_avg,
                    "peer_mad": p_mad,
                    "peer_min": min(peer_costs),
                    "peer_max": max(peer_costs),
                    "peer_dispersion": "LOW" if p_mad / max(p_med, 1.0) < 0.1 else "MEDIUM",
                    "peer_attenuation_status": peer_attenuation_status
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
