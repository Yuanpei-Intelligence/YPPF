"""Tests of ``scheduler/deploy_checks.py`` with mocked config and RPC."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django_apscheduler.models import DjangoJob, DjangoJobExecution

from utils.deploy_check import FAIL, OK, WARN
from scheduler import deploy_checks as plugin


def debug(enabled: bool):
    return patch('utils.deploy_check.DEBUG', enabled)


class SchedulerConfigCheckTests(SimpleTestCase):
    def test_use_scheduler_off_is_production_level(self):
        with patch.object(plugin, 'CONFIG', SimpleNamespace(use_scheduler=False)):
            with debug(False):
                self.assertEqual(plugin._check_use_scheduler()[0], FAIL)
            with debug(True):
                self.assertEqual(plugin._check_use_scheduler()[0], WARN)
        with patch.object(plugin, 'CONFIG', SimpleNamespace(use_scheduler=True)), \
                debug(False):
            self.assertEqual(
                plugin._check_use_scheduler(), (OK, 'scheduler.use_scheduler', 'on'))

    def test_rpc_port_must_be_a_port_number(self):
        self.assertEqual(
            plugin._check_rpc_port(6666, None), (OK, 'scheduler.rpc_port', '6666'))
        for port, error in ((None, 'ImproperlyConfigured'), (0, None),
                            (True, None), (70000, None)):
            with self.subTest(port=port):
                self.assertEqual(plugin._check_rpc_port(port, error)[0], FAIL)

    def test_rpc_health_call(self):
        connect = 'scheduler.deploy_checks.rpyc.connect'
        with patch(connect, side_effect=ConnectionRefusedError):
            refused = plugin._check_rpc_health(6666)

        conn = MagicMock()
        conn.root.health_check.return_value = True
        with patch(connect, return_value=conn) as connect_mock:
            running = plugin._check_rpc_health(6666)
            conn.root.health_check.return_value = False
            unhealthy = plugin._check_rpc_health(6666)
            conn.root.health_check.side_effect = EOFError
            broken = plugin._check_rpc_health(6666)

        self.assertEqual(refused[0], FAIL)
        self.assertIn('scheduler not running (connection refused on port 6666)',
                      refused[2])
        self.assertEqual(running, (OK, 'scheduler RPC', 'scheduler running'))
        connect_mock.assert_called_with(
            'localhost', 6666, config={'sync_request_timeout': 5})
        self.assertEqual(unhealthy[0], FAIL)
        self.assertEqual(
            broken, (FAIL, 'scheduler RPC', 'health call failed (EOFError)'))
        self.assertEqual(conn.close.call_count, 3)

    def test_rpc_is_probed_only_online(self):
        config = SimpleNamespace(use_scheduler=True, rpc_port=6666)
        with patch.object(plugin, 'CONFIG', config), \
                patch.object(plugin, 'db_connection_healthy', return_value=False), \
                patch.object(plugin, '_check_rpc_health',
                             return_value=(OK, 'scheduler RPC', '')) as probe:
            offline = list(plugin.checks())
            probe.assert_not_called()
            online = list(plugin.checks(online=True))
        probe.assert_called_once_with(6666)
        self.assertIn((WARN, 'job store', 'skipped: database unreachable'), offline)
        self.assertEqual(len(online), len(offline) + 1)

    def test_unimportable_jobs_module_is_reported_by_class(self):
        registry = MagicMock()
        registry.get_app_configs.return_value = [
            SimpleNamespace(name='broken_app'), SimpleNamespace(name='quiet_app')]

        def find_spec(module_name):
            return object() if module_name == 'broken_app.jobs' else None

        with patch.object(plugin, 'apps', registry), \
                patch.object(plugin, 'find_spec', side_effect=find_spec), \
                patch.object(plugin, 'import_module',
                             side_effect=RuntimeError('password=hunter2')):
            failures = plugin._import_job_modules()
        self.assertEqual(failures, ['broken_app.jobs (RuntimeError)'])


class SchedulerJobStoreCheckTests(TestCase):
    def test_missing_periodic_jobs_need_collect_jobs(self):
        periodic = [SimpleNamespace(job_id='weather'), SimpleNamespace(job_id='library')]
        DjangoJob.objects.create(id='weather', job_state=b'state')
        with patch.object(plugin, '_periodical_jobs', periodic), \
                patch.object(plugin, '_import_job_modules', return_value=[]), \
                debug(False):
            missing = list(plugin._check_periodic_jobs())
            DjangoJob.objects.create(id='library', job_state=b'state')
            complete = list(plugin._check_periodic_jobs())

        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0][:2], (FAIL, 'periodic jobs'))
        self.assertIn('1 of 2 not in the job store (library)', missing[0][2])
        self.assertEqual(
            complete, [(OK, 'periodic jobs', 'all 2 registered (2 stored jobs)')])

    def test_import_failures_are_reported_before_the_job_count(self):
        with patch.object(plugin, '_periodical_jobs', []), \
                patch.object(plugin, '_import_job_modules',
                             return_value=['yp_library.jobs (ModuleNotFoundError)']):
            results = list(plugin._check_periodic_jobs())
        self.assertEqual(results[0][:2], (FAIL, 'jobs modules'))
        self.assertEqual(results[1][:2], (OK, 'periodic jobs'))

    def test_recent_failed_and_missed_executions_warn(self):
        job = DjangoJob.objects.create(id='weather', job_state=b'state')
        now = datetime(2026, 9, 10, 12, 0)
        for hours, status in ((1, DjangoJobExecution.ERROR),
                              (2, DjangoJobExecution.SUCCESS),
                              (3, DjangoJobExecution.MISSED),
                              (30, DjangoJobExecution.ERROR)):
            DjangoJobExecution.objects.create(
                job=job, status=status, run_time=now - timedelta(hours=hours))

        self.assertEqual(plugin._check_recent_executions(now), (
            WARN, 'job executions (24 h)',
            '1 failed, 1 missed or skipped of 3: see Django job executions '
            'in the admin'))
        DjangoJobExecution.objects.exclude(
            status=DjangoJobExecution.SUCCESS).delete()
        self.assertEqual(
            plugin._check_recent_executions(now),
            (OK, 'job executions (24 h)', '1 recorded, none failed'))
