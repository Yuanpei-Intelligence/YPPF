"""Tests of ``dormitory/deploy_checks.py``."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from utils.deploy_check import OK, WARN
from generic.models import User
from questionnaire.models import Survey
from dormitory import deploy_checks as plugin


class DormitoryDeployChecksTests(TestCase):
    def check(self, title, database_ok=True):
        config = SimpleNamespace(routine_qa_survey_title=title)
        with patch.object(plugin, 'CONFIG', config):
            return plugin._check_routine_qa_survey(database_ok)

    def add_survey(self, title):
        if not hasattr(self, 'survey_owner'):
            self.survey_owner = User.objects.create_user(
                'dormitory-survey-owner', 'Owner', password='pw')
        Survey.objects.create(
            title=title, creator=self.survey_owner,
            start_time=datetime(2026, 8, 1), end_time=datetime(2026, 9, 1))

    def test_routine_qa_survey_must_exist_exactly_once(self):
        name = 'dormitory.routine_qa_survey_title'
        absent = self.check('Routine QA')
        self.add_survey('Routine QA')
        present = self.check('Routine QA')
        self.add_survey('Routine QA')
        duplicated = self.check('Routine QA')

        self.assertEqual(absent[0], WARN)
        self.assertEqual(present, (OK, name, 'the survey exists'))
        self.assertEqual(duplicated[0], WARN)
        self.assertIn("2 surveys titled 'Routine QA'", duplicated[2])
        self.assertEqual(self.check('')[0], WARN)
        self.assertEqual(self.check('Routine QA', database_ok=False),
                         (WARN, name, 'skipped: database unreachable'))
