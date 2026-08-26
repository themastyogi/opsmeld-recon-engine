"""
Supporting structured models for Data Trust Engine.
DataTrustFinding remains canonically defined in MCP/modules/data_trust.py during migration.
"""
from dataclasses import dataclass, field
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
    company_name: str = "CRONUS IN"
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
