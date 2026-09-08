from datetime import datetime, timedelta
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import Client, TestCase

from app.config import CourseConfig
from app.course_forms import CourseSurveyForm
from app.course_survey_utils import get_course_prerequisite_survey, has_completed_course_survey
from app.models import NaturalPerson, User
from questionnaire.models import AnswerSheet, AnswerText, Choice, Question, Survey
from rest_framework.exceptions import ValidationError


class CourseSurveyTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 1, 12)
        self.user = User.objects.create_user('S2026001', 'Student', User.Type.STUDENT, password='pw')
        self.person = NaturalPerson.objects.create(
            self.user, name='Student', identity=NaturalPerson.Identity.STUDENT)
        self.user.is_newuser = False
        self.user.save(update_fields=['is_newuser'])
        self.survey = Survey.objects.create(
            title='Required', creator=self.user, status=Survey.Status.PUBLISHED,
            start_time=self.now - timedelta(days=1), end_time=self.now + timedelta(days=1))
        self.question = Question.objects.create(
            survey=self.survey, order=1, topic='Why?', type=Question.Type.TEXT)
        self.config = {'enabled': True, 'rules': [], 'fallback': 'Required'}
        conf = self.enterContext(patch('app.course_survey_utils.CONFIG'))
        conf.course.prerequisite_survey = self.config
        for target in ('app.course_views.datetime', 'questionnaire.utils.datetime'):
            clock = self.enterContext(patch(target, wraps=datetime))
            clock.now.return_value = self.now
        self.enterContext(patch('app.course_views.utils.get_sidebar_and_navbar', return_value={}))
        self.client.force_login(self.user)

    def test_default_disabled_and_ordered_matching(self):
        self.assertEqual(CourseConfig({}).prerequisite_survey, {})
        self.config['enabled'] = False
        self.assertIsNone(get_course_prerequisite_survey(self.user))
        self.config['enabled'] = True
        self.config['rules'] = [
            {'pattern': '^S2026', 'survey': 'Required'},
            {'pattern': 'S', 'survey': 'Does not exist'},
        ]
        self.assertEqual(get_course_prerequisite_survey(self.user), self.survey)
        self.config['rules'] = [{'pattern': '^X', 'survey': 'Does not exist'}]
        self.assertEqual(get_course_prerequisite_survey(self.user), self.survey)

    def test_invalid_configuration_fails_closed(self):
        for rules in ([{'pattern': '[', 'survey': 'Required'}], [None], 'invalid'):
            self.config['rules'] = rules
            with self.assertRaises(ImproperlyConfigured):
                get_course_prerequisite_survey(self.user)
            self.assertEqual(self.client.get('/selectCourse/').status_code, 503)
        self.config['rules'] = []
        self.config['fallback'] = 'missing'
        self.assertEqual(self.client.get('/selectCourse/').status_code, 503)
        self.config['fallback'] = 'Required'
        self.survey.pk = None
        self.survey.save()
        self.assertEqual(self.client.get('/selectCourse/').status_code, 503)

    def test_get_is_read_only_and_direct_selection_is_blocked(self):
        for path in ('/selectCourse/', '/yppf/selectCourse/'):
            response = self.client.get(path)
            self.assertContains(response, '选课前置问卷')
            self.assertNotContains(response, '全部课程')
            with patch('app.course_views.registration_status_change') as change:
                self.assertEqual(self.client.post(path, {'action': 'select', 'courseid': 1}).status_code, 403)
                change.assert_not_called()
        self.assertFalse(AnswerSheet.objects.exists())

    def test_draft_resumes_and_submission_unlocks(self):
        sheet = AnswerSheet.objects.create(survey=self.survey, creator=self.user)
        AnswerText.objects.create(answersheet=sheet, question=self.question, body='Old draft')
        self.assertFalse(has_completed_course_survey(self.user, self.survey))
        self.assertContains(self.client.get('/selectCourse/'), 'Old draft')
        response = self.client.post('/selectCourse/', {
            'action': 'submit_survey', str(self.question.pk): 'My answer'})
        self.assertRedirects(response, '/selectCourse/', fetch_redirect_response=False)
        sheet.refresh_from_db()
        self.assertEqual(sheet.status, AnswerSheet.Status.SUBMITTED)
        self.assertEqual(AnswerText.objects.get(answersheet=sheet).body, 'My answer')
        self.assertTrue(has_completed_course_survey(self.user, self.survey))
        self.assertTemplateUsed(self.client.get('/selectCourse/'), 'course/select_course.html')

    def test_new_submission_and_required_validation(self):
        self.assertEqual(self.client.post('/selectCourse/', {'action': 'submit_survey'}).status_code, 400)
        self.assertFalse(AnswerSheet.objects.exists())
        response = self.client.post('/selectCourse/', {
            'action': 'submit_survey', str(self.question.pk): 'Answer'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(has_completed_course_survey(self.user, self.survey))

    def test_other_user_submission_does_not_unlock(self):
        other = User.objects.create_user('other', 'Other', User.Type.STUDENT, password='pw')
        AnswerSheet.objects.create(survey=self.survey, creator=other, status=AnswerSheet.Status.SUBMITTED)
        self.assertContains(self.client.get('/selectCourse/'), '选课前置问卷')

    def test_completed_user_can_post_selection_and_invalid_input_is_rejected(self):
        AnswerSheet.objects.create(survey=self.survey, creator=self.user, status=AnswerSheet.Status.SUBMITTED)
        with patch('app.course_views.Course.objects.activated') as courses:
            courses.return_value.filter.return_value.exists.return_value = True
            with patch('app.course_views.registration_status_change',
                       return_value={'warn_code': 2, 'warn_message': 'Success'}) as change:
                response = self.client.post('/selectCourse/', {'action': 'select', 'courseid': 1})
                self.assertEqual(response.status_code, 302)
                change.assert_called_once_with(1, self.person, 'select')
                change.reset_mock()
                self.client.post('/selectCourse/', {'action': 'select', 'courseid': 'invalid'})
                change.assert_not_called()

    def test_unavailable_survey_and_already_submitted(self):
        self.survey.status = Survey.Status.ENDED
        self.survey.save(update_fields=['status'])
        self.assertEqual(self.client.get('/selectCourse/').status_code, 503)
        AnswerSheet.objects.create(survey=self.survey, creator=self.user, status=AnswerSheet.Status.SUBMITTED)
        self.assertTemplateUsed(self.client.get('/selectCourse/'), 'course/select_course.html')

    def test_auth_method_csrf_and_permission_gates(self):
        self.client.logout()
        self.assertEqual(self.client.get('/selectCourse/').status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post('/selectCourse/', {'action': 'submit_survey'}).status_code, 403)
        self.assertEqual(client.delete('/selectCourse/').status_code, 403)
        response = client.get('/selectCourse/')
        token = response.cookies['csrftoken'].value
        response = client.post('/selectCourse/', {
            'action': 'submit_survey', str(self.question.pk): 'Answer', 'csrfmiddlewaretoken': token})
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.put('/selectCourse/').status_code, 405)
        with patch.object(NaturalPerson, 'has_permission', return_value=False):
            self.assertEqual(self.client.get('/selectCourse/').status_code, 302)

    def test_disabled_gate_preserves_page_and_inactive_selection_rejection(self):
        self.config['enabled'] = False
        self.assertTemplateUsed(self.client.get('/selectCourse/'), 'course/select_course.html')
        self.user.active = False
        self.user.save(update_fields=['active'])
        with patch('app.course_views.registration_status_change') as change:
            response = self.client.post('/selectCourse/', {'action': 'select', 'courseid': 1})
            self.assertEqual(response.status_code, 302)
            change.assert_not_called()

    def test_organization_and_teacher_behavior(self):
        # The organization gate must run before the prerequisite lookup.
        with patch('app.course_views.get_person_or_org'), patch.object(User, 'is_org', return_value=True):
            with patch('app.course_views.get_course_prerequisite_survey') as lookup:
                self.assertEqual(self.client.get('/selectCourse/').status_code, 302)
                lookup.assert_not_called()
        self.person.identity = NaturalPerson.Identity.TEACHER
        self.person.save(update_fields=['identity'])
        # Even a misconfigured prerequisite must not block teachers.
        self.config['fallback'] = 'missing'
        with patch('app.course_views.get_course_prerequisite_survey') as lookup:
            for path in ('/selectCourse/', '/yppf/selectCourse/'):
                response = self.client.get(path)
                self.assertTemplateUsed(response, 'course/select_course.html')
                self.assertNotContains(response, '选课前置问卷')
                self.client.post(path, {
                    'action': 'submit_survey', str(self.question.pk): 'Answer'})
                with patch('app.course_views.registration_status_change') as change:
                    self.client.post(path, {'action': 'select', 'courseid': 1})
                    change.assert_not_called()
            lookup.assert_not_called()
        self.assertFalse(AnswerSheet.objects.exists())

    def test_student_profile_requires_survey_for_all_person_account_types(self):
        for account_type in User.Type.Persons():
            self.user.utype = account_type
            self.user.save(update_fields=['utype'])
            self.assertContains(self.client.get('/selectCourse/'), '选课前置问卷')

    def test_submission_failure_rolls_back_draft_replacement(self):
        sheet = AnswerSheet.objects.create(survey=self.survey, creator=self.user)
        AnswerText.objects.create(answersheet=sheet, question=self.question, body='Preserved')
        with patch('app.course_survey_utils.submit_answersheet', side_effect=ValidationError('Closed')):
            response = self.client.post('/selectCourse/', {
                'action': 'submit_survey', str(self.question.pk): 'Replacement'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AnswerText.objects.get(answersheet=sheet).body, 'Preserved')
        sheet.refresh_from_db()
        self.assertEqual(sheet.status, AnswerSheet.Status.DRAFT)

    def test_choice_types_and_invalid_answers(self):
        single = Question.objects.create(survey=self.survey, order=2, topic='Single', type=Question.Type.SINGLE)
        multiple = Question.objects.create(
            survey=self.survey, order=3, topic='Multiple', type=Question.Type.MULTIPLE, min_choices=2)
        ranking = Question.objects.create(survey=self.survey, order=4, topic='Ranking', type=Question.Type.RANKING)
        for question in (single, multiple, ranking):
            for order in (1, 2):
                Choice.objects.create(question=question, order=order, text=f'Option {order}')
        data = {str(self.question.pk): 'Text', str(single.pk): '1',
                str(multiple.pk): ['1', '2'], str(ranking.pk): '2,1'}
        self.assertTrue(CourseSurveyForm(self.survey, data).is_valid())
        for key, value in ((single.pk, '99'), (multiple.pk, ['1']), (ranking.pk, '1,1')):
            invalid = {**data, str(key): value}
            self.assertFalse(CourseSurveyForm(self.survey, invalid).is_valid())
        response = self.client.post('/selectCourse/', {**data, 'action': 'submit_survey'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(has_completed_course_survey(self.user, self.survey))

    def test_webview_render_and_expiry(self):
        self.assertContains(self.client.get('/selectCourse/', HTTP_USER_AGENT='MicroMessenger'),
                            '提交问卷并进入选课')
        self.survey.end_time = self.now - timedelta(seconds=1)
        self.survey.save(update_fields=['end_time'])
        self.assertEqual(self.client.get('/selectCourse/').status_code, 503)

    def test_survey_text_is_escaped(self):
        self.question.description = '<script>alert(1)</script>'
        self.question.save(update_fields=['description'])
        response = self.client.get('/selectCourse/')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
