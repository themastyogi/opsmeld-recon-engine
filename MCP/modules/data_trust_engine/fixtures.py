"""
Opsmeld Data Trust — Synthetic & Demo Test Fixtures Module.
Isolated fixture data generator for offline preview, integration testing, and demo execution modes.
Production acquisition code must NEVER depend on fixture builders.
"""
from datetime import date, timedelta
from typing import Any, Dict, List, Optional


def get_sample_transactions(company_id: Optional[str] = None) -> List[Dict[str, Any]]:
    comp_prefix = "IN"
    multiplier = 1.0
    comp_name = "CRONUS IN"
    if company_id:
        if "c37ac1c0" in company_id or "US" in company_id or "My Company" in company_id:
            comp_prefix = "US"
            multiplier = 1.8
            comp_name = "My Company"
        elif "c4e0106b" in company_id or "Sandbox" in company_id or "Europe" in company_id:
            comp_prefix = "SB"
            multiplier = 0.6
            comp_name = "Sandbox"

    today_str = date.today().isoformat()
    past_str = (date.today() - timedelta(days=15)).isoformat()
    future_str = (date.today() + timedelta(days=10)).isoformat()

    adequate_peer_history = [
        {"account_no": "60100", "vendor_name": f"{comp_name} Supplies", "narration": f"[{comp_name}] Office paper and pens", "amount": 120.0 * multiplier},
        {"account_no": "60100", "vendor_name": f"{comp_name} Supplies", "narration": f"[{comp_name}] Printer toner cartridge", "amount": 250.0 * multiplier},
    ] * 12

    small_peer_history = [
        {"account_no": "60300", "vendor_name": "ChemTech Corp", "narration": f"[{comp_name}] Solvent supply", "amount": 180.0 * multiplier},
    ] * 4

    return [
        # TX-1001: Independent Subledger Bypass (Rule Pack 2 ONLY) -> HIGH Policy Violation, zero Narration mismatch
        {
            "id": f"TX-{comp_prefix}-1001",
            "document_no": f"GJV-{comp_prefix}-2026-0891",
            "account_no": "10200",
            "gl_account_no": "10200",
            "account_name": f"[{comp_name}] Accounts Payable Control",
            "posting_date": today_str,
            "amount": round(45000.00 * multiplier, 2),
            "user": f"JSMITH_{comp_prefix}",
            "source_code": "GENJNL",
            "document_type": "General Journal",
            "narration": f"[{comp_name}] Standard AP control ledger adjustment",
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
