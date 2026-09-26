"""
Library checks of ``python manage.py deploy_check``: the ``library`` section
read by the library pages and API, and the external library database used by
the hourly ``update_lib_data`` job; ``online`` connects to that database.
Level policy: ``utils.deploy_check``.
"""
import os
from typing import Iterator

from utils.deploy_check import FAIL, OK, WARN, is_blank, resolve_setting
from yp_library.config import library_config as CONFIG


__all__ = ['checks']


Result = tuple[str, str, str]

# Config attribute -> key under "library" in config.json.
LIBRARY_SETTINGS = {
    'organization_name': 'organization_name',
    'start_time': 'open_time_start',
    'end_time': 'open_time_end',
}
# yp_library.jobs reads the connection from these variables; the check
# mirrors it and reports only which names are unset, never their values.
DATABASE_ENV = ('LIB_DB_HOST', 'LIB_DB_USER', 'LIB_DB_PASSWORD', 'LIB_DB')
CONNECT_TIMEOUT_SECONDS = 5


def checks(*, online: bool = False) -> Iterator[Result]:
    """Yield the library checks; ``online`` connects to the library database."""
    yield _check_library_config()
    unset_env = [name for name in DATABASE_ENV if not os.environ.get(name)]
    yield _check_database_env(unset_env)
    if online and not unset_env:
        yield _check_database_connection()


def _check_library_config() -> Result:
    name = 'library'
    missing = []
    for attr, key in LIBRARY_SETTINGS.items():
        value, error = resolve_setting(CONFIG, attr)
        if error or is_blank(value):
            missing.append(f'library.{key}')
    if missing:
        return FAIL, name, f'missing {", ".join(missing)}: library pages and API fail'
    return OK, name, 'organization and opening hours set'


def _check_database_env(unset: list[str]) -> Result:
    name = 'library database'
    if unset:
        return (WARN, name, f'{", ".join(unset)} unset in this environment: the '
                'hourly update_lib_data job fails')
    return OK, name, 'LIB_DB_* set'


def _check_database_connection() -> Result:
    name = 'library database connection'
    # pymssql is an optional dependency, needed only for this probe.
    import pymssql
    try:
        conn = pymssql.connect(
            server=os.environ['LIB_DB_HOST'],
            user=os.environ['LIB_DB_USER'],
            password=os.environ['LIB_DB_PASSWORD'],
            database=os.environ['LIB_DB'],
            login_timeout=CONNECT_TIMEOUT_SECONDS,
        )
    except pymssql.Error as exc:
        return FAIL, name, f'cannot connect ({type(exc).__name__})'
    conn.close()
    return OK, name, 'connected'
