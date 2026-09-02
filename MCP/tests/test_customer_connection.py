import os
import sys
import pathlib
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.customer_connection import CustomerConnection, CustomerConnectionRepository
from core.bc_mcp_client import BCMCPClient
from modules.data_trust_engine.authorization import CompanyAccessManager


class TestMultiCustomerConnectionSupport(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = pathlib.Path(__file__).resolve().parent / 'tmp_test_data'
        self.tmp_dir.mkdir(exist_ok=True)
        self.repo = CustomerConnectionRepository(storage_path=self.tmp_dir / 'test_connections.json')

    def tearDown(self):
        import shutil
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_customer_token_cache_boundary_isolation(self):
        conn_a = CustomerConnection(customer_id='cust_A', entra_tenant_id='tenant_A')
        conn_b = CustomerConnection(customer_id='cust_B', entra_tenant_id='tenant_B')

        path_a = conn_a.get_isolated_cache_path()
        path_b = conn_b.get_isolated_cache_path()

        self.assertNotEqual(str(path_a), str(path_b))
        self.assertIn('cust_A_tenant_A', str(path_a))
        self.assertIn('cust_B_tenant_B', str(path_b))

    def test_dynamic_new_customer_onboarding_without_source_code_edits(self):
        conn_new = CustomerConnection(
            customer_id='cust_enterprise_99',
            entra_tenant_id='tenant_9999_uuid',
            bc_environment='Production',
            oauth_client_id='client_9999_uuid',
            credential_ref='CUST_99_SECRET'
        )
        self.repo.save_connection(conn_new)

        resolved = self.repo.get_connection('cust_enterprise_99')
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.entra_tenant_id, 'tenant_9999_uuid')

    def test_tenant_isolation_different_tenants_have_different_companies(self):
        mgr = CompanyAccessManager()
        client_a = MagicMock(spec=BCMCPClient)
        client_a.get_access_token.return_value = 'TOKEN_A'
        client_a.config = MagicMock()
        client_a.config.client_key = 'cust_a'
        client_a._execute_bc_rest.return_value = {
            'value': [
                {'id': 'A1', 'name': 'Alpha Corp', 'displayName': 'Alpha Corp'}
            ]
        }

        client_b = MagicMock(spec=BCMCPClient)
        client_b.get_access_token.return_value = 'TOKEN_B'
        client_b.config = MagicMock()
        client_b.config.client_key = 'cust_b'
        client_b._execute_bc_rest.return_value = {
            'value': [
                {'id': 'B1', 'name': 'Beta Corp', 'displayName': 'Beta Corp'}
            ]
        }

        comps_a, source_a, _ = mgr.get_discovered_companies_with_provenance(client_a)
        comps_b, source_b, _ = mgr.get_discovered_companies_with_provenance(client_b)

        self.assertEqual(len(comps_a), 1)
        self.assertEqual(comps_a[0]['name'], 'Alpha Corp')

        self.assertEqual(len(comps_b), 1)
        self.assertEqual(comps_b[0]['name'], 'Beta Corp')

        self.assertNotEqual(comps_a, comps_b)

    def test_acl_filtering_occurs_after_live_discovery(self):
        mgr = CompanyAccessManager()
        client = MagicMock(spec=BCMCPClient)
        client.get_access_token.return_value = 'VALID_TOKEN'
        client._execute_bc_rest.return_value = {
            'value': [
                {'id': 'G1', 'name': 'C1', 'displayName': 'Company 1'},
                {'id': 'G2', 'name': 'C2', 'displayName': 'Company 2'},
                {'id': 'G3', 'name': 'C3', 'displayName': 'Company 3'},
                {'id': 'G4', 'name': 'C4', 'displayName': 'Company 4'}
            ]
        }

        discovered, source, err = mgr.get_discovered_companies_with_provenance(client)
        self.assertEqual(len(discovered), 4)

        allowed_comp_ids = ['G1', 'G2', 'G3']
        filtered = [c for c in discovered if c['id'] in allowed_comp_ids]
        self.assertEqual(len(filtered), 3)

    def test_production_auth_failure_returns_authentication_required(self):
        mgr = CompanyAccessManager()
        client = MagicMock(spec=BCMCPClient)
        client.get_access_token.return_value = ''

        os.environ.pop('OPSMELD_MODE', None)
        comps, source, err = mgr.get_discovered_companies_with_provenance(client)

        self.assertEqual(comps, [])
        self.assertEqual(source, 'AUTHENTICATION_REQUIRED')

    def test_snapshot_seed_available_only_in_explicit_fixture_mode(self):
        mgr = CompanyAccessManager()
        client = MagicMock(spec=BCMCPClient)
        client.get_access_token.return_value = ''
        client.config = MagicMock()
        client.config.client_key = 'fixture'

        comps, source, err = mgr.get_discovered_companies_with_provenance(client)
        self.assertEqual(len(comps), 3)
        self.assertEqual(source, 'SNAPSHOT_SEED')


if __name__ == '__main__':
    unittest.main()
