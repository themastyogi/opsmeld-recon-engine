"""
Opsmeld Data Trust — Platform State Model & Conditional Error Mapping Module.
Defines explicit user states, rule-level execution statuses, and support reference (run_id) messaging.
"""
from typing import Optional, Dict, Any, List


class DataTrustState:
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    ACCESS_DENIED = "ACCESS_DENIED"
    AUTHENTICATION_UNAVAILABLE = "AUTHENTICATION_UNAVAILABLE"
    COMPANY_NOT_FOUND = "COMPANY_NOT_FOUND"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    DATA_REQUEST_INVALID = "DATA_REQUEST_INVALID"
    CONFIGURATION_MISSING = "CONFIGURATION_MISSING"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_FINDINGS = "NO_FINDINGS"


class RuleExecutionStatus:
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    ACCESS_DENIED = "ACCESS_DENIED"
    CONFIGURATION_MISSING = "CONFIGURATION_MISSING"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DISABLED = "DISABLED"
    NOT_RUN = "NOT_RUN"


def build_user_message(state: str, run_id: Optional[str] = None, detail: Optional[str] = None) -> str:
    """Builds a business-friendly user message with optional support reference (run_id)."""
    ref_suffix = f" Reference: {run_id}" if run_id else ""
    if detail:
        return f"Business Central data error: {detail}.{ref_suffix}"

    messages = {
        DataTrustState.SUCCESS: "Analysis complete.",
        DataTrustState.PARTIAL: f"Analysis completed with limited data. Some rule checks could not be evaluated.{ref_suffix}",
        DataTrustState.ACCESS_DENIED: f"You don't have permission to view Data Trust data for this company.{ref_suffix}",
        DataTrustState.AUTHENTICATION_UNAVAILABLE: f"Business Central authentication is unavailable. Please sign in again.{ref_suffix}",
        DataTrustState.COMPANY_NOT_FOUND: f"The selected company could not be found in Business Central.{ref_suffix}",
        DataTrustState.DATA_UNAVAILABLE: f"Business Central data could not be retrieved. No Data Trust findings were generated.{ref_suffix}",
        DataTrustState.DATA_REQUEST_INVALID: f"Unable to retrieve Business Central data.{ref_suffix}",
        DataTrustState.CONFIGURATION_MISSING: f"Data Trust is not fully configured for this company.{ref_suffix}",
        DataTrustState.INSUFFICIENT_EVIDENCE: f"Not enough historical data or evidence is available to complete analysis. No finding was generated.",
        DataTrustState.NO_FINDINGS: f"No Data Trust issues were identified for the selected company and period."
    }
    return messages.get(state, f"Status: {state}.{ref_suffix}")


def map_http_error(
    http_status: int,
    error_code: Optional[str] = None,
    is_company_resolution: bool = False,
    endpoint: Optional[str] = None,
    run_id: Optional[str] = None,
    detail: Optional[str] = None
) -> Dict[str, Any]:
    """
    Conditional HTTP error mapping with explicit error detail.
    """
    if http_status == 401:
        st = DataTrustState.AUTHENTICATION_UNAVAILABLE
    elif http_status == 403:
        st = DataTrustState.ACCESS_DENIED
    elif http_status == 404:
        st = DataTrustState.COMPANY_NOT_FOUND if is_company_resolution else DataTrustState.DATA_REQUEST_INVALID
    elif http_status == 400:
        st = DataTrustState.DATA_REQUEST_INVALID
    else:
        st = DataTrustState.DATA_UNAVAILABLE

    msg = build_user_message(st, run_id=run_id, detail=detail)
    return {
        "status": st,
        "message": msg,
        "http_status": http_status,
        "error_code": error_code
    }
