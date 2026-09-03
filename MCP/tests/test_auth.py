"""
Unit tests for AuthManager module.
"""

import unittest
from core.auth import AuthManager


class TestAuthManager(unittest.TestCase):

    def setUp(self):
        self.auth = AuthManager()

    def test_authenticate_valid_credentials(self):
        token = self.auth.authenticate(self.auth.admin_user, self.auth.admin_pass)
        self.assertIsNotNone(token)
        self.assertTrue(self.auth.validate_session(token))

    def test_authenticate_invalid_password(self):
        token = self.auth.authenticate(self.auth.admin_user, "wrongpassword_123")
        self.assertIsNone(token)

    def test_authenticate_invalid_user(self):
        token = self.auth.authenticate("unknown@opsmeld.com", self.auth.admin_pass)
        self.assertIsNone(token)

    def test_revoke_session(self):
        token = self.auth.authenticate(self.auth.admin_user, self.auth.admin_pass)
        self.assertTrue(self.auth.validate_session(token))
        self.auth.revoke_session(token)
        self.assertFalse(self.auth.validate_session(token))

    def test_authenticate_user_password_hash_verification(self):
        """Asserts authenticate('realuser@company.com', 'wrong-password') returns None using a real stored hash."""
        from core.models import get_datastore, User
        ds = get_datastore()
        test_user = User(
            user_id="usr_real_001",
            entra_oid="oid_real_001",
            email="realuser@company.com",
            display_name="Real User"
        )
        ds.users[test_user.user_id] = test_user
        ds.org_users.setdefault("org_abc_001", set()).add(test_user.user_id)
        ds.user_org[test_user.user_id] = "org_abc_001"

        # Store real PBKDF2-HMAC-SHA256 hash for realuser@company.com
        self.auth.set_user_password("realuser@company.com", "correct_secret_password_123")

        # 1. Wrong password MUST return None (rejected)
        wrong_token = self.auth.authenticate("realuser@company.com", "wrong-password")
        self.assertIsNone(wrong_token)

        # 2. Correct password MUST succeed and return valid session token
        valid_token = self.auth.authenticate("realuser@company.com", "correct_secret_password_123")
        self.assertIsNotNone(valid_token)
        session = self.auth.get_session(valid_token)
        self.assertIsNotNone(session)
        self.assertEqual(session.email, "realuser@company.com")
        self.assertTrue(session.provisioned)

    def test_resolve_user_organization_fails_closed_on_empty_identity(self):
        """Task 5: Asserts resolve_user_organization returns None on None, empty string, or whitespace."""
        from core.models import get_datastore
        ds = get_datastore()
        self.assertIsNone(ds.resolve_user_organization(None))
        self.assertIsNone(ds.resolve_user_organization(""))
        self.assertIsNone(ds.resolve_user_organization("   "))
        self.assertIsNone(ds.resolve_user_organization(None, entra_oid=None))
        self.assertIsNone(ds.resolve_user_organization("nonexistent@domain.com"))

        # Confirms legitimate admin identity still resolves properly
        resolved = ds.resolve_user_organization("admin@opsmeld.com")
        self.assertIsNotNone(resolved)
        user, org = resolved
        self.assertEqual(user.user_id, "usr_admin_001")
        self.assertEqual(org.organization_id, "org_abc_001")


if __name__ == "__main__":
    unittest.main()
