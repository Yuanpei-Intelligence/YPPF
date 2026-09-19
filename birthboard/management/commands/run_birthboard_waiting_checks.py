from django.core.management.base import BaseCommand

from birthboard.jobs import birthboard_waiting_remind_and_autoreject


class Command(BaseCommand):
    help = "Run birthboard waiting reminder/auto-reject checks immediately"

    def handle(self, *args, **options):
        birthboard_waiting_remind_and_autoreject()
        self.stdout.write(self.style.SUCCESS("birthboard waiting checks finished"))
