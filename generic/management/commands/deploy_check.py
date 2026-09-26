"""
``deploy_check``: the project-wide deployment self-check.

Any installed app may ship ``<app package>/deploy_checks.py`` exposing::

    def checks(*, online: bool = False) -> Iterable[tuple[str, str, str]]:
        '''Yield (level, name, detail); level is 'OK', 'WARN' or 'FAIL'.'''

The command imports every such module in ``INSTALLED_APPS`` order (only the
apps selected with ``--app`` when given), runs it, and prints the results
grouped by app label, or a JSON list of ``{app, level, name, detail}``
objects with ``--format json``. It exits non-zero when a check fails unless
``--warn-only`` is given; ``--strict`` also fails on warnings. Plugins may
perform network I/O only when ``--online`` is given.

Plugins yield plain tuples, import nothing from this module, never print
and never yield secrets. A plugin that cannot be imported or raises is
reported as one ``FAIL`` line naming only the exception class; Django's
``--traceback`` option adds the message and prints the traceback.
"""
import json
import traceback
from dataclasses import asdict, dataclass
from importlib import import_module
from importlib.util import find_spec
from typing import Any

from django.apps import AppConfig, apps
from django.core.management.base import BaseCommand, CommandError

from utils.deploy_check import FAIL, LEVELS, WARN


PLUGIN_MODULE = 'deploy_checks'


@dataclass(frozen=True)
class CheckResult:
    """One reported line: the app label and a plugin's (level, name, detail)."""
    app: str
    level: str
    name: str
    detail: str


class Command(BaseCommand):
    help = ('Run the deployment self-checks that installed apps ship as '
            '<app>/deploy_checks.py; exits non-zero on failures unless '
            '--warn-only.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--app', action='append', dest='app_labels', metavar='LABEL',
            help='only run the checks of this app label; repeatable')
        parser.add_argument(
            '--online', action='store_true',
            help='also probe external services (network I/O)')
        exit_policy = parser.add_mutually_exclusive_group()
        exit_policy.add_argument(
            '--warn-only', action='store_true',
            help='report failures but exit 0')
        exit_policy.add_argument(
            '--strict', action='store_true',
            help='exit non-zero on warnings as well as failures')
        parser.add_argument(
            '--format', choices=('text', 'json'), default='text',
            help='text grouped by app (default) or a JSON list')

    def handle(self, *args, **options):
        if options['warn_only'] and options['strict']:
            raise CommandError('--warn-only and --strict are mutually exclusive')
        results: list[CheckResult] = []
        for app_config in self._selected_apps(options['app_labels']):
            results.extend(self._run_plugin(app_config, options))

        if options['format'] == 'json':
            payload = [asdict(result) for result in results]
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._write_text(results)

        blocking = (FAIL, WARN) if options['strict'] else (FAIL,)
        failed = [result for result in results if result.level in blocking]
        if failed and not options['warn_only']:
            names = ', '.join(f'{result.app}/{result.name}' for result in failed)
            raise CommandError(
                f'deploy_check: {len(failed)} check(s) did not pass: {names}')

    def _selected_apps(self, labels: list[str] | None) -> list[AppConfig]:
        app_configs = list(apps.get_app_configs())
        if not labels:
            return app_configs
        known = {app_config.label for app_config in app_configs}
        unknown = [label for label in labels if label not in known]
        if unknown:
            raise CommandError('unknown app label(s): ' + ', '.join(unknown))
        return [
            app_config for app_config in app_configs
            if app_config.label in labels
        ]

    def _run_plugin(self, app_config: AppConfig,
                    options: dict[str, Any]) -> list[CheckResult]:
        module_name = f'{app_config.name}.{PLUGIN_MODULE}'
        try:
            spec = find_spec(module_name)
        except ModuleNotFoundError:
            # The app is a plain module rather than a package: no plugin.
            return []
        if spec is None:
            return []

        label = app_config.label
        # A broken plugin must not hide the other apps' results, so anything
        # it raises (ImportError included) becomes one FAIL line for its app.
        try:
            module = import_module(module_name)
        except Exception as exc:
            return [self._crash_result(label, 'import failed', exc, options)]
        checks = getattr(module, 'checks', None)
        if not callable(checks):
            return [CheckResult(
                label, FAIL, PLUGIN_MODULE, 'defines no checks() function')]

        results = []
        try:
            for item in checks(online=options['online']):
                results.append(self._to_result(label, item))
        except Exception as exc:
            results.append(
                self._crash_result(label, 'check crashed', exc, options))
        return results

    def _crash_result(self, label: str, what: str, exc: Exception,
                      options: dict[str, Any]) -> CheckResult:
        detail = f'{what} ({type(exc).__name__})'
        # Exception messages may quote configuration values: opt-in only.
        if options.get('traceback'):
            detail += f': {exc}'
            self.stderr.write(''.join(traceback.format_exception(exc)))
        return CheckResult(label, FAIL, PLUGIN_MODULE, detail)

    @staticmethod
    def _to_result(label: str, item: Any) -> CheckResult:
        try:
            level, name, detail = item
        except (TypeError, ValueError):
            return CheckResult(label, FAIL, PLUGIN_MODULE,
                               'yielded a result that is not (level, name, detail)')
        if level not in LEVELS:
            return CheckResult(label, FAIL, str(name), 'yielded an unknown level')
        return CheckResult(
            label, level, str(name), '' if detail is None else str(detail))

    def _write_text(self, results: list[CheckResult]) -> None:
        current_app = None
        for result in results:
            if result.app != current_app:
                current_app = result.app
                self.stdout.write(f'== {current_app} ==')
            line = f'  [{result.level}] {result.name}'
            if result.detail:
                line += f': {result.detail}'
            self.stdout.write(line)
        failures = sum(result.level == FAIL for result in results)
        warnings = sum(result.level == WARN for result in results)
        app_count = len({result.app for result in results})
        self.stdout.write(
            f'{len(results)} checks in {app_count} app(s): '
            f'{failures} failed, {warnings} warning(s)')
