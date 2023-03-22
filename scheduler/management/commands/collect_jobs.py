from importlib import import_module

from django.apps import apps
from django.core.management.base import BaseCommand

from scheduler.scheduler import scheduler, PeriodicalJob


class Command(BaseCommand):
    help = "Register periodical jobs."

    def handle(self, *args, **options):
        for app in apps.get_app_configs():
            job_module_path = app.name + '.jobs'
            try:
                jobs = import_module(job_module_path)
            except:
                continue
            print('Looking for periodical jobs in', job_module_path)
            for pjob in filter(lambda obj: hasattr(obj, '__periodical__'), jobs.__dict__.values()):
                pjob: PeriodicalJob = pjob.__periodical__  # type: ignore
                job_id, fn, trigger = pjob.job_id, pjob.function, pjob.trigger
                print(f'\t{job_id} (fn: {fn.__name__}, trigger: {trigger})')
                scheduler.add_job(fn, trigger, id=job_id, replace_existing=True, **pjob.tg_args)
