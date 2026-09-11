"""Tests of the term overview (``services.term_overview``, README §10)."""
from datetime import date, datetime, time
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from app.models import Activity, Participation
from semester.models import CalendarEvent
from timetable import services
from timetable.models import CourseExam, TimetableEntry, TimetableEntryOverride
from timetable.sources.activity import ActivitySource
from timetable.sources.appoint import AppointSource
from timetable.sources.base import Occurrence
from timetable.sources.college import CollegeCourseSource
from timetable.sources.exam import ExamSource
from timetable.sources.stored import StoredEntriesSource
from timetable.tests.helpers import (
    make_activity, make_appoint, make_college_course, make_entry,
    make_organization, make_person, make_term,
)

SLOT_KEYS = {
    'key', 'kind', 'source', 'title', 'subtitle', 'location', 'weekday', 'start',
    'end', 'start_section', 'end_section', 'weeks', 'weeks_text', 'parity',
    'color_key', 'role', 'tag', 'ref',
}
TODAY = date(2026, 9, 23)                    # week 2 of the default test term


class _FixedSource:
    """A third-party source without ``rule_occurrences`` (fixed answers)."""

    key = 'fixed'
    label = '固定'

    def __init__(self, occurrences):
        self.items = list(occurrences)

    def occurrences(self, person, term, week_from, week_to, settings):
        return list(self.items)


class DescribeWeeksTests(SimpleTestCase):

    def test_patterns(self):
        cases = [
            ([3], ('第3周', 0)),
            (range(1, 17), ('1-16周', 0)),
            ([5, 6], ('5-6周', 0)),
            (range(1, 16, 2), ('1-15周 单周', 1)),
            (range(2, 17, 2), ('2-16周 双周', 2)),
            ([3, 5], ('3-5周 单周', 1)),
            ([*range(1, 9), *range(10, 17)], ('1-8,10-16周', 0)),
            ([1, 2, 3, 5, 7, 8], ('1-3,5,7-8周', 0)),
            ([1, 4, 7], ('1,4,7周', 0)),
            ([1, 3, 5, 6], ('1,3,5-6周', 0)),
            ([16, 2, 4, 2, 6, 8, 10, 12, 14], ('2-16周 双周', 2)),
            ([], ('', 0)),
        ]
        for weeks, expected in cases:
            with self.subTest(weeks=list(weeks)):
                self.assertEqual(services.describe_weeks(weeks), expected)


class TermOverviewTests(TestCase):

    def setUp(self):
        self.term = make_term()                  # 2026-09-14, 16 weeks
        self.user, self.person = make_person()
        self.sources = [StoredEntriesSource(), CollegeCourseSource(), ActivitySource(),
                        AppointSource(), ExamSource()]
        patcher = patch('timetable.services.load_sources',
                        side_effect=lambda: list(self.sources))
        patcher.start()
        self.addCleanup(patcher.stop)

    def overview(self):
        return services.term_overview(self.person, self.term, today=TODAY)

    def test_empty_term(self):
        overview = self.overview()
        self.assertEqual(set(overview), {'term', 'slots', 'exams'})
        self.assertEqual((overview['term']['code'], overview['term']['current_week']),
                         ('26-27-1', 2))
        self.assertEqual((overview['slots'], overview['exams']), ([], []))

    def test_groups_weeks_and_describes_patterns(self):
        weekly = make_entry(self.person, self.term, name='高数', weekday=1, room='理教201',
                            teacher='束琳', tag='必修')
        make_entry(self.person, self.term, name='单周课', weekday=2, start_section=3,
                   end_section=4, week_end=15, parity=1)
        make_entry(self.person, self.term, name='双周课', weekday=3, parity=2)
        make_entry(self.person, self.term, name='一次课', weekday=4,
                   week_start=3, week_end=3)
        manual = make_entry(self.person, self.term, name='自习', weekday=5, start_section=0,
                            end_section=0, start_time=time(19, 0), end_time=time(21, 0),
                            source=TimetableEntry.Source.MANUAL,
                            category=TimetableEntry.Category.OTHER,
                            role=TimetableEntry.Role.AUDIT)
        _, other = make_person('tt_other', '别人')
        make_entry(other, self.term, name='别人的课', weekday=1)
        overview = self.overview()
        self.assertEqual(overview['exams'], [])
        slots = overview['slots']
        self.assertEqual(
            [(s['title'], s['weekday'], s['weeks_text'], s['parity']) for s in slots],
            [('高数', 1, '1-16周', 0), ('单周课', 2, '1-15周 单周', 1),
             ('双周课', 3, '2-16周 双周', 2), ('一次课', 4, '第3周', 0),
             ('自习', 5, '1-16周', 0)])
        self.assertEqual(slots[0], {
            'key': f'portal:{weekly.pk}:0', 'kind': 'course', 'source': 'portal',
            'title': '高数', 'subtitle': '束琳', 'location': '理教201', 'weekday': 1,
            'start': '08:00', 'end': '09:50', 'start_section': 1, 'end_section': 2,
            'weeks': list(range(1, 17)), 'weeks_text': '1-16周', 'parity': 0,
            'color_key': '高数', 'role': 'enrolled', 'tag': '必修',
            'ref': {'entry_id': weekly.pk},
        })
        for slot in slots:
            self.assertEqual(set(slot), SLOT_KEYS)
        self.assertEqual(slots[1]['weeks'], list(range(1, 16, 2)))
        self.assertEqual((slots[1]['start'], slots[1]['end']), ('10:10', '12:00'))
        self.assertEqual(slots[2]['weeks'], list(range(2, 17, 2)))
        self.assertEqual(slots[3]['weeks'], [3])
        custom = slots[4]
        self.assertEqual(
            (custom['kind'], custom['source'], custom['start'], custom['end'],
             custom['start_section'], custom['end_section'], custom['role'],
             custom['ref']),
            ('custom', 'manual', '19:00', '21:00', None, None, 'audit',
             {'entry_id': manual.pk}))
        self.assertEqual(len({slot['key'] for slot in slots}), len(slots))

    def test_calendar_suspensions_do_not_punch_gaps(self):
        make_entry(self.person, self.term, name='周一课', weekday=1)
        CalendarEvent.objects.create(kind='holiday', start_date=self.term.date_of(3, 1),
                                     end_date=self.term.date_of(3, 1), name='国庆节放假')
        CalendarEvent.objects.create(kind='exam', start_date=self.term.date_of(15, 1),
                                     end_date=self.term.date_of(16, 7), name='停课复习考试')
        CalendarEvent.objects.create(kind='swap', start_date=self.term.date_of(4, 6),
                                     end_date=self.term.date_of(4, 6),
                                     name='按周一课表上课', follows_weekday=1)
        slots = self.overview()['slots']
        self.assertEqual([(s['weekday'], s['weeks'], s['weeks_text']) for s in slots],
                         [(1, list(range(1, 17)), '1-16周')])
        # The week view does follow the calendar: nothing on the holiday, the
        # swap Saturday carries the Monday lesson.
        week3 = services.week_view(self.person, self.term, 3, today=TODAY)
        self.assertEqual(week3['occurrences'], [])
        week4 = services.week_view(self.person, self.term, 4, today=TODAY)
        self.assertEqual([o['weekday'] for o in week4['occurrences']], [1, 6])

    def test_overrides_cancel_move_and_change_weeks(self):
        entry = make_entry(self.person, self.term, name='高数', weekday=1, room='理教201')
        TimetableEntryOverride.objects.create(entry=entry, week_start=9, week_end=9,
                                              canceled=True)
        TimetableEntryOverride.objects.create(entry=entry, week_start=5, week_end=5,
                                              fields={'weekday': 3})
        TimetableEntryOverride.objects.create(
            entry=entry, week_start=13, week_end=None,
            fields={'start_section': 3, 'end_section': 4})
        TimetableEntryOverride.objects.create(entry=entry, week_start=11, week_end=11,
                                              fields={'room': '二教101'})
        # A changed teacher is not part of the slot key: that week stays merged.
        TimetableEntryOverride.objects.create(entry=entry, week_start=7, week_end=7,
                                              fields={'teacher': '代课老师'})
        slots = self.overview()['slots']
        self.assertEqual(
            [(s['weekday'], s['start'], s['end'], s['location'], s['weeks_text'])
             for s in slots],
            [(1, '08:00', '09:50', '理教201', '1-4,6-8,10,12周'),
             (1, '08:00', '09:50', '二教101', '第11周'),
             (1, '10:10', '12:00', '理教201', '13-16周'),
             (3, '08:00', '09:50', '理教201', '第5周')])
        self.assertEqual(slots[0]['weeks'], [1, 2, 3, 4, 6, 7, 8, 10, 12])
        self.assertEqual(slots[0]['subtitle'], '')
        self.assertEqual((slots[2]['start_section'], slots[2]['end_section']), (3, 4))
        self.assertEqual([s['key'] for s in slots],
                         [f'portal:{entry.pk}:{n}' for n in range(4)])
        self.assertEqual([s['ref'] for s in slots], [{'entry_id': entry.pk}] * 4)

    def test_hidden_entries_hidden_tags_and_source_toggles(self):
        make_entry(self.person, self.term, name='可见课', weekday=1)
        make_entry(self.person, self.term, name='隐藏课', weekday=2, hidden=True)
        make_entry(self.person, self.term, name='选修课', weekday=3, tag='选修')
        retagged = make_entry(self.person, self.term, name='改标签课', weekday=4)
        TimetableEntryOverride.objects.create(entry=retagged, week_start=4, week_end=4,
                                              fields={'tag': '选修'})
        org, _ = make_organization()
        course, _ = make_college_course(org, self.person, datetime(2026, 9, 16, 14, 0))
        settings = services.get_or_create_settings(self.person)
        settings.hidden_tags = ['选修']
        settings.save()

        def summary():
            return [(slot['title'], slot['kind'], slot['weeks_text'])
                    for slot in self.overview()['slots']]

        self.assertEqual(summary(), [
            ('可见课', 'course', '1-16周'),
            ('书院课测试', 'college', '1-16周'),
            ('改标签课', 'course', '1-3,5-16周'),
        ])
        college = self.overview()['slots'][1]
        self.assertEqual(
            (college['key'], college['source'], college['weekday'], college['start'],
             college['end'], college['start_section'], college['location'],
             college['subtitle'], college['role'], college['tag'], college['ref']),
            (f'college:{course.pk}:0', 'college', 3, '14:00', '15:50', None, 'Room B',
             '书院老师', '', '', {'course_id': course.pk}))
        settings.show_courses = False
        settings.save()
        self.assertEqual(summary(), [('书院课测试', 'college', '1-16周')])
        settings.show_courses = True
        settings.show_college = False
        settings.save()
        self.assertEqual([title for title, _, _ in summary()], ['可见课', '改标签课'])

    def test_college_generated_activities(self):
        """A moved generated activity is its own slot; a canceled one leaves a gap."""
        org, teacher = make_organization()
        course, course_time = make_college_course(
            org, self.person, datetime(2026, 9, 16, 14, 0))
        generated = {'category': Activity.ActivityCategory.COURSE,
                     'course_time': course_time, 'title': '书院课测试-第n次课'}
        # Week 1 as the weekly time, week 2 moved, week 3 canceled.
        make_activity(org, teacher, datetime(2026, 9, 16, 14, 0), location='Room B',
                      end=datetime(2026, 9, 16, 15, 50), **generated)
        make_activity(org, teacher, datetime(2026, 9, 23, 14, 30), location='Room C',
                      end=datetime(2026, 9, 23, 15, 30), **generated)
        make_activity(org, teacher, datetime(2026, 9, 30, 14, 0), location='Room B',
                      end=datetime(2026, 9, 30, 15, 50),
                      status=Activity.Status.CANCELED, **generated)
        slots = self.overview()['slots']
        self.assertEqual(
            [(s['start'], s['end'], s['location'], s['weeks_text'], s['ref'], s['key'])
             for s in slots],
            [('14:00', '15:50', 'Room B', '1,4-16周', {'course_id': course.pk},
              f'college:{course.pk}:0'),
             ('14:30', '15:30', 'Room C', '第2周', {'course_id': course.pk},
              f'college:{course.pk}:1')])

    def test_exams_listed_once_and_one_off_events_left_out(self):
        make_entry(self.person, self.term, name='高数', weekday=1,
                   course_code='00130201', class_no='01')
        make_entry(self.person, self.term, name='高数', weekday=3,
                   course_code='00130201', class_no='01')
        make_entry(self.person, self.term, name='英语', weekday=2,
                   exam_date=date(2026, 12, 29), exam_period='下午', exam_room='二教101')
        make_entry(self.person, self.term, name='期中考试', weekday=4, start_section=3,
                   end_section=4, week_start=8, week_end=8,
                   source=TimetableEntry.Source.MANUAL,
                   category=TimetableEntry.Category.EXAM)
        CourseExam.objects.create(
            term=self.term, course_code='00130201', class_no='01', name='高数',
            start=datetime(2026, 12, 28, 8, 30), end=datetime(2026, 12, 28, 10, 30),
            room='理教101')
        # The same exam once more from another source is not listed twice.
        self.sources.append(_FixedSource([Occurrence(
            id='fixed:1:2026-12-28', source='fixed', kind='exam', title='高数 考试',
            location='理教101', start=datetime(2026, 12, 28, 8, 30),
            end=datetime(2026, 12, 28, 10, 30), date=date(2026, 12, 28), week=16,
            weekday=1)]))
        org, teacher = make_organization()
        activity = make_activity(org, teacher, datetime(2026, 9, 15, 19, 0), title='报名活动')
        Participation.objects.create(activity=activity, person=self.person,
                                     status=Participation.AttendStatus.APPLYSUCCESS)
        make_appoint(self.user, datetime(2026, 9, 15, 20, 0), usage='讨论')
        overview = self.overview()
        self.assertEqual([(s['title'], s['kind']) for s in overview['slots']],
                         [('高数', 'course'), ('英语', 'course'), ('高数', 'course')])
        self.assertEqual(overview['exams'], [
            {'title': '期中考试', 'date': '2026-11-05', 'start': '10:10', 'end': '12:00',
             'location': '', 'week': 8},
            {'title': '高数 考试', 'date': '2026-12-28', 'start': '08:30', 'end': '10:30',
             'location': '理教101', 'week': 16},
            {'title': '英语 考试', 'date': '2026-12-29', 'start': '14:00', 'end': '16:00',
             'location': '二教101', 'week': 16},
        ])
        # The activity and the appointment are real occurrences of week 1.
        week1 = services.week_view(self.person, self.term, 1, today=TODAY)
        kinds = {o['kind'] for o in week1['occurrences']}
        self.assertTrue({'activity', 'appoint'} <= kinds)
