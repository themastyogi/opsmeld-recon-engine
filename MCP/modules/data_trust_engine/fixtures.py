"""
Opsmeld Data Trust — Synthetic & Demo Test Fixtures Module.
Isolated fixture data generator for offline preview, integration testing, and demo execution modes.
Production acquisition code must NEVER depend on fixture builders.
"""
from datetime import date, timedelta
import hashlib
from typing import Any, Dict, List, Optional


def get_sample_transactions(company_id: Optional[str] = None) -> List[Dict[str, Any]]:
    comp_str = str(company_id or "DEFAULT_COMPANY")
    comp_hash = hashlib.md5(comp_str.encode("utf-8")).hexdigest()
    comp_prefix = comp_hash[:4].upper()
    seed_num = int(comp_hash[:4], 16)
    multiplier = round(0.5 + (seed_num % 250) / 100.0, 2)
    comp_name = comp_str[:20]

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
            "id": f"TX-{comp_prefix}-1002",
            "document_no": f"PINV-{comp_prefix}-90412",
            "account_no": "60100",
            "gl_account_no": "60100",
            "account_name": f"[{comp_name}] Office Supplies Expense",
            "vendor_name": f"{comp_name} Fabrikam Supplies",
            "posting_date": today_str,
            "amount": round(14200.00 * multiplier, 2),
            "user": f"MKUMAR_{comp_prefix}",
            "source_code": "PURCHASES",
            "document_type": "Purchase Invoice",
            "narration": f"[{comp_name}] Purchase of structural steel beams and aluminium sheets",
            "peer_history": adequate_peer_history
        },
        # TX-1003: Independent Posting-Date Policy Violation (Rule Pack 1 ONLY) -> Future-Dating Limit Exceeded
        {
            "id": f"TX-{comp_prefix}-1003",
            "document_no": f"GJV-{comp_prefix}-2026-0904",
            "account_no": "60200",
            "gl_account_no": "60200",
            "account_name": f"[{comp_name}] Professional Legal Fees",
            "posting_date": future_str,
            "amount": round(8500.00 * multiplier, 2),
            "user": f"JSMITH_{comp_prefix}",
            "source_code": "GENJNL",
            "document_type": "General Journal",
            "narration": f"[{comp_name}] Standard monthly legal retainer payment",
            "peer_history": []
        },
        # TX-1004: Independent Narration Anomaly (Rule Pack 3 ONLY) -> MEDIUM Evidence Strength (2 signals: N2, N3)
        {
            "id": f"TX-{comp_prefix}-1004",
            "document_no": f"PINV-{comp_prefix}-90425",
            "account_no": "60100",
            "gl_account_no": "60100",
            "account_name": f"[{comp_name}] Office Supplies Expense",
            "vendor_name": f"{comp_name} Fabrikam Supplies",
            "posting_date": today_str,
            "amount": round(450.00 * multiplier, 2),
            "user": f"MKUMAR_{comp_prefix}",
            "source_code": "PURCHASES",
            "document_type": "Purchase Invoice",
            "narration": f"[{comp_name}] Quantum computing server array lease",
            "peer_history": adequate_peer_history
        },
        # TX-1005: Independent Narration Anomaly (Rule Pack 3 ONLY) -> LOW Evidence Strength (1 signal: N5 Amount Pattern Break)
        {
            "id": f"TX-{comp_prefix}-1005",
            "document_no": f"PINV-{comp_prefix}-90430",
            "account_no": "60500",
            "gl_account_no": "60500",
            "account_name": f"[{comp_name}] Travel & Entertainment",
            "vendor_name": f"{comp_name} Global Travel Corp",
            "posting_date": today_str,
            "amount": round(18500.00 * multiplier, 2),
            "user": f"JSMITH_{comp_prefix}",
            "source_code": "PURCHASES",
            "document_type": "Purchase Invoice",
            "narration": f"[{comp_name}] Flight tickets and hotel accommodation",
            "peer_history": [
                {"account_no": "60500", "vendor_name": f"{comp_name} Global Travel Corp", "narration": f"[{comp_name}] Flight tickets and hotel accommodation", "amount": round(185.0 * multiplier, 2)}
            ] * 20
        },
        # TX-1006: Hard-gated Baseline Candidate (Rule Pack 3 ONLY) -> INSUFFICIENT EVIDENCE (peer count 4 < 20)
        {
            "id": f"TX-{comp_prefix}-1006",
            "document_no": f"PINV-{comp_prefix}-90433",
            "account_no": "60300",
            "gl_account_no": "60300",
            "account_name": f"[{comp_name}] IT Hardware & Software",
            "vendor_name": f"{comp_name} ChemTech Corp",
            "posting_date": today_str,
            "amount": round(6200.00 * multiplier, 2),
            "user": f"JSMITH_{comp_prefix}",
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
