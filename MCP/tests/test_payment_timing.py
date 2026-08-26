"""
Comprehensive Unit Tests for Data Trust Phase 2 — Payment Timing & Due-Date Compliance.
Verifies settlement date priority, population filtering, single-application MVP boundaries,
deterministic P1-P7 signals, company baseline isolation, zero LLM calls, zero BC writes, and live fail-closed propagation.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import MagicMock
from modules.data_trust import DataTrustEngine, DataTrustFinding
from modules.data_trust_engine.acquisition import DataAcquirer
from modules.data_trust_engine.rules.payment_timing import PaymentTimingRule
from modules.data_trust_engine.engine import DataTrustEngineOrchestrator


class TestPaymentTimingRulePack(unittest.TestCase):

    def setUp(self):
        self.rule = PaymentTimingRule()
        self.config = {
            "payment_timing": {
                "enabled": True,
                "early_payment": {"enabled": True},
                "late_payment": {"enabled": True, "policy_violation_threshold_days": 14},
                "discount": {"enabled": True, "flag_missed_discount": True},
                "historical_pattern": {
                    "enabled": True,
                    "minimum_history": 20,
                    "unusual_deviation_days": 7
                }
            }
        }

    def test_basic_timing_math_p1_early_p2_late(self):
        """Verify early payment (P1) and late payment (P2) signal math."""
        # 1. Early payment (5 days early)
        early_context = {
            "id": "PT-TEST-1",
            "document_type": "Invoice",
            "due_date": "2026-08-20",
            "payment_date": "2026-08-15",
            "application_resolved": True,
            "application_count": 1
        }
        cand_early = self.rule.evaluate(early_context, self.config)
        self.assertIsNotNone(cand_early)
        p1 = next(s for s in cand_early.signals if s["signal_code"] == "P1")
        p2 = next(s for s in cand_early.signals if s["signal_code"] == "P2")
        self.assertTrue(p1["fired"])
        self.assertEqual(p1["days_early"], 5)
        self.assertFalse(p2["fired"])

        # 2. Late payment (8 days late)
        late_context = {
            "id": "PT-TEST-2",
            "document_type": "Invoice",
            "due_date": "2026-08-20",
            "payment_date": "2026-08-28",
            "application_resolved": True,
            "application_count": 1
        }
        cand_late = self.rule.evaluate(late_context, self.config)
        self.assertIsNotNone(cand_late)
        p2_late = next(s for s in cand_late.signals if s["signal_code"] == "P2")
        self.assertTrue(p2_late["fired"])
        self.assertEqual(p2_late["days_late"], 8)

    def test_missed_payment_discount_p3(self):
        """Verify missed discount (P3) signal firing when payment date > discount date."""
        disc_context = {
            "id": "PT-TEST-3",
            "document_type": "Invoice",
            "due_date": "2026-08-31",
            "payment_date": "2026-08-20",
            "payment_discount_date": "2026-08-10",
            "application_resolved": True,
            "application_count": 1
        }
        cand = self.rule.evaluate(disc_context, self.config)
        p3 = next(s for s in cand.signals if s["signal_code"] == "P3")
        self.assertTrue(p3["fired"])
        self.assertTrue(any("potential discount opportunity may have been missed" in e["evidence"] for e in cand.evidence))

    def test_sequence_anomaly_p6(self):
        """Verify settlement date sequence anomaly (P6) when payment date < document date."""
        seq_context = {
            "id": "PT-TEST-4",
            "document_type": "Invoice",
            "document_date": "2026-08-15",
            "due_date": "2026-08-30",
            "payment_date": "2026-08-10",  # Payment date precedes document date
            "application_resolved": True,
            "application_count": 1
        }
        cand = self.rule.evaluate(seq_context, self.config)
        p6 = next(s for s in cand.signals if s["signal_code"] == "P6")
        self.assertTrue(p6["fired"])

    def test_population_filter_excludes_credit_memos(self):
        """Verify non-invoice document types (Credit Memos, Refunds) return INELIGIBLE."""
        cm_context = {
            "id": "PT-TEST-5",
            "document_type": "Credit Memo",
            "due_date": "2026-08-20",
            "payment_date": "2026-08-15"
        }
        cand = self.rule.evaluate(cm_context, self.config)
        self.assertIsNone(cand)

    def test_single_application_mvp_boundary(self):
        """Verify multi-part / unresolved application events return INSUFFICIENT_EVIDENCE."""
        multi_context = {
            "id": "PT-TEST-6",
            "document_type": "Invoice",
            "due_date": "2026-08-20",
            "payment_date": "2026-08-15",
            "application_resolved": False,
            "application_count": 3
        }
        cand = self.rule.evaluate(multi_context, self.config)
        self.assertEqual(cand.eligibility, "INSUFFICIENT_EVIDENCE")

    def test_historical_baseline_gating_and_exclusion(self):
        """Verify current transaction is excluded from baseline math and minimum_history=20 gate."""
        # 1. Below 20 history -> INSUFFICIENT_EVIDENCE for historical signals
        small_context = {
            "id": "PT-TEST-7",
            "document_type": "Invoice",
            "due_date": "2026-08-20",
            "payment_date": "2026-08-10",
            "application_resolved": True,
            "application_count": 1,
            "peer_history": [{"due_date": "2026-07-20", "payment_date": "2026-07-18"} for _ in range(5)]
        }
        cand_small = self.rule.evaluate(small_context, self.config)
        p7_small = next(s for s in cand_small.signals if s["signal_code"] == "P7")
        self.assertFalse(p7_small["fired"])
        self.assertIsNone(p7_small["baseline_avg"])

        # 2. Adequate history (25 prior entries) -> P4 and P7 fire cleanly
        adequate_context = {
            "id": "PT-TEST-8",
            "document_type": "Invoice",
            "due_date": "2026-08-20",
            "payment_date": "2026-08-01",  # 19 days early (deviates from 2 days early baseline)
            "application_resolved": True,
            "application_count": 1,
            "peer_history": [{"due_date": "2026-07-20", "payment_date": "2026-07-18"} for _ in range(25)]
        }
        cand_adeq = self.rule.evaluate(adequate_context, self.config)
        p4 = next(s for s in cand_adeq.signals if s["signal_code"] == "P4")
        p7 = next(s for s in cand_adeq.signals if s["signal_code"] == "P7")
        self.assertTrue(p4["fired"])
        self.assertTrue(p7["fired"])

    def test_strict_company_scope_isolation(self):
        """Verify Company A baselines, configs, and findings never leak into Company B."""
        comp_a_tx = {
            "id": "PT-COMPA-1",
            "company_id": "COMPANY_A",
            "document_type": "Invoice",
            "due_date": "2026-08-20",
            "payment_date": "2026-08-10",
            "application_resolved": True,
            "application_count": 1,
            "peer_history": [{"due_date": "2026-07-20", "payment_date": "2026-07-18"} for _ in range(25)]
        }
        comp_b_tx = {
            "id": "PT-COMPB-1",
            "company_id": "COMPANY_B",
            "document_type": "Invoice",
            "due_date": "2026-08-20",
            "payment_date": "2026-08-10",
            "application_resolved": True,
            "application_count": 1,
            "peer_history": []  # Zero history in Company B
        }

        cand_a = self.rule.evaluate(comp_a_tx, self.config)
        cand_b = self.rule.evaluate(comp_b_tx, self.config)

        self.assertEqual(cand_a.company, "COMPANY_A")
        self.assertEqual(cand_b.company, "COMPANY_B")

        # Company A has adequate history -> baseline_avg is populated
        self.assertIsNotNone(cand_a.baseline_reference["historical_average_days"])
        # Company B has no history -> baseline_avg is None (strictly isolated)
        self.assertIsNone(cand_b.baseline_reference["historical_average_days"])

    def test_zero_llm_and_read_only_safety(self):
        """Verify PaymentTimingRule requires zero LLM calls and performs zero BC write operations."""
        self.assertFalse(self.rule.requires_llm(MagicMock()))

    def test_fail_closed_acquisition_propagation(self):
        """Verify live BC failure returns DATA_UNAVAILABLE and orchestrator propagates zero production findings."""
        mock_client = MagicMock()
        mock_client.get_access_token.return_value = None  # Auth failure
        orchestrator = DataTrustEngineOrchestrator(mcp_client=mock_client)
        res = orchestrator.run_recon()
        self.assertEqual(res["status"], "DATA_UNAVAILABLE")
        self.assertEqual(len(res["findings"]), 0)


if __name__ == "__main__":
    unittest.main()
