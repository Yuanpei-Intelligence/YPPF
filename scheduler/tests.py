from unittest.mock import Mock

from django.test import SimpleTestCase

from scheduler.management.commands.collect_jobs import collect_periodical_jobs


class CollectPeriodicalJobsTests(SimpleTestCase):
    def test_birthboard_cron_jobs_are_registered(self):
        target_scheduler = Mock()

        collect_periodical_jobs(target_scheduler)

        registered_ids = {
            call.kwargs['id'] for call in target_scheduler.add_job.call_args_list
        }
        self.assertIn('birthboard_nightly_update_2345', registered_ids)
        self.assertIn('birthboard_nightly_retry_0005', registered_ids)
        self.assertIn('birthboard_retry_pending_takedowns', registered_ids)
        retry_call = next(
            call for call in target_scheduler.add_job.call_args_list
            if call.kwargs['id'] == 'birthboard_retry_pending_takedowns'
        )
        self.assertEqual(retry_call.kwargs['minutes'], 3)
