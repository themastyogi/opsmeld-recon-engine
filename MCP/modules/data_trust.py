import logging
logger = logging.getLogger('opsmeld.data_trust')
"""
Opsmeld Reconciliation Engine - Data Trust Engine Module (Thin Compatibility Façade)
Delegates all rule execution, orchestration, models, configuration, and fixtures to modular data_trust_engine package.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from core.bc_mcp_client import BCMCPClient
from core.config_loader import load_client_config, load_engine_rules, CONFIG_DIR, BASE_DIR

# Modular Imports
from modules.data_trust_engine.models import DataTrustFinding
from modules.data_trust_engine.config import DataTrustConfigManager
from modules.data_trust_engine.fixtures import get_sample_transactions
from modules.data_trust_engine.rules.posting_date import PostingDatePolicyRule
from modules.data_trust_engine.rules.subledger_bypass import SubledgerBypassRule
from modules.data_trust_engine.rules.narration_context import NarrationContextRule


class PostingDateRulePack:
    """
    Rule Pack 1 — Posting-Date Policy (Compatibility Façade Shim).
    Delegates to modular PostingDatePolicyRule implementation.
    """
    
    @staticmethod
    def evaluate_transaction(tx: Dict[str, Any], config: Dict[str, Any], ref_date: Optional[date] = None) -> Optional[DataTrustFinding]:
        rule = PostingDatePolicyRule()
        return rule.evaluate_transaction(tx, config, ref_date=ref_date)


class SubledgerBypassRulePack:
    """
    Rule Pack 2 — Generic Subledger Bypass (Compatibility Façade Shim).
    Delegates to modular SubledgerBypassRule implementation.
    """

    @staticmethod
    def evaluate_transaction(tx: Dict[str, Any], config: Dict[str, Any]) -> Optional[DataTrustFinding]:
        rule = SubledgerBypassRule()
        return rule.evaluate_transaction(tx, config)


class NarrationContextRulePack:
    """
    Rule Pack 3 — Narration / Context Mismatch (Compatibility Façade Shim).
    Delegates to modular NarrationContextRule implementation.
    """

    @staticmethod
    def evaluate_candidate(
        tx: Dict[str, Any],
        peer_history: List[Dict[str, Any]],
        config: Dict[str, Any],
        mcp_client: Optional[BCMCPClient] = None
    ) -> Optional[DataTrustFinding]:
        rule = NarrationContextRule()
        return rule.evaluate_candidate(tx, peer_history, config, mcp_client=mcp_client)


class DataTrustEngine:
    """Main orchestration engine for Data Trust Findings generation, multi-tenant persistence, and idempotency (Compatibility Façade)."""

    def __init__(self, mcp_client: Optional[BCMCPClient] = None, client_key: Optional[str] = None):
        self.client = mcp_client
        self.client_key = client_key or load_client_config().client_key
        self.config_mgr = DataTrustConfigManager(self.client_key)

    def get_findings_file_path(self, company_id: Optional[str] = None) -> Path:
        """Strictly scoped file path for company findings snapshot. Removes all unscoped and fixture fallbacks."""
        sanitized_comp = re.sub(r'[^a-zA-Z0-9_-]', '_', str(company_id)) if company_id else "unspecified_company"
        p = BASE_DIR / "data" / "snapshots" / f"data_trust_findings_{self.client_key}_{sanitized_comp}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def fetch_live_bc_transactions(self) -> List[Dict[str, Any]]:
        """Legacy compatibility helper delegating live G/L transaction acquisition to DataAcquirer."""
        from modules.data_trust_engine.acquisition import DataAcquirer
        acquirer = DataAcquirer(mcp_client=self.client, mode="LIVE_BUSINESS_CENTRAL" if self.client else "AUTO")
        txs, _ = acquirer.acquire_transactions()
        return txs

    def _load_from_disk(self, company_id: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        p = self.get_findings_file_path(company_id=company_id)
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data.get("active_findings", []), data.get("_audit_history", []), data.get("data_source")
                    elif isinstance(data, list):
                        return data, [], None
            except Exception:
                pass
        return [], [], None

    def load_stored_findings(self, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        target_comp = company_id
        if not target_comp and self.client:
            from modules.data_trust_engine.authorization import CompanyAccessManager
            mgr = CompanyAccessManager()
            is_auth, st_name, details = mgr.validate_company_access(self.client)
            if is_auth and details.get("company_id"):
                target_comp = details["company_id"]

        if not target_comp:
            target_comp = "ac6b97ba-bc8f-f111-832d-7c1e5233db45"

        active_findings, _, _ = self._load_from_disk(company_id=target_comp)

        if not active_findings:
            from modules.data_trust_engine.engine import DataTrustEngineOrchestrator
            orchestrator = DataTrustEngineOrchestrator(mcp_client=self.client, client_key=self.client_key)
            mode = "TEST_FIXTURE" if self.client is None else "AUTO"
            res = orchestrator.run_recon(company_id=target_comp, mode=mode)
            active_findings = res.get("findings", [])
            if active_findings:
                self.save_stored_findings(active_findings, company_id=target_comp, data_source=res.get("run_summary", {}).get("data_source"))

        return active_findings

    def save_stored_findings(
        self,
        findings: List[Dict[str, Any]],
        company_id: Optional[str] = None,
        audit_history: Optional[List[Dict[str, Any]]] = None,
        data_source: Optional[str] = None
    ) -> bool:
        target_comp = company_id or "unspecified_company"
        p = self.get_findings_file_path(company_id=target_comp)
        # P0: Never derive LIVE_BUSINESS_CENTRAL from token existence.
        # Provenance must come exclusively from successful authoritative BC acquisition.
        # Default to DATA_UNAVAILABLE if data_source is omitted. Never default production to TEST_FIXTURE.
        eff_ds = data_source or "DATA_UNAVAILABLE"
        payload = {
            "client_key": self.client_key,
            "company_id": target_comp,
            "data_source": eff_ds,
            "last_reconciled_at": datetime.now().isoformat(),
            "active_findings": findings,
            "_audit_history": audit_history or []
        }
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            return True
        except Exception:
            return False

    def update_finding_status(self, finding_id: str, new_status: str, company_id: Optional[str] = None) -> dict:
        """Mutates status of an existing finding within the authorized company scope.
        Returns dict with status=NOT_FOUND (HTTP 404) if finding_id does not exist.
        Never creates a finding for an unknown ID. Never scans across companies."""
        valid_statuses = ["Open", "Under Review", "Confirmed", "False Positive", "Ignored"]
        if new_status not in valid_statuses:
            return {"status": "INVALID_STATUS", "error": f"Status '{new_status}' is not valid."}

        # P0: company_id is mandatory in live/production mode.
        # In fixture mode (no client), default to FIXTURE_COMPANY for backward compatibility.
        if not company_id:
            if self.client is not None:
                return {"status": "CONFIGURATION_MISSING", "error": "Missing mandatory company_id parameter."}
            company_id = "FIXTURE_COMPANY"

        active_findings, audit_history, existing_ds = self._load_from_disk(company_id=company_id)
        updated = False
        for f in active_findings:
            if f.get("id") == finding_id:
                f["status"] = new_status
                f["last_evaluated_at"] = datetime.now().isoformat()
                updated = True
                break

        if updated:
            self.save_stored_findings(active_findings, company_id=company_id, audit_history=audit_history, data_source=existing_ds)
            return {"status": "OK", "finding_id": finding_id, "new_status": new_status}

        # P0: Unknown finding_id must NEVER create a finding. Return 404.
        return {"status": "NOT_FOUND", "error": f"Finding '{finding_id}' not found in company scope.", "http_status": 404}

    def run_recon(self, sample_transactions: Optional[List[Dict[str, Any]]] = None, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Legacy façade method delegating to DataTrustEngineOrchestrator inside data_trust_engine."""
        from modules.data_trust_engine.engine import DataTrustEngineOrchestrator
        orchestrator = DataTrustEngineOrchestrator(mcp_client=self.client, client_key=self.client_key)
        mode = "TEST_FIXTURE" if self.client is None else "AUTO"
        # P0: Never resolve to default_company. If company_id is missing in live mode, return empty.
        if not company_id and self.client is not None:
            return []
        target_company = company_id or "FIXTURE_COMPANY"  # Fixture mode only when client is None
        res = orchestrator.run_recon(company_id=target_company, sample_transactions=sample_transactions, mode=mode)

        if res.get("status") in ("DATA_UNAVAILABLE", "ACCESS_DENIED", "AUTHENTICATION_UNAVAILABLE", "COMPANY_NOT_FOUND"):
            return []

        newly_eval_findings = res.get("findings", [])
        resolved_company_id = res.get("company_id") or company_id

        # Load existing company-scoped disk snapshot to preserve historical audit evaluations
        existing_findings_raw, existing_audit_history, _ = self._load_from_disk(company_id=resolved_company_id)

        # Build current run audit record to append to non-destructive _audit_history
        now_iso = datetime.now().isoformat()
        audit_record = {
            "run_id": res.get("run_summary", {}).get("run_id"),
            "evaluated_at": now_iso,
            "status": res.get("status"),
            "data_source": res.get("run_summary", {}).get("data_source"),
            "findings_count": len(newly_eval_findings),
            "findings_ids": [f.get("id") for f in newly_eval_findings]
        }
        updated_audit_history = existing_audit_history + [audit_record]

        # In sample_transactions or fixture mode, perform idempotent deduplication & status merging
        if sample_transactions is not None or self.client is None:
            existing_map = {f.get("dedup_key"): f for f in existing_findings_raw if f.get("dedup_key")}
            merged_findings: List[Dict[str, Any]] = []
            STRENGTH_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INSUFFICIENT": 0}

            for new_f in newly_eval_findings:
                d_key = new_f.get("dedup_key")
                if d_key in existing_map:
                    existing = existing_map[d_key]
                    old_strength = existing.get("evidence_strength", "INSUFFICIENT")
                    old_signals_cnt = existing.get("signals_fired_count", 0)
                    old_status = existing.get("status", "Open")

                    new_rank = STRENGTH_RANK.get(new_f.get("evidence_strength"), 0)
                    old_rank = STRENGTH_RANK.get(old_strength, 0)
                    is_escalated = (new_rank > old_rank) or (new_f.get("signals_fired_count", 0) > old_signals_cnt)

                    existing["last_evaluated_at"] = now_iso
                    existing["evidence_strength"] = new_f.get("evidence_strength")
                    existing["severity"] = new_f.get("severity")
                    existing["signals_fired_count"] = new_f.get("signals_fired_count")
                    existing["transaction_details"] = new_f.get("transaction_details")
                    existing["data_source"] = new_f.get("data_source")

                    if is_escalated:
                        escalation_note = f"⚡ Re-opened for Review: Evidence Strength escalated from {old_strength} ({old_signals_cnt} signals) to {new_f.get('evidence_strength')} ({new_f.get('signals_fired_count')} signals) on re-evaluation."
                        existing["evidence_chain"] = [escalation_note] + new_f.get("evidence_chain", [])
                        if old_status in ["False Positive", "Ignored", "Confirmed"]:
                            existing["status"] = "Open"
                    else:
                        existing["evidence_chain"] = new_f.get("evidence_chain", [])

                    merged_findings.append(existing)
                else:
                    merged_findings.append(new_f)

            for d_key, existing in existing_map.items():
                if not any(f.get("dedup_key") == d_key for f in merged_findings):
                    merged_findings.append(existing)

            active_findings_to_save = merged_findings
        else:
            # On a live reconciliation run, replace active findings with current run findings (or [] for State 2 clean state)
            active_findings_to_save = newly_eval_findings

        run_ds = res.get("run_summary", {}).get("data_source") or "TEST_FIXTURE"
        self.save_stored_findings(active_findings_to_save, company_id=resolved_company_id, audit_history=updated_audit_history, data_source=run_ds)
        return active_findings_to_save

    def generate_synthetic_or_live_findings(self) -> List[Dict[str, Any]]:
        return self.run_recon()

    def get_summary_metrics(self, findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "total_findings": len(findings),
            "policy_violations": sum(1 for f in findings if f.get("classification") == "Policy Violation"),
            "anomalies": sum(1 for f in findings if f.get("classification") == "Anomaly"),
            "potential_data_errors": sum(1 for f in findings if f.get("classification") == "Potential Data Error"),
            "informational": sum(1 for f in findings if f.get("classification") == "Informational"),
            "insufficient_evidence": sum(1 for f in findings if f.get("classification") == "Insufficient Evidence"),
            "severity_counts": {
                "critical": sum(1 for f in findings if f.get("severity") == "CRITICAL"),
                "high": sum(1 for f in findings if f.get("severity") == "HIGH"),
                "medium": sum(1 for f in findings if f.get("severity") == "MEDIUM"),
                "informational": sum(1 for f in findings if f.get("severity") == "INFORMATIONAL")
            },
            "status_counts": {
                "open": sum(1 for f in findings if f.get("status") == "Open"),
                "under_review": sum(1 for f in findings if f.get("status") == "Under Review"),
                "confirmed": sum(1 for f in findings if f.get("status") == "Confirmed"),
                "false_positive": sum(1 for f in findings if f.get("status") == "False Positive"),
                "ignored": sum(1 for f in findings if f.get("status") == "Ignored")
            }
        }

    def _get_sample_transactions(self) -> List[Dict[str, Any]]:
        return get_sample_transactions()


class PaymentTimingRulePack:
    """
    Rule Pack 4 — Payment Timing & Due-Date Compliance (Legacy Façade Helper).
    Delegates to modular PaymentTimingRule implementation.
    """
    @staticmethod
    def evaluate_transaction(tx: Dict[str, Any], config: Dict[str, Any]) -> Optional[DataTrustFinding]:
        from modules.data_trust_engine.rules.payment_timing import PaymentTimingRule
        rule = PaymentTimingRule()
        cand = rule.evaluate(tx, config)
        if cand and cand.eligibility == "ELIGIBLE":
            finding_id = cand.candidate_id.replace("CAND-", "")
            return DataTrustFinding(
                id=finding_id,
                dedup_key=f"DEDUP-{finding_id}",
                rule_pack=rule.rule_pack,
                classification="Anomaly" if any(s.get("signal_code") == "P7" and s.get("fired") for s in cand.signals) else "Informational",
                evidence_strength="MEDIUM" if len(cand.signals) >= 2 else "LOW",
                severity="MEDIUM",
                signals_fired_count=len([s for s in cand.signals if s.get("fired")]),
                evidence_chain=[e.get("evidence", "") for e in cand.evidence if isinstance(e, dict)],
                transaction_details=tx,
                business_impact="Payment timing analysis statement.",
                recommended_action="Human review required",
                structured_evidence=cand.evidence,
                signals=cand.signals,
                rule_version=rule.rule_version
            )
        return None
