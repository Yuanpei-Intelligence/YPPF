from django.core.management.base import BaseCommand


class Command(BaseCommand):
	help = "Simulate birthboard nightly update job (23:45)"

	def handle(self, *args, **options):
		from birthboard.jobs import birthboard_nightly_update_2345

		birthboard_nightly_update_2345()
		self.stdout.write(
			self.style.SUCCESS("birthboard nightly update 23:45 finished")
		)