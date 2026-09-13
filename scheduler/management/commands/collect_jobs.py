from importlib import import_module

from django.apps import apps
from django.core.management.base import BaseCommand

from scheduler.periodic import _periodical_jobs


def collect_periodical_jobs(target_scheduler, output=None):
    """Discover application job modules and register their periodic jobs."""
    for app in apps.get_app_configs():
        job_module_path = app.name + '.jobs'
        try:
            import_module(job_module_path)
        except ModuleNotFoundError as exc:
            if exc.name != job_module_path:
                raise
            continue
        if output is not None:
            output.write(f'Looking for periodical jobs in {job_module_path}')

    for pjob in _periodical_jobs:
        if output is not None:
            output.write(
                f'\t{pjob.job_id} '
                f'(fn: {pjob.function.__name__}, trigger: {pjob.trigger})'
            )
        target_scheduler.add_job(
            pjob.function,
            pjob.trigger,
            id=pjob.job_id,
            replace_existing=True,
            **pjob.tg_args,
        )


class Command(BaseCommand):
    help = "Register periodical jobs."

    def handle(self, *args, **options):
        from scheduler.scheduler import scheduler

        collect_periodical_jobs(scheduler, output=self.stdout)
