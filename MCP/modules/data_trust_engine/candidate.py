"""
CandidateTransaction model produced by deterministic rule evaluation.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass
class CandidateTransaction:
    candidate_id: str
    rule_id: str
    rule_version: str
    tenant: str
    company: str
    source_record: Dict[str, Any]
    eligibility: str = "ELIGIBLE"  # ELIGIBLE | INSUFFICIENT_EVIDENCE | INELIGIBLE
    baseline_reference: Optional[Dict[str, Any]] = None
    signals: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    requires_llm: bool = False
