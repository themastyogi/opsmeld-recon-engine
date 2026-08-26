import logging
logger = logging.getLogger('opsmeld.data_trust')
"""
Opsmeld Reconciliation Engine - Data Trust Engine Module (Multi-Tenant & Idempotent)
Detects, validates, classifies, explains, and assesses business impact for Business Central data & transactions.
Enforces multi-tenant config scoping, dedup idempotency, audit trail logging, and single-pass candidate LLM interpretation.
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


@dataclass
class DataTrustFinding:
    id: str
    dedup_key: str
    rule_pack: str  # "Posting-Date Policy" | "Subledger Bypass" | "Narration / Context Mismatch"
    classification: str  # "Policy Violation" | "Anomaly" | "Potential Data Error" | "Informational" | "Insufficient Evidence"
    evidence_strength: str  # "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT"
    severity: str  # "CRITICAL" | "HIGH" | "MEDIUM" | "INFORMATIONAL"
    signals_fired_count: int
    evidence_chain: List[str]
    transaction_details: Dict[str, Any]
    business_impact: str
    recommended_action: str  # "Human review required"
    status: str = "Open"  # "Open" | "Under Review" | "Confirmed" | "False Positive" | "Ignored"
    data_source: str = "LIVE_BUSINESS_CENTRAL"  # "LIVE_BUSINESS_CENTRAL" | "SNAPSHOT_SEED"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_evaluated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    structured_evidence: List[Dict[str, Any]] = field(default_factory=list)
    signals: List[Dict[str, Any]] = field(default_factory=list)
    source_metadata: Optional[Dict[str, Any]] = None
    llm_metadata: Optional[Dict[str, Any]] = None
    rule_version: str = "1.0" 

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DataTrustConfigManager:
    """Manages loading, persisting, and auditing client-specific Data Trust configuration."""
    
    def __init__(self, client_key: Optional[str] = None):
        self.client_key = client_key or load_client_config().client_key
        self.config_path = CONFIG_DIR / f"data_trust_config_{self.client_key}.json"
        self.default_config_path = CONFIG_DIR / "data_trust_config.json"
        self.audit_log_path = BASE_DIR / "data" / "snapshots" / f"data_trust_config_audit_{self.client_key}.json"

    def load_config(self) -> Dict[str, Any]:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        if self.default_config_path.exists():
            try:
                with open(self.default_config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return self._default_config()

    def save_config(self, config_data: Dict[str, Any], user: str = "admin@opsmeld.com") -> bool:
        try:
            old_config = self.load_config()
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)

            self._log_audit_trail(old_config, config_data, user)
            return True
        except Exception:
            return False

    def load_audit_trail(self) -> List[Dict[str, Any]]:
        if self.audit_log_path.exists():
            try:
                with open(self.audit_log_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _log_audit_trail(self, old_cfg: Dict[str, Any], new_cfg: Dict[str, Any], user: str):
        try:
            audit_records = self.load_audit_trail()
            audit_records.append({
                "timestamp": datetime.now().isoformat(),
                "user": user,
                "client_key": self.client_key,
                "changes_summary": "Configuration updated via Admin Console",
                "old_config": old_cfg,
                "new_config": new_cfg
            })
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.audit_log_path, "w", encoding="utf-8") as f:
                json.dump(audit_records, f, indent=2)
        except Exception:
            pass

    def _default_config(self) -> Dict[str, Any]:
        return {
            "posting_date_policy": {
                "company_default": {
                    "scope_type": "Company",
                    "scope_value": "DEFAULT",
                    "allowed_posting_mode": "CURRENT_MONTH",
                    "backdating": {
                        "allowed": True,
                        "maximum_days": 7,
                        "approval_required_above_days": 3
                    },
                    "future_dating": {
                        "allowed": True,
                        "maximum_days": 2
                    },
                    "month_close": {
                        "close_date": "2026-08-31",
                        "adjustment_window_days": 5,
                        "approval_required": True
                    },
                    "year_close": {
                        "close_date": "2026-12-31",
                        "adjustment_window_days": 10,
                        "approval_required": True
                    }
                }
            },
            "subledger_control_accounts": [
                {
                    "account_no": "10200",
                    "account_name": "Accounts Payable Control",
                    "subledger_type": "VENDOR",
                    "expected_posting_sources": ["Purchase", "Payables", "Purchases", "VendorLedger"],
                    "direct_posting_allowed": False
                },
                {
                    "account_no": "10100",
                    "account_name": "Accounts Receivable Control",
                    "subledger_type": "CUSTOMER",
                    "expected_posting_sources": ["Sales", "Receivables", "CustLedger"],
                    "direct_posting_allowed": False
                },
                {
                    "account_no": "10500",
                    "account_name": "Inventory Control Account",
                    "subledger_type": "ITEM",
                    "expected_posting_sources": ["Inventory", "Purchase", "Sales", "ItemLedger"],
                    "direct_posting_allowed": False
                },
                {
                    "account_no": "20100",
                    "account_name": "Bank Account Control",
                    "subledger_type": "BANK",
                    "expected_posting_sources": ["Bank", "Cash Receipt", "Payment"],
                    "direct_posting_allowed": False
                }
            ],
            "narration_context": {
                "minimum_peer_transactions": 20,
                "taxonomy_level_2": {
                    "Office Supplies": ["stationery", "printer", "paper", "toner", "furniture", "desk", "chair", "pen", "office"],
                    "Raw Materials": ["steel", "aluminium", "aluminum", "plastic", "metal", "sheet", "resin", "copper", "raw material"],
                    "Professional Fees": ["legal", "audit", "consulting", "advisory", "tax", "accounting", "attorney", "retainer"],
                    "IT Hardware & Software": ["laptop", "monitor", "keyboard", "server", "cable", "memory", "storage", "software", "license"],
                    "Travel & Entertainment": ["flight", "hotel", "taxi", "meal", "travel", "lodging", "uber", "airline"]
                }
            }
        }


class PostingDateRulePack:
    """
    Rule Pack 1 — Posting-Date Policy (100% Deterministic — No LLM).
    Evaluates transaction posting dates against scope policies, backdating/future-dating thresholds, and close windows.
    """
    
    @staticmethod
    def evaluate_transaction(tx: Dict[str, Any], config: Dict[str, Any], ref_date: Optional[date] = None) -> Optional[DataTrustFinding]:
        policies = config.get("posting_date_policy", {})
        tx_id = tx.get('id') or tx.get('document_no') or '000'
        
        if not policies:
            # Baseline policy not configured for scope -> INSUFFICIENT EVIDENCE
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


class SubledgerBypassRulePack:
    """
    Rule Pack 2 — Generic Subledger Bypass (100% Deterministic — No LLM).
    Detects direct G/L journal entries posted to control accounts outside permitted source codes.
    """

    @staticmethod
    def evaluate_transaction(tx: Dict[str, Any], config: Dict[str, Any]) -> Optional[DataTrustFinding]:
        control_accounts = config.get("subledger_control_accounts", [])
        if not control_accounts:
            return None

        account_no = str(tx.get("account_no") or tx.get("account_id") or tx.get("gl_account_no") or tx.get("G_L_Account_No") or "")
        if not account_no:
            return None

        matched_ctrl = None
        for ctrl in control_accounts:
            if str(ctrl.get("account_no")) == account_no:
                matched_ctrl = ctrl
                break

        if not matched_ctrl:
            return None

        source_code = str(tx.get("source_code") or tx.get("source") or tx.get("Source_Code") or tx.get("document_type") or "GENJNL")
        expected_sources = matched_ctrl.get("expected_posting_sources", [])
        direct_allowed = matched_ctrl.get("direct_posting_allowed", False)

        source_matched = any(exp.lower() in source_code.lower() for exp in expected_sources)

        if not source_matched and not direct_allowed:
            subledger_type = matched_ctrl.get("subledger_type", "OTHER")
            account_name = matched_ctrl.get("account_name", f"Account {account_no}")
            amount = tx.get("amount") or tx.get("amount_lcy") or 0.0
            user = tx.get("user") or tx.get("user_id") or "UNKNOWN"
            doc_no = tx.get("document_no") or tx.get("doc_no") or "N/A"
            tx_date = tx.get("posting_date") or tx.get("date") or "N/A"
            tx_id = tx.get('id') or doc_no

            evidence = [
                f"G/L Account {account_no} ({account_name}) is a mapped {subledger_type} Subledger Control Account.",
                f"Transaction posting source '{source_code}' is outside Expected Posting Sources: {expected_sources}.",
                f"Direct Posting Allowed flag is set to False for Account {account_no}.",
                f"Transaction context: Document '{doc_no}', Amount ${float(amount):,.2f}, Posted by User '{user}' on Date '{tx_date}'."
            ]

            reconcil_impact = (
                f"Direct G/L bypass on Control Account {account_no} creates a subledger-to-GL mismatch for {subledger_type} subledger. "
                f"Subledger reports will fail to reconcile with General Ledger balance by ${float(amount):,.2f}."
            )

            return DataTrustFinding(
                id=f"DT-BYPASS-{tx_id}",
                dedup_key=f"Subledger Bypass:{account_no}:{tx_id}",
                rule_pack="Subledger Bypass",
                classification="Policy Violation",
                evidence_strength="HIGH",
                severity="HIGH",
                signals_fired_count=len(evidence),
                evidence_chain=evidence,
                transaction_details=tx,
                business_impact=reconcil_impact,
                recommended_action="Human review required (never auto-corrected)"
            )

        return None


class NarrationContextRulePack:
    """
    Rule Pack 3 — Narration / Context Mismatch.
    Evaluates Candidate Transactions carrying signals N1–N5.
    Calculates Evidence Strength deterministically and executes single-pass LLM candidate interpretation.
    """

    @staticmethod
    def evaluate_candidate(
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

        llm_reasoning = NarrationContextRulePack._run_llm_interpretation(
            tx=tx,
            signals_fired=signals_fired,
            evidence_items=evidence_items,
            mcp_client=mcp_client
        )

        provider_name = llm_reasoning.get("provider", "Deterministic Rule Engine Fallback")
        evidence_items.append(f"[LLM Interpretation — {provider_name}] {llm_reasoning.get('explanation')}")

        classification = llm_reasoning.get("classification", "Anomaly")
        severity = "HIGH" if evidence_strength == "HIGH" else ("MEDIUM" if evidence_strength == "MEDIUM" else "INFORMATIONAL")

        impact = (
            f"Narration context mismatch detected for account '{account}' and entity '{entity}'. "
            f"Transactions with inconsistent description context may indicate misclassified expenses, incorrect cost allocation, or data entry errors."
        )

        return DataTrustFinding(
            id=f"DT-NARR-{tx_id}",
            dedup_key=f"Narration / Context Mismatch:{account}:{tx_id}",
            rule_pack="Narration / Context Mismatch",
            classification=classification,
            evidence_strength=evidence_strength,
            severity=severity,
            signals_fired_count=signal_count,
            evidence_chain=evidence_items,
            transaction_details=tx,
            business_impact=impact,
            recommended_action="Human review required (never auto-corrected)"
        )

    @staticmethod
    def _run_llm_interpretation(
        tx: Dict[str, Any],
        signals_fired: List[str],
        evidence_items: List[str],
        mcp_client: Optional[BCMCPClient] = None
    ) -> Dict[str, Any]:
        account = str(tx.get("account_no") or tx.get("account_name") or "GL Account")
        narration = str(tx.get("narration") or tx.get("description") or "N/A")
        amount = tx.get("amount") or 0.0

        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")
        gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

        provider = "Deterministic Rule Engine Fallback"
        classification = "Potential Data Error" if "N2" in str(signals_fired) else "Anomaly"
        reasoning = ""
        supporting_evidence = list(evidence_items)
        contradictory_evidence = ["No historical override recorded."]
        recommended_review_level = "Standard Review"

        system_prompt = (
            "You are the Opsmeld Data Trust Expert's interpretation layer.\n\n"
            "You will be given a candidate transaction and the deterministic evidence already gathered about it (which signals fired, and why).\n\n"
            "Your task: determine whether the transaction's context (narration, account, vendor, document type) is consistent or inconsistent with its historical accounting context, using ONLY the evidence supplied below.\n\n"
            "Rules:\n"
            "- Do not invent facts not present in the supplied evidence.\n"
            "- Do not determine whether the transaction is fraudulent — only whether the context is consistent or inconsistent.\n"
            "- If the supplied evidence is ambiguous or insufficient to support a conclusion, classify as 'Insufficient Evidence' rather than guessing.\n\n"
            "Call the record_candidate_interpretation tool with your answer."
        )

        user_content = (
            f"Candidate Transaction:\n"
            f"- Account: {account}\n"
            f"- Narration: {narration}\n"
            f"- Amount: ${float(amount):,.2f}\n"
            f"- Fired Deterministic Signals: {signals_fired}\n"
            f"- Evidence Chain:\n" + "\n".join(f"  * {item}" for item in evidence_items)
        )

        # 1. Primary Provider: Anthropic Claude API (Haiku / Sonnet) with Forced Tool Use
        if anthropic_key:
            try:
                import urllib.request
                url = "https://api.anthropic.com/v1/messages"
                tool_def = {
                    "name": "record_candidate_interpretation",
                    "description": "Return a structured interpretation of a Data Trust candidate transaction.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "classification": {
                                "type": "string",
                                "enum": ["Anomaly", "Potential Data Error", "Insufficient Evidence"]
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "2-3 sentence explanation grounded only in the supplied evidence."
                            },
                            "supporting_evidence": {
                                "type": "array",
                                "items": {"type": "string"}
                            },
                            "contradictory_evidence": {
                                "type": "array",
                                "items": {"type": "string"}
                            },
                            "recommended_review_level": {
                                "type": "string",
                                "enum": ["Standard Review", "Priority Review", "No Action Needed"]
                            }
                        },
                        "required": ["classification", "reasoning", "supporting_evidence", "contradictory_evidence", "recommended_review_level"]
                    }
                }
                payload = {
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 512,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_content}],
                    "tools": [tool_def],
                    "tool_choice": {"type": "tool", "name": "record_candidate_interpretation"}
                }
                headers = {
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    for content_block in res.get("content", []):
                        if content_block.get("type") == "tool_use":
                            tool_input = content_block.get("input", {})
                            classification = tool_input.get("classification", classification)
                            reasoning = tool_input.get("reasoning", "")
                            supporting_evidence = tool_input.get("supporting_evidence", supporting_evidence)
                            contradictory_evidence = tool_input.get("contradictory_evidence", contradictory_evidence)
                            recommended_review_level = tool_input.get("recommended_review_level", recommended_review_level)
                            provider = "Anthropic Claude (Haiku 3.5)"
                            break
            except Exception as e:
                logger.error(f'Anthropic LLM call failed: {e}')
                pass

        # 2. Fallback Provider 1: OpenAI API
        if not reasoning and openai_key:
            try:
                import urllib.request
                url = "https://api.openai.com/v1/chat/completions"
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    "temperature": 0.2
                }
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    r_data = json.loads(resp.read().decode("utf-8"))
                    reasoning = r_data["choices"][0]["message"]["content"].strip()
                    provider = "OpenAI (gpt-4o-mini)"
            except Exception as e:
                logger.error(f'OpenAI LLM call failed: {e}')
                pass

        # 3. Fallback Provider 2: Google Gemini API
        if not reasoning and gemini_key:
            try:
                import urllib.request
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
                payload = {"contents": [{"parts": [{"text": f"{system_prompt}\n\n{user_content}"}]}]}
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    r_data = json.loads(resp.read().decode("utf-8"))
                    reasoning = r_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    provider = "Google Gemini (1.5 Flash)"
            except Exception as e:
                logger.error(f'Gemini LLM call failed: {e}')
                pass

        # 4. Fallback Provider 3: Static Rule Engine Template
        if not reasoning:
            reasoning = (
                f"Candidate contextual analysis: Narration '{narration}' for account '{account}' "
                f"(Amount: ${float(amount):,.2f}) presents semantic divergence with historical accounting context. "
                f"Deterministic signals [{', '.join(signals_fired)}] fired with supporting evidence."
            )
            provider = "Deterministic Rule Engine Fallback"

        return {
            "classification": classification,
            "explanation": reasoning,
            "supporting_evidence": supporting_evidence,
            "contradictory_evidence": contradictory_evidence,
            "recommended_review_level": recommended_review_level,
            "provider": provider
        }


class DataTrustEngine:
    """Main orchestration engine for Data Trust Findings generation, multi-tenant persistence, and idempotency."""

    def __init__(self, mcp_client: Optional[BCMCPClient] = None, client_key: Optional[str] = None):
        self.client = mcp_client
        self.client_key = client_key or load_client_config().client_key
        self.config_mgr = DataTrustConfigManager(self.client_key)

    def get_findings_file_path(self) -> Path:
        p = BASE_DIR / "data" / "snapshots" / f"data_trust_findings_{self.client_key}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def fetch_live_bc_transactions(self) -> List[Dict[str, Any]]:
        """Queries live Business Central OData/REST endpoints for G/L entries and Purchase Invoices."""
        if not self.client:
            return []

        token = self.client.get_access_token()
        if not token:
            return []

        try:
            comp_resp = self.client._execute_bc_rest("companies")
            if not isinstance(comp_resp, dict) or "value" not in comp_resp or not comp_resp["value"]:
                return []

            comp_id = comp_resp["value"][0].get("id")
            if not comp_id:
                return []

            gl_resp = self.client._execute_bc_rest(f"companies({comp_id})/generalLedgerEntries?$top=100&$orderby=postingDate desc")
            gl_entries = gl_resp.get("value", []) if isinstance(gl_resp, dict) else []

            live_txs: List[Dict[str, Any]] = []

            peer_history_by_account: Dict[str, List[Dict[str, Any]]] = {}
            for gle in gl_entries:
                acc_no = str(gle.get("accountNumber") or gle.get("glAccountNumber") or gle.get("accountNo") or "")
                if acc_no:
                    if acc_no not in peer_history_by_account:
                        peer_history_by_account[acc_no] = []
                    peer_history_by_account[acc_no].append({
                        "account_no": acc_no,
                        "vendor_name": str(gle.get("vendorName") or gle.get("description") or ""),
                        "narration": str(gle.get("description") or gle.get("comment") or ""),
                        "amount": abs(float(gle.get("amount") or 0.0))
                    })

            for gle in gl_entries:
                acc_no = str(gle.get("accountNumber") or gle.get("glAccountNumber") or gle.get("accountNo") or "")
                tx_obj = {
                    "id": str(gle.get("id") or gle.get("entryNumber") or gle.get("documentNumber") or "GL-000"),
                    "document_no": str(gle.get("documentNumber") or gle.get("documentNo") or "DOC-000"),
                    "account_no": acc_no,
                    "gl_account_no": acc_no,
                    "account_name": str(gle.get("accountName") or gle.get("description") or f"G/L Account {acc_no}"),
                    "vendor_name": str(gle.get("vendorName") or gle.get("description") or ""),
                    "posting_date": str(gle.get("postingDate") or gle.get("documentDate") or date.today().isoformat()),
                    "amount": abs(float(gle.get("amount") or 0.0)),
                    "user": str(gle.get("userId") or gle.get("user") or "BC_USER"),
                    "source_code": str(gle.get("sourceCode") or gle.get("source") or "GENJNL"),
                    "document_type": str(gle.get("documentType") or gle.get("document_type") or "General Journal"),
                    "narration": str(gle.get("description") or gle.get("comment") or "Live BC Entry"),
                    "peer_history": peer_history_by_account.get(acc_no, [])
                }
                live_txs.append(tx_obj)

            return live_txs
        except Exception:
            return []

    def _load_from_disk(self) -> List[Dict[str, Any]]:
        p = self.get_findings_file_path()
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def load_stored_findings(self) -> List[Dict[str, Any]]:
        findings = self._load_from_disk()
        if not findings:
            return self.run_recon()
        return findings

    def save_stored_findings(self, findings: List[Dict[str, Any]]) -> bool:
        p = self.get_findings_file_path()
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(findings, f, indent=2)
            return True
        except Exception:
            return False

    def update_finding_status(self, finding_id: str, new_status: str) -> bool:
        valid_statuses = ["Open", "Under Review", "Confirmed", "False Positive", "Ignored"]
        if new_status not in valid_statuses:
            return False
        findings = self.load_stored_findings()
        updated = False
        for f in findings:
            if f.get("id") == finding_id:
                f["status"] = new_status
                f["last_evaluated_at"] = datetime.now().isoformat()
                updated = True
                break
        if updated:
            self.save_stored_findings(findings)
        return updated

    def run_recon(self, sample_transactions: Optional[List[Dict[str, Any]]] = None, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Legacy façade method delegating to DataTrustEngineOrchestrator inside data_trust_engine."""
        from modules.data_trust_engine.engine import DataTrustEngineOrchestrator
        orchestrator = DataTrustEngineOrchestrator(mcp_client=self.client, client_key=self.client_key)
        res = orchestrator.run_recon(company_id=company_id, sample_transactions=sample_transactions)

        if res.get("status") in ("DATA_UNAVAILABLE", "ACCESS_DENIED", "AUTHENTICATION_UNAVAILABLE", "COMPANY_NOT_FOUND"):
            return []

        newly_eval_findings = res.get("findings", [])
        if sample_transactions is not None and not newly_eval_findings:
            return []

        # Idempotent deduplication & status merging against existing stored findings
        existing_findings_raw = self._load_from_disk()
        existing_map = {f.get("dedup_key"): f for f in existing_findings_raw if f.get("dedup_key")}

        merged_findings: List[Dict[str, Any]] = []
        now_iso = datetime.now().isoformat()
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

        self.save_stored_findings(merged_findings)
        return merged_findings

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
        today_str = date.today().isoformat()
        past_str = (date.today() - timedelta(days=15)).isoformat()
        future_str = (date.today() + timedelta(days=10)).isoformat()

        adequate_peer_history = [
            {"account_no": "60100", "vendor_name": "Fabrikam Supplies", "narration": "Office paper and pens", "amount": 120.0},
            {"account_no": "60100", "vendor_name": "Fabrikam Supplies", "narration": "Printer toner cartridge", "amount": 250.0},
        ] * 12

        small_peer_history = [
            {"account_no": "60300", "vendor_name": "ChemTech Corp", "narration": "Solvent supply", "amount": 180.0},
        ] * 4

        return [
            # TX-1001: Independent Subledger Bypass (Rule Pack 2 ONLY) -> HIGH Policy Violation, zero Narration mismatch
            {
                "id": "TX-1001",
                "document_no": "GJV-2026-0891",
                "account_no": "10200",
                "gl_account_no": "10200",
                "account_name": "Accounts Payable Control",
                "posting_date": today_str,
                "amount": 45000.00,
                "user": "JSMITH",
                "source_code": "GENJNL",
                "document_type": "General Journal",
                "narration": "Standard AP control ledger adjustment",
                "peer_history": []
            },
            # TX-1002: Independent Narration Anomaly (Rule Pack 3 ONLY) -> HIGH Evidence Strength (3 signals: N2, N3, N5)
            {
                "id": "TX-1002",
                "document_no": "PINV-90412",
                "account_no": "60100",
                "gl_account_no": "60100",
                "account_name": "Office Supplies Expense",
                "vendor_name": "Fabrikam Supplies",
                "posting_date": today_str,
                "amount": 14200.00,
                "user": "MKUMAR",
                "source_code": "PURCHASES",
                "document_type": "Purchase Invoice",
                "narration": "Purchase of structural steel beams and aluminium sheets",
                "peer_history": adequate_peer_history
            },
            # TX-1003: Independent Posting-Date Policy Violation (Rule Pack 1 ONLY) -> Future-Dating Limit Exceeded
            {
                "id": "TX-1003",
                "document_no": "GJV-2026-0904",
                "account_no": "60200",
                "gl_account_no": "60200",
                "account_name": "Professional Legal Fees",
                "posting_date": future_str,
                "amount": 8500.00,
                "user": "JSMITH",
                "source_code": "GENJNL",
                "document_type": "General Journal",
                "narration": "Standard monthly legal retainer payment",
                "peer_history": []
            },
            # TX-1004: Independent Narration Anomaly (Rule Pack 3 ONLY) -> MEDIUM Evidence Strength (2 signals: N2, N3)
            {
                "id": "TX-1004",
                "document_no": "PINV-90425",
                "account_no": "60100",
                "gl_account_no": "60100",
                "account_name": "Office Supplies Expense",
                "vendor_name": "Fabrikam Supplies",
                "posting_date": today_str,
                "amount": 450.00,
                "user": "MKUMAR",
                "source_code": "PURCHASES",
                "document_type": "Purchase Invoice",
                "narration": "Quantum computing server array lease",
                "peer_history": adequate_peer_history
            },
            # TX-1005: Independent Narration Anomaly (Rule Pack 3 ONLY) -> LOW Evidence Strength (1 signal: N5 Amount Pattern Break)
            {
                "id": "TX-1005",
                "document_no": "PINV-90430",
                "account_no": "60500",
                "gl_account_no": "60500",
                "account_name": "Travel & Entertainment",
                "vendor_name": "Global Travel Corp",
                "posting_date": today_str,
                "amount": 18500.00,
                "user": "JSMITH",
                "source_code": "PURCHASES",
                "document_type": "Purchase Invoice",
                "narration": "Flight tickets and hotel accommodation",
                "peer_history": [
                    {"account_no": "60500", "vendor_name": "Global Travel Corp", "narration": "Flight tickets and hotel accommodation", "amount": 185.0}
                ] * 20
            },
            # TX-1006: Hard-gated Baseline Candidate (Rule Pack 3 ONLY) -> INSUFFICIENT EVIDENCE (peer count 4 < 20)
            {
                "id": "TX-1006",
                "document_no": "PINV-90433",
                "account_no": "60300",
                "gl_account_no": "60300",
                "account_name": "IT Hardware & Software",
                "vendor_name": "ChemTech Corp",
                "posting_date": today_str,
                "amount": 6200.00,
                "user": "JSMITH",
                "source_code": "PURCHASES",
                "document_type": "Purchase Invoice",
                "narration": "Specialized industrial chemical solvent purchase",
                "peer_history": small_peer_history
            },
            # TX-1007: Clean Compliant Transaction -> 0 Findings generated
            {
                "id": "TX-1007",
                "document_no": "PINV-90440",
                "account_no": "60100",
                "gl_account_no": "60100",
                "account_name": "Office Supplies Expense",
                "vendor_name": "Fabrikam Supplies",
                "posting_date": today_str,
                "amount": 180.00,
                "user": "MKUMAR",
                "source_code": "PURCHASES",
                "document_type": "Purchase Invoice",
                "narration": "Printer paper and office stationery",
                "peer_history": adequate_peer_history
            }
        ]

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
