"""
Configuration of the PKU portal integration (``config.json → pku_portal``).

See ``timetable/README.md`` §2 for the documented keys.
"""
from boot.config import ROOT_CONFIG
from utils.config import Config, LazySetting

__all__ = ['PkuPortalConfig', 'CONFIG']


class PkuPortalConfig(Config):
    """Settings for the IAAA / portal client and the binding policy."""

    # Feature switch; when false the login endpoint answers PORTAL_DISABLED.
    enabled = LazySetting('enabled', default=False, type=bool)
    # Fernet key (urlsafe base64 of 32 random bytes) protecting stored portal
    # cookies. Empty means "derive from SECRET_KEY" (see pku_account.crypto).
    session_key = LazySetting('session_key', default='', type=str)
    # Seconds per HTTP call to iaaa.pku.edu.cn / portal.pku.edu.cn.
    timeout = LazySetting('timeout', default=15, type=(int, float))
    # Failed IAAA logins tolerated per binding before it is locked.
    max_login_failures = LazySetting('max_login_failures', default=5, type=int)
    # Duration of that lock.
    lock_seconds = LazySetting('lock_seconds', default=900, type=int)


CONFIG = PkuPortalConfig(ROOT_CONFIG, 'pku_portal')
