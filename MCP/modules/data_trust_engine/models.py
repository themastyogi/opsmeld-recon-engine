"""
Supporting structured models for Data Trust Engine.
DataTrustFinding, StructuredEvidence, SourceMetadata, LLMMetadata canonical definitions.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List


@dataclass
class StructuredEvidence:
    evidence_id: str
    source_system: str = "Business Central"
    entity_table: str = ""
    record_id: str = ""
    field_name: str = ""
    observed_value: Any = None
    expected_value: Any = None
    baseline_ref: Optional[str] = None
    rule_signal: str = ""
    timestamp: str = ""
    explanation: str = ""


@dataclass
class SourceMetadata:
    tenant_id: str = "default_tenant"
    company_name: str = "default_company"
    source_endpoint: str = ""
    retrieved_at: str = ""
    provenance_state: str = "SNAPSHOT_SEED"  # LIVE_BUSINESS_CENTRAL | SNAPSHOT_SEED | DATA_UNAVAILABLE


@dataclass
class LLMMetadata:
    provider: str = ""
    model: str = ""
    prompt_version: str = "1.0"
    call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    estimated_cost: float = 0.0
    status: str = "UNINTERPRETED"  # SUCCESS | UNINTERPRETED | INSUFFICIENT_EVIDENCE


@dataclass
class DataTrustFinding:
    id: str
    dedup_key: str
    rule_pack: str  # "Posting-Date Policy" | "Subledger Bypass" | "Narration / Context Mismatch" | "Payment Timing & Compliance"
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
