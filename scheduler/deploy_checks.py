"""
Scheduler checks of ``python manage.py deploy_check``.

Offline: ``scheduler.use_scheduler`` and ``rpc_port``, periodic jobs missing
from the django_apscheduler job store, and failed or skipped executions in
the last 24 hours. ``online`` adds the RPC health call that
``scheduler_health`` uses. Level policy: ``utils.deploy_check``.
"""
from datetime import datetime, timedelta
from importlib import import_module
from importlib.util import find_spec
from typing import Any, Iterator

import rpyc
from django.apps import apps
from django.db.models import Count, Q
from django_apscheduler.models import DjangoJob, DjangoJobExecution

from utils.deploy_check import (
    FAIL, OK, WARN, preview, production_level, resolve_setting,
)
from utils.health_check import db_connection_healthy
from scheduler.config import scheduler_config as CONFIG
from scheduler.periodic import _periodical_jobs


__all__ = ['checks']


Result = tuple[str, str, str]

RPC_HOST = 'localhost'
RPC_TIMEOUT_SECONDS = 5
EXECUTION_WINDOW = timedelta(hours=24)


def checks(*, online: bool = False) -> Iterator[Result]:
    """Yield the scheduler checks; ``online`` adds the RPC health call."""
    yield _check_use_scheduler()
    port, port_error = resolve_setting(CONFIG, 'rpc_port')
    yield _check_rpc_port(port, port_error)
    if db_connection_healthy():
        yield from _check_periodic_jobs()
        yield _check_recent_executions(datetime.now())
    else:
        yield WARN, 'job store', 'skipped: database unreachable'
    if online and _valid_port(port, port_error):
        yield _check_rpc_health(port)


def _valid_port(port: Any, error: str | None) -> bool:
    return (error is None and isinstance(port, int)
            and not isinstance(port, bool) and 0 < port < 65536)


def _check_use_scheduler() -> Result:
    name = 'scheduler.use_scheduler'
    enabled, error = resolve_setting(CONFIG, 'use_scheduler')
    if error is None and enabled:
        return OK, name, 'on'
    # scheduler.scheduler never starts its job store in this case, so added
    # jobs stay in memory and are lost.
    return (production_level(), name, 'off: scheduled work (course stages, '
            'reminders, periodic jobs) is never stored or run')


def _check_rpc_port(port: Any, error: str | None) -> Result:
    name = 'scheduler.rpc_port'
    if _valid_port(port, error):
        return OK, name, str(port)
    return FAIL, name, 'missing or not a port number: runscheduler cannot start'


def _import_job_modules() -> list[str]:
    # Import every app's jobs module, as collect_jobs does, so that their
    # @periodical jobs are known. collect_jobs silently skips a module that
    # fails to import; report it instead.
    failures = []
    for app_config in apps.get_app_configs():
        module_name = f'{app_config.name}.jobs'
        try:
            if find_spec(module_name) is None:
                continue
        except ModuleNotFoundError:
            continue
        try:
            import_module(module_name)
        except Exception as exc:
            failures.append(f'{module_name} ({type(exc).__name__})')
    return failures


def _check_periodic_jobs() -> Iterator[Result]:
    failures = _import_job_modules()
    if failures:
        yield (FAIL, 'jobs modules', f'cannot import {preview(failures)}: '
               'their periodic jobs are never registered')
    name = 'periodic jobs'
    job_ids = sorted({job.job_id for job in _periodical_jobs})
    stored = set(DjangoJob.objects.values_list('id', flat=True))
    missing = [job_id for job_id in job_ids if job_id not in stored]
    if missing:
        yield (production_level(), name, f'{len(missing)} of {len(job_ids)} '
               f'not in the job store ({preview(missing)}): '
               'run python manage.py collect_jobs')
    else:
        yield OK, name, f'all {len(job_ids)} registered ({len(stored)} stored jobs)'


def _check_recent_executions(now: datetime) -> Result:
    name = 'job executions (24 h)'
    counts = DjangoJobExecution.objects.filter(
        run_time__gte=now - EXECUTION_WINDOW,
    ).aggregate(
        total=Count('id'),
        failed=Count('id', filter=Q(status=DjangoJobExecution.ERROR)),
        skipped=Count('id', filter=Q(status__in=[
            DjangoJobExecution.MISSED, DjangoJobExecution.MAX_INSTANCES,
        ])),
    )
    if counts['failed'] or counts['skipped']:
        return (WARN, name, f"{counts['failed']} failed, {counts['skipped']} "
                f"missed or skipped of {counts['total']}: see Django job "
                'executions in the admin')
    return OK, name, f"{counts['total']} recorded, none failed"


def _check_rpc_health(port: int) -> Result:
    name = 'scheduler RPC'
    try:
        conn = rpyc.connect(
            RPC_HOST, port,
            config={'sync_request_timeout': RPC_TIMEOUT_SECONDS})
    except ConnectionRefusedError:
        return (FAIL, name, 'scheduler not running (connection refused on port '
                f'{port}): start python manage.py runscheduler')
    except OSError as exc:
        return FAIL, name, f'unreachable ({type(exc).__name__})'
    try:
        healthy = conn.root.health_check()
    except (OSError, EOFError) as exc:
        return FAIL, name, f'health call failed ({type(exc).__name__})'
    finally:
        conn.close()
    if healthy:
        return OK, name, 'scheduler running'
    return (FAIL, name, 'scheduler reports unhealthy: its database connection '
            'or job loop is down')
