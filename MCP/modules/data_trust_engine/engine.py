"""
DataTrustEngine orchestrator inside modular package data_trust_engine.
Executes complete pipeline: authorization gate -> population routing -> rule candidates -> optional LLM -> canonical finding.
Generates unique run_id correlation IDs, per-rule execution status tracking, and server-authorized diagnostic models.
"""
import datetime
import time
import uuid
from typing import Optional, Dict, Any, List
from core.bc_mcp_client import BCMCPClient
from core.config_loader import load_client_config
from modules.data_trust_engine.models import DataTrustFinding
from modules.data_trust_engine.config import DataTrustConfigManager
from modules.data_trust_engine.acquisition import DataAcquirer
from modules.data_trust_engine.authorization import CompanyAccessManager
from modules.data_trust_engine.company_context import DataTrustState, RuleExecutionStatus, build_user_message
from modules.data_trust_engine.llm_interpreter import LLMInterpreter
from modules.data_trust_engine.rules.posting_date import PostingDatePolicyRule
from modules.data_trust_engine.rules.subledger_bypass import SubledgerBypassRule
from modules.data_trust_engine.rules.narration_context import NarrationContextRule
from modules.data_trust_engine.rules.payment_timing import PaymentTimingRule
from modules.data_trust_engine.rules.inventory_costing import InventoryCostingRule


class DataTrustEngineOrchestrator:
    def __init__(self, mcp_client: Optional[BCMCPClient] = None, client_key: Optional[str] = None):
        self.client = mcp_client
        self.client_key = client_key or load_client_config().client_key
        self.acquirer = DataAcquirer(mcp_client=mcp_client)
        self.auth_mgr = CompanyAccessManager()
        self.interpreter = LLMInterpreter()
        self.config_mgr = DataTrustConfigManager(self.client_key)
        self.rules = [
            PostingDatePolicyRule(),
            SubledgerBypassRule(),
            NarrationContextRule(),
            PaymentTimingRule(),
            InventoryCostingRule()
        ]

    def run_recon(self, company_id: Optional[str] = None, session_info: Optional[Dict[str, Any]] = None, sample_transactions: Optional[List[Dict[str, Any]]] = None, mode: str = 'AUTO') -> Dict[str, Any]:
        """
        Executes end-to-end reconciliation:
        Server Gate -> Population Routing -> Candidate Evaluation -> Canonical Finding.
        Returns rich structured execution response.
        """
        start_time = time.time()
        run_id = f"DT-{datetime.date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        self.acquirer.mode = mode

        # Step 1: Server-Side Company Authorization Gate
        is_auth, auth_state, auth_info = self.auth_mgr.validate_company_access(self.client, company_id, session_info, run_id=run_id, mode=mode)

        target_comp_id = auth_info.get("company_id") or company_id
        target_comp_name = auth_info.get("company_name") or auth_info.get("company_id") or company_id

        if is_auth and mode not in ("TEST_FIXTURE", "DEMO_FIXTURE") and (not target_comp_id or not target_comp_name):
            is_auth = False
            auth_state = DataTrustState.CONFIGURATION_MISSING
            auth_info["message"] = build_user_message(DataTrustState.CONFIGURATION_MISSING, run_id=run_id)

        rule_status: Dict[str, str] = {
            "POSTING_DATE": RuleExecutionStatus.NOT_RUN,
            "SUBLEDGER_BYPASS": RuleExecutionStatus.NOT_RUN,
            "NARRATION_CONTEXT": RuleExecutionStatus.NOT_RUN,
            "PAYMENT_TIMING": RuleExecutionStatus.NOT_RUN,
            "INVENTORY_COSTING": RuleExecutionStatus.NOT_RUN
        }

        if not is_auth:
            user_msg = auth_info.get("message") or build_user_message(auth_state, run_id=run_id)
            diag = None
            if auth_info.get("http_status"):
                diag = {
                    "http_status": auth_info.get("http_status"),
                    "error_code": "AccessDenied",
                    "error_message": user_msg,
                    "endpoint": "companies",
                    "timestamp": datetime.datetime.now().isoformat()
                }
            return {
                "run_id": run_id,
                "status": auth_state,
                "tenant_id": self.client_key,
                "company_id": target_comp_id,
                "company_name": target_comp_name,
                "findings": [],
                "rule_status": {k: RuleExecutionStatus.ACCESS_DENIED for k in rule_status},
                "message": user_msg,
                "diagnostics": diag,
                "run_summary": {
                    "records_scanned": 0,
                    "candidates_generated": 0,
                    "llm_calls": 0,
                    "findings_generated": 0,
                    "duration_seconds": round(time.time() - start_time, 2),
                    "data_source": "DATA_UNAVAILABLE"
                }
            }

        # Step 2: Load & Validate Authoritative Configuration
        config = self.config_mgr.load_config()
        config["tenant_id"] = self.client_key

        if config.get("_is_valid") is False:
            logger.error(f"Invalid Data Trust configuration: {config.get('_validation_errors')}")
            for r in self.rules:
                if r.rule_id == "posting_date_policy": rule_status["POSTING_DATE"] = RuleExecutionStatus.CONFIGURATION_MISSING
                elif r.rule_id == "subledger_bypass": rule_status["SUBLEDGER_BYPASS"] = RuleExecutionStatus.CONFIGURATION_MISSING
                elif r.rule_id == "narration_context": rule_status["NARRATION_CONTEXT"] = RuleExecutionStatus.CONFIGURATION_MISSING
                elif r.rule_id == "payment_timing": rule_status["PAYMENT_TIMING"] = RuleExecutionStatus.CONFIGURATION_MISSING
                elif r.rule_id == "inventory_costing": rule_status["INVENTORY_COSTING"] = RuleExecutionStatus.CONFIGURATION_MISSING
            return []

        # Step 3: Population Routing by rule.required_data_source
        gl_rules = [r for r in self.rules if getattr(r, "required_data_source", "GENERAL_LEDGER") == "GENERAL_LEDGER" and r.enabled]
        pt_rules = [r for r in self.rules if getattr(r, "required_data_source", "GENERAL_LEDGER") == "PAYMENT_TRANSACTIONS" and r.enabled]

        gl_txs: List[Dict[str, Any]] = []
        gl_provenance = "AUTO"
        pt_txs: List[Dict[str, Any]] = []
        pt_provenance = "AUTO"

        if sample_transactions is not None:
            gl_txs = sample_transactions
            gl_provenance = "SNAPSHOT_SEED"
            for r in gl_rules:
                if r.rule_id == "posting_date_policy": rule_status["POSTING_DATE"] = RuleExecutionStatus.SUCCESS
                elif r.rule_id == "subledger_bypass": rule_status["SUBLEDGER_BYPASS"] = RuleExecutionStatus.SUCCESS
                elif r.rule_id == "narration_context": rule_status["NARRATION_CONTEXT"] = RuleExecutionStatus.SUCCESS
        elif gl_rules:
            gl_txs, gl_provenance = self.acquirer.acquire_transactions()
            if gl_provenance == "DATA_UNAVAILABLE":
                for r in gl_rules:
                    if r.rule_id == "posting_date_policy": rule_status["POSTING_DATE"] = RuleExecutionStatus.DATA_UNAVAILABLE
                    elif r.rule_id == "subledger_bypass": rule_status["SUBLEDGER_BYPASS"] = RuleExecutionStatus.DATA_UNAVAILABLE
                    elif r.rule_id == "narration_context": rule_status["NARRATION_CONTEXT"] = RuleExecutionStatus.DATA_UNAVAILABLE
            else:
                for r in gl_rules:
                    if r.rule_id == "posting_date_policy": rule_status["POSTING_DATE"] = RuleExecutionStatus.SUCCESS
                    elif r.rule_id == "subledger_bypass": rule_status["SUBLEDGER_BYPASS"] = RuleExecutionStatus.SUCCESS
                    elif r.rule_id == "narration_context": rule_status["NARRATION_CONTEXT"] = RuleExecutionStatus.SUCCESS

        if pt_rules:
            pt_lb = config.get("payment_timing", {}).get("historical_pattern", {}).get("lookback_months")
            pt_txs, pt_provenance = self.acquirer.acquire_payment_transactions(company_id=target_comp_id, lookback_months=pt_lb)
            if pt_provenance == "DATA_UNAVAILABLE":
                rule_status["PAYMENT_TIMING"] = RuleExecutionStatus.DATA_UNAVAILABLE
            else:
                rule_status["PAYMENT_TIMING"] = RuleExecutionStatus.SUCCESS

        ic_rules = [r for r in self.rules if getattr(r, "required_data_source", "GENERAL_LEDGER") == "INVENTORY_COST_TRANSACTIONS" and r.enabled]
        ic_txs: List[Dict[str, Any]] = []
        ic_provenance = "AUTO"

        if ic_rules:
            lookback_months = config.get("inventory_costing", {}).get("historical_pattern", {}).get("lookback_months")
            ic_txs, ic_provenance = self.acquirer.acquire_inventory_cost_transactions(company_id=target_comp_id, lookback_months=lookback_months)
            if ic_provenance == "DATA_UNAVAILABLE":
                rule_status["INVENTORY_COSTING"] = RuleExecutionStatus.DATA_UNAVAILABLE
            else:
                rule_status["INVENTORY_COSTING"] = RuleExecutionStatus.SUCCESS

        candidates = []
        findings: List[DataTrustFinding] = []
        llm_calls_count = 0

        for tx in gl_txs:
            for rule in gl_rules:
                cand = rule.evaluate(tx, config)
                if cand and cand.eligibility == "ELIGIBLE":
                    candidates.append((rule, cand))

        for ptx in pt_txs:
            for rule in pt_rules:
                cand = rule.evaluate(ptx, config)
                if cand and cand.eligibility == "ELIGIBLE":
                    candidates.append((rule, cand))

        for ictx in ic_txs:
            for rule in ic_rules:
                ictx["historical_transactions"] = ic_txs
                cand_or_finding = rule.evaluate(ictx, config)
                if cand_or_finding:
                    if isinstance(cand_or_finding, DataTrustFinding):
                        findings.append(cand_or_finding)
                    elif getattr(cand_or_finding, "eligibility", "") == "ELIGIBLE":
                        candidates.append((rule, cand_or_finding))

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
            
            classification = cand.classification or "Informational"
            severity = cand.severity or ("HIGH" if classification == "Policy Violation" else ("INFORMATIONAL" if classification == "Informational" else "MEDIUM"))
            if not cand.classification and not cand.severity:
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
                dedup_key=cand.dedup_key or f"DEDUP-{finding_id}",
                rule_pack=rule.rule_pack,
                classification=classification,
                evidence_strength=cand.evidence_strength or ("HIGH" if len(cand.signals) >= 3 else ("MEDIUM" if len(cand.signals) >= 2 else "LOW")),
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

        # Step 3: Determine overall execution status
        unavail_count = sum(1 for st in rule_status.values() if st == RuleExecutionStatus.DATA_UNAVAILABLE)
        success_count = sum(1 for st in rule_status.values() if st == RuleExecutionStatus.SUCCESS)

        if unavail_count == len(rule_status):
            overall_status = DataTrustState.DATA_UNAVAILABLE
            message = build_user_message(DataTrustState.DATA_UNAVAILABLE, run_id=run_id)
        elif unavail_count > 0 and success_count > 0:
            overall_status = DataTrustState.PARTIAL
            message = build_user_message(DataTrustState.PARTIAL, run_id=run_id, detail=f" {unavail_count} rule pack(s) unavailable.")
        elif len(findings) == 0:
            overall_status = DataTrustState.NO_FINDINGS
            message = build_user_message(DataTrustState.NO_FINDINGS, run_id=run_id)
        else:
            overall_status = DataTrustState.SUCCESS
            message = build_user_message(DataTrustState.SUCCESS, run_id=run_id)

        total_scanned = len(gl_txs) + len(pt_txs)
        main_provenance = pt_provenance if pt_rules else gl_provenance

        return {
            "run_id": run_id,
            "status": overall_status,
            "tenant_id": self.client_key,
            "company_id": target_comp_id,
            "company_name": target_comp_name,
            "findings": [f.to_dict() for f in findings],
            "rule_status": rule_status,
            "message": message,
            "diagnostics": None,  # Clean runs omit diagnostics
            "run_summary": {
                "records_scanned": total_scanned,
                "candidates_generated": len(candidates),
                "llm_calls": llm_calls_count,
                "findings_generated": len(findings),
                "duration_seconds": round(time.time() - start_time, 2),
                "data_source": main_provenance
            }
        }
