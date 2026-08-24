"""
Opsmeld Reconciliation Engine - Authentication & Access Boundary Module
Provides lightweight application Sign In authentication, session token management,
and security access controls for Azure F1 client previews.
"""

import hashlib
import os
import secrets
import time
from typing import Dict, Any, Optional

# Active session store: session_id -> {username, created_at, expires_at}
_ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
SESSION_TTL_SECONDS = 86400  # 24 hours


class AuthManager:
    def __init__(self):
        self.admin_user = os.environ.get("OPSMELD_ADMIN_USER", "admin@opsmeld.com")
        self.admin_pass = os.environ.get("OPSMELD_ADMIN_PASSWORD", "opsmeld2026")

    def authenticate(self, username: str, password: str) -> Optional[str]:
        """Validates provisioned credentials and returns a session token if valid."""
        username = (username or "").strip().lower()
        admin_user_clean = self.admin_user.strip().lower()
        
        if (username == admin_user_clean or username == "admin") and password == self.admin_pass:
            session_token = secrets.token_hex(32)
            _ACTIVE_SESSIONS[session_token] = {
                "username": username,
                "created_at": time.time(),
                "expires_at": time.time() + SESSION_TTL_SECONDS
            }
            return session_token
        return None

    def validate_session(self, session_token: Optional[str]) -> bool:
        """Validates if a session token is active and not expired."""
        if not session_token:
            return False
        
        # Strip Bearer or Cookie quotes if present
        session_token = session_token.replace("Bearer ", "").replace("session=", "").strip()
        
        session = _ACTIVE_SESSIONS.get(session_token)
        if not session:
            return False
        
        if time.time() > session["expires_at"]:
            del _ACTIVE_SESSIONS[session_token]
            return False
        
        return True

    def revoke_session(self, session_token: Optional[str]):
        """Logs out user by invalidating the session token."""
        if session_token and session_token in _ACTIVE_SESSIONS:
            del _ACTIVE_SESSIONS[session_token]


_AUTH_MANAGER_INSTANCE = AuthManager()


def get_auth_manager() -> AuthManager:
    return _AUTH_MANAGER_INSTANCE
