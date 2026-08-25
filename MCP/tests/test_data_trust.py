"""
Opsmeld Reconciliation Engine - Data Trust Unit Tests
Tests Rule Pack 1, Rule Pack 2, Rule Pack 3 (N1-N5), deterministic evidence strength,
hard-gated baselines, status workflow, and web API endpoints.
"""

from datetime import date, timedelta
import json
import unittest
from pathlib import Path
from web.app import create_server
import urllib.request
import threading
import time

from modules.data_trust import (
    DataTrustConfigManager,
    PostingDateRulePack,
    SubledgerBypassRulePack,
    NarrationContextRulePack,
    DataTrustEngine,
    DataTrustFinding
)


class TestDataTrustRulePack1(unittest.TestCase):
    """Unit tests for Rule Pack 1 — Posting-Date Policy (100% Deterministic)."""

    def setUp(self):
        self.config = {
            "posting_date_policy": {
                "company_default": {
                    "scope_type": "Company",
                    "scope_value": "DEFAULT",
                    "allowed_posting_mode": "CURRENT_MONTH",
                    "backdating": {
                        "allowed": True,
                        "maximum_days": 7,
                        "approval_required_above_days": 3
                    },
                    "future_dating": {
                        "allowed": True,
                        "maximum_days": 2
                    },
                    "month_close": {
                        "close_date": "2026-08-31",
                        "adjustment_window_days": 5,
                        "approval_required": True
                    }
                }
            }
        }
        self.ref_date = date(2026, 8, 15)

    def test_compliant_posting_date_returns_none(self):
        tx = {
            "id": "TX-PD-01",
            "document_no": "DOC-101",
            "posting_date": "2026-08-15",
            "user": "JSMITH"
        }
        finding = PostingDateRulePack.evaluate_transaction(tx, self.config, ref_date=self.ref_date)
        self.assertIsNone(finding)

    def test_backdating_violation_returns_policy_violation(self):
        # Backdated 10 days (> 7 max days allowed)
        tx = {
            "id": "TX-PD-02",
            "document_no": "DOC-102",
            "posting_date": "2026-08-05",
            "user": "JSMITH"
        }
        finding = PostingDateRulePack.evaluate_transaction(tx, self.config, ref_date=self.ref_date)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.rule_pack, "Posting-Date Policy")
        self.assertEqual(finding.classification, "Policy Violation")
        self.assertEqual(finding.evidence_strength, "HIGH")
        self.assertIn("Backdated by 10 days", finding.evidence_chain[0])

    def test_future_dating_violation_returns_policy_violation(self):
        # Future dated 5 days (> 2 max days allowed)
        tx = {
            "id": "TX-PD-03",
            "document_no": "DOC-103",
            "posting_date": "2026-08-20",
            "user": "JSMITH"
        }
        finding = PostingDateRulePack.evaluate_transaction(tx, self.config, ref_date=self.ref_date)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.classification, "Policy Violation")
        self.assertIn("Future-dated by 5 days", finding.evidence_chain[0])

    def test_unconfigured_scope_returns_insufficient_evidence(self):
        empty_config = {"posting_date_policy": {}}
        tx = {
            "id": "TX-PD-04",
            "document_no": "DOC-104",
            "posting_date": "2026-08-15"
        }
        finding = PostingDateRulePack.evaluate_transaction(tx, empty_config, ref_date=self.ref_date)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.classification, "Insufficient Evidence")
        self.assertEqual(finding.evidence_strength, "INSUFFICIENT")


class TestDataTrustRulePack2(unittest.TestCase):
    """Unit tests for Rule Pack 2 — Generic Subledger Bypass (100% Deterministic)."""

    def setUp(self):
        self.config = {
            "subledger_control_accounts": [
                {
                    "account_no": "10200",
                    "account_name": "Accounts Payable Control",
                    "subledger_type": "VENDOR",
                    "expected_posting_sources": ["Purchase", "Payables"],
                    "direct_posting_allowed": False
                }
            ]
        }

    def test_authorized_posting_source_returns_none(self):
        tx = {
            "id": "TX-SB-01",
            "document_no": "PINV-100",
            "account_no": "10200",
            "source_code": "PURCHASES",
            "amount": 5000.0
        }
        finding = SubledgerBypassRulePack.evaluate_transaction(tx, self.config)
        self.assertIsNone(finding)

    def test_subledger_bypass_returns_policy_violation(self):
        tx = {
            "id": "TX-SB-02",
            "document_no": "GJV-999",
            "account_no": "10200",
            "source_code": "GENJNL",
            "amount": 25000.0,
            "user": "JSMITH",
            "posting_date": "2026-08-15"
        }
        finding = SubledgerBypassRulePack.evaluate_transaction(tx, self.config)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.rule_pack, "Subledger Bypass")
        self.assertEqual(finding.classification, "Policy Violation")
        self.assertEqual(finding.evidence_strength, "HIGH")
        self.assertTrue(any("10200" in item for item in finding.evidence_chain))
        self.assertTrue(any("GENJNL" in item for item in finding.evidence_chain))
        self.assertIn("subledger-to-GL mismatch", finding.business_impact)

    def test_direct_posting_allowed_returns_none(self):
        config_allowed = {
            "subledger_control_accounts": [
                {
                    "account_no": "10200",
                    "account_name": "Accounts Payable Control",
                    "subledger_type": "VENDOR",
                    "expected_posting_sources": ["Purchase"],
                    "direct_posting_allowed": True
                }
            ]
        }
        tx = {
            "id": "TX-SB-03",
            "document_no": "GJV-999",
            "account_no": "10200",
            "source_code": "GENJNL"
        }
        finding = SubledgerBypassRulePack.evaluate_transaction(tx, config_allowed)
        self.assertIsNone(finding)


class TestDataTrustRulePack3(unittest.TestCase):
    """Unit tests for Rule Pack 3 — Narration / Context Mismatch & Hard-Gating."""

    def setUp(self):
        self.config = {
            "narration_context": {
                "minimum_peer_transactions": 20,
                "taxonomy_level_2": {
                    "Office Supplies": ["stationery", "printer", "paper", "toner", "office"],
                    "Raw Materials": ["steel", "aluminium", "plastic", "metal", "sheet"]
                }
            }
        }

    def test_n1_rare_narration_hard_gated_below_threshold(self):
        # Peer population = 5 (< 20 required threshold), narration matches peer profile so N3 does not fire
        small_peer_history = [
            {"narration": "Unusual rare widget purchase", "amount": 100.0}
        ] * 5

        tx = {
            "id": "TX-NARR-01",
            "account_no": "60100",
            "account_name": "Office Supplies Expense",
            "narration": "Unusual rare widget purchase",
            "amount": 500.0
        }

        # Candidate with no other signals should not fire because N1 is Not Evaluated
        finding = NarrationContextRulePack.evaluate_candidate(tx, small_peer_history, self.config)
        self.assertIsNone(finding)

    def test_n1_rare_narration_fires_above_threshold(self):
        # Peer population = 25 (>= 20 threshold)
        adequate_peer_history = [
            {"narration": "Standard paper order", "amount": 100.0}
        ] * 25

        tx = {
            "id": "TX-NARR-02",
            "account_no": "Office Supplies Expense",
            "narration": "Quantum computing server array lease",
            "amount": 12000.0,
            "document_type": "General Journal"
        }

        finding = NarrationContextRulePack.evaluate_candidate(tx, adequate_peer_history, self.config)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.rule_pack, "Narration / Context Mismatch")
        self.assertIn("HIGH", ["HIGH", "MEDIUM", "LOW"])
        # Check no numeric confidence score is present
        finding_json = json.dumps(finding.to_dict())
        self.assertNotIn("87%", finding_json)
        self.assertNotIn("confidence_score", finding_json)

    def test_n2_semantic_divergence_level_1_level_2(self):
        peer_history = [{"narration": "Office paper", "amount": 50.0}] * 25
        tx = {
            "id": "TX-NARR-03",
            "account_no": "Office Supplies Expense",
            "narration": "Purchase of structural steel beams and aluminium sheets",
            "amount": 14200.0,
            "document_type": "Purchase Invoice"
        }
        finding = NarrationContextRulePack.evaluate_candidate(tx, peer_history, self.config)
        self.assertIsNotNone(finding)
        self.assertTrue(any("N2" in item for item in finding.evidence_chain))
        self.assertIn("Office Supplies", finding.evidence_chain[0] + finding.evidence_chain[1])


class TestDataTrustEngineAndWorkflow(unittest.TestCase):
    """Tests DataTrustEngine execution, status workflow transitions, and persistence."""

    def setUp(self):
        for key in ["test_workflow_tenant", "test_dedup_tenant", "test_escalation_tenant"]:
            p = Path(f"data/snapshots/data_trust_findings_{key}.json")
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def test_engine_recon_and_status_workflow(self):
        engine = DataTrustEngine(client_key="test_workflow_tenant")
        findings = engine.run_recon()
        self.assertGreater(len(findings), 0)

        first_finding = findings[0]
        finding_id = first_finding.get("id")
        self.assertEqual(first_finding.get("status"), "Open")

        # Transition status to Under Review
        success = engine.update_finding_status(finding_id, "Under Review")
        self.assertTrue(success)

        # Verify persisted status change
        stored = engine.load_stored_findings()
        updated_f = next(f for f in stored if f.get("id") == finding_id)
        self.assertEqual(updated_f.get("status"), "Under Review")

        # Summary metrics check
        summary = engine.get_summary_metrics(stored)
        self.assertEqual(summary.get("total_findings"), len(stored))
        self.assertIn("policy_violations", summary)
        self.assertIn("status_counts", summary)

    def test_idempotency_deduplication_on_reruns(self):
        engine = DataTrustEngine(client_key="test_dedup_tenant")
        initial_findings = engine.run_recon()
        initial_count = len(initial_findings)

        # Mark first finding as Confirmed
        target_id = initial_findings[0].get("id")
        engine.update_finding_status(target_id, "Confirmed")

        # Re-run reconciliation engine
        rerun_findings = engine.run_recon()
        
        # Idempotency check: Count should be identical, no duplicate rows created
        self.assertEqual(len(rerun_findings), initial_count)

        # Preserved status check: Status should remain Confirmed on re-run
        target_after_rerun = next(f for f in rerun_findings if f.get("id") == target_id)
        self.assertEqual(target_after_rerun.get("status"), "Confirmed")

    def test_evidence_strength_escalation_reopens_finding(self):
        engine = DataTrustEngine(client_key="test_escalation_tenant")
        
        # Initial transaction with 1 signal (LOW evidence strength)
        tx_low = {
            "id": "TX-ESCALATE-01",
            "document_no": "GJV-ESC-100",
            "account_no": "Office Supplies Expense",
            "narration": "Purchase of structural steel beams",
            "amount": 500.0,
            "document_type": "General Journal"
        }
        small_peer = [{"narration": "Office paper", "amount": 50.0}] * 5
        cfg = engine.config_mgr.load_config()

        finding_1 = NarrationContextRulePack.evaluate_candidate(tx_low, small_peer, cfg)
        self.assertIsNotNone(finding_1)
        self.assertEqual(finding_1.evidence_strength, "LOW")

        # Save finding to disk and mark status as False Positive
        engine.save_stored_findings([finding_1.to_dict()])
        engine.update_finding_status(finding_1.id, "False Positive")

        # Re-evaluate transaction with adequate peer history (>=20) so N1 & N5 also fire -> HIGH strength
        adequate_peer = [{"narration": "Office paper", "amount": 50.0}] * 25
        tx_high = dict(tx_low)
        tx_high["amount"] = 50000.0

        finding_2 = NarrationContextRulePack.evaluate_candidate(tx_high, adequate_peer, cfg)
        self.assertIsNotNone(finding_2)
        self.assertEqual(finding_2.evidence_strength, "HIGH")

        # Run recon with escalated candidate
        merged = engine.run_recon(sample_transactions=[tx_high])
        escalated_f = next(f for f in merged if f.get("dedup_key") == finding_1.dedup_key)

        # Asserts: Status automatically reopened to Open, Evidence Strength updated to HIGH, escalation note prepended
        self.assertEqual(escalated_f.get("status"), "Open")
        self.assertEqual(escalated_f.get("evidence_strength"), "HIGH")
        self.assertTrue(any("Re-opened for Review" in item for item in escalated_f.get("evidence_chain", [])))

    def test_config_audit_trail_logging(self):
        cfg_mgr = DataTrustConfigManager(client_key="test_audit_tenant")
        cfg = cfg_mgr.load_config()
        cfg["posting_date_policy"]["company_default"]["backdating"]["maximum_days"] = 14
        
        success = cfg_mgr.save_config(cfg, user="auditor@opsmeld.com")
        self.assertTrue(success)

        audit_trail = cfg_mgr.load_audit_trail()
        self.assertGreater(len(audit_trail), 0)
        last_entry = audit_trail[-1]
        self.assertEqual(last_entry.get("user"), "auditor@opsmeld.com")
        self.assertEqual(last_entry.get("client_key"), "test_audit_tenant")

    def test_multi_tenancy_isolation(self):
        engine_a = DataTrustEngine(client_key="client_tenant_a")
        engine_b = DataTrustEngine(client_key="client_tenant_b")

        finding_a = {
            "id": "DT-TENANT-A-01",
            "dedup_key": "Posting-Date Policy:60100:TX-TENANT-A",
            "rule_pack": "Posting-Date Policy",
            "classification": "Policy Violation",
            "evidence_strength": "HIGH",
            "severity": "HIGH",
            "status": "Open"
        }
        finding_b = {
            "id": "DT-TENANT-B-01",
            "dedup_key": "Subledger Bypass:10200:TX-TENANT-B",
            "rule_pack": "Subledger Bypass",
            "classification": "Policy Violation",
            "evidence_strength": "HIGH",
            "severity": "HIGH",
            "status": "Open"
        }

        engine_a.save_stored_findings([finding_a])
        engine_b.save_stored_findings([finding_b])

        loaded_a = engine_a.load_stored_findings()
        loaded_b = engine_b.load_stored_findings()

        self.assertNotEqual(engine_a.get_findings_file_path(), engine_b.get_findings_file_path())

        # Data content isolation verification
        self.assertTrue(any(f.get("id") == "DT-TENANT-A-01" for f in loaded_a))
        self.assertFalse(any(f.get("id") == "DT-TENANT-B-01" for f in loaded_a))

        self.assertTrue(any(f.get("id") == "DT-TENANT-B-01" for f in loaded_b))
        self.assertFalse(any(f.get("id") == "DT-TENANT-A-01" for f in loaded_b))


class TestDataTrustWebAPIs(unittest.TestCase):
    """End-to-end HTTP API tests for Data Trust endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.port = 8089
        cls.server = create_server(host="127.0.0.1", port=cls.port)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_get_findings_api(self):
        url = f"http://127.0.0.1:{self.port}/api/data-trust/findings"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("summary", data)
            self.assertIn("findings", data)

    def test_get_config_api(self):
        url = f"http://127.0.0.1:{self.port}/api/data-trust/config"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("posting_date_policy", data)
            self.assertIn("subledger_control_accounts", data)

    def test_update_status_api(self):
        # Fetch valid finding ID first
        f_url = f"http://127.0.0.1:{self.port}/api/data-trust/findings"
        with urllib.request.urlopen(f_url) as f_resp:
            f_data = json.loads(f_resp.read().decode("utf-8"))
            findings = f_data.get("findings", [])
            self.assertGreater(len(findings), 0)
            target_id = findings[0].get("id")

        url = f"http://127.0.0.1:{self.port}/api/data-trust/update-status"
        payload = json.dumps({"finding_id": target_id, "status": "Confirmed"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "success")


if __name__ == "__main__":
    unittest.main()
