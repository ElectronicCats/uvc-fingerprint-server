"""Admin authentication."""

import logging

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from checador.config import Config

logger = logging.getLogger(__name__)


class AuthManager:
    """Handles admin authentication."""
    
    def __init__(self, config: Config):
        self.config = config
        self.ph = PasswordHasher()
    
    def verify_password(self, password: str) -> bool:
        """Verify admin password."""
        try:
            self.ph.verify(self.config.app.admin_password_hash, password)
            return True
        except VerifyMismatchError:
            return False
        except Exception as e:
            logger.error(f"Error verifying password: {e}")
            return False
    
    def hash_password(self, password: str) -> str:
        """Hash a password (for setup)."""
        return self.ph.hash(password)