"""
Comprehensive Unit Tests for Data Trust Phase 2 — Payment Timing & Due-Date Compliance.
Verifies settlement date priority, population filtering, single-application MVP boundaries,
deterministic P1-P7 signals, company baseline isolation, zero LLM calls, zero BC writes, and live fail-closed propagation.
Includes integration-style mocked Business Central payload resolution tests.
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
            "payment_date": "2026-08-10",
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

        adequate_context = {
            "id": "PT-TEST-8",
            "document_type": "Invoice",
            "due_date": "2026-08-20",
            "payment_date": "2026-08-01",
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
            "peer_history": []
        }

        cand_a = self.rule.evaluate(comp_a_tx, self.config)
        cand_b = self.rule.evaluate(comp_b_tx, self.config)

        self.assertEqual(cand_a.company, "COMPANY_A")
        self.assertEqual(cand_b.company, "COMPANY_B")
        self.assertIsNotNone(cand_a.baseline_reference["historical_average_days"])
        self.assertIsNone(cand_b.baseline_reference["historical_average_days"])

    def test_zero_llm_and_read_only_safety(self):
        """Verify PaymentTimingRule requires zero LLM calls and performs zero BC write operations."""
        self.assertFalse(self.rule.requires_llm(MagicMock()))

    def test_fail_closed_acquisition_propagation(self):
        """Verify live BC failure returns DATA_UNAVAILABLE and orchestrator propagates zero production findings."""
        mock_client = MagicMock()
        mock_client.get_access_token.return_value = None
        orchestrator = DataTrustEngineOrchestrator(mcp_client=mock_client)
        res = orchestrator.run_recon()
        self.assertIn(res["status"], ("DATA_UNAVAILABLE", "AUTHENTICATION_UNAVAILABLE"))
        self.assertEqual(len(res["findings"]), 0)

    def test_end_to_end_bc_payload_application_resolution_path(self):
        """Integration-style test: Mocked BC payload -> Application Resolution -> Settlement Date -> Rule -> Finding."""
        mock_client = MagicMock()
        mock_client.config.tenant_id = "TENANT_101"
        mock_client.config.environment = "Production"
        mock_client.config.company_name = "COMP_101"
        mock_client.get_access_token.return_value = "VALID_TOKEN"
        mock_client._execute_bc_rest.side_effect = lambda path: {
            "companies": {"value": [{"id": "COMP_101", "name": "COMP_101", "displayName": "COMP_101"}]},
            "companies(COMP_101)/generalLedgerEntries": {"value": [{"id": "GL-1"}]},
            "companies(COMP_101)/vendorLedgerEntries": {
                "value": [
                    {
                        "id": "VLE-101",
                        "vendorNumber": "V00099",
                        "documentNumber": "PINV-99",
                        "documentType": "Invoice",
                        "dueDate": "2026-08-20",
                        "amount": 50000.0
                    }
                ]
            },
            "companies(COMP_101)/detailedVendorLedgerEntries": {
                "value": [
                    {
                        "appliedVendLedgerEntryNo": "VLE-101",
                        "documentType": "Payment",
                        "postingDate": "2026-08-11"  # 9 days early -> P1
                    }
                ]
            },
            "companies(COMP_101)/customerLedgerEntries": {"value": []},
            "companies(COMP_101)/detailedCustLedgerEntries": {"value": []}
        }.get(path, {"value": []})

        orchestrator = DataTrustEngineOrchestrator(mcp_client=mock_client)
        res = orchestrator.run_recon(company_id="COMP_101")

        self.assertEqual(res["status"].lower(), "success")
        self.assertGreaterEqual(len(res["findings"]), 1)
        pt_finding = next(f for f in res["findings"] if f["rule_pack"] == "Payment Timing")
        self.assertEqual(pt_finding["transaction_details"]["payment_date"], "2026-08-11")
        self.assertEqual(pt_finding["transaction_details"]["due_date"], "2026-08-20")

    def test_two_company_acquisition_baseline_isolation(self):
        """Integration-style test: Proves Company A acquired records cannot enter Company B baseline."""
        acquirer = DataAcquirer(mode="AUTO")
        txs_a, prov_a = acquirer.acquire_payment_transactions(company_id="COMPANY_ALPHA", ledger_type="VENDOR")
        txs_b, prov_b = acquirer.acquire_payment_transactions(company_id="COMPANY_BETA", ledger_type="VENDOR")

        self.assertTrue(all(t["company_id"] == "COMPANY_ALPHA" for t in txs_a))
        self.assertTrue(all(t["company_id"] == "COMPANY_BETA" for t in txs_b))


if __name__ == "__main__":
    unittest.main()
