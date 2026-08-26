"""
DataTrustEngine orchestrator inside modular package data_trust_engine.
"""
from typing import Optional, Dict, Any, List
from core.bc_mcp_client import BCMCPClient
from core.config_loader import load_client_config
from modules.data_trust_engine.acquisition import DataAcquirer
from modules.data_trust_engine.llm_interpreter import LLMInterpreter
from modules.data_trust_engine.rules.posting_date import PostingDatePolicyRule
from modules.data_trust_engine.rules.subledger_bypass import SubledgerBypassRule
from modules.data_trust_engine.rules.narration_context import NarrationContextRule


class DataTrustEngineOrchestrator:
    def __init__(self, mcp_client: Optional[BCMCPClient] = None, client_key: Optional[str] = None):
        self.client = mcp_client
        self.client_key = client_key or load_client_config().client_key
        self.acquirer = DataAcquirer(mcp_client=mcp_client)
        self.interpreter = LLMInterpreter()
        self.rules = [
            PostingDatePolicyRule(),
            SubledgerBypassRule(),
            NarrationContextRule()
        ]
