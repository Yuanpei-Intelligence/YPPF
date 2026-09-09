"""Tests of the timetable mini-program API (``/api/v2/timetable/``)."""
from datetime import date, datetime, timedelta
from importlib.util import find_spec
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from generic.models import User
from semester.models import CalendarEvent
from api.config import WXMiniappConfig
from timetable import catalog
from timetable.models import ImportLog, SubscribeQuota, TimetableEntry, TimetableSettings
from timetable.tests.helpers import (
    make_entry, make_person, make_term, portal_payload, read_fixture,
)


def _this_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


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
                 client_error=None, fetch_error=None):
        self.account = account
        self.payload = payload
        self.login_error = login_error
        self.client_error = client_error
        self.fetch_error = fetch_error
        self.login_calls = []
        self.fetch_calls = []
        self.marked = []
        self.invalidated = []

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
            ('get', self.url('entry-list')),
            ('post', self.url('entry-list')),
            ('patch', self.url('entry-detail', pk=entry.pk)),
            ('delete', self.url('entry-detail', pk=entry.pk)),
            ('post', self.url('import-portal')),
            ('post', self.url('import-text')),
            ('get', self.url('settings')),
            ('patch', self.url('settings')),
            ('get', self.url('ics')),
            ('post', self.url('ics-rotate')),
            ('get', self.url('subscribe-templates')),
            ('post', self.url('subscribe-grant')),
            ('get', self.url('catalog')),
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
            'code', 'name', 'week1_monday', 'total_weeks', 'current_week', 'section_times',
            'calendar'})
        self.assertEqual(response.data['current']['calendar'], [])

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
        self.assertEqual(set(entry), {
            'id', 'term', 'source', 'name', 'course_code', 'class_no', 'teacher', 'room',
            'weekday', 'start_section', 'end_section', 'start_time', 'end_time',
            'week_start', 'week_end', 'parity', 'note', 'hidden', 'color'})
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

    def test_patch_imported_entry_only_hidden(self):
        entry = make_entry(self.person, self.term, name='高数')
        response = self.client.patch(
            self.url('entry-detail', pk=entry.pk), {'hidden': True}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['hidden'])
        response = self.client.patch(
            self.url('entry-detail', pk=entry.pk), {'name': '改名', 'hidden': False},
            format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['code'], 'permission_denied')
        entry.refresh_from_db()
        self.assertEqual(entry.name, '高数')
        self.assertTrue(entry.hidden)

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
            'start_section', 'end_section', 'week_start', 'week_end', 'parity', 'raw', 'note'})
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
        self.assertEqual(response.data, {
            'reminder_enabled': False, 'reminder_minutes': 20, 'show_courses': True,
            'show_college': True, 'show_activities': True, 'show_appointments': True,
            'share_show_name': True})
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
        self.assertEqual(set(row), {'id', 'course_code', 'name', 'class_no', 'teacher',
                                    'credits', 'time_text', 'slots'})
        self.assertEqual(row['name'], '高等数学A（二）')
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
        self.assertEqual([(o['title'], o['weekday']) for o in data['occurrences']],
                         [('周一课', 1), ('周一课', 6)])
        self.assertEqual(data['occurrences'][1]['date'], data['week_dates'][5])
        self.assertEqual([e['name'] for e in data['term']['calendar']], ['假期', '按周一课表上课'])
        response = self.client.get(self.url('week'), {'week': 3})
        self.assertEqual([day['kind'] for day in response.data['days']], [None] * 7)
        self.assertEqual([o['title'] for o in response.data['occurrences']],
                         ['周一课', '周四课', '周六课'])
