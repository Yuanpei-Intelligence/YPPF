"""
Core checks of ``python manage.py deploy_check``.

Besides ``generic`` itself this plugin covers the settings owned by packages
that are not Django apps: ``boot`` (debug mode, ``SECRET_KEY``, database and
migrations, ``config.json`` drift, the ``global`` section, static and media
directories), ``record`` (log directory), ``api`` (``wx_miniapp``),
``extern`` (the WeChat Work relay) and the ``email`` and ``weather``
integrations. ``online`` adds the mini-program access-token probe. Level
policy and the no-secrets rule: ``utils.deploy_check``.
"""
import json
import os
from datetime import date
from typing import Any, Iterator

from django.conf import settings
from django.core.cache import cache
from django.core.checks.security.base import (
    SECRET_KEY_INSECURE_PREFIX,
    SECRET_KEY_MIN_LENGTH,
    SECRET_KEY_MIN_UNIQUE_CHARACTERS,
)
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from boot.config import GLOBAL_CONFIG, ROOT_CONFIG, absolute_path
from utils.config import LazySetting
from utils.deploy_check import (
    FAIL, OK, WARN,
    debug_mode, is_blank, is_local_host, is_placeholder, preview,
    production_level, resolve_setting, url_host,
)
from utils.health_check import db_connection_healthy
from utils.models.semester import Semester
from record.log.config import log_config
from extern.config import wechat_config
from api.auth.wechat_api import (
    WX_ACCESS_TOKEN_CACHE_KEY,
    WechatAPIError,
    get_wechat_access_token,
)
from api.config import CONFIG as MINIAPP_CONFIG
from app.config import CONFIG as APP_CONFIG
from generic.models import User


__all__ = ['checks']


Result = tuple[str, str, str]

TEMPLATE_PATH = './config_template.json'
# Not compared key by key: maps whose keys each deployment chooses (their
# consumers fall back to defaults) and sections another plugin validates.
FREE_FORM_PATHS = frozenset({
    'help_messages',
    'max_inform_rank',
    'wechat.app2url',
    'wx_miniapp.subscribe_templates',
    'course.prerequisite_survey',
})
HTTP_SCHEMES = ('http', 'https')
WECHAT_API_HOST = 'api.weixin.qq.com'


def checks(*, online: bool = False) -> Iterator[Result]:
    """Yield the core checks; ``online`` adds the mini-program token probe."""
    template = _load_template()
    yield _check_debug()
    yield _check_secret_key()
    database_ok = db_connection_healthy()
    yield _check_database(database_ok)
    if database_ok:
        yield _check_migrations()
        yield _check_official_user()
    yield _check_config_keys(template, ROOT_CONFIG)
    yield _check_salt('global.hash_salt', GLOBAL_CONFIG, 'salt', template,
                      'signed check-in and registration links are forgeable')
    yield _check_base_url()
    yield _check_term_setting(date.today())
    yield _check_directory('global.tmp_dir', GLOBAL_CONFIG.temporary_dir)
    log_dir = log_config.log_dir
    yield _check_directory(
        'log.dir', absolute_path(log_dir) if isinstance(log_dir, str) else log_dir)
    yield _check_directory('MEDIA_ROOT', settings.MEDIA_ROOT)
    yield _check_static_dirs()
    yield _check_miniapp_credentials()
    yield _check_jscode2session_url()
    if online:
        yield _check_miniapp_access_token()
    yield _check_wechat_api_url()
    yield _check_salt('wechat.salt', wechat_config, 'salt', template,
                      'requests to the WeChat relay use a public signing salt')
    yield _check_email_url()
    yield _check_salt('email.salt', APP_CONFIG.email, 'salt', template,
                      'requests to the email relay use a public signing salt')
    yield _check_weather()


def _check_debug() -> Result:
    if debug_mode():
        return WARN, 'debug mode', 'YPPF_DEBUG=true: development only'
    return OK, 'debug mode', 'off'


def _check_secret_key() -> Result:
    name = 'SECRET_KEY'
    if debug_mode():
        return (WARN, name, 'the public development key (debug mode); '
                'production reads SESSION_KEY')
    key, error = resolve_setting(settings, 'SECRET_KEY')
    if error or is_blank(key) or is_placeholder(key):
        return FAIL, name, 'SESSION_KEY is empty or a placeholder'
    if (len(key) < SECRET_KEY_MIN_LENGTH
            or len(set(key)) < SECRET_KEY_MIN_UNIQUE_CHARACTERS
            or key.startswith(SECRET_KEY_INSECURE_PREFIX)):
        return (WARN, name, 'SESSION_KEY is weak: use at least '
                f'{SECRET_KEY_MIN_LENGTH} random characters')
    return OK, name, 'set from SESSION_KEY'


def _check_database(reachable: bool) -> Result:
    if reachable:
        return OK, 'database', f'reachable ({connection.vendor})'
    return (FAIL, 'database', 'unreachable: check the DB_* environment '
            'variables or django.db in config.json')


def _check_migrations() -> Result:
    name = 'migrations'
    executor = MigrationExecutor(connection)
    conflicts = executor.loader.detect_conflicts()
    if conflicts:
        return (FAIL, name, 'conflicting leaf migrations in '
                f'{preview(sorted(conflicts))}: run makemigrations --merge')
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    pending = [f'{migration.app_label}.{migration.name}' for migration, _ in plan]
    if pending:
        return (FAIL, name, f'{len(pending)} unapplied ({preview(pending)}): '
                'run python manage.py migrate')
    return OK, name, 'all applied'


def _check_official_user() -> Result:
    name = 'global.official_user'
    username, error = resolve_setting(GLOBAL_CONFIG, 'official_uid')
    if error or is_blank(username):
        return FAIL, name, 'missing: system notifications have no sender'
    if User.objects.filter(username=username).exists():
        return OK, name, f'account {username} exists'
    return (production_level(), name,
            f'no account {username}: system notifications fail')


def _load_template() -> dict[str, Any] | None:
    # The repository template is the reference for drift and default values.
    try:
        with open(absolute_path(TEMPLATE_PATH), encoding='utf8') as file:
            template = json.load(file)
    except (OSError, ValueError):
        return None
    return template if isinstance(template, dict) else None


def _missing_paths(template: dict[str, Any], actual: dict[str, Any],
                   prefix: str = '') -> list[str]:
    # Dotted paths present in the template but absent from the actual config.
    missing = []
    for key, expected in template.items():
        path = f'{prefix}{key}'
        if path in FREE_FORM_PATHS:
            continue
        if key not in actual:
            missing.append(path)
        elif isinstance(expected, dict):
            if isinstance(actual[key], dict):
                missing.extend(_missing_paths(expected, actual[key], f'{path}.'))
            else:
                missing.append(f'{path} (not an object)')
    return missing


def _check_config_keys(template: dict[str, Any] | None,
                       actual: dict[str, Any]) -> Result:
    name = 'config.json keys'
    if template is None:
        return WARN, name, 'config_template.json is unreadable: drift not checked'
    missing = _missing_paths(template, actual)
    if missing:
        return (WARN, name, f'{len(missing)} template key(s) missing, code '
                f'defaults apply where defined: {preview(missing, 8)}')
    return OK, name, 'every config_template.json key is present'


def _template_value(template: dict[str, Any] | None, path: str) -> Any:
    value: Any = template
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _check_salt(name: str, config: Any, attr: str,
                template: dict[str, Any] | None, impact: str) -> Result:
    # ``name`` is also the template path whose value counts as a default.
    salt, error = resolve_setting(config, attr)
    defaults = {_template_value(template, name)}
    setting = getattr(type(config), attr, None)
    if isinstance(setting, LazySetting):
        defaults.add(setting.default)
    if error or is_blank(salt) or is_placeholder(salt) or salt in defaults:
        return production_level(), name, f'unset or the template default: {impact}'
    return OK, name, 'customised'


def _check_base_url() -> Result:
    name = 'global.base_url'
    url, error = resolve_setting(GLOBAL_CONFIG, 'base_url')
    scheme, host = url_host(url)
    if error or scheme not in HTTP_SCHEMES or not host:
        return (FAIL, name, 'not an absolute http(s) URL: absolute links and '
                'CSRF_TRUSTED_ORIGINS break')
    if is_local_host(host):
        return (production_level(), name, f'{scheme}://{host} is local: links in '
                'notifications, QR codes and WeChat messages are unreachable')
    return OK, name, f'{scheme}://{host}'


def _expected_terms(today: date) -> list[tuple[int, Semester]]:
    """
    Terms that ``global.acadamic_year`` / ``semester`` may name on ``today``.

    Academic year ``Y`` starts in September ``Y``; its Fall term runs until
    January and its Spring term from February to July. January-February and
    July-August accept both neighbouring terms while the setting is switched.
    """
    year, month = today.year, today.month
    if month >= 9:
        return [(year, Semester.FALL)]
    if month <= 2:
        return [(year - 1, Semester.FALL), (year - 1, Semester.SPRING)]
    if month <= 6:
        return [(year - 1, Semester.SPRING)]
    return [(year - 1, Semester.SPRING), (year, Semester.FALL)]


def _check_term_setting(today: date) -> Result:
    name = 'global.acadamic_year/semester'
    year, year_error = resolve_setting(GLOBAL_CONFIG, 'acadamic_year')
    term, term_error = resolve_setting(GLOBAL_CONFIG, 'semester')
    if year_error or term_error:
        return (FAIL, name, 'missing or invalid: positions and course selection '
                'fail')
    expected = _expected_terms(today)
    if (year, term) in expected:
        return OK, name, f'{year} {term.value}'
    wanted = ' or '.join(f'{y} {t.value}' for y, t in expected)
    return (production_level(), name, f'{year} {term.value} is not the term of '
            f'{today:%Y-%m-%d} (expected {wanted}): current positions and '
            'courses use the wrong term')


def _check_directory(name: str, path: Any) -> Result:
    if isinstance(path, os.PathLike):
        path = os.fspath(path)
    if is_blank(path):
        return FAIL, name, 'not set to a path'
    path = os.path.abspath(path)
    access = os.W_OK | os.X_OK
    if os.path.isdir(path):
        if os.access(path, access):
            return OK, name, f'{path} is writable'
        return FAIL, name, f'{path} is not writable'
    if os.path.lexists(path):
        return FAIL, name, f'{path} exists but is not a directory'
    parent = os.path.dirname(path)
    while not os.path.lexists(parent) and os.path.dirname(parent) != parent:
        parent = os.path.dirname(parent)
    if os.path.isdir(parent) and os.access(parent, access):
        return OK, name, f'{path} will be created on first use'
    return FAIL, name, f'{path} is missing and cannot be created'


def _check_static_dirs() -> Result:
    name = 'STATICFILES_DIRS'
    paths = [
        str(entry[1] if isinstance(entry, (list, tuple)) else entry)
        for entry in settings.STATICFILES_DIRS
    ]
    missing = [path for path in paths if not os.path.isdir(path)]
    if missing:
        return (FAIL, name, f'{preview(missing)} missing: pages render without '
                'styles and scripts (check STATIC_DIR)')
    return OK, name, f'{preview(paths)} present'


def _unset_miniapp_credentials() -> list[str]:
    unset = []
    for attr in ('appid', 'secret'):
        value, error = resolve_setting(MINIAPP_CONFIG, attr)
        if error or is_blank(value) or is_placeholder(value):
            unset.append(attr)
    return unset


def _check_miniapp_credentials() -> Result:
    name = 'wx_miniapp.appid/secret'
    unset = _unset_miniapp_credentials()
    if unset:
        return (production_level(), name, f'{" and ".join(unset)} unset or a '
                'template placeholder: mini-program login fails')
    return OK, name, 'set'


def _check_jscode2session_url() -> Result:
    name = 'wx_miniapp.jscode2session_url'
    url, error = resolve_setting(MINIAPP_CONFIG, 'jscode2session_url')
    scheme, host = url_host(url)
    if not error and scheme == 'https' and host == WECHAT_API_HOST:
        return OK, name, f'https://{host}'
    if error or not host:
        problem = 'not an absolute URL'
    elif is_local_host(host):
        problem = f'{scheme}://{host} is a local mock'
    else:
        problem = f'{scheme}://{host} is not https://{WECHAT_API_HOST}'
    return production_level(), name, f'{problem}: real mini-program logins fail'


def _check_miniapp_access_token() -> Result:
    name = 'wx_miniapp access token'
    if _unset_miniapp_credentials():
        return WARN, name, 'skipped: appid/secret unset'
    # The helper reuses an unexpired cached token. Forcing a new one would
    # invalidate the token that other processes hold, so it is not bypassed.
    cached = cache.get(WX_ACCESS_TOKEN_CACHE_KEY) is not None
    try:
        get_wechat_access_token()
    except WechatAPIError as exc:
        return FAIL, name, f'WeChat rejected the request: errcode {exc.errcode}'
    except ValueError:
        return FAIL, name, 'no usable answer from WeChat (network or response)'
    if cached:
        return OK, name, 'a cached token has not expired (not re-requested)'
    return OK, name, 'obtained from WeChat'


def _check_wechat_api_url() -> Result:
    name = 'wechat.api_url'
    url, error = resolve_setting(wechat_config, 'api_url')
    scheme, host = url_host(url)
    if error or scheme not in HTTP_SCHEMES or not host:
        return (production_level(), name, 'unset or not an absolute http(s) URL: '
                'WeChat Work messages are not sent')
    if is_local_host(host):
        # A relay on the same server is a valid topology, unlike a mock.
        return (WARN, name, f'{scheme}://{host} is local: make sure the WeChat '
                'relay runs on this host')
    return OK, name, f'{scheme}://{host}'


def _check_email_url() -> Result:
    name = 'email.url'
    url, error = resolve_setting(APP_CONFIG.email, 'url')
    scheme, host = url_host(url)
    if error or scheme not in HTTP_SCHEMES or not host:
        return (production_level(), name, 'unset or not an absolute http(s) URL: '
                'password reset by email fails')
    return OK, name, f'{scheme}://{host}'


def _check_weather() -> Result:
    name = 'weather.api_key'
    key, error = resolve_setting(APP_CONFIG, 'weather_api_key')
    if error or is_blank(key) or is_placeholder(key):
        return (WARN, name, 'unset or a template placeholder: the hourly weather '
                'job fails and the homepage shows no weather')
    return OK, name, 'set'
