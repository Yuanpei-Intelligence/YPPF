"""Tests of ``manage.py deploy_check``, its plugin contract and the core plugin."""
import inspect
import json
import os
from datetime import date
from importlib import import_module
from importlib.util import find_spec
from io import StringIO
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from utils.config import Config, LazySetting
from utils.deploy_check import (
    FAIL, LEVELS, OK, WARN,
    is_local_host, is_placeholder, production_level, resolve_setting, url_host,
)
from utils.models.semester import Semester
from api.auth.wechat_api import WechatAPIError
from generic import deploy_checks as core
from generic.management.commands import deploy_check
from generic.models import User


def debug(enabled: bool):
    """Patch the debug flag that ``production_level()`` reads."""
    return patch('utils.deploy_check.DEBUG', enabled)


def fake_plugin(*results, error: BaseException | None = None) -> ModuleType:
    """A plugin module yielding ``results`` and then raising ``error``."""
    module = ModuleType('fake_deploy_checks')
    module.calls = []

    def checks(*, online: bool = False):
        module.calls.append(online)
        yield from results
        if error is not None:
            raise error

    module.checks = checks
    return module


class _Unresolvable:
    """A config object whose every setting fails to resolve."""

    def __getattr__(self, name):
        raise ImproperlyConfigured(f'{name} should be str')


class DeployCheckCommandTests(SimpleTestCase):
    """Discovery, output and exit semantics with fake plugin modules."""

    def setUp(self):
        self.plugins: dict[str, object] = {}
        registry = MagicMock()
        registry.get_app_configs.return_value = [
            SimpleNamespace(label='alpha', name='pkg.alpha'),
            SimpleNamespace(label='plain', name='plain_module'),
            SimpleNamespace(label='beta', name='pkg.beta'),
        ]
        self.enterContext(patch.object(deploy_check, 'apps', registry))
        self.enterContext(patch.object(
            deploy_check, 'find_spec', side_effect=self.find_spec))
        self.enterContext(patch.object(
            deploy_check, 'import_module', side_effect=self.import_module))

    def find_spec(self, module_name):
        if module_name.startswith('plain_module.'):
            # What importlib raises when the app is a module, not a package.
            raise ModuleNotFoundError(module_name)
        return object() if module_name in self.plugins else None

    def import_module(self, module_name):
        plugin = self.plugins[module_name]
        if isinstance(plugin, BaseException):
            raise plugin
        return plugin

    def run_command(self, *args, **options):
        stdout, stderr = StringIO(), StringIO()
        try:
            call_command(deploy_check.Command(), *args,
                         stdout=stdout, stderr=stderr, **options)
        except CommandError as exc:
            return stdout.getvalue(), stderr.getvalue(), exc
        return stdout.getvalue(), stderr.getvalue(), None

    def test_discovers_plugins_in_app_order_and_groups_text_output(self):
        self.plugins['pkg.beta.deploy_checks'] = fake_plugin((OK, 'gamma', ''))
        self.plugins['pkg.alpha.deploy_checks'] = fake_plugin(
            (OK, 'first', 'fine'), (WARN, 'second', 'look at it'))

        stdout, _, error = self.run_command()

        self.assertIsNone(error)
        self.assertEqual(stdout.splitlines(), [
            '== alpha ==',
            '  [OK] first: fine',
            '  [WARN] second: look at it',
            '== beta ==',
            '  [OK] gamma',
            '3 checks in 2 app(s): 0 failed, 1 warning(s)',
        ])

    def test_online_flag_is_passed_to_plugins(self):
        plugin = fake_plugin((OK, 'probe', ''))
        self.plugins['pkg.alpha.deploy_checks'] = plugin

        self.run_command()
        self.run_command('--online')

        self.assertEqual(plugin.calls, [False, True])

    def test_failure_exits_non_zero_unless_warn_only(self):
        self.plugins['pkg.alpha.deploy_checks'] = fake_plugin(
            (FAIL, 'broken', 'fix me'), (WARN, 'soft', 'maybe'))

        stdout, _, error = self.run_command()

        self.assertIsInstance(error, CommandError)
        self.assertIn('alpha/broken', str(error))
        self.assertNotIn('alpha/soft', str(error))
        self.assertIn('2 checks in 1 app(s): 1 failed, 1 warning(s)', stdout)
        self.assertIsNone(self.run_command('--warn-only')[2])

    def test_strict_also_fails_on_warnings(self):
        self.plugins['pkg.alpha.deploy_checks'] = fake_plugin(
            (OK, 'fine', ''), (WARN, 'soft', 'maybe'))

        self.assertIsNone(self.run_command()[2])
        error = self.run_command('--strict')[2]

        self.assertIsInstance(error, CommandError)
        self.assertIn('alpha/soft', str(error))

    def test_warn_only_and_strict_are_mutually_exclusive(self):
        with self.assertRaises(CommandError):
            call_command(deploy_check.Command(), '--warn-only', '--strict',
                         stdout=StringIO(), stderr=StringIO())
        with self.assertRaises(CommandError):
            call_command(deploy_check.Command(), warn_only=True, strict=True,
                         stdout=StringIO(), stderr=StringIO())

    def test_json_output_lists_every_result(self):
        self.plugins['pkg.alpha.deploy_checks'] = fake_plugin((OK, 'first', 'fine'))
        self.plugins['pkg.beta.deploy_checks'] = fake_plugin(
            (FAIL, 'second', 'broken'))

        stdout, _, error = self.run_command('--format', 'json')

        self.assertEqual(json.loads(stdout), [
            {'app': 'alpha', 'level': 'OK', 'name': 'first', 'detail': 'fine'},
            {'app': 'beta', 'level': 'FAIL', 'name': 'second', 'detail': 'broken'},
        ])
        self.assertIsInstance(error, CommandError)

    def test_app_option_selects_labels_and_rejects_unknown_ones(self):
        alpha = fake_plugin((OK, 'a', ''))
        beta = fake_plugin((OK, 'b', ''))
        self.plugins['pkg.alpha.deploy_checks'] = alpha
        self.plugins['pkg.beta.deploy_checks'] = beta

        stdout, _, error = self.run_command('--app', 'beta')
        self.assertIsNone(error)
        self.assertEqual(stdout.splitlines()[0], '== beta ==')
        self.assertNotIn('alpha', stdout)

        _, _, error = self.run_command('--app', 'beta', '--app', 'nope')
        self.assertIsInstance(error, CommandError)
        self.assertEqual(str(error), 'unknown app label(s): nope')
        self.assertEqual(alpha.calls, [])
        self.assertEqual(beta.calls, [False])

    def test_crashing_plugin_is_one_fail_without_the_message(self):
        self.plugins['pkg.alpha.deploy_checks'] = fake_plugin(
            (OK, 'before', ''), error=KeyError('token=hunter2'))
        self.plugins['pkg.beta.deploy_checks'] = fake_plugin((OK, 'after', ''))

        stdout, stderr, error = self.run_command()

        self.assertIn('  [OK] before', stdout)
        self.assertIn('  [FAIL] deploy_checks: check crashed (KeyError)', stdout)
        self.assertIn('  [OK] after', stdout)
        self.assertNotIn('hunter2', stdout + stderr + str(error))
        self.assertIn('alpha/deploy_checks', str(error))

    def test_traceback_option_shows_the_crash(self):
        self.plugins['pkg.alpha.deploy_checks'] = fake_plugin(
            error=KeyError('token=hunter2'))

        stdout, stderr, _ = self.run_command('--traceback')

        self.assertIn("check crashed (KeyError): 'token=hunter2'", stdout)
        self.assertIn('Traceback', stderr)

    def test_import_error_inside_a_plugin_is_a_fail(self):
        self.plugins['pkg.alpha.deploy_checks'] = ImportError(
            'No module named private_dependency')
        self.plugins['pkg.beta.deploy_checks'] = fake_plugin((OK, 'after', ''))

        stdout, _, error = self.run_command()

        self.assertIn('  [FAIL] deploy_checks: import failed (ImportError)', stdout)
        self.assertNotIn('private_dependency', stdout)
        self.assertIn('  [OK] after', stdout)
        self.assertIsInstance(error, CommandError)

    def test_malformed_plugins_are_failures(self):
        self.plugins['pkg.alpha.deploy_checks'] = fake_plugin(
            ('BAD', 'odd', ''), (OK, 'two-tuple'))
        self.plugins['pkg.beta.deploy_checks'] = ModuleType('no_checks')

        stdout, _, _ = self.run_command()

        self.assertIn('  [FAIL] odd: yielded an unknown level', stdout)
        self.assertIn('  [FAIL] deploy_checks: yielded a result that is not '
                      '(level, name, detail)', stdout)
        self.assertIn('  [FAIL] deploy_checks: defines no checks() function', stdout)


class PluginContractTests(SimpleTestCase):
    """The plugins shipped in this repository follow the fixed protocol."""

    def test_project_plugins_expose_keyword_only_online_flag(self):
        found = []
        for app_config in apps.get_app_configs():
            module_name = f'{app_config.name}.deploy_checks'
            try:
                if find_spec(module_name) is None:
                    continue
            except ModuleNotFoundError:
                continue
            module = import_module(module_name)
            with self.subTest(module=module_name):
                online = inspect.signature(module.checks).parameters['online']
                self.assertEqual(online.kind, inspect.Parameter.KEYWORD_ONLY)
                self.assertIs(online.default, False)
                self.assertNotIn('management.commands', inspect.getsource(module))
            found.append(app_config.label)
        self.assertLessEqual(
            {'generic', 'semester', 'app', 'Appointment', 'scheduler',
             'yp_library', 'dormitory'},
            set(found))


class DeployCheckHelperTests(SimpleTestCase):
    def test_production_level_follows_debug_mode(self):
        with debug(False):
            self.assertEqual(production_level(), FAIL)
        with debug(True):
            self.assertEqual(production_level(), WARN)

    def test_url_host_keeps_only_scheme_and_host(self):
        self.assertEqual(
            url_host('HTTPS://user:pw@Api.Example:8443/path?token=abc'),
            ('https', 'api.example'))
        self.assertEqual(url_host('api.example/path'), ('', ''))
        self.assertEqual(url_host('http://[::1'), ('', ''))
        self.assertEqual(url_host(None), ('', ''))

    def test_local_hosts_and_placeholders(self):
        for host in ('localhost', '127.0.0.1', '::1', '0.0.0.0', 'web.localhost'):
            with self.subTest(host=host):
                self.assertTrue(is_local_host(host))
        self.assertFalse(is_local_host('api.weixin.qq.com'))
        self.assertTrue(is_placeholder('$MINIAPP_SECRET$'))
        self.assertFalse(is_placeholder('$'))
        self.assertFalse(is_placeholder('real-value'))

    def test_resolve_setting_reports_only_the_error_class(self):
        class PortConfig(Config):
            port = LazySetting('port', type=int)

        self.assertEqual(
            resolve_setting(PortConfig({'port': 'not-a-port'}), 'port'),
            (None, 'ImproperlyConfigured'))
        self.assertEqual(
            resolve_setting(PortConfig({'port': 6666}), 'port'), (6666, None))


class CorePluginTests(SimpleTestCase):
    """Core checks with mocked configuration, cache, network and migrations."""

    TEMPLATE = {
        'global': {'base_url': 'http://localhost:8000',
                   'hash_salt': 'default_hash_salt'},
        'log': {'dir': 'log'},
        'django': {'db': {'NAME': '$DATABASE$'}},
        'help_messages': {'页面': 'text'},
        'wechat': {'api_url': '', 'app2url': {'default': ''}},
        'course': {'prerequisite_survey': {'enabled': False, 'rules': []}},
    }

    def test_localhost_jscode2session_url_fails_only_outside_debug(self):
        miniapp = SimpleNamespace(
            appid='wx-app', secret='s3cret',
            jscode2session_url='http://localhost:9000/sns/jscode2session?secret=s3cret')
        with patch.object(core, 'MINIAPP_CONFIG', miniapp):
            with debug(False):
                level, name, detail = core._check_jscode2session_url()
            with debug(True):
                debug_level = core._check_jscode2session_url()[0]
            miniapp.jscode2session_url = 'https://api.weixin.qq.com/sns/jscode2session'
            with debug(False):
                real = core._check_jscode2session_url()
            miniapp.jscode2session_url = 'https://mock.example/sns/jscode2session'
            with debug(False):
                other_host = core._check_jscode2session_url()[0]

        self.assertEqual((level, name), (FAIL, 'wx_miniapp.jscode2session_url'))
        self.assertIn('http://localhost is a local mock', detail)
        self.assertNotIn('s3cret', detail)
        self.assertEqual(debug_level, WARN)
        self.assertEqual(
            real, (OK, 'wx_miniapp.jscode2session_url', 'https://api.weixin.qq.com'))
        self.assertEqual(other_host, FAIL)

    def test_miniapp_credentials_are_never_printed(self):
        miniapp = SimpleNamespace(appid='wx-real-appid', secret='$MINIAPP_SECRET$')
        with patch.object(core, 'MINIAPP_CONFIG', miniapp), debug(False):
            level, _, detail = core._check_miniapp_credentials()
        self.assertEqual(level, FAIL)
        self.assertTrue(detail.startswith('secret unset or a template placeholder'))
        self.assertNotIn('wx-real-appid', detail)

    def test_access_token_probe_reports_errcode_only(self):
        miniapp = SimpleNamespace(appid='wx-app', secret='s3cret')
        cache = MagicMock()
        cache.get.return_value = None
        rejected = WechatAPIError('微信接口错误: invalid appsecret rid: 42', 40125)
        with patch.object(core, 'MINIAPP_CONFIG', miniapp), \
                patch.object(core, 'cache', cache):
            with patch.object(core, 'get_wechat_access_token', side_effect=rejected):
                errcode = core._check_miniapp_access_token()
            with patch.object(core, 'get_wechat_access_token',
                              side_effect=ValueError('无法访问微信接口')):
                unreachable = core._check_miniapp_access_token()
            with patch.object(core, 'get_wechat_access_token',
                              return_value='token-value'):
                fetched = core._check_miniapp_access_token()
                cache.get.return_value = 'token-value'
                cached = core._check_miniapp_access_token()

        self.assertEqual(errcode, (FAIL, 'wx_miniapp access token',
                                   'WeChat rejected the request: errcode 40125'))
        self.assertEqual(unreachable[0], FAIL)
        self.assertEqual(
            fetched, (OK, 'wx_miniapp access token', 'obtained from WeChat'))
        self.assertEqual(cached[0], OK)
        self.assertIn('cached', cached[2])
        self.assertNotIn('token-value', cached[2])

    def test_access_token_probe_is_skipped_without_credentials(self):
        miniapp = SimpleNamespace(appid='', secret='')
        with patch.object(core, 'MINIAPP_CONFIG', miniapp), \
                patch.object(core, 'get_wechat_access_token') as fetch:
            self.assertEqual(core._check_miniapp_access_token()[0], WARN)
        fetch.assert_not_called()

    def test_pending_and_conflicting_migrations_fail(self):
        executor = MagicMock()
        executor.loader.detect_conflicts.return_value = {}
        executor.migration_plan.return_value = [
            (SimpleNamespace(app_label='app', name='0099_new_field'), False),
            (SimpleNamespace(app_label='generic', name='0100_more'), False),
        ]
        with patch.object(core, 'MigrationExecutor', return_value=executor):
            pending = core._check_migrations()
            executor.migration_plan.return_value = []
            applied = core._check_migrations()
            executor.loader.detect_conflicts.return_value = {'app': ['a', 'b']}
            conflicting = core._check_migrations()

        self.assertEqual(pending[0], FAIL)
        self.assertIn('2 unapplied (app.0099_new_field, generic.0100_more)', pending[2])
        self.assertEqual(applied, (OK, 'migrations', 'all applied'))
        self.assertEqual(conflicting[0], FAIL)
        self.assertIn('conflicting leaf migrations in app', conflicting[2])

    def test_config_diff_reports_missing_template_keys(self):
        actual = {
            'global': {'base_url': 'https://yppf.example'},
            'django': 'not-a-section',
            'wechat': {'api_url': 'https://relay.example', 'app2url': {}},
            'course': {'prerequisite_survey': {'enabled': False}},
        }

        self.assertEqual(
            core._missing_paths(self.TEMPLATE, actual),
            ['global.hash_salt', 'log', 'django (not an object)'])
        level, name, detail = core._check_config_keys(self.TEMPLATE, actual)
        self.assertEqual((level, name), (WARN, 'config.json keys'))
        self.assertIn('3 template key(s) missing', detail)
        self.assertEqual(core._check_config_keys(self.TEMPLATE, self.TEMPLATE)[0], OK)
        self.assertEqual(core._check_config_keys(None, actual)[0], WARN)
        self.assertIn('global', core._load_template())

    def test_salt_equal_to_a_default_is_production_level(self):
        class GlobalSettings(Config):
            salt = LazySetting('hash_salt', default='salt')

        def level_of(config):
            return core._check_salt(
                'global.hash_salt', config, 'salt', self.TEMPLATE, 'impact')[0]

        with debug(False):
            for salt in ('default_hash_salt', '', '$HASH_SALT$'):
                with self.subTest(salt=salt):
                    self.assertEqual(level_of(SimpleNamespace(salt=salt)), FAIL)
            # config.json omits the key, so the code default applies.
            self.assertEqual(level_of(GlobalSettings({})), FAIL)
            self.assertEqual(level_of(_Unresolvable()), FAIL)
            self.assertEqual(level_of(SimpleNamespace(salt='x7Qp-9vLm')), OK)
        with debug(True):
            self.assertEqual(level_of(SimpleNamespace(salt='default_hash_salt')), WARN)

    def test_base_url_and_relay_urls(self):
        def base_url(url):
            with patch.object(core, 'GLOBAL_CONFIG', SimpleNamespace(base_url=url)):
                return core._check_base_url()

        def relay(url):
            with patch.object(core, 'wechat_config', SimpleNamespace(api_url=url)):
                return core._check_wechat_api_url()

        with debug(False):
            self.assertEqual(base_url('http://127.0.0.1:8000/')[0], FAIL)
            self.assertEqual(base_url('yppf.example')[0], FAIL)
            self.assertEqual(
                base_url('https://yppf.example/'),
                (OK, 'global.base_url', 'https://yppf.example'))
            self.assertEqual(relay('')[0], FAIL)
            # A relay on the same server is a valid topology: warn only.
            self.assertEqual(relay('http://localhost:9001/send')[0], WARN)
            self.assertEqual(
                relay('https://relay.example/send?key=k'),
                (OK, 'wechat.api_url', 'https://relay.example'))
        with debug(True):
            self.assertEqual(base_url('http://localhost:8000')[0], WARN)
            self.assertEqual(relay('')[0], WARN)

    def test_term_setting_matches_the_date(self):
        cases = [
            (date(2026, 9, 10), 2026, Semester.FALL, OK),
            (date(2026, 9, 10), 2023, Semester.SPRING, FAIL),
            (date(2027, 1, 20), 2026, Semester.FALL, OK),
            (date(2027, 2, 25), 2026, Semester.SPRING, OK),
            (date(2027, 4, 1), 2026, Semester.FALL, FAIL),
            (date(2027, 8, 1), 2026, Semester.SPRING, OK),
            (date(2027, 8, 1), 2027, Semester.FALL, OK),
            (date(2026, 12, 1), 2026, Semester.ANNUAL, FAIL),
        ]
        with debug(False):
            for today, year, term, level in cases:
                config = SimpleNamespace(acadamic_year=year, semester=term)
                with self.subTest(today=today, year=year, term=term), \
                        patch.object(core, 'GLOBAL_CONFIG', config):
                    self.assertEqual(core._check_term_setting(today)[0], level)
            with patch.object(core, 'GLOBAL_CONFIG', _Unresolvable()):
                self.assertEqual(core._check_term_setting(date(2026, 9, 10))[0], FAIL)
        config = SimpleNamespace(acadamic_year=2023, semester=Semester.SPRING)
        with debug(True), patch.object(core, 'GLOBAL_CONFIG', config):
            level, _, detail = core._check_term_setting(date(2026, 9, 10))
        self.assertEqual(level, WARN)
        self.assertIn('expected 2026 Fall', detail)

    def test_secret_key(self):
        strong = 'q' * 10 + 'wertyuiopasdfghjklzxcvbnm1234567890QWERTYUIOP'
        with debug(True):
            self.assertEqual(core._check_secret_key()[0], WARN)
        with debug(False):
            with override_settings(SECRET_KEY='too-short'):
                self.assertEqual(core._check_secret_key()[0], WARN)
            with override_settings(SECRET_KEY='$SESSION_KEY$'):
                self.assertEqual(core._check_secret_key()[0], FAIL)
            with override_settings(SECRET_KEY=''):
                self.assertEqual(core._check_secret_key()[0], FAIL)
            with override_settings(SECRET_KEY=strong):
                result = core._check_secret_key()
        self.assertEqual(result, (OK, 'SECRET_KEY', 'set from SESSION_KEY'))

    def test_directory_checks(self):
        with TemporaryDirectory() as root:
            file_path = os.path.join(root, 'file')
            with open(file_path, 'w', encoding='utf8'):
                pass
            existing = core._check_directory('tmp', root)
            creatable = core._check_directory('tmp', os.path.join(root, 'a', 'b'))
            not_a_dir = core._check_directory('tmp', file_path)
            under_file = core._check_directory('tmp', os.path.join(file_path, 'c'))
            with patch.object(core.os, 'access', return_value=False):
                read_only = core._check_directory('tmp', root)

        self.assertEqual(existing[0], OK)
        self.assertEqual(creatable[0], OK)
        self.assertIn('will be created on first use', creatable[2])
        self.assertEqual(not_a_dir[0], FAIL)
        self.assertEqual(under_file[0], FAIL)
        self.assertEqual(read_only[0], FAIL)
        self.assertEqual(
            core._check_directory('tmp', ''), (FAIL, 'tmp', 'not set to a path'))


class CorePluginDatabaseTests(TestCase):
    def test_official_user_must_exist(self):
        User.objects.create_user('zz-official', 'Official', password='pw')
        with debug(False):
            with patch.object(core, 'GLOBAL_CONFIG',
                              SimpleNamespace(official_uid='zz-official')):
                found = core._check_official_user()
            with patch.object(core, 'GLOBAL_CONFIG',
                              SimpleNamespace(official_uid='zz-missing')):
                missing = core._check_official_user()
        self.assertEqual(
            found, (OK, 'global.official_user', 'account zz-official exists'))
        self.assertEqual(missing[0], FAIL)

    def test_checks_yield_valid_results_and_probe_only_online(self):
        miniapp = SimpleNamespace(
            appid='wx-app', secret='s3cret',
            jscode2session_url='https://api.weixin.qq.com/sns/jscode2session')
        cache = MagicMock()
        cache.get.return_value = None
        with patch.object(core, 'MINIAPP_CONFIG', miniapp), \
                patch.object(core, 'cache', cache), \
                patch.object(core, 'get_wechat_access_token',
                             return_value='token-value') as fetch:
            offline = list(core.checks())
            fetch.assert_not_called()
            online = list(core.checks(online=True))
            fetch.assert_called_once_with()

        self.assertEqual(len(online), len(offline) + 1)
        for level, name, detail in online:
            with self.subTest(name=name):
                self.assertIn(level, LEVELS)
                self.assertIsInstance(detail, str)
        self.assertIn((OK, 'migrations', 'all applied'), offline)
        serialized = json.dumps(online, ensure_ascii=False)
        self.assertNotIn('s3cret', serialized)
        self.assertNotIn('token-value', serialized)
