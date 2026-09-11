"""Tests of the timetable mini-program API (``/api/v2/timetable/``)."""
import tempfile
from datetime import date, datetime, timedelta
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from generic.models import User
from semester.models import CalendarEvent
from api.config import WXMiniappConfig
from timetable import catalog, services
from timetable.models import (
    CourseCatalogEntry,
    CourseExam,
    ImportLog,
    SubscribeQuota,
    TimetableEntry,
    TimetableEntryOverride,
    TimetableSettings,
)
from timetable.sources.exam import ExamSource
from timetable.sources.stored import StoredEntriesSource
from timetable.tests.helpers import (
    make_entry, make_person, make_term, portal_payload, read_fixture,
)

ENTRY_KEYS = {
    'id', 'term', 'source', 'name', 'course_code', 'class_no', 'teacher', 'room',
    'weekday', 'start_section', 'end_section', 'start_time', 'end_time',
    'week_start', 'week_end', 'parity', 'note', 'hidden', 'color',
    'role', 'category', 'tag', 'catalog', 'overrides', 'exam',
}
OVERRIDE_KEYS = {'id', 'week_start', 'week_end', 'canceled', 'fields', 'updated_at'}
CATALOG_KEYS = {'id', 'course_code', 'name', 'class_no', 'teacher', 'credits', 'time_text',
                'slots', 'department', 'category', 'audience', 'hours_per_week',
                'weeks_text', 'note', 'added'}


def _this_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


class _FakeElective:
    """Stand-in for ``pku_account.extern.elective.ElectiveClient``."""

    def __init__(self, pku):
        self.pku = pku

    def login(self, username, password):
        self.pku.elective_logins.append(username)
        if self.pku.elective_error is not None:
            raise self.pku.elective_error
        return self

    def get_results_html(self):
        return self.pku.elective_html


class _FakePku:
    """Stand-in for the lazily imported ``pku_account`` integration."""

    class PortalDisabled(Exception):
        pass

    class AccountLocked(Exception):
        pass

    class AlreadyBoundElsewhere(Exception):
        pass

    class NotBound(Exception):
        pass

    class SessionUnavailable(Exception):
        pass

    class IaaaError(Exception):
        def __init__(self, code='E01', msg='用户名或密码错误'):
            super().__init__(msg)
            self.code = code
            self.msg = msg

    class OtpRequired(IaaaError):
        pass

    class CaptchaRequired(IaaaError):
        pass

    class PortalUnreachable(Exception):
        pass

    class PortalSessionExpired(Exception):
        pass

    def __init__(self, account=None, payload=None, login_error=None,
                 client_error=None, fetch_error=None, elective_html=None,
                 elective_error=None):
        self.account = account
        self.payload = payload
        self.login_error = login_error
        self.client_error = client_error
        self.fetch_error = fetch_error
        self.elective_html = elective_html
        self.elective_error = elective_error
        self.login_calls = []
        self.fetch_calls = []
        self.elective_logins = []
        self.marked = []
        self.invalidated = []
        self.ElectiveClient = _FakeElective(self)

    def login_and_bind(self, user, username, password, *, consent_timetable=None,
                       consent_grades=None):
        self.login_calls.append((user, username, consent_timetable))
        if self.login_error is not None:
            raise self.login_error
        return self.account

    def get_binding(self, user):
        return self.account

    def get_client(self, user):
        if self.client_error is not None:
            raise self.client_error
        return self

    def get_course_info(self, term_code):
        self.fetch_calls.append(term_code)
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.payload

    def mark_session_ok(self, account, *, synced=True):
        self.marked.append((account, synced))

    def invalidate_session(self, account, reason):
        self.invalidated.append((account, reason))


def _account(consent=True):
    return SimpleNamespace(consent_timetable=consent, last_sync_at=None)


class TimetableAPITestCase(APITestCase):

    def setUp(self):
        self.client = APIClient()
        self.user, self.person = make_person('tt_api_student', 'API 同学')
        self.other_user, self.other_person = make_person('tt_api_other', '别的同学')
        self.org_user = User.objects.create_user(
            'tt_api_org', '某小组', User.Type.ORG, password='pw')
        # Today is in teaching week 2 of the current term.
        self.term = make_term(week1_monday=_this_monday() - timedelta(days=7))
        self.old_term = make_term(code='25-26-2', week1_monday=_this_monday() - timedelta(days=210))
        self.client.force_authenticate(user=self.user)

    def url(self, name, **kwargs):
        return reverse(f'api:timetable:{name}', kwargs=kwargs or None)


class AuthTests(TimetableAPITestCase):

    def endpoints(self):
        entry = make_entry(self.person, self.term, source=TimetableEntry.Source.MANUAL)
        return [
            ('get', self.url('terms')),
            ('get', self.url('week')),
            ('get', self.url('agenda')),
            ('get', self.url('overview')),
            ('get', self.url('entry-list')),
            ('post', self.url('entry-list')),
            ('get', self.url('entry-detail', pk=entry.pk)),
            ('patch', self.url('entry-detail', pk=entry.pk)),
            ('delete', self.url('entry-detail', pk=entry.pk)),
            ('delete', self.url('entry-overrides', pk=entry.pk)),
            ('delete', self.url('entry-override-detail', pk=entry.pk, oid=1)),
            ('post', self.url('import-portal')),
            ('post', self.url('import-text')),
            ('get', self.url('settings')),
            ('patch', self.url('settings')),
            ('get', self.url('ics')),
            ('post', self.url('ics-rotate')),
            ('get', self.url('subscribe-templates')),
            ('post', self.url('subscribe-grant')),
            ('get', self.url('catalog')),
            ('post', self.url('catalog-add', pk=1)),
            ('get', self.url('share-assets')),
        ]

    def test_anonymous_gets_401(self):
        self.client.force_authenticate(user=None)
        for method, url in self.endpoints():
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {}, format='json')
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
                self.assertEqual(response.data['code'], 'not_authenticated')
                self.assertIn('message', response.data)

    def test_organization_gets_403(self):
        self.client.force_authenticate(user=self.org_user)
        for method, url in self.endpoints():
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {}, format='json')
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(response.data['code'], 'permission_denied')

    def test_person_without_profile_gets_403(self):
        orphan = User.objects.create_user('tt_api_orphan', '无档案', User.Type.STUDENT,
                                          password='pw')
        self.client.force_authenticate(user=orphan)
        response = self.client.get(self.url('terms'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TermsAndWeekTests(TimetableAPITestCase):

    def test_terms(self):
        make_term(code='27-28-1', week1_monday=date(2027, 9, 13), is_active=False)
        response = self.client.get(self.url('terms'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['current']['code'], '26-27-1')
        self.assertEqual(response.data['current']['current_week'], 2)
        self.assertEqual([t['code'] for t in response.data['terms']], ['26-27-1', '25-26-2'])
        self.assertEqual(set(response.data['current']), {
            'code', 'name', 'week1_monday', 'total_weeks', 'exam_week_start', 'teaching_weeks',
            'current_week', 'section_times', 'calendar'})
        self.assertEqual(response.data['current']['calendar'], [])
        self.assertIsNone(response.data['current']['exam_week_start'])
        self.assertEqual(response.data['current']['teaching_weeks'], 16)

    def test_terms_exam_weeks(self):
        """``exam_week_start`` / ``teaching_weeks`` of §8.4 on the Term payload."""
        self.term.total_weeks = 19
        self.term.exam_week_start = 17
        self.term.save()
        response = self.client.get(self.url('terms'))
        current = response.data['current']
        self.assertEqual((current['total_weeks'], current['exam_week_start'],
                          current['teaching_weeks']), (19, 17, 16))
        week = self.client.get(self.url('week'), {'week': 19}).data
        self.assertEqual((week['week'], week['term']['teaching_weeks']), (19, 16))

    def test_terms_without_any_term(self):
        self.term.delete()
        self.old_term.delete()
        response = self.client.get(self.url('terms'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['current'])
        self.assertEqual(response.data['terms'], [])

    def test_week_defaults_to_current_term_and_week(self):
        make_entry(self.person, self.term, name='高数', weekday=1)
        make_entry(self.other_person, self.term, name='别人的课', weekday=1)
        response = self.client.get(self.url('week'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data['term']['code'], '26-27-1')
        self.assertEqual(data['week'], 2)
        self.assertEqual(len(data['week_dates']), 7)
        self.assertEqual(data['week_dates'][0], _this_monday().isoformat())
        self.assertEqual(data['today'], {
            'date': date.today().isoformat(),
            'weekday': date.today().isoweekday(), 'week': 2})
        self.assertEqual([o['title'] for o in data['occurrences']], ['高数'])
        self.assertEqual(data['occurrences'][0]['kind'], 'course')
        self.assertEqual(data['conflicts'], [])
        self.assertIn({'key': 'stored', 'label': '课程'}, data['sources'])

    def test_week_explicit_and_clamped(self):
        response = self.client.get(self.url('week'), {'term': '25-26-2', 'week': 99})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['term']['code'], '25-26-2')
        self.assertEqual(response.data['week'], 16)
        self.assertIsNone(response.data['today']['week'])
        response = self.client.get(self.url('week'), {'week': 0})
        self.assertEqual(response.data['week'], 1)

    def test_week_bad_input(self):
        response = self.client.get(self.url('week'), {'week': 'abc'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'validation_error')
        self.assertIn('week', response.data['errors'])
        response = self.client.get(self.url('week'), {'term': 'no-such'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'TERM_NOT_FOUND')

    def test_week_without_any_term(self):
        self.term.delete()
        self.old_term.delete()
        response = self.client.get(self.url('week'))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'NO_CURRENT_TERM')


class AgendaTests(TimetableAPITestCase):
    """``agenda/`` (README §6.5)."""

    def test_defaults_to_today_and_seven_days(self):
        today = date.today()
        make_entry(self.person, self.term, name='今天的课', weekday=today.isoweekday())
        make_entry(self.other_person, self.term, name='别人的课', weekday=today.isoweekday())
        response = self.client.get(self.url('agenda'))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        data = response.data
        self.assertEqual(set(data), {'from', 'days', 'sources'})
        self.assertEqual(data['from'], today.isoformat())
        self.assertEqual([day['date'] for day in data['days']],
                         [(today + timedelta(days=i)).isoformat() for i in range(7)])
        first = data['days'][0]
        self.assertEqual(set(first), {'date', 'weekday', 'term', 'week', 'kind', 'label',
                                      'occurrences'})
        self.assertEqual((first['weekday'], first['term'], first['week'], first['kind'],
                          first['label']), (today.isoweekday(), '26-27-1', 2, None, None))
        self.assertEqual([o['title'] for o in first['occurrences']], ['今天的课'])
        occurrence = first['occurrences'][0]
        self.assertEqual((occurrence['kind'], occurrence['date'], occurrence['week']),
                         ('course', today.isoformat(), 2))
        self.assertIn({'key': 'stored', 'label': '课程'}, data['sources'])

    def test_term_boundary_holiday_and_capping(self):
        sunday = self.term.week1_monday - timedelta(days=1)
        make_entry(self.person, self.term, name='周一课', weekday=1)
        CalendarEvent.objects.create(kind='holiday', start_date=sunday, end_date=sunday,
                                     name='开学前一天')
        response = self.client.get(self.url('agenda'), {'from': sunday.isoformat(), 'days': 2})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['from'], sunday.isoformat())
        self.assertEqual(response.data['days'][0], {
            'date': sunday.isoformat(), 'weekday': 7, 'term': None, 'week': None,
            'kind': 'holiday', 'label': '开学前一天', 'occurrences': []})
        monday = response.data['days'][1]
        self.assertEqual((monday['term'], monday['week'], monday['kind']), ('26-27-1', 1, None))
        self.assertEqual([o['title'] for o in monday['occurrences']], ['周一课'])
        response = self.client.get(self.url('agenda'), {'from': sunday.isoformat(), 'days': 99})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['days']), 14)

    def test_without_any_term(self):
        self.term.delete()
        self.old_term.delete()
        response = self.client.get(self.url('agenda'), {'days': 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual([(day['term'], day['week'], day['occurrences'])
                          for day in response.data['days']], [(None, None, [])])

    def test_show_courses_toggle(self):
        today = date.today()
        make_entry(self.person, self.term, name='今天的课', weekday=today.isoweekday())
        response = self.client.patch(self.url('settings'), {'show_courses': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.get(self.url('agenda'), {'days': 1})
        self.assertEqual(response.data['days'][0]['occurrences'], [])
        self.assertIn({'key': 'stored', 'label': '课程'}, response.data['sources'])
        self.assertEqual(self.client.get(self.url('week')).data['occurrences'], [])

    def test_bad_input(self):
        cases = [{'from': '2026-13-01'}, {'from': 'yesterday'}, {'from': '2026/09/14'},
                 {'days': 0}, {'days': -1}, {'days': 'abc'}, {'days': '1.5'}]
        for params in cases:
            with self.subTest(params=params):
                response = self.client.get(self.url('agenda'), params)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data['code'], 'validation_error')
                self.assertIn(next(iter(params)), response.data['errors'])
        # Empty query values count as omitted (today / 7 days).
        response = self.client.get(self.url('agenda'), {'from': '', 'days': ''})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['from'], date.today().isoformat())
        self.assertEqual(len(response.data['days']), 7)


class OverviewTests(TimetableAPITestCase):
    """``overview/`` (README §10)."""

    SLOT_KEYS = {
        'key', 'kind', 'source', 'title', 'subtitle', 'location', 'weekday', 'start',
        'end', 'start_section', 'end_section', 'weeks', 'weeks_text', 'parity',
        'color_key', 'role', 'tag', 'ref',
    }

    def setUp(self):
        super().setUp()
        patcher = patch('timetable.services.load_sources',
                        return_value=[StoredEntriesSource(), ExamSource()])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_shape_and_default_term(self):
        entry = make_entry(self.person, self.term, name='高数', weekday=1, week_end=15,
                           parity=1, course_code='00130201', class_no='01')
        make_entry(self.other_person, self.term, name='别人的课', weekday=1)
        exam_day = self.term.date_of(16, 2)
        CourseExam.objects.create(
            term=self.term, course_code='00130201', class_no='01', name='高数',
            start=datetime(exam_day.year, exam_day.month, exam_day.day, 8, 30),
            end=datetime(exam_day.year, exam_day.month, exam_day.day, 10, 30),
            room='考场A')
        response = self.client.get(self.url('overview'))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        data = response.data
        self.assertEqual(set(data), {'term', 'slots', 'exams'})
        self.assertEqual((data['term']['code'], data['term']['current_week']),
                         ('26-27-1', 2))
        self.assertEqual(len(data['slots']), 1)
        slot = data['slots'][0]
        self.assertEqual(set(slot), self.SLOT_KEYS)
        self.assertEqual(
            (slot['key'], slot['kind'], slot['title'], slot['weekday'], slot['start'],
             slot['end'], slot['weeks'], slot['weeks_text'], slot['parity'], slot['ref']),
            (f'portal:{entry.pk}:0', 'course', '高数', 1, '08:00', '09:50',
             list(range(1, 16, 2)), '1-15周 单周', 1, {'entry_id': entry.pk}))
        self.assertEqual(data['exams'], [{
            'title': '高数 考试', 'date': exam_day.isoformat(), 'start': '08:30',
            'end': '10:30', 'location': '考场A', 'week': 16}])

    def test_explicit_and_unknown_term(self):
        make_entry(self.person, self.old_term, name='上学期课', weekday=2)
        response = self.client.get(self.url('overview'), {'term': '25-26-2'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['term']['code'], '25-26-2')
        self.assertEqual([s['title'] for s in response.data['slots']], ['上学期课'])
        # The default term has nothing: empty lists, not an error.
        response = self.client.get(self.url('overview'), {'term': ''})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual((response.data['slots'], response.data['exams']), ([], []))
        response = self.client.get(self.url('overview'), {'term': 'no-such'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'TERM_NOT_FOUND')

    def test_without_any_term(self):
        self.term.delete()
        self.old_term.delete()
        response = self.client.get(self.url('overview'))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'NO_CURRENT_TERM')


class EntryTests(TimetableAPITestCase):

    def manual_body(self, **overrides):
        body = {
            'name': '自习', 'weekday': 3, 'start_section': 3, 'end_section': 4,
            'week_start': 1, 'week_end': 16, 'parity': 0, 'room': '图书馆',
        }
        body.update(overrides)
        return body

    def test_list_scoped_to_person_and_term(self):
        mine = make_entry(self.person, self.term, name='我的课')
        hidden = make_entry(self.person, self.term, name='隐藏课', hidden=True)
        make_entry(self.person, self.old_term, name='旧课')
        make_entry(self.other_person, self.term, name='别人的课')
        response = self.client.get(self.url('entry-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({e['id'] for e in response.data}, {mine.pk, hidden.pk})
        entry = next(e for e in response.data if e['id'] == mine.pk)
        self.assertEqual(entry['term'], '26-27-1')
        self.assertEqual(entry['source'], 'portal')
        self.assertEqual(entry['start_time'], '08:00')
        self.assertEqual(entry['end_time'], '09:50')
        self.assertEqual(set(entry), ENTRY_KEYS)
        self.assertEqual((entry['role'], entry['category'], entry['tag']),
                         ('enrolled', 'course', ''))
        self.assertEqual((entry['catalog'], entry['overrides'], entry['exam']), (None, [], None))
        response = self.client.get(self.url('entry-list'), {'term': '25-26-2'})
        self.assertEqual([e['name'] for e in response.data], ['旧课'])

    def test_create_manual_entry_fills_times_from_sections(self):
        response = self.client.post(self.url('entry-list'), self.manual_body(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['source'], 'manual')
        self.assertEqual(response.data['term'], '26-27-1')
        self.assertEqual(response.data['start_time'], '10:10')
        self.assertEqual(response.data['end_time'], '12:00')
        entry = TimetableEntry.objects.get(pk=response.data['id'])
        self.assertEqual(entry.person, self.person)
        self.assertEqual(len(entry.external_key), 32)
        self.assertFalse(entry.hidden)

    def test_create_with_explicit_times_and_other_term(self):
        body = self.manual_body(term='25-26-2', start_section=0, end_section=0,
                                start_time='21:00', end_time='22:30', color='#aabbcc')
        response = self.client.post(self.url('entry-list'), body, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['term'], '25-26-2')
        self.assertEqual(response.data['start_time'], '21:00')
        self.assertEqual(response.data['color'], '#aabbcc')

    def test_create_validation(self):
        cases = [
            self.manual_body(start_section=0, end_section=0),           # no times
            self.manual_body(week_start=5, week_end=2),
            self.manual_body(start_section=4, end_section=3),
            self.manual_body(weekday=8),
            self.manual_body(week_end=17),
            self.manual_body(start_section=0, end_section=0,
                             start_time='22:00', end_time='21:00'),
            self.manual_body(color='red'),
            self.manual_body(name=''),
            self.manual_body(term='no-such'),
        ]
        for body in cases:
            with self.subTest(body=body):
                response = self.client.post(self.url('entry-list'), body, format='json')
                self.assertIn(response.status_code,
                              (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND))
        self.assertEqual(TimetableEntry.objects.count(), 0)

    def test_patch_manual_entry(self):
        entry = make_entry(self.person, self.term, name='自习',
                           source=TimetableEntry.Source.MANUAL)
        response = self.client.patch(
            self.url('entry-detail', pk=entry.pk),
            {'name': '晚自习', 'start_section': 10, 'end_section': 11, 'hidden': True},
            format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        entry.refresh_from_db()
        self.assertEqual(entry.name, '晚自习')
        self.assertEqual((entry.start_section, entry.end_section), (10, 11))
        self.assertEqual(entry.start_time.strftime('%H:%M'), '18:40')
        self.assertEqual(entry.end_time.strftime('%H:%M'), '20:30')
        self.assertTrue(entry.hidden)
        response = self.client.patch(
            self.url('entry-detail', pk=entry.pk), {'week_start': 9, 'week_end': 3},
            format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_imported_entry_annotations_and_whole_range_override(self):
        """Imported entries: annotations on the row, other keys in the (None, None) override."""
        entry = make_entry(self.person, self.term, name='高数')
        response = self.client.patch(
            self.url('entry-detail', pk=entry.pk), {'hidden': True}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['hidden'])
        response = self.client.patch(
            self.url('entry-detail', pk=entry.pk),
            {'name': '改名', 'hidden': False, 'tag': '必修', 'color': '#112233',
             'role': 'audit'},
            format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        entry.refresh_from_db()
        self.assertEqual((entry.name, entry.hidden, entry.tag, entry.color, entry.role),
                         ('高数', False, '必修', '#112233', 'audit'))
        override = entry.overrides.get()
        self.assertEqual((override.week_start, override.week_end, override.canceled,
                          override.fields), (None, None, False, {'name': '改名'}))
        self.assertEqual(response.data['name'], '高数')
        self.assertEqual(len(response.data['overrides']), 1)
        self.assertEqual(set(response.data['overrides'][0]), OVERRIDE_KEYS)
        self.assertEqual(response.data['overrides'][0]['fields'], {'name': '改名'})
        # Keys merge into the same override; recurrence keys stay off limits.
        response = self.client.patch(
            self.url('entry-detail', pk=entry.pk), {'room': '理教101'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(entry.overrides.get().fields, {'name': '改名', 'room': '理教101'})
        for body in ({'week_start': 2}, {'parity': 1}, {'week_end': 10}):
            with self.subTest(body=body):
                response = self.client.patch(
                    self.url('entry-detail', pk=entry.pk), body, format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(next(iter(body)), response.data['errors'])
        # The week view draws the override.
        week = self.client.get(self.url('week')).data
        self.assertEqual([(o['title'], o['location'], o['modified']) for o in week['occurrences']],
                         [('改名', '理教101', True)])

    def test_delete_rules(self):
        manual = make_entry(self.person, self.term, source=TimetableEntry.Source.MANUAL)
        imported = make_entry(self.person, self.term)
        response = self.client.delete(self.url('entry-detail', pk=imported.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.delete(self.url('entry-detail', pk=manual.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(TimetableEntry.objects.filter(pk=manual.pk).exists())
        self.assertTrue(TimetableEntry.objects.filter(pk=imported.pk).exists())

    def test_other_persons_entry_is_404(self):
        theirs = make_entry(self.other_person, self.term, source=TimetableEntry.Source.MANUAL)
        response = self.client.patch(
            self.url('entry-detail', pk=theirs.pk), {'hidden': True}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'not_found')
        response = self.client.delete(self.url('entry-detail', pk=theirs.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        response = self.client.delete(self.url('entry-detail', pk=999999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ImportTextTests(TimetableAPITestCase):

    def test_dry_run(self):
        response = self.client.post(
            self.url('import-text'),
            {'text': read_fixture('elective_table.html'), 'dry_run': True}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['format'], 'elective')
        self.assertEqual(len(response.data['blocks']), 4)
        self.assertEqual(set(response.data['blocks'][0]), {
            'name', 'teacher', 'room', 'course_code', 'class_no', 'weekday',
            'start_section', 'end_section', 'week_start', 'week_end', 'parity', 'raw', 'note',
            'exam_date', 'exam_period', 'exam_room'})
        response = self.client.post(
            self.url('import-text'),
            {'text': read_fixture('portal_page.html'), 'dry_run': True}, format='json')
        math = [block for block in response.data['blocks'] if block['name'] == '高等数学A（二）']
        self.assertEqual((math[0]['exam_date'], math[0]['exam_period'], math[0]['exam_room']),
                         ('2026-06-18', '上午', '理教306'))
        self.assertEqual(TimetableEntry.objects.count(), 0)
        self.assertEqual(ImportLog.objects.count(), 0)

    def test_dry_run_unknown_format(self):
        response = self.client.post(
            self.url('import-text'), {'text': 'nothing useful', 'dry_run': True}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'format': 'unknown', 'blocks': []})

    def test_commit(self):
        response = self.client.post(
            self.url('import-text'),
            {'text': read_fixture('portal_page.html'), 'term': '25-26-2'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data, {
            'term': '25-26-2', 'created': 6, 'updated': 0, 'removed': 0, 'total': 6})
        entries = TimetableEntry.objects.filter(person=self.person, term=self.old_term)
        self.assertEqual(entries.count(), 6)
        self.assertEqual(set(entries.values_list('source', flat=True)), {'paste'})

    def test_commit_failure(self):
        response = self.client.post(
            self.url('import-text'), {'text': 'nothing useful'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'PARSE_FAILED')
        self.assertIn('message', response.data)
        response = self.client.post(self.url('import-text'), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'validation_error')


class ImportPortalTests(TimetableAPITestCase):

    def post(self, fake, body=None):
        with patch('api.timetable.views._load_pku', return_value=fake):
            return self.client.post(self.url('import-portal'), body or {}, format='json')

    def test_no_binding(self):
        response = self.post(_FakePku(account=None))
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'PKU_LOGIN_REQUIRED')
        self.assertIn('message', response.data)

    def test_session_unavailable(self):
        fake = _FakePku(account=_account(), client_error=_FakePku.SessionUnavailable())
        response = self.post(fake)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'PKU_LOGIN_REQUIRED')

    def test_session_expired_invalidates(self):
        account = _account()
        fake = _FakePku(account=account, fetch_error=_FakePku.PortalSessionExpired())
        response = self.post(fake)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'PKU_LOGIN_REQUIRED')
        self.assertEqual(fake.invalidated, [(account, 'expired')])
        self.assertEqual(fake.marked, [])

    def test_consent_required(self):
        response = self.post(_FakePku(account=_account(consent=False), payload=portal_payload()))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['code'], 'CONSENT_REQUIRED')
        self.assertEqual(TimetableEntry.objects.count(), 0)

    def test_success_with_existing_session(self):
        account = _account()
        fake = _FakePku(account=account, payload=portal_payload())
        response = self.post(fake)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data, {
            'term': '26-27-1', 'created': 7, 'updated': 0, 'removed': 0, 'total': 7})
        self.assertEqual(fake.fetch_calls, ['26-27-1'])
        self.assertEqual(fake.login_calls, [])
        self.assertEqual(fake.marked, [(account, True)])
        entries = TimetableEntry.objects.filter(person=self.person, term=self.term)
        self.assertEqual(entries.count(), 7)
        self.assertEqual(set(entries.values_list('source', flat=True)), {'portal'})

    def test_success_with_credentials_binds_with_consent(self):
        account = _account()
        fake = _FakePku(account=account, payload=portal_payload())
        with self.assertNoLogs('api.timetable', level='DEBUG'):
            response = self.post(fake, {'username': '2300012345', 'password': 's3cret',
                                        'term': '25-26-2'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(fake.login_calls, [(self.user, '2300012345', True)])
        self.assertEqual(fake.fetch_calls, ['25-26-2'])
        self.assertEqual(response.data['term'], '25-26-2')
        self.assertEqual(fake.marked, [(account, True)])

    def test_error_mapping(self):
        cases = [
            (_FakePku.IaaaError(), 400, 'IAAA_ERROR', '用户名或密码错误'),
            (_FakePku.OtpRequired('OTP', '需要短信验证'), 400, 'OTP_REQUIRED', '需要短信验证'),
            (_FakePku.CaptchaRequired('C', '需要验证码'), 400, 'CAPTCHA_REQUIRED', '需要验证码'),
            (_FakePku.AccountLocked('锁定中'), 429, 'LOCKED', '锁定中'),
            (_FakePku.AlreadyBoundElsewhere('已绑定'), 409, 'ALREADY_BOUND_ELSEWHERE', '已绑定'),
            (_FakePku.PortalDisabled('已关闭'), 503, 'PORTAL_DISABLED', '已关闭'),
            (_FakePku.PortalUnreachable('连不上'), 503, 'PORTAL_UNREACHABLE', '连不上'),
        ]
        for error, expected_status, code, message in cases:
            with self.subTest(code=code):
                fake = _FakePku(account=_account(), login_error=error)
                response = self.post(fake, {'username': 'u', 'password': 'p'})
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.data['code'], code)
                self.assertEqual(response.data['message'], message)
        fake = _FakePku(account=_account(), fetch_error=_FakePku.PortalUnreachable('超时'))
        response = self.post(fake)
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data['code'], 'PORTAL_UNREACHABLE')
        fake = _FakePku(account=_account(), client_error=_FakePku.NotBound())
        response = self.post(fake)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'PKU_LOGIN_REQUIRED')

    def test_parse_failure_does_not_mark_session(self):
        fake = _FakePku(account=_account(), payload={'success': False, 'remark': '系统维护'})
        response = self.post(fake)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'PARSE_FAILED')
        self.assertEqual(fake.marked, [])
        self.assertEqual(ImportLog.objects.filter(status=ImportLog.Status.FAILED).count(), 1)

    def test_empty_course_table_falls_back_to_elective_results(self):
        account = _account()
        fake = _FakePku(account=account, payload={'success': True, 'course': []},
                        elective_html=read_fixture('elective_table.html'))
        with self.assertNoLogs('api.timetable', level='DEBUG'):
            response = self.post(fake, {'username': '2300012345', 'password': 's3cret'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data, {
            'term': '26-27-1', 'created': 4, 'updated': 0, 'removed': 0, 'total': 4})
        self.assertEqual(fake.fetch_calls, ['26-27-1'])
        self.assertEqual(fake.elective_logins, ['2300012345'])
        self.assertEqual(fake.marked, [(account, True)])
        entries = TimetableEntry.objects.filter(person=self.person, term=self.term)
        self.assertEqual(set(entries.values_list('source', flat=True)), {'portal'})
        log = ImportLog.objects.get(person=self.person)
        self.assertEqual(log.message, 'no lessons in portal payload; imported from elective results')

    def test_elective_fallback_needs_credentials_and_a_current_term(self):
        fake = _FakePku(account=_account(), payload={'success': True, 'course': []},
                        elective_html=read_fixture('elective_table.html'))
        response = self.post(fake)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'PARSE_FAILED')
        response = self.post(fake, {'username': 'u', 'password': 'p', 'term': '25-26-2'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'PARSE_FAILED')
        self.assertEqual(fake.elective_logins, [])
        self.assertEqual(TimetableEntry.objects.count(), 0)

    def test_failed_elective_fallback_answers_like_an_empty_table(self):
        cases = [
            (_FakePku.PortalUnreachable('连不上'), 'PortalUnreachable'),
            (_FakePku.PortalSessionExpired(), 'PortalSessionExpired'),
            (_FakePku.OtpRequired('AUTHEN_MODE', '需要二次验证'), 'OtpRequired AUTHEN_MODE'),
        ]
        for error, outcome in cases:
            with self.subTest(outcome=outcome):
                fake = _FakePku(account=_account(), payload={'success': True, 'course': []},
                                elective_error=error)
                with self.assertLogs('api.timetable.views', level='WARNING') as logs:
                    response = self.post(fake, {'username': '2300012345', 'password': 's3cret'})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data, {'code': 'PARSE_FAILED',
                                                 'message': '门户未返回任何课程，本地课表未改动'})
                self.assertEqual(fake.marked, [])
                shown = '\n'.join(logs.output)
                self.assertIn(outcome, shown)
                self.assertNotIn('s3cret', shown)
                self.assertNotIn('2300012345', shown)
                log = ImportLog.objects.filter(status=ImportLog.Status.FAILED).latest('id')
                self.assertEqual(log.message,
                                 f'no lessons in portal payload; elective fallback: {outcome}')

    def test_integration_unavailable(self):
        with patch('api.timetable.views._load_pku', side_effect=ImportError('no pku_account')), \
                self.assertLogs('api.timetable.views', level='WARNING'):
            response = self.client.post(self.url('import-portal'), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data['code'], 'PORTAL_DISABLED')

    def test_unknown_term(self):
        response = self.post(_FakePku(account=_account()), {'term': 'no-such'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'TERM_NOT_FOUND')

    @skipUnless(find_spec('pku_account.services') is not None, 'pku_account not present')
    def test_real_pku_account_module_names(self):
        """The bridge resolves every name it needs from the real module."""
        from pku_account import services as pku_services
        with patch('pku_account.services.get_binding', return_value=None):
            response = self.client.post(self.url('import-portal'), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'PKU_LOGIN_REQUIRED')
        account = _account()
        with patch('pku_account.services.get_binding', return_value=account), \
                patch('pku_account.services.get_client',
                      side_effect=pku_services.SessionUnavailable('gone')):
            response = self.client.post(self.url('import-portal'), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'PKU_LOGIN_REQUIRED')


class SettingsAndIcsTests(TimetableAPITestCase):

    def test_settings_get_and_patch(self):
        response = self.client.get(self.url('settings'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sources = response.data.pop('sources')
        self.assertEqual(response.data, {
            'reminder_enabled': False, 'reminder_minutes': 20, 'show_courses': True,
            'show_college': True, 'show_activities': True, 'show_appointments': True,
            'show_exams': True, 'share_show_name': True, 'hidden_tags': [], 'tags': []})
        self.assertIn({'key': 'stored', 'label': '课程', 'setting': 'show_courses'}, sources)
        for item in sources:
            self.assertEqual(set(item), {'key', 'label', 'setting'})
        response = self.client.patch(
            self.url('settings'),
            {'reminder_enabled': True, 'reminder_minutes': 30, 'show_college': False,
             'show_courses': False,
             'ics_token': '00000000-0000-0000-0000-000000000000'},
            format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['reminder_minutes'], 30)
        self.assertFalse(response.data['show_college'])
        self.assertFalse(response.data['show_courses'])
        self.assertNotIn('ics_token', response.data)
        settings = TimetableSettings.objects.get(person=self.person)
        self.assertTrue(settings.reminder_enabled)
        self.assertFalse(settings.show_courses)
        self.assertTrue(settings.show_activities)
        response = self.client.patch(self.url('settings'), {'show_courses': True}, format='json')
        self.assertTrue(response.data['show_courses'])
        self.assertNotEqual(str(settings.ics_token), '00000000-0000-0000-0000-000000000000')
        response = self.client.patch(self.url('settings'), {'reminder_minutes': 5000}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'validation_error')

    def test_ics_url_and_rotate(self):
        make_entry(self.person, self.term, name='高数', weekday=1)
        response = self.client.get(self.url('ics'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        token = response.data['token']
        settings = TimetableSettings.objects.get(person=self.person)
        self.assertEqual(token, str(settings.ics_token))
        self.assertTrue(response.data['url'].startswith('http'))
        self.assertTrue(response.data['url'].endswith(f'/timetable/ics/{token}.ics'))
        feed_url = reverse('timetable:ics_feed', kwargs={'token': token})
        feed = APIClient().get(feed_url)
        self.assertEqual(feed.status_code, status.HTTP_200_OK)
        self.assertEqual(feed['Content-Type'], 'text/calendar; charset=utf-8')
        self.assertEqual(feed['Cache-Control'], 'private, max-age=3600')
        self.assertIn('BEGIN:VEVENT', feed.content.decode('utf-8'))
        self.assertIn('SUMMARY:高数', feed.content.decode('utf-8'))

        response = self.client.post(self.url('ics-rotate'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotEqual(response.data['token'], token)
        settings.refresh_from_db()
        self.assertEqual(response.data['token'], str(settings.ics_token))
        self.assertEqual(APIClient().get(feed_url).status_code, status.HTTP_404_NOT_FOUND)
        new_url = reverse('timetable:ics_feed', kwargs={'token': response.data['token']})
        self.assertEqual(APIClient().get(new_url).status_code, status.HTTP_200_OK)

    def test_ics_feed_errors(self):
        client = APIClient()
        response = client.get('/timetable/ics/12345678-1234-1234-1234-123456789012.ics')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        response = client.get('/timetable/ics/not-a-token.ics')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        settings = TimetableSettings.objects.create(person=self.person)
        feed_url = reverse('timetable:ics_feed', kwargs={'token': settings.ics_token})
        self.assertEqual(client.post(feed_url).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class SubscribeTests(TimetableAPITestCase):

    def test_templates_null_when_unconfigured(self):
        with patch.object(WXMiniappConfig, 'subscribe_templates', {}):
            response = self.client.get(self.url('subscribe-templates'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'class_reminder': {'template_id': None}})
        with patch.object(WXMiniappConfig, 'subscribe_templates',
                          {'class_reminder': {'id': '  ', 'page': 'pages/timetable/index'}}):
            response = self.client.get(self.url('subscribe-templates'))
        self.assertEqual(response.data, {'class_reminder': {'template_id': None}})

    def test_templates_configured(self):
        templates = {'class_reminder': {'id': 'TPL-1'}, 'other': {'id': ''}}
        with patch.object(WXMiniappConfig, 'subscribe_templates', templates):
            response = self.client.get(self.url('subscribe-templates'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {
            'class_reminder': {'template_id': 'TPL-1'},
            'other': {'template_id': None},
        })

    def test_grant_defaults_accumulates_and_caps(self):
        with patch('timetable.reminders.CONFIG') as config:
            config.subscribe_quota_cap = 5
            response = self.client.post(self.url('subscribe-grant'),
                                        {'template_key': 'class_reminder'}, format='json')
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
            self.assertEqual(response.data, {'template_key': 'class_reminder', 'count': 1})
            response = self.client.post(self.url('subscribe-grant'),
                                        {'template_key': 'class_reminder', 'count': 10},
                                        format='json')
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
            self.assertEqual(response.data, {'template_key': 'class_reminder', 'count': 5})
        quota = SubscribeQuota.objects.get(user=self.user, template_key='class_reminder')
        self.assertEqual(quota.count, 5)
        self.assertFalse(SubscribeQuota.objects.filter(user=self.other_user).exists())

    def test_grant_validation(self):
        cases = [{}, {'template_key': 'no-such'}, {'template_key': 'class_reminder', 'count': 0},
                 {'template_key': 'class_reminder', 'count': 'x'}]
        for body in cases:
            with self.subTest(body=body):
                response = self.client.post(self.url('subscribe-grant'), body, format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data['code'], 'validation_error')
        self.assertEqual(SubscribeQuota.objects.count(), 0)


class CatalogTests(TimetableAPITestCase):

    def setUp(self):
        super().setUp()
        catalog.upsert_catalog_rows(self.term, [
            {'course_code': '00130201', 'name': '高等数学A（二）', 'class_no': '01',
             'teacher': '张三', 'credits': '5', 'weeks_text': '1-16周',
             'time_text': '周一1-2节 理教406;周三3-4节 理教406'},
            {'course_code': '04831410', 'name': '程序设计实习', 'class_no': '1',
             'teacher': '李四', 'weeks_text': '1-16', 'time_text': '周二3-4节 理教201'},
        ])
        catalog.upsert_catalog_rows(self.old_term, [
            {'course_code': '00130202', 'name': '高等数学A（三）', 'class_no': '01'},
        ])

    def test_search_shape_and_filters(self):
        response = self.client.get(self.url('catalog'), {'q': '高等'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data), 1)
        row = response.data[0]
        self.assertEqual(set(row), CATALOG_KEYS)
        self.assertEqual(row['name'], '高等数学A（二）')
        self.assertFalse(row['added'])
        self.assertEqual((row['department'], row['category'], row['audience'],
                          row['hours_per_week'], row['weeks_text'], row['note']),
                         ('', '', '', '', '1-16周', ''))
        # credits is a JSON number (or null), never a string.
        self.assertIsInstance(row['credits'], float)
        self.assertEqual(row['credits'], 5.0)
        self.assertEqual(row['time_text'], '周一1-2节 理教406;周三3-4节 理教406')
        self.assertEqual(row['slots'], [
            {'weekday': 1, 'start_section': 1, 'end_section': 2,
             'week_start': 1, 'week_end': 16, 'parity': 0, 'room': '理教406'},
            {'weekday': 3, 'start_section': 3, 'end_section': 4,
             'week_start': 1, 'week_end': 16, 'parity': 0, 'room': '理教406'},
        ])
        # Every slot carries exactly the LessonBlock keys the entry form reads.
        for slot in row['slots']:
            self.assertEqual(set(slot), {'weekday', 'start_section', 'end_section',
                                         'week_start', 'week_end', 'parity', 'room'})
            self.assertTrue(1 <= slot['weekday'] <= 7)
            self.assertIn(slot['parity'], (0, 1, 2))
            self.assertIsInstance(slot['room'], str)
            for key in ('start_section', 'end_section', 'week_start', 'week_end'):
                self.assertIsInstance(slot[key], int)
        by_teacher = self.client.get(self.url('catalog'), {'q': '李四'}).data
        self.assertEqual([r['name'] for r in by_teacher], ['程序设计实习'])
        self.assertIsNone(by_teacher[0]['credits'])
        by_code = self.client.get(self.url('catalog'), {'q': '0483'}).data
        self.assertEqual([r['course_code'] for r in by_code], ['04831410'])
        other = self.client.get(self.url('catalog'), {'q': '高等', 'term': '25-26-2'}).data
        self.assertEqual([r['name'] for r in other], ['高等数学A（三）'])

    def test_blank_query_limit_and_errors(self):
        self.assertEqual(self.client.get(self.url('catalog')).data, [])
        self.assertEqual(self.client.get(self.url('catalog'), {'q': '  '}).data, [])
        catalog.upsert_catalog_rows(self.term, [
            {'course_code': f'{i:08d}', 'name': f'批量课程{i}', 'class_no': '01'}
            for i in range(25)
        ])
        response = self.client.get(self.url('catalog'), {'q': '批量课程'})
        self.assertEqual(len(response.data), 20)
        response = self.client.get(self.url('catalog'), {'q': '高等', 'term': 'no-such'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'TERM_NOT_FOUND')
        response = self.client.get(self.url('catalog'), {'q': 'x' * 65})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'validation_error')


class CalendarTests(TimetableAPITestCase):
    """``calendar`` on terms and ``days`` on the week view (README §6.4)."""

    def setUp(self):
        super().setUp()
        week2 = self.term.week_dates(2)      # this week
        self.holiday = CalendarEvent.objects.create(
            kind='holiday', start_date=week2[3], end_date=week2[4], name='假期')
        self.swap = CalendarEvent.objects.create(
            kind='swap', start_date=week2[5], end_date=week2[5],
            name='按周一课表上课', follows_weekday=1)
        CalendarEvent.objects.create(
            kind='info', start_date=self.old_term.week1_monday,
            end_date=self.old_term.week1_monday, name='上学期注册')
        make_entry(self.person, self.term, name='周一课', weekday=1)
        make_entry(self.person, self.term, name='周四课', weekday=4)
        make_entry(self.person, self.term, name='周六课', weekday=6)

    def test_terms_include_calendar(self):
        response = self.client.get(self.url('terms'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        week2 = self.term.week_dates(2)
        expected = [
            {'kind': 'holiday', 'start': week2[3].isoformat(), 'end': week2[4].isoformat(),
             'name': '假期', 'follows_weekday': None},
            {'kind': 'swap', 'start': week2[5].isoformat(), 'end': week2[5].isoformat(),
             'name': '按周一课表上课', 'follows_weekday': 1},
        ]
        self.assertEqual(response.data['current']['calendar'], expected)
        by_code = {term['code']: term for term in response.data['terms']}
        self.assertEqual(by_code['26-27-1']['calendar'], expected)
        self.assertEqual(by_code['25-26-2']['calendar'], [{
            'kind': 'info', 'start': self.old_term.week1_monday.isoformat(),
            'end': self.old_term.week1_monday.isoformat(),
            'name': '上学期注册', 'follows_weekday': None}])

    def test_week_has_days_and_follows_the_calendar(self):
        response = self.client.get(self.url('week'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(len(data['days']), 7)
        self.assertEqual([day['date'] for day in data['days']], data['week_dates'])
        self.assertEqual(data['days'][0], {
            'date': data['week_dates'][0], 'weekday': 1, 'kind': None,
            'label': None, 'follows_weekday': None})
        self.assertEqual(data['days'][3], {
            'date': data['week_dates'][3], 'weekday': 4, 'kind': 'holiday',
            'label': '假期', 'follows_weekday': None})
        self.assertEqual(data['days'][5], {
            'date': data['week_dates'][5], 'weekday': 6, 'kind': 'swap',
            'label': '按周一课表上课', 'follows_weekday': 1})
        self.assertEqual(
            [(o['title'], o['weekday'], o['status'], o['swap_from'])
             for o in data['occurrences']],
            [('周一课', 1, '', None), ('周四课', 4, 'suspended', None),
             ('周一课', 6, '', 1), ('周六课', 6, 'suspended', None)])
        self.assertEqual(data['occurrences'][2]['date'], data['week_dates'][5])
        # The suspended Saturday lesson overlaps the swapped one without a conflict.
        self.assertEqual(data['conflicts'], [])
        self.assertEqual([e['name'] for e in data['term']['calendar']], ['假期', '按周一课表上课'])
        response = self.client.get(self.url('week'), {'week': 3})
        self.assertEqual([day['kind'] for day in response.data['days']], [None] * 7)
        self.assertEqual([o['title'] for o in response.data['occurrences']],
                         ['周一课', '周四课', '周六课'])

    def test_agenda_carries_status_and_swap_from(self):
        """README §11 on ``agenda/``: suspended lessons and 调休 copies."""
        week2 = self.term.week_dates(2)
        response = self.client.get(self.url('agenda'),
                                   {'from': week2[3].isoformat(), 'days': 3})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        days = response.data['days']
        self.assertEqual(
            [(day['kind'], [(o['title'], o['status'], o['swap_from'])
                            for o in day['occurrences']]) for day in days],
            [('holiday', [('周四课', 'suspended', None)]),
             ('holiday', []),
             ('swap', [('周一课', '', 1), ('周六课', 'suspended', None)])])
        self.assertEqual((days[2]['occurrences'][0]['date'], days[2]['occurrences'][0]['weekday']),
                         (week2[5].isoformat(), 6))

    def test_ignore_calendar_patch(self):
        """README §11: 照常上课 through the scoped PATCH, its undo and validation."""
        thursday = TimetableEntry.objects.get(person=self.person, name='周四课')
        manual = make_entry(self.person, self.term, name='自习', weekday=5,
                            source=TimetableEntry.Source.MANUAL)

        def patch_entry(entry, body):
            return self.client.patch(self.url('entry-detail', pk=entry.pk), body, format='json')

        def lessons(title):
            occurrences = self.client.get(self.url('week')).data['occurrences']
            return [(o['status'], o['swap_from'], o['modified'])
                    for o in occurrences if o['title'] == title]

        self.assertEqual(lessons('周四课'), [('suspended', None, False)])
        response = patch_entry(thursday, {'scope': 'single', 'week': 2, 'ignore_calendar': True})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual([(o['week_start'], o['week_end'], o['canceled'], o['fields'])
                          for o in response.data['overrides']],
                         [(2, 2, False, {'ignore_calendar': True})])
        self.assertEqual(lessons('周四课'), [('', None, True)])
        detail = self.client.get(self.url('entry-detail', pk=thursday.pk)).data
        self.assertEqual(detail['overrides'][0]['fields'], {'ignore_calendar': True})
        # false returns to the calendar; with nothing wider to beat the override
        # is removed, so the lesson is no longer modified (§11.4).
        response = patch_entry(thursday, {'scope': 'single', 'week': 2, 'ignore_calendar': False})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['overrides'], [])
        self.assertEqual(lessons('周四课'), [('suspended', None, False)])
        # A manual entry keeps it in the whole-range override; deleting that restores.
        self.assertEqual(lessons('自习'), [('suspended', None, False)])
        response = patch_entry(manual, {'ignore_calendar': True})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual([(o['week_start'], o['week_end'], o['fields'])
                          for o in response.data['overrides']],
                         [(None, None, {'ignore_calendar': True})])
        self.assertEqual(lessons('自习'), [('', None, True)])
        oid = response.data['overrides'][0]['id']
        response = self.client.delete(self.url('entry-override-detail', pk=manual.pk, oid=oid))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(lessons('自习'), [('suspended', None, False)])
        # Anything but a boolean is rejected and writes nothing.
        for value in ('maybe', None, 2, [], {'a': 1}):
            with self.subTest(value=value):
                response = patch_entry(
                    thursday, {'scope': 'single', 'week': 3, 'ignore_calendar': value})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                                 response.data)
                self.assertEqual(response.data['code'], 'validation_error')
                self.assertIn('ignore_calendar', response.data['errors'])
        self.assertEqual(TimetableEntryOverride.objects.filter(entry=thursday).count(), 0)
        # A whole-range true keeps a single week's false, which wins that week.
        response = patch_entry(thursday, {'ignore_calendar': True})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(lessons('周四课'), [('', None, True)])
        response = patch_entry(thursday, {'scope': 'single', 'week': 2, 'ignore_calendar': False})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual([(o['week_start'], o['week_end'], o['fields'])
                          for o in response.data['overrides']],
                         [(None, None, {'ignore_calendar': True}),
                          (2, 2, {'ignore_calendar': False})])
        self.assertEqual(lessons('周四课'), [('suspended', None, True)])

    def test_manual_entries_follow_the_calendar_by_category(self):
        """README §11.1: a 其它 entry on a holiday or swap date is untouched; 课程 is not."""
        base = {'term': self.term.code, 'week_start': 2, 'week_end': 2,
                'start_section': 0, 'end_section': 0}
        bodies = [
            {'name': '临时活动', 'weekday': 4, 'start_time': '13:30', 'end_time': '14:30',
             'category': 'other'},
            {'name': '手动课', 'weekday': 4, 'start_time': '15:00', 'end_time': '16:00'},
            {'name': '周一活动', 'weekday': 1, 'start_time': '19:00', 'end_time': '20:00',
             'category': 'other'},
        ]
        for body in bodies:
            response = self.client.post(self.url('entry-list'), {**base, **body}, format='json')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['category'], 'other')
        data = self.client.get(self.url('week')).data
        self.assertEqual(
            [(o['title'], o['weekday'], o['status'], o['swap_from'])
             for o in data['occurrences']],
            [('周一课', 1, '', None), ('周一活动', 1, '', None),
             ('周四课', 4, 'suspended', None), ('临时活动', 4, '', None),
             ('手动课', 4, 'suspended', None),
             ('周一课', 6, '', 1), ('周六课', 6, 'suspended', None)])
        self.assertEqual(data['conflicts'], [])
        week2 = self.term.week_dates(2)
        response = self.client.get(self.url('agenda'), {'from': week2[3].isoformat(), 'days': 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual([(o['title'], o['kind'], o['status'])
                          for o in response.data['days'][0]['occurrences']],
                         [('周四课', 'course', 'suspended'), ('临时活动', 'custom', ''),
                          ('手动课', 'course', 'suspended')])


def _catalog_rows(term, old_term=None):
    catalog.upsert_catalog_rows(term, [
        {'course_code': '00130201', 'name': '高等数学A（二）', 'class_no': '01',
         'teacher': '张三', 'credits': '5', 'weeks_text': '1-16周',
         'time_text': '周一1-2节 理教406;周三3-4节 理教406', 'department': '数学科学学院'},
        {'course_code': '04831410', 'name': '程序设计实习', 'class_no': '1',
         'teacher': '李四', 'weeks_text': '1-16', 'time_text': '周二3-4节 理教201'},
        {'course_code': '02330010', 'name': '无时间的课', 'class_no': '01', 'teacher': '王五'},
    ])
    if old_term is not None:
        catalog.upsert_catalog_rows(old_term, [
            {'course_code': '00130202', 'name': '高等数学A（三）', 'class_no': '01',
             'time_text': '周一1-2节 理教406'},
        ])


class QuickAddTests(TimetableAPITestCase):
    """``POST catalog/<id>/add/`` (README §8.1)."""

    def setUp(self):
        super().setUp()
        _catalog_rows(self.term, self.old_term)
        self.math = CourseCatalogEntry.objects.get(course_code='00130201', term=self.term)
        self.programming = CourseCatalogEntry.objects.get(course_code='04831410')
        self.no_slots = CourseCatalogEntry.objects.get(course_code='02330010')
        self.old_math = CourseCatalogEntry.objects.get(course_code='00130202')

    def add(self, row, body=None):
        return self.client.post(self.url('catalog-add', pk=row.pk), body or {}, format='json')

    def test_adds_one_entry_per_slot_as_audit(self):
        response = self.add(self.math)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(len(response.data), 2)
        first, second = response.data
        self.assertEqual(set(first), ENTRY_KEYS)
        self.assertEqual((first['source'], first['role'], first['category'], first['term']),
                         ('manual', 'audit', 'course', '26-27-1'))
        self.assertEqual((first['name'], first['course_code'], first['class_no'],
                          first['teacher'], first['room']),
                         ('高等数学A（二）', '00130201', '01', '张三', '理教406'))
        self.assertEqual((first['weekday'], first['start_section'], first['end_section'],
                          first['start_time'], first['end_time'], first['week_start'],
                          first['week_end'], first['parity']),
                         (1, 1, 2, '08:00', '09:50', 1, 16, 0))
        self.assertEqual((second['weekday'], second['start_section'], second['end_section']),
                         (3, 3, 4))
        self.assertEqual(first['catalog']['id'], self.math.pk)
        self.assertEqual(first['catalog']['department'], '数学科学学院')
        self.assertEqual(first['catalog']['credits'], 5.0)
        entries = TimetableEntry.objects.filter(person=self.person, catalog_entry=self.math)
        self.assertEqual(entries.count(), 2)
        for entry in entries:
            self.assertEqual(len(entry.external_key), 32)
            self.assertEqual(entry.raw_text, '')
        # The catalog now reports the row as added.
        rows = self.client.get(self.url('catalog'), {'q': '高等'}).data
        self.assertEqual([(row['name'], row['added']) for row in rows], [('高等数学A（二）', True)])
        rows = self.client.get(self.url('catalog'), {'q': '程序'}).data
        self.assertFalse(rows[0]['added'])
        # The lessons show up in the week view as courses of an audit role.
        week = self.client.get(self.url('week')).data
        self.assertEqual([(o['title'], o['kind'], o['role']) for o in week['occurrences']],
                         [('高等数学A（二）', 'course', 'audit'), ('高等数学A（二）', 'course', 'audit')])

    def test_role_and_slot_selection(self):
        response = self.add(self.math, {'role': 'enrolled', 'slots': [1]})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual([(e['role'], e['weekday']) for e in response.data], [('enrolled', 3)])

    def test_already_added(self):
        self.assertEqual(self.add(self.math).status_code, status.HTTP_201_CREATED)
        response = self.add(self.math)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'timetable.catalog_already_added')
        self.assertIn('高等数学A（二）', response.data['message'])
        # A manual entry linked through the entry form counts as added too.
        response = self.client.post(self.url('entry-list'), {
            'name': '程序设计实习', 'weekday': 2, 'start_section': 3, 'end_section': 4,
            'week_start': 1, 'week_end': 16, 'catalog_id': self.programming.pk,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(self.add(self.programming).status_code, status.HTTP_409_CONFLICT)
        # Another person is not affected.
        self.client.force_authenticate(user=self.other_user)
        self.assertEqual(self.add(self.math).status_code, status.HTTP_201_CREATED)

    def test_not_found(self):
        response = self.add(self.old_math)                       # row of another term
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'timetable.catalog_not_found')
        response = self.add(self.math, {'term': '25-26-2'})
        self.assertEqual(response.data['code'], 'timetable.catalog_not_found')
        response = self.client.post(self.url('catalog-add', pk=999999), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        response = self.add(self.math, {'term': 'no-such'})
        self.assertEqual(response.data['code'], 'TERM_NOT_FOUND')
        self.assertEqual(TimetableEntry.objects.count(), 0)

    def test_no_slots_and_bad_indices(self):
        response = self.add(self.no_slots)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'timetable.catalog_no_slots')
        for body in ({'slots': [2]}, {'slots': [0, 5]}, {'slots': ['x']}, {'slots': [-1]}):
            with self.subTest(body=body):
                response = self.add(self.math, body)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data['code'], 'validation_error')
                self.assertIn('slots', response.data['errors'])
        response = self.add(self.math, {'role': 'teacher'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('role', response.data['errors'])
        self.assertEqual(TimetableEntry.objects.count(), 0)


class EntryDetailAndScopeTests(TimetableAPITestCase):
    """``GET entries/<id>/``, scoped ``PATCH`` and override deletion (README §8.2)."""

    def setUp(self):
        super().setUp()
        _catalog_rows(self.term, self.old_term)
        self.math = CourseCatalogEntry.objects.get(course_code='00130201', term=self.term)
        self.entry = make_entry(self.person, self.term, name='高数', weekday=1,
                                course_code='00130201', class_no='01', room='理教406')

    def patch(self, body, entry=None):
        entry = entry or self.entry
        return self.client.patch(self.url('entry-detail', pk=entry.pk), body, format='json')

    def week(self, week):
        return self.client.get(self.url('week'), {'week': week}).data['occurrences']

    def test_retrieve(self):
        response = self.client.get(self.url('entry-detail', pk=self.entry.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data), ENTRY_KEYS)
        self.assertEqual(response.data['name'], '高数')
        theirs = make_entry(self.other_person, self.term)
        response = self.client.get(self.url('entry-detail', pk=theirs.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'not_found')

    def test_retrieve_with_catalog_and_exam(self):
        self.entry.catalog_entry = self.math
        self.entry.save()
        exam = CourseExam.objects.create(
            term=self.term, course_code='00130201', class_no='01', name='高等数学A（二）',
            start=datetime(2027, 1, 12, 8, 30), end=datetime(2027, 1, 12, 10, 30),
            room='理教201', method='闭卷')
        CourseExam.objects.create(
            term=self.term, course_code='00130201', class_no='01', name='高等数学A（二）',
            start=datetime(2027, 1, 20, 8, 30), end=datetime(2027, 1, 20, 10, 30))
        response = self.client.get(self.url('entry-detail', pk=self.entry.pk))
        self.assertEqual(response.data['catalog'], {
            'id': self.math.pk, 'course_code': '00130201', 'name': '高等数学A（二）',
            'class_no': '01', 'teacher': '张三', 'credits': 5.0, 'department': '数学科学学院',
            'category': '', 'time_text': '周一1-2节 理教406;周三3-4节 理教406',
            'weeks_text': '1-16周', 'note': ''})
        self.assertEqual(response.data['exam'], {
            'id': exam.pk, 'start': '2027-01-12T08:30:00', 'end': '2027-01-12T10:30:00',
            'room': '理教201', 'method': '闭卷', 'note': ''})
        listed = self.client.get(self.url('entry-list')).data
        self.assertEqual(listed[0]['exam']['id'], exam.pk)

    def test_retrieve_with_own_imported_exam(self):
        """README §8.4: without a matching CourseExam the entry's own 考试信息 is its exam."""
        own = make_entry(self.person, self.term, name='量子力学', weekday=2,
                         exam_date=date(2027, 1, 12), exam_period='下午', exam_room='二教411')
        response = self.client.get(self.url('entry-detail', pk=own.pk))
        self.assertEqual(response.data['exam'], {
            'id': None, 'start': '2027-01-12T14:00:00', 'end': '2027-01-12T16:00:00',
            'room': '二教411', 'method': '', 'note': '教务部统一考试时段'})
        # A matching CourseExam wins over the entry's own exam info.
        self.entry.exam_date = date(2027, 1, 20)
        self.entry.save()
        exam = CourseExam.objects.create(
            term=self.term, course_code='00130201', class_no='01', name='高等数学A（二）',
            start=datetime(2027, 1, 12, 8, 30), end=datetime(2027, 1, 12, 10, 30))
        response = self.client.get(self.url('entry-detail', pk=self.entry.pk))
        self.assertEqual(response.data['exam']['id'], exam.pk)
        listed = {item['id']: item['exam'] for item in self.client.get(self.url('entry-list')).data}
        self.assertIsNone(listed[own.pk]['id'])
        self.assertEqual(listed[self.entry.pk]['id'], exam.pk)

    def test_create_with_catalog_role_category_tag(self):
        body = {'name': '高等数学A（二）', 'weekday': 1, 'start_section': 1, 'end_section': 2,
                'week_start': 1, 'week_end': 16, 'catalog_id': self.math.pk, 'role': 'audit',
                'category': 'course', 'tag': '旁听课', 'note': 'n' * 2000}
        response = self.client.post(self.url('entry-list'), body, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual((response.data['role'], response.data['category'], response.data['tag'],
                          response.data['catalog']['id']), ('audit', 'course', '旁听课', self.math.pk))
        entry = TimetableEntry.objects.get(pk=response.data['id'])
        self.assertEqual((entry.catalog_entry, entry.role, entry.tag), (self.math, 'audit', '旁听课'))
        # An exam-type manual entry renders as kind 'exam'.
        body.update({'catalog_id': None, 'category': 'exam', 'name': '期中考试', 'weekday': 3,
                     'week_start': 8, 'week_end': 8, 'note': ''})
        response = self.client.post(self.url('entry-list'), body, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIsNone(response.data['catalog'])
        kinds = {o['title']: o['kind'] for o in self.week(8)}
        self.assertEqual(kinds['期中考试'], 'exam')
        old_math = CourseCatalogEntry.objects.get(course_code='00130202')
        cases = [
            {'catalog_id': old_math.pk},        # other term
            {'catalog_id': 999999},
            {'tag': 'x' * 25},
            {'note': 'n' * 2001},
            {'role': 'teacher'},
            {'category': 'holiday'},
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                response = self.client.post(self.url('entry-list'), {**body, **extra},
                                            format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(next(iter(extra)), response.data['errors'])

    def test_patch_all_annotations_and_unlink(self):
        response = self.patch({'catalog_id': self.math.pk, 'tag': '必修', 'category': 'course'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['catalog']['id'], self.math.pk)
        response = self.patch({'catalog_id': None})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsNone(response.data['catalog'])
        self.entry.refresh_from_db()
        self.assertIsNone(self.entry.catalog_entry)
        self.assertEqual(self.entry.overrides.count(), 0)

    def test_single_following_and_resolution_order(self):
        response = self.patch({'scope': 'single', 'week': 3, 'room': '理教101',
                               'start_section': 3, 'end_section': 4})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        override = response.data['overrides'][0]
        self.assertEqual((override['week_start'], override['week_end'], override['canceled']),
                         (3, 3, False))
        self.assertEqual(override['fields'], {'room': '理教101', 'start_section': 3,
                                              'end_section': 4, 'start_time': '10:10',
                                              'end_time': '12:00'})
        self.entry.refresh_from_db()
        self.assertEqual((self.entry.room, self.entry.start_section), ('理教406', 1))
        week3 = self.week(3)
        self.assertEqual([(o['location'], o['start_section'], o['start'][11:], o['modified'])
                          for o in week3], [('理教101', 3, '10:10:00', True)])
        self.assertEqual([(o['location'], o['modified']) for o in self.week(2)],
                         [('理教406', False)])
        # "This and following": canceled from week 5 on.
        response = self.patch({'scope': 'following', 'week': 5, 'canceled': True})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual([(o['week_start'], o['week_end'], o['canceled'])
                          for o in response.data['overrides']],
                         [(3, 3, False), (5, None, True)])
        self.assertEqual(len(self.week(4)), 1)
        self.assertEqual(self.week(5), [])
        self.assertEqual(self.week(16), [])
        # A single-week override inside the canceled range restores that week.
        response = self.patch({'scope': 'single', 'week': 7, 'canceled': False, 'room': '补课教室'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual([(o['location'], o['modified']) for o in self.week(7)],
                         [('补课教室', True)])
        self.assertEqual(self.week(8), [])
        # Same range → same override, keys merged.
        response = self.patch({'scope': 'single', 'week': 7, 'teacher': '代课老师'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        week7 = [o for o in response.data['overrides'] if o['week_start'] == 7]
        self.assertEqual(len(week7), 1)
        self.assertEqual(week7[0]['fields'], {'room': '补课教室', 'teacher': '代课老师'})
        self.assertEqual(self.entry.overrides.count(), 3)

    def test_weekday_move_and_whole_range_override_survives_reimport(self):
        # A course imported from the portal, moved to Wednesday in week 2 only.
        services.import_portal(self.person, self.term, portal_payload())
        entry = TimetableEntry.objects.get(person=self.person, name='高等数学A（二）',
                                           weekday=1, start_section=1)
        response = self.patch({'scope': 'single', 'week': 2, 'weekday': 3}, entry)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        moved = [o for o in self.week(2) if o['ref']['entry_id'] == entry.pk]
        self.assertEqual([(o['weekday'], o['week'], o['modified']) for o in moved], [(3, 2, True)])
        self.assertEqual(moved[0]['date'], self.term.date_of(2, 3).isoformat())
        # scope=all on an imported entry lands in the whole-range override …
        response = self.patch({'room': '新教室', 'note': '换教室了'}, entry)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        entry.refresh_from_db()
        self.assertEqual(entry.room, '理教406')
        whole = entry.overrides.get(week_start=None, week_end=None)
        self.assertEqual(whole.fields, {'room': '新教室', 'note': '换教室了'})
        # … and survives a re-import that changes nothing else.
        services.import_portal(self.person, self.term, portal_payload())
        entry.refresh_from_db()
        self.assertEqual([(o.week_start, o.week_end) for o in entry.overrides.order_by('id')],
                         [(2, 2), (None, None)])
        self.assertEqual([o['location'] for o in self.week(3)
                          if o['ref']['entry_id'] == entry.pk], ['新教室'])
        # A narrower override wins over the whole-range one, later ids win ties.
        response = self.patch({'scope': 'single', 'week': 3, 'room': '单周教室'}, entry)
        self.assertEqual([o['location'] for o in self.week(3)
                          if o['ref']['entry_id'] == entry.pk], ['单周教室'])

    def test_scope_validation(self):
        cases = [
            ({'scope': 'single', 'room': 'x'}, 'week'),                 # week missing
            ({'scope': 'following', 'week': 0, 'room': 'x'}, 'week'),
            ({'scope': 'single', 'week': 17, 'room': 'x'}, 'week'),
            ({'scope': 'single', 'week': 'abc', 'room': 'x'}, 'week'),
            ({'scope': 'weekly', 'week': 2}, 'scope'),
            ({'scope': 'single', 'week': 2, 'hidden': True}, 'scope'),
            ({'scope': 'following', 'week': 2, 'role': 'audit'}, 'scope'),
            ({'scope': 'single', 'week': 2, 'category': 'other'}, 'scope'),
            ({'scope': 'single', 'week': 2, 'catalog_id': None}, 'scope'),
            ({'scope': 'single', 'week': 2, 'week_start': 1}, 'scope'),
            ({'scope': 'following', 'week': 2, 'parity': 1}, 'scope'),
            ({'canceled': True}, 'canceled'),
            ({'scope': 'all', 'canceled': False, 'room': 'x'}, 'canceled'),
            ({'scope': 'single', 'week': 2, 'color': 'red'}, 'color'),
            ({'scope': 'single', 'week': 2, 'start_section': 5, 'end_section': 1}, 'end_section'),
            ({'scope': 'single', 'week': 2, 'weekday': 8}, 'weekday'),
        ]
        for body, field in cases:
            with self.subTest(body=body):
                response = self.patch(body)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
                self.assertEqual(response.data['code'], 'validation_error')
                self.assertIn(field, response.data['errors'])
        self.assertEqual(TimetableEntryOverride.objects.count(), 0)
        # A manual entry accepts scoped edits too, and an empty patch is a no-op.
        manual = make_entry(self.person, self.term, name='自习', source=TimetableEntry.Source.MANUAL)
        response = self.patch({'scope': 'single', 'week': 2, 'canceled': True}, manual)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['overrides'][0]['canceled'], True)
        response = self.patch({}, manual)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data['overrides']), 1)

    def test_delete_overrides(self):
        self.patch({'scope': 'single', 'week': 2, 'room': 'a'})
        self.patch({'scope': 'single', 'week': 3, 'room': 'b'})
        self.patch({'scope': 'following', 'week': 4, 'canceled': True})
        overrides = list(self.entry.overrides.order_by('id'))
        self.assertEqual(len(overrides), 3)
        response = self.client.delete(
            self.url('entry-override-detail', pk=self.entry.pk, oid=overrides[0].pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.entry.overrides.count(), 2)
        response = self.client.delete(
            self.url('entry-override-detail', pk=self.entry.pk, oid=overrides[0].pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'timetable.override_not_found')
        # Another person cannot see or reset the overrides.
        theirs = make_entry(self.other_person, self.term)
        self.client.force_authenticate(user=self.other_user)
        response = self.client.delete(
            self.url('entry-override-detail', pk=self.entry.pk, oid=overrides[1].pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'not_found')
        response = self.client.delete(self.url('entry-overrides', pk=self.entry.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.entry.overrides.count(), 2)
        self.assertEqual(self.client.delete(self.url('entry-overrides', pk=theirs.pk)).status_code,
                         status.HTTP_204_NO_CONTENT)
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(self.url('entry-overrides', pk=self.entry.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.entry.overrides.count(), 0)
        self.assertEqual(len(self.week(5)), 1)


class SettingsTagsTests(TimetableAPITestCase):
    """``sources``/``tags``/``hidden_tags``/``show_exams`` of §8.3 and their effect."""

    def setUp(self):
        super().setUp()
        sources = [StoredEntriesSource(), ExamSource()]
        for target in ('timetable.services.load_sources', 'timetable.ics.load_sources'):
            patcher = patch(target, return_value=list(sources))
            patcher.start()
            self.addCleanup(patcher.stop)
        today = date.today()
        self.required = make_entry(self.person, self.term, name='必修课',
                                   weekday=today.isoweekday(), tag='必修',
                                   course_code='00130201', class_no='01')
        self.elective = make_entry(self.person, self.term, name='选修课',
                                   weekday=today.isoweekday(), start_section=3,
                                   end_section=4, tag='选修')
        make_entry(self.person, self.old_term, name='旧课', weekday=1, tag='旧标签')
        make_entry(self.other_person, self.term, name='别人的课', weekday=1, tag='别人的')
        self.exam = CourseExam.objects.create(
            term=self.term, course_code='00130201', class_no='01', name='必修课',
            start=datetime.combine(self.term.date_of(2, today.isoweekday()), datetime.min.time())
            .replace(hour=19), end=datetime.combine(
                self.term.date_of(2, today.isoweekday()), datetime.min.time()).replace(hour=21),
            room='考场A')

    def titles(self, **params):
        response = self.client.get(self.url('week'), params)
        return [o['title'] for o in response.data['occurrences']]

    def test_sources_and_tags(self):
        response = self.client.get(self.url('settings'))
        self.assertEqual(response.data['sources'], [
            {'key': 'stored', 'label': '课程', 'setting': 'show_courses'},
            {'key': 'exam', 'label': '考试', 'setting': 'show_exams'},
        ])
        self.assertEqual(response.data['tags'], ['必修', '旧标签', '选修'])
        self.assertEqual(response.data['hidden_tags'], [])
        self.assertTrue(response.data['show_exams'])

    def test_hidden_tags_patch_and_effect(self):
        response = self.client.patch(
            self.url('settings'), {'hidden_tags': ['选修', ' 选修 ', '', '无此标签']}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['hidden_tags'], ['无此标签', '选修'])
        settings = TimetableSettings.objects.get(person=self.person)
        self.assertEqual(settings.hidden_tags, ['选修', '无此标签'])
        self.assertEqual(self.titles(), ['必修课', '必修课 考试'])
        agenda = self.client.get(self.url('agenda'), {'days': 1}).data
        self.assertEqual([o['title'] for o in agenda['days'][0]['occurrences']],
                         ['必修课', '必修课 考试'])
        feed = APIClient().get(reverse('timetable:ics_feed', kwargs={
            'token': settings.ics_token})).content.decode('utf-8')
        self.assertIn('SUMMARY:必修课', feed)
        self.assertNotIn('SUMMARY:选修课', feed)
        # Hiding the tag of the course hides its exam too.
        response = self.client.patch(self.url('settings'), {'hidden_tags': ['必修']}, format='json')
        self.assertEqual(self.titles(), ['选修课'])
        # Entries stay listed so the tag can be un-hidden; the entry list is unfiltered.
        listed = self.client.get(self.url('entry-list')).data
        self.assertEqual({e['tag'] for e in listed}, {'必修', '选修'})
        response = self.client.patch(self.url('settings'), {'hidden_tags': []}, format='json')
        self.assertEqual(self.titles(), ['必修课', '选修课', '必修课 考试'])
        for body in ({'hidden_tags': ['x' * 25]}, {'hidden_tags': 'abc'},
                     {'hidden_tags': [['nested']]}, {'show_exams': 'maybe'}):
            with self.subTest(body=body):
                response = self.client.patch(self.url('settings'), body, format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(next(iter(body)), response.data['errors'])

    def test_show_exams_toggle(self):
        exam = [o for o in self.client.get(self.url('week')).data['occurrences']
                if o['kind'] == 'exam'][0]
        self.assertEqual((exam['source'], exam['title'], exam['location'], exam['role'],
                          exam['start_section'], exam['ref']),
                         ('exam', '必修课 考试', '考场A', '', None,
                          {'exam_id': self.exam.pk, 'entry_id': self.required.pk}))
        response = self.client.patch(self.url('settings'), {'show_exams': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data['show_exams'])
        self.assertEqual(self.titles(), ['必修课', '选修课'])


class ShareAssetsTests(TimetableAPITestCase):
    """``GET share/assets/`` (README §8.5) with WeChat mocked."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        settings = override_settings(MEDIA_ROOT=self.tmp.name, MEDIA_URL='/media/')
        settings.enable()
        self.addCleanup(settings.disable)

    # The shipped config points official_qrcode_url at a static file; these two
    # tests pin an empty value so they do not depend on the local config.json.
    NO_OFFICIAL_QR = {'miniapp_page': 'pages/timetable/index', 'env_version': 'release',
                      'official_qrcode_url': '', 'slogan': '元培智慧书院 · YPPF'}

    def test_assets_and_cache(self):
        with patch('timetable.share.fetch_miniapp_code', return_value=b'\x89PNGdata') as fetch, \
                patch('timetable.share.get_share_config', return_value=self.NO_OFFICIAL_QR):
            response = self.client.get(self.url('share-assets'))
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
            self.assertEqual(set(response.data), {'miniapp_qrcode', 'official_qrcode', 'slogan'})
            self.assertTrue(response.data['miniapp_qrcode'].startswith('http'))
            self.assertTrue(response.data['miniapp_qrcode'].endswith(
                '/media/timetable/share/miniapp_timetable.png'))
            self.assertIsNone(response.data['official_qrcode'])
            self.assertEqual(response.data['slogan'], '元培智慧书院 · YPPF')
            fetch.assert_called_once_with('timetable', 'pages/timetable/index',
                                          env_version='release', width=430)
            cached = Path(self.tmp.name) / 'timetable' / 'share' / 'miniapp_timetable.png'
            self.assertEqual(cached.read_bytes(), b'\x89PNGdata')
            # The second call is served from the cache.
            self.client.get(self.url('share-assets'))
            fetch.assert_called_once()

    def test_failure_answers_null(self):
        with patch('timetable.share.fetch_miniapp_code', return_value=None), \
                patch('timetable.share.get_share_config', return_value=self.NO_OFFICIAL_QR), \
                self.assertNoLogs('timetable.share', level='ERROR'):
            response = self.client.get(self.url('share-assets'))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsNone(response.data['miniapp_qrcode'])
        self.assertIsNone(response.data['official_qrcode'])

    def test_official_qrcode_configuration(self):
        config = {'miniapp_page': 'pages/timetable/index', 'env_version': 'trial',
                  'official_qrcode_url': 'https://cdn.example.com/oa.png', 'slogan': '口号'}
        with patch('timetable.share.fetch_miniapp_code', return_value=None), \
                patch('timetable.share.get_share_config', return_value=config):
            response = self.client.get(self.url('share-assets'))
        self.assertEqual(response.data['official_qrcode'], 'https://cdn.example.com/oa.png')
        self.assertEqual(response.data['slogan'], '口号')
        config['official_qrcode_url'] = 'timetable/share/official.png'
        with patch('timetable.share.fetch_miniapp_code', return_value=None), \
                patch('timetable.share.get_share_config', return_value=config):
            response = self.client.get(self.url('share-assets'))
        self.assertTrue(response.data['official_qrcode'].endswith(
            '/media/timetable/share/official.png'))
        self.assertTrue(response.data['official_qrcode'].startswith('http'))
