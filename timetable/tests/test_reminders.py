"""Reminder tests: due-window selection, channel order, quota, audit log, job."""
from datetime import date, datetime, time
from unittest.mock import MagicMock, patch

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from app.models import Notification
from boot.config import GLOBAL_CONFIG
from generic.models import User, UserWechatProfile
from api.config import WXMiniappConfig
from timetable import reminders
from timetable.jobs import send_due_class_reminders
from timetable.models import AcademicTerm, ReminderLog, SubscribeQuota, TimetableSettings
from timetable.sources.base import Occurrence
from timetable.sources.stored import StoredEntriesSource
from timetable.tests.helpers import make_entry, make_person, make_term

TEMPLATE = {
    'id': 'TPL-123',
    'fields': {'course': 'thing1', 'time': 'time2', 'location': 'thing3', 'note': 'thing4'},
    'page': 'pages/timetable/index',
}
# Monday of teaching week 2 of the test term (week 1 starts 2026-09-14).
MONDAY = date(2026, 9, 21)


def _occurrence(id_, on, start, end, **extra):
    fields = {
        'id': id_, 'source': 'manual', 'kind': 'custom', 'title': id_,
        'start': datetime.combine(on, start), 'end': datetime.combine(on, end),
        'date': on, 'week': 2, 'weekday': on.isoweekday(),
    }
    fields.update(extra)
    return Occurrence(**fields)


class _ListSource:
    """A source that returns fixed occurrences (filtered by week)."""

    key = 'fake'
    label = '假来源'

    def __init__(self, occurrences, fail_for=None):
        self.items = list(occurrences)
        self.fail_for = fail_for

    def occurrences(self, person, term, week_from, week_to, settings):
        if self.fail_for is not None and person.pk == self.fail_for.pk:
            raise RuntimeError('source exploded')
        return [item for item in self.items if week_from <= item.week <= week_to]


class ReminderTestCase(TestCase):

    def setUp(self):
        self.term = make_term()                      # 26-27-1, week 1 = 2026-09-14
        self.user, self.person = make_person()
        self.settings = TimetableSettings.objects.create(
            person=self.person, reminder_enabled=True, reminder_minutes=20)
        if not User.objects.filter(username=GLOBAL_CONFIG.official_uid).exists():
            User.objects.create_user(GLOBAL_CONFIG.official_uid, '官方账号', password='pw')
        publish = patch('app.notification_utils.publish_notification')
        self.publish = publish.start()
        self.addCleanup(publish.stop)


class DueRemindersTests(ReminderTestCase):

    def setUp(self):
        super().setUp()
        self.entry = make_entry(self.person, self.term, name='高数', weekday=1)   # Mon 08:00-09:50
        self.entry_id = f'portal:{self.entry.pk}:2026-09-21'
        patcher = patch('timetable.reminders.load_sources',
                        return_value=[StoredEntriesSource()])
        patcher.start()
        self.addCleanup(patcher.stop)

    def due(self, now):
        return [(person.pk, item.id) for person, item in reminders.due_reminders(now)]

    def test_window_is_left_open_right_closed(self):
        expected = [(self.person.pk, self.entry_id)]
        cases = [
            (datetime(2026, 9, 21, 7, 40), True),        # due moment itself
            (datetime(2026, 9, 21, 7, 44, 59), True),    # inside the first job interval
            (datetime(2026, 9, 21, 7, 45), True),        # a missed tick is caught up (15-minute look-back)
            (datetime(2026, 9, 21, 7, 54, 59), True),    # still inside the look-back window
            (datetime(2026, 9, 21, 7, 55), False),       # exactly one window later: excluded (left-open)
            (datetime(2026, 9, 21, 7, 39, 59), False),   # not due yet
            (datetime(2026, 9, 21, 7, 35), False),
            (datetime(2026, 9, 21, 8, 0), False),        # the class has started: never remind late
        ]
        for now, is_due in cases:
            with self.subTest(now=now):
                self.assertEqual(self.due(now), expected if is_due else [])

    def test_reminder_minutes_and_disabled_flag(self):
        self.settings.reminder_minutes = 0
        self.settings.save()
        self.assertEqual(self.due(datetime(2026, 9, 21, 8, 0)), [(self.person.pk, self.entry_id)])
        self.assertEqual(self.due(datetime(2026, 9, 21, 7, 40)), [])
        self.settings.reminder_enabled = False
        self.settings.save()
        self.assertEqual(self.due(datetime(2026, 9, 21, 8, 0)), [])

    def test_hidden_logged_and_other_days_excluded(self):
        make_entry(self.person, self.term, name='隐藏课', weekday=1, hidden=True)
        make_entry(self.person, self.term, name='周二课', weekday=2)
        make_entry(self.person, self.term, name='单周课', weekday=1, parity=1)   # week 2 is even
        self.assertEqual(self.due(datetime(2026, 9, 21, 7, 40)), [(self.person.pk, self.entry_id)])
        ReminderLog.objects.create(
            person=self.person, occurrence_id=self.entry_id,
            channel=ReminderLog.Channel.NOTIFICATION,
            scheduled_for=datetime(2026, 9, 21, 7, 40))
        self.assertEqual(self.due(datetime(2026, 9, 21, 7, 40)), [])

    def test_canceled_excluded_and_every_source_used(self):
        items = [
            _occurrence('college:1:2026-09-21', MONDAY, time(8, 0), time(9, 50),
                        source='college', kind='college', status='canceled'),
            _occurrence('activity:2:2026-09-21', MONDAY, time(8, 0), time(9, 0),
                        source='activity', kind='activity', status='applied'),
            _occurrence('manual:3:2026-09-21', MONDAY, time(8, 0), time(9, 0), hidden=True),
            _occurrence('manual:4:2026-09-22', date(2026, 9, 22), time(8, 0), time(9, 0)),
        ]
        with patch('timetable.reminders.load_sources',
                   return_value=[StoredEntriesSource(), _ListSource(items)]):
            due = self.due(datetime(2026, 9, 21, 7, 40))
        self.assertEqual(due, [(self.person.pk, 'activity:2:2026-09-21'),
                               (self.person.pk, self.entry_id)])

    def test_no_current_term_or_outside_teaching_weeks(self):
        self.assertEqual(self.due(datetime(2026, 9, 7, 7, 40)), [])     # before week 1
        self.assertEqual(self.due(datetime(2027, 1, 4, 7, 40)), [])     # week 17
        AcademicTerm.objects.update(is_active=False)
        self.assertEqual(self.due(datetime(2026, 9, 21, 7, 40)), [])

    def test_failing_source_skips_only_that_person(self):
        other_user, other = make_person('tt_other', '别人')
        TimetableSettings.objects.create(person=other, reminder_enabled=True, reminder_minutes=20)
        items = [_occurrence('manual:9:2026-09-21', MONDAY, time(8, 0), time(9, 0))]
        with patch('timetable.reminders.load_sources',
                   return_value=[_ListSource(items, fail_for=self.person)]), \
                self.assertLogs('timetable.reminders', level='ERROR') as logs:
            due = self.due(datetime(2026, 9, 21, 7, 40))
        self.assertEqual(due, [(other.pk, 'manual:9:2026-09-21')])
        self.assertIn('sources failed', logs.output[0])


class SendClassReminderTests(ReminderTestCase):

    def setUp(self):
        super().setUp()
        self.occurrence = _occurrence(
            'portal:1:2026-09-21', MONDAY, time(8, 0), time(9, 50),
            source='portal', kind='course', title='高等数学A（二）',
            location='理教406', subtitle='张三', start_section=1, end_section=2)
        template = patch('timetable.reminders.get_subscribe_template', return_value=TEMPLATE)
        self.get_template = template.start()
        self.addCleanup(template.stop)
        send = patch('timetable.reminders.send_subscribe_message', return_value=(True, 0, 'ok'))
        self.send_message = send.start()
        self.addCleanup(send.stop)
        self.now = datetime(2026, 9, 21, 7, 40)

    def bind_wechat(self, quota=2):
        UserWechatProfile.objects.create(user=self.user, openid='OPENID-1')
        SubscribeQuota.objects.create(user=self.user, template_key='class_reminder', count=quota)

    def quota(self):
        return SubscribeQuota.objects.get(user=self.user, template_key='class_reminder').count

    def send(self):
        return reminders.send_class_reminder(self.person, self.occurrence, now=self.now)

    def assert_notification(self, log, detail_prefix):
        self.assertEqual(log.channel, ReminderLog.Channel.NOTIFICATION)
        self.assertTrue(log.detail.startswith(detail_prefix), log.detail)
        notification = Notification.objects.get(receiver=self.user)
        self.assertEqual(notification.title, '上课提醒')
        self.assertEqual(notification.content, '高等数学A（二） 08:00–09:50 @理教406')
        self.assertEqual(notification.typename, Notification.Type.NEEDREAD)
        self.assertIsNone(notification.URL)
        self.assertEqual(notification.sender.username, GLOBAL_CONFIG.official_uid)
        self.publish.assert_called_once_with(notification)

    def test_subscribe_channel_consumes_quota(self):
        self.bind_wechat(quota=2)
        log = self.send()
        self.assertEqual((log.channel, log.detail), ('subscribe', 'ok'))
        self.assertEqual(log.person, self.person)
        self.assertEqual(log.occurrence_id, 'portal:1:2026-09-21')
        self.assertEqual(log.scheduled_for, datetime(2026, 9, 21, 7, 40))
        self.assertEqual(log.sent_at, self.now)
        self.send_message.assert_called_once_with(
            'OPENID-1', 'TPL-123', 'pages/timetable/index', {
                'thing1': {'value': '高等数学A（二）'},
                'time2': {'value': '2026年09月21日 08:00'},
                'thing3': {'value': '理教406'},
                'thing4': {'value': '第2周 周一 第1-2节'},
            })
        self.assertEqual(self.quota(), 1)
        self.assertEqual(Notification.objects.count(), 0)
        self.publish.assert_not_called()

    def test_43101_zeroes_quota_and_falls_back(self):
        self.bind_wechat(quota=3)
        self.send_message.return_value = (False, 43101, 'user refused')
        log = self.send()
        self.assert_notification(log, '43101 user refused')
        self.assertEqual(self.quota(), 0)
        self.send_message.assert_called_once()

    def test_other_failure_restores_quota_and_falls_back(self):
        self.bind_wechat(quota=1)
        self.send_message.return_value = (False, 40001, 'invalid credential')
        log = self.send()
        self.assert_notification(log, '40001')
        self.assertEqual(self.quota(), 1)

    def test_no_template_uses_notification_only(self):
        self.get_template.return_value = None
        self.bind_wechat(quota=2)
        log = self.send()
        self.assert_notification(log, 'no template')
        self.send_message.assert_not_called()
        self.assertEqual(self.quota(), 2)

    def test_no_wx_profile_uses_notification(self):
        SubscribeQuota.objects.create(user=self.user, template_key='class_reminder', count=2)
        log = self.send()
        self.assert_notification(log, 'no wx_profile')
        self.send_message.assert_not_called()
        self.assertEqual(self.quota(), 2)

    def test_no_quota_uses_notification(self):
        self.bind_wechat(quota=0)
        log = self.send()
        self.assert_notification(log, 'no quota')
        self.send_message.assert_not_called()
        self.assertEqual(self.quota(), 0)

    def test_notification_failure_is_logged_as_skipped(self):
        self.get_template.return_value = None
        with patch('app.notification_utils.notification_create',
                   side_effect=RuntimeError('db down')), \
                self.assertLogs('timetable.reminders', level='ERROR'):
            log = self.send()
        self.assertEqual(log.channel, ReminderLog.Channel.SKIPPED)
        self.assertTrue(log.detail.startswith('notification failed'), log.detail)
        self.assertEqual(Notification.objects.count(), 0)

    def test_sends_only_once_per_occurrence(self):
        self.bind_wechat(quota=2)
        first = self.send()
        second = self.send()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.channel, 'subscribe')
        self.send_message.assert_called_once()
        self.assertEqual(self.quota(), 1)
        self.assertEqual(ReminderLog.objects.count(), 1)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ReminderLog.objects.create(
                person=self.person, occurrence_id='portal:1:2026-09-21',
                channel=ReminderLog.Channel.SKIPPED,
                scheduled_for=datetime(2026, 9, 21, 7, 40))

    def test_scheduled_for_uses_config_default_without_settings(self):
        self.settings.delete()
        with patch('timetable.reminders.CONFIG') as config:
            config.reminder_default_minutes = 30
            log = self.send()
        self.assertEqual(log.scheduled_for, datetime(2026, 9, 21, 7, 30))


class BuildReminderDataTests(SimpleTestCase):

    def test_mapping_formatting_and_truncation(self):
        occurrence = _occurrence(
            'x', MONDAY, time(8, 0), time(9, 50), title='一' * 25, location='',
            kind='course', start_section=3, end_section=3)
        data = reminders.build_reminder_data(occurrence, {'fields': {
            'course': 'thing1', 'time': 'time2', 'location': 'thing3',
            'note': 'thing4', 'date': 'date5', 'unknown': 'thing6',
            'kind': 'phrase7', 'week': 'number8', 'teacher': 'character_string9',
            'end_time': 'time10',
        }})
        self.assertEqual(data['thing1'], {'value': '一' * 20})
        self.assertEqual(data['time2'], {'value': '2026年09月21日 08:00'})
        self.assertEqual(data['thing3'], {'value': '待定'})
        self.assertEqual(data['thing4'], {'value': '第2周 周一 第3节'})
        self.assertEqual(data['date5'], {'value': '2026年09月21日'})
        self.assertNotIn('thing6', data)
        self.assertEqual(data['phrase7'], {'value': '学校课程'})
        self.assertEqual(data['number8'], {'value': '2'})
        self.assertEqual(data['character_string9'], {'value': '待定'})
        self.assertEqual(data['time10'], {'value': '2026年09月21日 09:50'})

    def test_default_fields_when_template_has_none(self):
        occurrence = _occurrence('x', MONDAY, time(8, 0), time(9, 0), title='自习')
        data = reminders.build_reminder_data(occurrence, {'id': 'TPL'})
        self.assertEqual(set(data), {'thing1', 'time2', 'thing3', 'thing4'})
        self.assertEqual(data['thing1'], {'value': '自习'})
        self.assertEqual(data['thing4'], {'value': '第2周 周一'})

    def test_reminder_content(self):
        with_room = _occurrence('x', MONDAY, time(8, 0), time(9, 50), title='高数', location='理教406')
        without = _occurrence('y', MONDAY, time(14, 0), time(15, 0), title='自习')
        self.assertEqual(reminders.reminder_content(with_room), '高数 08:00–09:50 @理教406')
        self.assertEqual(reminders.reminder_content(without), '自习 14:00–15:00')


class QuotaTests(TestCase):

    def setUp(self):
        self.user, self.person = make_person()

    def test_grant_accumulates_and_caps(self):
        with patch('timetable.reminders.CONFIG') as config:
            config.subscribe_quota_cap = 3
            self.assertEqual(reminders.grant_subscribe_quota(self.user, 'class_reminder').count, 1)
            self.assertEqual(reminders.grant_subscribe_quota(self.user, 'class_reminder', 1).count, 2)
            self.assertEqual(reminders.grant_subscribe_quota(self.user, 'class_reminder', 5).count, 3)
        self.assertEqual(SubscribeQuota.objects.get(user=self.user).count, 3)

    def test_template_keys_include_configured_and_default(self):
        with patch.object(WXMiniappConfig, 'subscribe_templates', {'other': {'id': 'X'}}):
            self.assertEqual(reminders.subscribe_template_keys(), ['class_reminder', 'other'])
        with patch.object(WXMiniappConfig, 'subscribe_templates', {}):
            self.assertEqual(reminders.subscribe_template_keys(), ['class_reminder'])


class JobTests(ReminderTestCase):

    def test_registered_as_periodical_job(self):
        from scheduler.periodic import _periodical_jobs
        job = next(job for job in _periodical_jobs if job.job_id == 'timetable_class_reminders')
        self.assertEqual(job.trigger, 'interval')
        self.assertEqual(job.tg_args, {'minutes': 5})
        self.assertIs(job.function, send_due_class_reminders)

    def test_job_sends_due_reminders_end_to_end(self):
        entry = make_entry(self.person, self.term, name='高数', weekday=1)
        with patch('timetable.reminders.load_sources', return_value=[StoredEntriesSource()]), \
                patch('timetable.reminders.get_subscribe_template', return_value=None), \
                patch('timetable.jobs.datetime') as job_datetime:
            job_datetime.now.return_value = datetime(2026, 9, 21, 7, 42)
            handled = send_due_class_reminders()
            again = send_due_class_reminders()
        self.assertEqual((handled, again), (1, 0))
        log = ReminderLog.objects.get(person=self.person)
        self.assertEqual(log.occurrence_id, f'portal:{entry.pk}:2026-09-21')
        self.assertEqual(log.channel, ReminderLog.Channel.NOTIFICATION)
        self.assertEqual(log.sent_at, datetime(2026, 9, 21, 7, 42))
        self.assertEqual(Notification.objects.filter(receiver=self.user).count(), 1)

    def test_one_failure_does_not_stop_the_loop(self):
        first = _occurrence('manual:1:2026-09-21', MONDAY, time(8, 0), time(9, 0))
        second = _occurrence('manual:2:2026-09-21', MONDAY, time(8, 0), time(9, 0))
        outcomes = [RuntimeError('boom'), MagicMock(channel='notification', detail='no template')]
        with patch('timetable.reminders.due_reminders',
                   return_value=[(self.person, first), (self.person, second)]), \
                patch('timetable.reminders.send_class_reminder', side_effect=outcomes) as send, \
                self.assertLogs('timetable.jobs', level='ERROR') as logs:
            handled = send_due_class_reminders()
        self.assertEqual(handled, 1)
        self.assertEqual(send.call_count, 2)
        self.assertIn('manual:1:2026-09-21', logs.output[0])
