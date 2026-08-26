"""
DataTrustEngine orchestrator inside modular package data_trust_engine.
Executes complete pipeline: rule -> candidate -> optional LLM -> canonical finding.
Supports population routing via rule.required_data_source (GENERAL_LEDGER vs PAYMENT_TRANSACTIONS).
"""
import time
from typing import Optional, Dict, Any, List
from core.bc_mcp_client import BCMCPClient
from core.config_loader import load_client_config
from modules.data_trust import DataTrustFinding, DataTrustConfigManager
from modules.data_trust_engine.acquisition import DataAcquirer
from modules.data_trust_engine.llm_interpreter import LLMInterpreter
from modules.data_trust_engine.rules.posting_date import PostingDatePolicyRule
from modules.data_trust_engine.rules.subledger_bypass import SubledgerBypassRule
from modules.data_trust_engine.rules.narration_context import NarrationContextRule
from modules.data_trust_engine.rules.payment_timing import PaymentTimingRule


class DataTrustEngineOrchestrator:
    def __init__(self, mcp_client: Optional[BCMCPClient] = None, client_key: Optional[str] = None):
        self.client = mcp_client
        self.client_key = client_key or load_client_config().client_key
        self.acquirer = DataAcquirer(mcp_client=mcp_client)
        self.interpreter = LLMInterpreter()
        self.config_mgr = DataTrustConfigManager(self.client_key)
        self.rules = [
            PostingDatePolicyRule(),
            SubledgerBypassRule(),
            NarrationContextRule(),
            PaymentTimingRule()
        ]

    def run_recon(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes end-to-end reconciliation:
        DataAcquirer -> Population Routing by rule.required_data_source -> Rule Candidate -> Optional LLM -> Canonical Finding.
        Returns execution summary dict with status and findings list.
        """
        start_time = time.time()

        # Categorize rules by required_data_source
        gl_rules = [r for r in self.rules if getattr(r, "required_data_source", "GENERAL_LEDGER") == "GENERAL_LEDGER" and r.enabled]
        pt_rules = [r for r in self.rules if getattr(r, "required_data_source", "GENERAL_LEDGER") == "PAYMENT_TRANSACTIONS" and r.enabled]

        gl_txs: List[Dict[str, Any]] = []
        gl_provenance = "AUTO"
        pt_txs: List[Dict[str, Any]] = []
        pt_provenance = "AUTO"

        if gl_rules:
            gl_txs, gl_provenance = self.acquirer.acquire_transactions()
            if gl_provenance == "DATA_UNAVAILABLE":
                return {
                    "status": "DATA_UNAVAILABLE",
                    "findings": [],
                    "run_summary": {
                        "records_scanned": 0,
                        "candidates_generated": 0,
                        "llm_calls": 0,
                        "findings_generated": 0,
                        "duration_seconds": round(time.time() - start_time, 2),
                        "data_source": "DATA_UNAVAILABLE"
                    }
                }

        if pt_rules:
            pt_txs, pt_provenance = self.acquirer.acquire_payment_transactions(company_id=company_id)
            if pt_provenance == "DATA_UNAVAILABLE":
                return {
                    "status": "DATA_UNAVAILABLE",
                    "findings": [],
                    "run_summary": {
                        "records_scanned": 0,
                        "candidates_generated": 0,
                        "llm_calls": 0,
                        "findings_generated": 0,
                        "duration_seconds": round(time.time() - start_time, 2),
                        "data_source": "DATA_UNAVAILABLE"
                    }
                }

        config = self.config_mgr.load_config()
        config["tenant_id"] = self.client_key
        candidates = []

        # Population Routing: GENERAL_LEDGER population to gl_rules
        for tx in gl_txs:
            for rule in gl_rules:
                cand = rule.evaluate(tx, config)
                if cand and cand.eligibility == "ELIGIBLE":
                    candidates.append((rule, cand))

        # Population Routing: PAYMENT_TRANSACTIONS population to pt_rules
        for ptx in pt_txs:
            for rule in pt_rules:
                cand = rule.evaluate(ptx, config)
                if cand and cand.eligibility == "ELIGIBLE":
                    candidates.append((rule, cand))

        findings: List[DataTrustFinding] = []
        llm_calls_count = 0

        for rule, cand in candidates:
            llm_info = None
            if cand.requires_llm and rule.requires_llm(cand):
                summary = f"Transaction {cand.source_record.get('id')}: {cand.source_record.get('narration')}"
                sys_prompt = "You are an expert Data Trust reconciliation engine."
                interp, meta = self.interpreter.interpret_candidate(summary, sys_prompt)
                llm_info = meta.__dict__
                if meta.status == "SUCCESS":
                    llm_calls_count += 1

            finding_id = cand.candidate_id.replace("CAND-", "")
            
            classification = "Informational"
            severity = "MEDIUM"
            if any(s.get("signal_code") == "P6" and s.get("fired") for s in cand.signals):
                classification = "Potential Data Error"
                severity = "HIGH"
            elif any(s.get("signal_code") == "P7" and s.get("fired") for s in cand.signals):
                classification = "Anomaly"
                severity = "MEDIUM"
            elif cand.rule_id == "subledger_bypass":
                classification = "Policy Violation"
                severity = "HIGH"
            elif cand.requires_llm:
                classification = "Anomaly"
                severity = "MEDIUM"

            prov = pt_provenance if rule.required_data_source == "PAYMENT_TRANSACTIONS" else gl_provenance
            finding = DataTrustFinding(
                id=finding_id,
                dedup_key=f"DEDUP-{finding_id}",
                rule_pack=rule.rule_pack,
                classification=classification,
                evidence_strength="HIGH" if len(cand.signals) >= 3 else ("MEDIUM" if len(cand.signals) >= 2 else "LOW"),
                severity=severity,
                signals_fired_count=len([s for s in cand.signals if s.get("fired")]),
                evidence_chain=[e.get("evidence", "") for e in cand.evidence if isinstance(e, dict)],
                transaction_details=cand.source_record,
                business_impact="Requires review to verify payment timing, discount eligibility, and cash control alignment.",
                recommended_action="Human review required",
                data_source=prov,
                structured_evidence=cand.evidence,
                signals=cand.signals,
                source_metadata={"tenant_id": cand.tenant, "company": cand.company, "provenance_state": prov},
                llm_metadata=llm_info,
                rule_version=rule.rule_version
            )
            findings.append(finding)

        total_scanned = len(gl_txs) + len(pt_txs)
        main_provenance = pt_provenance if pt_rules else gl_provenance
        return {
            "status": "success",
            "findings": [f.to_dict() for f in findings],
            "run_summary": {
                "records_scanned": total_scanned,
                "candidates_generated": len(candidates),
                "llm_calls": llm_calls_count,
                "findings_generated": len(findings),
                "duration_seconds": round(time.time() - start_time, 2),
                "data_source": main_provenance
            }
        }
