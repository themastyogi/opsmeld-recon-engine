"""
Unit tests for AuthManager module.
"""

import unittest
from core.auth import AuthManager, get_auth_manager


class TestAuthManager(unittest.TestCase):

    def setUp(self):
        self.auth = AuthManager()

    def test_authenticate_valid_credentials(self):
        token = self.auth.authenticate("admin@opsmeld.com", "opsmeld2026")
        self.assertIsNotNone(token)
        self.assertTrue(self.auth.validate_session(token))

    def test_authenticate_invalid_password(self):
        token = self.auth.authenticate("admin@opsmeld.com", "wrongpassword")
        self.assertIsNone(token)

    def test_authenticate_invalid_user(self):
        token = self.auth.authenticate("unknown@opsmeld.com", "opsmeld2026")
        self.assertIsNone(token)

    def test_revoke_session(self):
        token = self.auth.authenticate("admin@opsmeld.com", "opsmeld2026")
        self.assertTrue(self.auth.validate_session(token))
        self.auth.revoke_session(token)
        self.assertFalse(self.auth.validate_session(token))


if __name__ == "__main__":
    unittest.main()
