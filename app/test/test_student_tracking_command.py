from copy import deepcopy
from datetime import datetime
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from app.student_tracking_survey import LOCK_NAME, SURVEY_TITLES
from generic.models import User
from questionnaire.models import Choice, Question, Survey


class StudentTrackingCommandTests(TestCase):
    def setUp(self):
        # Use synthetic content so CI does not need the private questionnaire.
        data_dir = self.enterContext(TemporaryDirectory())
        data_path = self.data_path = Path(data_dir) / 'survey.json'
        self.data = {
            'description': 'Synthetic survey description',
            'questions': [
                dict(order=order, topic=f'Question {order}', description=f'Help {order}',
                     type=Question.Type.SINGLE, required=True, choices=['Option B', 'Option A'])
                for order in range(1, 22)
            ],
        }
        self.data['questions'][-1].update(
            type=Question.Type.MULTIPLE, min_choices=2, max_choices=2,
            choices=['Option C', 'Option A', 'Option B'])
        data_path.write_text(json.dumps(self.data), encoding='utf-8')
        self.enterContext(patch('app.student_tracking_survey.DATA_PATH', data_path))
        self.creator = User.objects.create_user('tracking_creator', 'Creator', password='pw')
        self.options = dict(
            creator=self.creator.username,
            start='2026-09-08 08:00:00', end='2026-09-30 23:59:59', stdout=StringIO())

    def run_command(self, **overrides):
        call_command('create_student_tracking_questionnaire_2026', **{**self.options, **overrides})

    def test_creates_both_versions_with_exact_choices_and_titles(self):
        self.run_command()
        template = json.loads((Path(__file__).resolve().parents[2] / 'config_template.json').read_text())
        config = template['course']['prerequisite_survey']
        self.assertEqual([title for title, _ in SURVEY_TITLES],
                         [config['rules'][0]['survey'], config['fallback']])
        self.assertEqual(Survey.objects.count(), 2)
        self.assertEqual(Question.objects.count(), 32)
        self.assertEqual(Choice.objects.count(), 65)
        for title, count in SURVEY_TITLES:
            survey = Survey.objects.get(title=title)
            self.assertEqual(survey.creator, self.creator)
            self.assertEqual(survey.status, Survey.Status.DRAFT)
            self.assertEqual(survey.start_time, datetime(2026, 9, 8, 8))
            self.assertEqual(survey.end_time, datetime(2026, 9, 30, 23, 59, 59))
            self.assertEqual(survey.description, self.data['description'])
            self.assertEqual(list(survey.questions.values_list('order', flat=True)), list(range(1, count + 1)))
            self.assertFalse(survey.questions.filter(required=False).exists())
            for spec in self.data['questions'][:count]:
                question = survey.questions.get(order=spec['order'])
                self.assertEqual(question.topic, spec['topic'])
                self.assertEqual(question.description, spec['description'])
                self.assertEqual(list(question.choices.values_list('text', flat=True)), spec['choices'])
        regular = Survey.objects.get(title=SURVEY_TITLES[1][0])
        multiple = regular.questions.get(order=21)
        self.assertEqual(multiple.type, Question.Type.MULTIPLE)
        self.assertEqual((multiple.min_choices, multiple.max_choices), (2, 2))

    def test_missing_data_reports_setup_instruction(self):
        with patch('app.student_tracking_survey.DATA_PATH', Path('/missing/survey.json')):
            with self.assertRaisesMessage(CommandError, 'raw_data/student_tracking_survey_2026.json'):
                self.run_command()
        self.assertFalse(Survey.objects.exists())

    def assert_invalid_data_creates_nothing(self, data, message):
        self.data_path.write_text(json.dumps(data), encoding='utf-8')
        with patch.object(Survey.objects, 'create', wraps=Survey.objects.create) as create:
            with self.assertRaisesMessage(CommandError, message):
                self.run_command(publish=True)
            create.assert_not_called()
        self.assertFalse(Survey.objects.exists())
        self.assertFalse(Question.objects.exists())
        self.assertFalse(Choice.objects.exists())
        self.assertEqual(self.options['stdout'].getvalue(), '')

    def test_wrong_question_count_rejected_before_creation(self):
        for count in (0, 11, 20, 22):
            data = deepcopy(self.data)
            data['questions'] = (data['questions'] * 2)[:count]
            with self.subTest(count=count):
                self.assert_invalid_data_creates_nothing(data, '恰好 21')

    def test_invalid_question_orders_rejected_before_creation(self):
        for index, order in ((20, 20), (20, 22), (0, 0), (0, True), (0, 1.0), (0, '1')):
            data = deepcopy(self.data)
            data['questions'][index]['order'] = order
            with self.subTest(index=index, order=order):
                self.assert_invalid_data_creates_nothing(data, '题号')
        data = deepcopy(self.data)
        del data['questions'][-1]['order']
        self.assert_invalid_data_creates_nothing(data, '题号')
        data = deepcopy(self.data)
        data['questions'][0], data['questions'][1] = data['questions'][1], data['questions'][0]
        self.assert_invalid_data_creates_nothing(data, '题号')

    def test_invalid_question_types_rejected_before_creation(self):
        for index, question_type in ((0, Question.Type.MULTIPLE), (19, Question.Type.TEXT),
                                     (20, Question.Type.SINGLE), (20, Question.Type.RANKING),
                                     (20, 'UNKNOWN'), (20, None)):
            data = deepcopy(self.data)
            data['questions'][index]['type'] = question_type
            with self.subTest(index=index, question_type=question_type):
                self.assert_invalid_data_creates_nothing(data, '类型必须为')
        data = deepcopy(self.data)
        del data['questions'][-1]['type']
        self.assert_invalid_data_creates_nothing(data, '类型必须为')

    def test_invalid_question_structure_rejected_before_creation(self):
        for data in ([], {}, {'questions': {}}, {'questions': [None] * 21}):
            with self.subTest(data=data):
                self.assert_invalid_data_creates_nothing(data, '追踪问卷')

    def test_publish_and_repeat_preserve_existing_records(self):
        self.run_command(publish=True)
        original = list(Survey.objects.values())
        question_ids = list(Question.objects.values_list('pk', flat=True))
        choice_ids = list(Choice.objects.values_list('pk', flat=True))
        self.assertTrue(all(row['status'] == Survey.Status.PUBLISHED for row in original))
        self.run_command(end='2027-01-01 00:00:00')
        self.assertEqual(list(Survey.objects.values()), original)
        self.assertEqual(list(Question.objects.values_list('pk', flat=True)), question_ids)
        self.assertEqual(list(Choice.objects.values_list('pk', flat=True)), choice_ids)

    def test_invalid_arguments_do_not_create_surveys(self):
        for overrides in ({'creator': 'missing'}, {'start': 'invalid'},
                          {'start': self.options['end']}, {'end': '2020-01-01 00:00:00'}):
            with self.subTest(overrides=overrides), self.assertRaises(CommandError):
                self.run_command(**overrides)
            self.assertFalse(Survey.objects.exists())
        # A failed operation must release the bootstrap lock.
        self.run_command()
        self.assertEqual(Survey.objects.count(), 2)

    def test_failure_rolls_back_both_versions(self):
        create = Survey.objects.create

        def fail_second(**kwargs):
            if kwargs['title'] == SURVEY_TITLES[1][0]:
                raise RuntimeError('Simulated failure')
            return create(**kwargs)

        with patch.object(Survey.objects, 'create', side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                self.run_command()
        self.assertFalse(Survey.objects.exists())
        self.assertFalse(Question.objects.exists())
        self.assertFalse(Choice.objects.exists())
        self.run_command()
        self.assertEqual(Survey.objects.count(), 2)

    def test_duplicate_title_rejected_without_partial_creation(self):
        for _ in range(2):
            Survey.objects.create(
                title=SURVEY_TITLES[1][0], creator=self.creator, status=Survey.Status.DRAFT,
                start_time=datetime(2026, 9, 8), end_time=datetime(2026, 9, 30))
        with self.assertRaises(CommandError):
            self.run_command()
        self.assertEqual(Survey.objects.count(), 2)
        self.assertFalse(Question.objects.exists())

    def test_creates_only_missing_version(self):
        existing = Survey.objects.create(
            title=SURVEY_TITLES[0][0], creator=self.creator, status=Survey.Status.DRAFT,
            description='Preserve this manual survey',
            start_time=datetime(2026, 1, 1), end_time=datetime(2026, 12, 31))
        self.run_command(publish=True)
        existing.refresh_from_db()
        self.assertEqual(existing.description, 'Preserve this manual survey')
        self.assertEqual(existing.status, Survey.Status.DRAFT)
        self.assertEqual(existing.questions.count(), 0)
        regular = Survey.objects.get(title=SURVEY_TITLES[1][0])
        self.assertEqual(regular.questions.count(), 21)
        self.assertEqual(regular.status, Survey.Status.PUBLISHED)

    def test_concurrent_bootstrap_lock_prevents_creation(self):
        other = connection.copy(alias='tracking_lock_holder')
        try:
            with other.cursor() as cursor:
                cursor.execute('SELECT GET_LOCK(%s, 0)', [LOCK_NAME])
                self.assertEqual(cursor.fetchone()[0], 1)
                try:
                    with self.assertRaisesMessage(CommandError, '正在执行'):
                        self.run_command()
                    self.assertFalse(Survey.objects.exists())
                finally:
                    cursor.execute('SELECT RELEASE_LOCK(%s)', [LOCK_NAME])
        finally:
            other.close()
        self.run_command()
        self.assertEqual(Survey.objects.count(), 2)
