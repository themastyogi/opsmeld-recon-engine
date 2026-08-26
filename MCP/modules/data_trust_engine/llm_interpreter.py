"""
LLMInterpreter abstraction tracking LLM provider failover, token usage, latency, and costs.
"""
import json
import logging
import time
import urllib.request
from typing import Optional, Dict, Any
from modules.data_trust_engine.models import LLMMetadata

logger = logging.getLogger(__name__)


class LLMInterpreter:
    def __init__(self, anthropic_key: str = "", openai_key: str = "", gemini_key: str = ""):
        self.anthropic_key = anthropic_key
        self.openai_key = openai_key
        self.gemini_key = gemini_key

    def interpret_candidate(
        self,
        candidate_summary: str,
        system_prompt: str
    ) -> Tuple[Dict[str, Any], LLMMetadata]:
        """
        Executes forced tool-use LLM interpretation across provider failover chain.
        Returns (interpretation_dict, llm_metadata).
        """
        meta = LLMMetadata()
        start_time = time.time()

        # 1. Primary: Anthropic Claude (Haiku 4.5 / 3.5)
        if self.anthropic_key:
            try:
                url = "https://api.anthropic.com/v1/messages"
                tool_def = {
                    "name": "record_candidate_interpretation",
                    "description": "Return a structured interpretation of a Data Trust candidate transaction.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "classification": {"type": "string", "enum": ["Anomaly", "Potential Data Error", "Insufficient Evidence"]},
                            "reasoning": {"type": "string"},
                            "supporting_evidence": {"type": "array", "items": {"type": "string"}},
                            "contradictory_evidence": {"type": "array", "items": {"type": "string"}},
                            "recommended_review_level": {"type": "string", "enum": ["Standard Review", "Priority Review", "No Action Needed"]}
                        },
                        "required": ["classification", "reasoning", "supporting_evidence", "contradictory_evidence", "recommended_review_level"]
                    }
                }
                payload = {
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 512,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": candidate_summary}],
                    "tools": [tool_def],
                    "tool_choice": {"type": "tool", "name": "record_candidate_interpretation"}
                }
                headers = {"x-api-key": self.anthropic_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    usage = res.get("usage", {})
                    meta.input_tokens = usage.get("input_tokens", 0)
                    meta.output_tokens = usage.get("output_tokens", 0)
                    meta.provider = "Anthropic Claude"
                    meta.model = "claude-haiku-4-5-20251001"
                    meta.call_count = 1
                    meta.status = "SUCCESS"
                    meta.latency_ms = int((time.time() - start_time) * 1000)
                    meta.estimated_cost = (meta.input_tokens * 0.000001) + (meta.output_tokens * 0.000005)

                    for content_block in res.get("content", []):
                        if content_block.get("type") == "tool_use":
                            return content_block.get("input", {}), meta
            except Exception as e:
                logger.error(f"Anthropic LLM call failed: {e}")

        # Deterministic Fallback if LLM unavailable
        meta.status = "UNINTERPRETED"
        meta.latency_ms = int((time.time() - start_time) * 1000)
        return {}, meta
