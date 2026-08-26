"""
DataTrustRule abstract base class contract.
Rules produce candidate objects, not final findings.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from modules.data_trust_engine.candidate import CandidateTransaction


class DataTrustRule(ABC):
    rule_id: str
    rule_version: str = "1.0"
    rule_pack: str
    enabled: bool = True

    @abstractmethod
    def assess_eligibility(self, context: Dict[str, Any]) -> str:
        """Returns ELIGIBLE, INSUFFICIENT_EVIDENCE, or INELIGIBLE."""
        pass

    @abstractmethod
    def evaluate(self, context: Dict[str, Any], config: Dict[str, Any]) -> Optional[CandidateTransaction]:
        """Evaluates context and returns a CandidateTransaction if an exception candidate is detected."""
        pass

    @abstractmethod
    def requires_llm(self, candidate: CandidateTransaction) -> bool:
        """Determines if candidate requires LLM interpretation."""
        pass
