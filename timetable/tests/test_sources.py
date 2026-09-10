"""Source adapter tests: registry, 书院课, activities, appointments, date spans."""
from datetime import date, datetime, time
from unittest.mock import patch

from django.test import TestCase

from app.models import (
    Activity,
    Course,
    CourseParticipant,
    CourseTime,
    NaturalPerson,
    Organization,
    OrganizationType,
    Participation,
)
from Appointment.models import Appoint, Participant, Room
from generic.models import User
from utils.models.semester import Semester
from timetable.models import TimetableSettings
from timetable.sources import base
from timetable.sources.activity import ActivitySource
from timetable.sources.appoint import AppointSource
from timetable.sources.base import DateSpan, Occurrence
from timetable.sources.college import CollegeCourseSource
from timetable.sources.stored import StoredEntriesSource
from timetable.tests.helpers import make_entry, make_person, make_term


def _occurrence(id_, on, hour, **extra):
    fields = {
        'id': id_, 'source': 'fake', 'kind': 'activity', 'title': id_,
        'start': datetime.combine(on, time(hour, 0)),
        'end': datetime.combine(on, time(hour + 1, 0)),
        'date': on, 'week': 1, 'weekday': on.isoweekday(),
    }
    fields.update(extra)
    return Occurrence(**fields)


class LoadSourcesTests(TestCase):

    def setUp(self):
        base.reset_sources_cache()
        self.addCleanup(base.reset_sources_cache)

    def test_explicit_paths_skip_bad_entries_with_a_log_line(self):
        paths = [
            'timetable.sources.stored.StoredEntriesSource',
            'timetable.sources.nowhere.MissingSource',
            'timetable.sources.stored.NoSuchClass',
            'not-a-dotted-path',
            'timetable.sources.base.Occurrence',      # not an EventSource
            'timetable.sources.college.CollegeCourseSource',
            'timetable.sources.stored.StoredEntriesSource',  # duplicate key
        ]
        with self.assertLogs('timetable.sources.base', level='WARNING') as logs:
            sources = base.load_sources(paths)
        self.assertEqual([source.key for source in sources], ['stored', 'college'])
        self.assertEqual(len(logs.records), 4)
        self.assertTrue(all('skipped' in record.getMessage() for record in logs.records))
        self.assertEqual([source.setting for source in sources], ['show_courses', 'show_college'])

    def test_default_sources_and_setting_names(self):
        """Every shipped source declares the settings boolean toggling it (§8.3)."""
        from timetable.config import DEFAULT_SOURCES
        sources = base.load_sources(DEFAULT_SOURCES)
        self.assertEqual([(s.key, s.label, s.setting) for s in sources], [
            ('stored', '课程', 'show_courses'),
            ('college', '书院课', 'show_college'),
            ('activity', '活动', 'show_activities'),
            ('appoint', '预约', 'show_appointments'),
            ('exam', '考试', 'show_exams'),
        ])
        for source in sources:
            self.assertTrue(hasattr(TimetableSettings, source.setting))

        class Bare:
            key = 'bare'

            def occurrences(self, person, term, week_from, week_to, settings):
                return []

        with patch.dict('sys.modules', {'timetable.tests.fake_source': type(
                'module', (), {'Bare': Bare})()}):
            loaded = base.load_sources(['timetable.tests.fake_source.Bare'])
        self.assertEqual([(s.key, s.label, s.setting) for s in loaded], [('bare', 'bare', '')])

    def test_config_sources_are_cached(self):
        with patch('timetable.sources.base.CONFIG') as config:
            config.sources = [
                'timetable.sources.appoint.AppointSource',
                'timetable.sources.activity.ActivitySource',
            ]
            first = base.load_sources()
            config.sources = ['timetable.sources.stored.StoredEntriesSource']
            second = base.load_sources()
        self.assertEqual([s.key for s in first], ['appoint', 'activity'])
        self.assertEqual([s.key for s in second], ['appoint', 'activity'])
        self.assertEqual([s.label for s in first], ['预约', '活动'])
        base.reset_sources_cache()
        with patch('timetable.sources.base.CONFIG') as config:
            config.sources = ['timetable.sources.stored.StoredEntriesSource']
            self.assertEqual([s.key for s in base.load_sources()], ['stored'])

    def test_week_span(self):
        term = make_term()
        start, end = base.week_span(term, 2, 3)
        self.assertEqual(start, datetime(2026, 9, 21, 0, 0))
        self.assertEqual(end, datetime(2026, 10, 5, 0, 0))

    def test_occurrences_between_dispatch(self):
        """Date-based sources are asked directly, term-based ones via the default."""
        term = make_term()
        _, person = make_person()
        settings = TimetableSettings(person=person)
        calls = []
        monday, tuesday = date(2026, 9, 14), date(2026, 9, 15)

        class Direct:
            key, label = 'direct', '直接'

            def occurrences(self, person, term, week_from, week_to, settings):
                calls.append(('occurrences', 'direct'))
                return []

            def occurrences_between(self, person, span, settings):
                calls.append(('between', span.start, span.end))
                return [_occurrence('late', tuesday, 20), _occurrence('early', tuesday, 8)]

        class TermBased:
            key, label = 'term', '学期'

            def occurrences(self, person, term, week_from, week_to, settings):
                calls.append(('occurrences', term.code, week_from, week_to))
                return [_occurrence('in', tuesday, 9), _occurrence('out', date(2026, 9, 16), 9)]

        span = DateSpan.load(monday, tuesday)
        self.assertEqual([o.id for o in base.occurrences_between(Direct(), person, span, settings)],
                         ['early', 'late'])
        self.assertEqual([o.id for o in base.occurrences_between(TermBased(), person, span, settings)],
                         ['in'])
        self.assertEqual(calls, [('between', monday, tuesday), ('occurrences', term.code, 1, 1)])
        # A span with no term gives a term-based source nothing to answer.
        calls.clear()
        span = DateSpan.load(date(2026, 9, 1), date(2026, 9, 13))
        self.assertEqual(base.occurrences_between(TermBased(), person, span, settings), [])
        self.assertEqual(calls, [])
        # A reversed span is empty for both.
        span = DateSpan.load(tuesday, monday)
        self.assertEqual(base.occurrences_between(Direct(), person, span, settings), [])
        self.assertEqual(calls, [])


class DateSpanTests(TestCase):

    def test_term_of_and_week_of(self):
        fall = make_term()                                             # 2026-09-14 .. 2027-01-03
        summer = make_term(code='26-27-3', week1_monday=date(2026, 12, 28), total_weeks=2)
        make_term(code='25-26-2', week1_monday=date(2026, 2, 23), is_active=False)
        with self.assertNumQueries(1):
            span = DateSpan.load(date(2026, 9, 13), date(2026, 9, 15))
        self.assertEqual([term.code for term in span.terms], ['26-27-3', '26-27-1'])
        self.assertEqual(span.dates(), [date(2026, 9, 13), date(2026, 9, 14), date(2026, 9, 15)])
        self.assertEqual(span.bounds(), (datetime(2026, 9, 13), datetime(2026, 9, 16)))
        with self.assertNumQueries(0):
            self.assertIsNone(span.term_of(date(2026, 9, 13)))
            self.assertEqual(span.term_of(date(2026, 9, 14)), fall)
            self.assertEqual(span.term_of(date(2026, 12, 27)), fall)
            # Overlapping teaching spans: the latest-starting term wins.
            self.assertEqual(span.term_of(date(2026, 12, 28)), summer)
            self.assertEqual(span.term_of(date(2027, 1, 3)), summer)
            self.assertEqual(span.term_of(date(2027, 1, 10)), summer)
            self.assertIsNone(span.term_of(date(2027, 1, 11)))
            self.assertIsNone(span.term_of(date(2026, 3, 1)))           # inactive term
            self.assertEqual(span.week_of(date(2026, 9, 14)), 1)
            self.assertEqual(span.week_of(date(2026, 12, 28)), 1)
            self.assertEqual(span.week_of(date(2026, 12, 27)), 15)
            # Outside every term: relative to the latest term that started …
            self.assertEqual(span.week_of(date(2027, 1, 12)), 3)
            # … or, before the first one, to that first term.
            self.assertEqual(span.week_of(date(2026, 9, 13)), 0)
            self.assertEqual(span.week_of(date(2026, 9, 6)), -1)

    def test_without_terms(self):
        make_term(is_active=False)
        span = DateSpan.load(date(2026, 9, 14), date(2026, 9, 14))
        self.assertEqual(span.terms, [])
        self.assertIsNone(span.term_of(date(2026, 9, 14)))
        self.assertEqual(span.week_of(date(2026, 9, 14)), 0)
        self.assertEqual(DateSpan(date(2026, 9, 15), date(2026, 9, 14)).dates(), [])


class _AppFixtureMixin:
    """Teacher, student, organization and a term for app-backed sources."""

    def setUp(self):
        super().setUp()
        self.term = make_term()             # 26-27-1 → (2026, FALL)
        self.user, self.person = make_person()
        self.settings = TimetableSettings.objects.create(person=self.person)
        teacher_user = User.objects.create_user(
            'tt_teacher', '审核老师', User.Type.TEACHER, password='pw')
        self.teacher = NaturalPerson.objects.create(
            teacher_user, name='审核老师', identity=NaturalPerson.Identity.TEACHER)
        org_type = OrganizationType.objects.create(
            otype_id=9301, otype_name='课表测试类型', incharge=self.teacher,
            job_name_list=['负责人', '成员'])
        org_user = User.objects.create_user(
            'tt_org', '课表测试小组', User.Type.ORG, password='pw')
        self.org = Organization.objects.create(
            organization_id=org_user, oname='课表测试小组', otype=org_type)

    def activity(self, start, hours=2, **overrides):
        fields = {
            'title': f'活动 {start:%m%d}', 'organization_id': self.org,
            'examine_teacher': self.teacher, 'year': 2026,
            'semester': Semester.FALL, 'start': start,
            'end': datetime.combine(start.date(), time(start.hour + hours, start.minute)),
            'location': 'Room A', 'status': Activity.Status.WAITING,
            'publish_time': start, 'apply_end': start,
        }
        fields.update(overrides)
        return Activity.objects.create(**fields)


class CollegeCourseSourceTests(_AppFixtureMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.course = Course.objects.create(
            name='书院课测试', organization=self.org, year=2026,
            semester=Semester.FALL, type=Course.CourseType.INTELLECTUAL,
            status=Course.Status.SELECT_END, classroom='Room B', teacher='书院老师')
        # Wednesday of week 1, three weeks already generated.
        self.course_time = CourseTime.objects.create(
            course=self.course, start=datetime(2026, 9, 16, 14, 0),
            end=datetime(2026, 9, 16, 15, 50), cur_week=3, end_week=16)
        CourseParticipant.objects.create(
            course=self.course, person=self.person,
            status=CourseParticipant.Status.SUCCESS)
        course_activity = dict(category=Activity.ActivityCategory.COURSE,
                               course_time=self.course_time, title='书院课测试-第n次课')
        self.week1 = self.activity(datetime(2026, 9, 16, 14, 0), **course_activity)
        self.week2 = self.activity(datetime(2026, 9, 23, 14, 30), hours=1,
                                   status=Activity.Status.END, location='Room C',
                                   **course_activity)
        Participation.objects.create(activity=self.week2, person=self.person,
                                     status=Participation.AttendStatus.ATTENDED)
        self.week3 = self.activity(datetime(2026, 9, 30, 14, 0),
                                   status=Activity.Status.CANCELED, **course_activity)
        self.source = CollegeCourseSource()

    def occurrences(self, week_from=1, week_to=16, settings=None):
        return self.source.occurrences(
            self.person, self.term, week_from, week_to, settings or self.settings)

    def test_generated_activities_and_expansion(self):
        occurrences = self.occurrences()
        self.assertEqual(len(occurrences), 16)
        by_week = {o.week: o for o in occurrences}
        # canceled activity is kept as 已取消 (no fallback expansion for that week)
        self.assertEqual(by_week[3].status, 'canceled')
        self.assertEqual(by_week[3].ref['activity_id'], self.week3.pk)
        self.assertEqual(sorted(by_week), list(range(1, 17)))
        first = by_week[1]
        self.assertEqual((first.source, first.kind), ('college', 'college'))
        self.assertEqual(first.title, '书院课测试')
        self.assertEqual(first.subtitle, '书院老师')
        self.assertEqual(first.location, 'Room A')
        self.assertEqual(first.ref, {'course_id': self.course.pk, 'activity_id': self.week1.pk})
        self.assertEqual(first.status, '')
        self.assertEqual(first.color_key, '书院课测试')
        self.assertEqual(first.id, f'college:{self.course_time.pk}:2026-09-16')
        second = by_week[2]
        self.assertEqual(second.status, 'checked_in')
        self.assertEqual(second.start, datetime(2026, 9, 23, 14, 30))
        self.assertEqual(second.end, datetime(2026, 9, 23, 15, 30))
        self.assertEqual(second.location, 'Room C')
        fourth = by_week[4]
        self.assertEqual(fourth.ref, {'course_id': self.course.pk, 'activity_id': None})
        self.assertEqual(fourth.start, datetime(2026, 10, 7, 14, 0))
        self.assertEqual(fourth.end, datetime(2026, 10, 7, 15, 50))
        self.assertEqual(fourth.location, 'Room B')
        self.assertEqual(fourth.weekday, 3)
        self.assertEqual(by_week[16].date, date(2026, 12, 30))

    def test_week_range_and_settings(self):
        self.assertEqual([o.week for o in self.occurrences(2, 4)], [2, 3, 4])
        self.assertEqual(self.occurrences(5, 2), [])
        self.settings.show_college = False
        self.assertEqual(self.occurrences(), [])
        self.assertEqual(len(self.source.occurrences(self.person, self.term, 1, 16, None)), 16)

    def test_subtitle_falls_back_to_organization(self):
        self.course.teacher = ''
        self.course.save(update_fields=['teacher'])
        self.assertEqual(self.occurrences(1, 1)[0].subtitle, '课表测试小组')

    def test_only_successfully_selected_courses_of_matching_semester(self):
        other_term = make_term(code='25-26-2', week1_monday=date(2026, 2, 23))
        self.assertEqual(self.source.occurrences(self.person, other_term, 1, 16, self.settings), [])
        summer = make_term(code='26-27-3', week1_monday=date(2027, 7, 5))
        self.assertEqual(self.source.occurrences(self.person, summer, 1, 16, self.settings), [])
        participant = CourseParticipant.objects.get(course=self.course, person=self.person)
        participant.status = CourseParticipant.Status.SELECT
        participant.save(update_fields=['status'])
        self.assertEqual(self.occurrences(), [])
        _, stranger = make_person('tt_stranger', '路人')
        self.assertEqual(self.source.occurrences(stranger, self.term, 1, 16, self.settings), [])

    def test_aborted_course_is_ignored(self):
        self.course.status = Course.Status.ABORT
        self.course.save(update_fields=['status'])
        self.assertEqual(self.occurrences(), [])

    def test_occurrences_between(self):
        span = DateSpan.load(date(2026, 9, 14), date(2026, 9, 27))        # weeks 1-2
        occurrences = self.source.occurrences_between(self.person, span, self.settings)
        self.assertEqual([(o.week, o.date, o.status) for o in occurrences],
                         [(1, date(2026, 9, 16), ''), (2, date(2026, 9, 23), 'checked_in')])
        self.assertEqual([o.as_dict() for o in occurrences],
                         [o.as_dict() for o in self.occurrences(1, 2)])
        # Weeks 3 (canceled activity) and 4 (expanded): one lesson each.
        span = DateSpan.load(date(2026, 9, 28), date(2026, 10, 7))
        occurrences = self.source.occurrences_between(self.person, span, self.settings)
        self.assertEqual([(o.date, o.week, o.status, o.ref['activity_id']) for o in occurrences],
                         [(date(2026, 9, 30), 3, 'canceled', self.week3.pk),
                          (date(2026, 10, 7), 4, '', None)])
        # A generated lesson before week 1 is a real event: listed, week 0.
        early = self.activity(datetime(2026, 9, 9, 14, 0),
                              category=Activity.ActivityCategory.COURSE,
                              course_time=self.course_time, title='书院课测试-第0次课')
        span = DateSpan.load(date(2026, 9, 7), date(2026, 9, 13))
        occurrences = self.source.occurrences_between(self.person, span, self.settings)
        self.assertEqual([(o.date, o.week, o.ref['activity_id']) for o in occurrences],
                         [(date(2026, 9, 9), 0, early.pk)])
        self.settings.show_college = False
        self.assertEqual(self.source.occurrences_between(self.person, span, self.settings), [])

    def test_occurrences_between_lets_the_dates_decide_the_semester(self):
        spring = Course.objects.create(
            name='上学期书院课', organization=self.org, year=2025,
            semester=Semester.SPRING, type=Course.CourseType.INTELLECTUAL,
            status=Course.Status.END, classroom='Room D')
        CourseTime.objects.create(
            course=spring, start=datetime(2026, 9, 18, 10, 0),
            end=datetime(2026, 9, 18, 11, 50), cur_week=0, end_week=1)
        CourseParticipant.objects.create(
            course=spring, person=self.person, status=CourseParticipant.Status.SUCCESS)
        self.assertEqual([o.title for o in self.occurrences(1, 1)], ['书院课测试'])
        span = DateSpan.load(date(2026, 9, 14), date(2026, 9, 20))
        occurrences = self.source.occurrences_between(self.person, span, self.settings)
        self.assertEqual([(o.title, o.date) for o in occurrences],
                         [('书院课测试', date(2026, 9, 16)), ('上学期书院课', date(2026, 9, 18))])


class ActivitySourceTests(_AppFixtureMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.source = ActivitySource()
        self.applied = self.activity(datetime(2026, 9, 15, 19, 0), title='报名活动')
        Participation.objects.create(activity=self.applied, person=self.person,
                                     status=Participation.AttendStatus.APPLYSUCCESS)
        self.attended = self.activity(datetime(2026, 9, 17, 19, 0), title='签到活动',
                                      status=Activity.Status.END)
        Participation.objects.create(activity=self.attended, person=self.person,
                                     status=Participation.AttendStatus.ATTENDED)
        canceled = self.activity(datetime(2026, 9, 18, 19, 0), title='取消活动',
                                 status=Activity.Status.CANCELED)
        Participation.objects.create(activity=canceled, person=self.person,
                                     status=Participation.AttendStatus.APPLYSUCCESS)
        withdrawn = self.activity(datetime(2026, 9, 19, 19, 0), title='放弃活动')
        Participation.objects.create(activity=withdrawn, person=self.person,
                                     status=Participation.AttendStatus.CANCELED)
        course_activity = self.activity(datetime(2026, 9, 16, 19, 0), title='课程活动',
                                        category=Activity.ActivityCategory.COURSE)
        Participation.objects.create(activity=course_activity, person=self.person,
                                     status=Participation.AttendStatus.APPLYSUCCESS)
        self.later = self.activity(datetime(2026, 10, 13, 19, 0), title='第五周活动')
        Participation.objects.create(activity=self.later, person=self.person,
                                     status=Participation.AttendStatus.UNATTENDED)
        not_mine = self.activity(datetime(2026, 9, 15, 9, 0), title='别人的活动')
        _, other = make_person('tt_other', '别人')
        Participation.objects.create(activity=not_mine, person=other,
                                     status=Participation.AttendStatus.APPLYSUCCESS)

    def test_week_range_status_and_exclusions(self):
        occurrences = self.source.occurrences(self.person, self.term, 1, 2, self.settings)
        self.assertEqual([o.title for o in occurrences], ['报名活动', '签到活动'])
        self.assertEqual([o.status for o in occurrences], ['applied', 'checked_in'])
        first = occurrences[0]
        self.assertEqual((first.source, first.kind), ('activity', 'activity'))
        self.assertEqual(first.subtitle, '课表测试小组')
        self.assertEqual(first.location, 'Room A')
        self.assertEqual(first.ref, {'activity_id': self.applied.pk})
        self.assertEqual((first.week, first.weekday, first.date), (1, 2, date(2026, 9, 15)))
        self.assertEqual(first.id, f'activity:{self.applied.pk}:2026-09-15')
        self.assertIsNone(first.start_section)
        whole_term = self.source.occurrences(self.person, self.term, 1, 16, self.settings)
        self.assertEqual([o.title for o in whole_term], ['报名活动', '签到活动', '第五周活动'])
        self.assertEqual(whole_term[-1].status, '')
        self.assertEqual(whole_term[-1].week, 5)

    def test_settings_toggle(self):
        self.settings.show_activities = False
        self.assertEqual(self.source.occurrences(self.person, self.term, 1, 16, self.settings), [])

    def test_occurrences_between(self):
        span = DateSpan.load(date(2026, 9, 15), date(2026, 9, 17))
        occurrences = self.source.occurrences_between(self.person, span, self.settings)
        self.assertEqual([(o.title, o.status, o.week) for o in occurrences],
                         [('报名活动', 'applied', 1), ('签到活动', 'checked_in', 1)])
        self.assertEqual(occurrences[0].as_dict(),
                         self.source.occurrences(self.person, self.term, 1, 1, self.settings)[0].as_dict())
        span = DateSpan.load(date(2026, 9, 16), date(2026, 9, 16))   # only the course activity
        self.assertEqual(self.source.occurrences_between(self.person, span, self.settings), [])
        early = self.activity(datetime(2026, 9, 5, 19, 0), title='开学前活动')
        Participation.objects.create(activity=early, person=self.person,
                                     status=Participation.AttendStatus.APPLYSUCCESS)
        span = DateSpan.load(date(2026, 9, 1), date(2026, 9, 13))    # before the term
        occurrences = self.source.occurrences_between(self.person, span, self.settings)
        self.assertEqual([(o.title, o.date, o.week) for o in occurrences],
                         [('开学前活动', date(2026, 9, 5), -1)])
        self.settings.show_activities = False
        self.assertEqual(self.source.occurrences_between(self.person, span, self.settings), [])


class AppointSourceTests(TestCase):

    def setUp(self):
        self.term = make_term()
        self.user, self.person = make_person()
        self.settings = TimetableSettings.objects.create(person=self.person)
        other_user, _ = make_person('tt_other', '别人')
        self.me = Participant.objects.create(Sid=self.user)
        self.other = Participant.objects.create(Sid=other_user)
        self.room = Room.objects.create(
            Rid='B104T', Rtitle='B104 研讨/活动室', Rmin=0, Rmax=10,
            Rstart=time(8, 0), Rfinish=time(22, 0), Rstatus=Room.Status.PERMITTED)
        self.mine = self.appoint(self.me, datetime(2026, 9, 15, 20, 0), usage='讨论')
        self.joined = self.appoint(self.other, datetime(2026, 9, 18, 10, 0))
        self.joined.students.add(self.me, self.other)
        self.appoint(self.me, datetime(2026, 9, 16, 20, 0), status=Appoint.Status.CANCELED)
        theirs = self.appoint(self.other, datetime(2026, 9, 17, 20, 0))
        theirs.students.add(self.other)
        self.week3 = self.appoint(self.me, datetime(2026, 9, 29, 20, 0))
        self.source = AppointSource()

    def appoint(self, major, start, usage='', status=Appoint.Status.APPOINTED):
        appoint = Appoint.objects.create(
            Room=self.room, Astart=start,
            Afinish=start.replace(hour=start.hour + 1), Aneed_num=1,
            major_student=major, Ausage=usage, Astatus=status)
        appoint.students.add(major)
        return appoint

    def test_mine_and_joined_only(self):
        occurrences = self.source.occurrences(self.person, self.term, 1, 1, self.settings)
        self.assertEqual([o.ref['appoint_id'] for o in occurrences],
                         [self.mine.Aid, self.joined.Aid])
        first = occurrences[0]
        self.assertEqual(first.title, '地下室 B104 研讨/活动室')
        self.assertEqual(first.subtitle, '讨论')
        self.assertEqual(first.location, 'B104T')
        self.assertEqual((first.source, first.kind), ('appoint', 'appoint'))
        self.assertEqual(first.start, datetime(2026, 9, 15, 20, 0))
        self.assertEqual(first.end, datetime(2026, 9, 15, 21, 0))
        self.assertEqual((first.week, first.weekday), (1, 2))
        self.assertEqual(first.id, f'appoint:{self.mine.Aid}:2026-09-15')
        whole_term = self.source.occurrences(self.person, self.term, 1, 16, self.settings)
        self.assertEqual([o.ref['appoint_id'] for o in whole_term],
                         [self.mine.Aid, self.joined.Aid, self.week3.Aid])

    def test_settings_toggle(self):
        self.settings.show_appointments = False
        self.assertEqual(self.source.occurrences(self.person, self.term, 1, 16, self.settings), [])

    def test_occurrences_between(self):
        span = DateSpan.load(date(2026, 9, 15), date(2026, 9, 18))
        occurrences = self.source.occurrences_between(self.person, span, self.settings)
        self.assertEqual([o.ref['appoint_id'] for o in occurrences],
                         [self.mine.Aid, self.joined.Aid])
        self.assertEqual(occurrences[0].as_dict(),
                         self.source.occurrences(self.person, self.term, 1, 1, self.settings)[0].as_dict())
        span = DateSpan.load(date(2026, 9, 16), date(2026, 9, 17))   # canceled + someone else's
        self.assertEqual(self.source.occurrences_between(self.person, span, self.settings), [])
        span = DateSpan.load(date(2026, 9, 29), date(2026, 9, 29))
        self.assertEqual([(o.ref['appoint_id'], o.week) for o in
                          self.source.occurrences_between(self.person, span, self.settings)],
                         [(self.week3.Aid, 3)])
        self.settings.show_appointments = False
        self.assertEqual(self.source.occurrences_between(self.person, span, self.settings), [])


class StoredSourceTests(TestCase):

    def test_hidden_entries_are_not_expanded(self):
        term = make_term()
        _, person = make_person()
        make_entry(person, term, name='可见', weekday=1)
        make_entry(person, term, name='隐藏', weekday=2, hidden=True)
        _, other = make_person('tt_other', '别人')
        make_entry(other, term, name='别人的', weekday=3)
        source = StoredEntriesSource()
        occurrences = source.occurrences(person, term, 1, 2, TimetableSettings(person=person))
        self.assertEqual([o.title for o in occurrences], ['可见', '可见'])
        self.assertEqual((source.key, source.label, source.setting),
                         ('stored', '课程', 'show_courses'))

    def test_show_courses_toggle(self):
        term = make_term()
        _, person = make_person()
        make_entry(person, term, name='可见', weekday=1)
        source = StoredEntriesSource()
        settings = TimetableSettings(person=person, show_courses=False)
        self.assertEqual(source.occurrences(person, term, 1, 1, settings), [])
        settings.show_courses = True
        self.assertEqual([o.title for o in source.occurrences(person, term, 1, 1, settings)], ['可见'])
        self.assertEqual([o.title for o in source.occurrences(person, term, 1, 1, None)], ['可见'])

    def test_occurrences_between_follows_the_term_of_each_date(self):
        fall = make_term()
        summer = make_term(code='26-27-3', week1_monday=date(2026, 12, 28), total_weeks=2)
        _, person = make_person()
        make_entry(person, fall, name='秋季课', weekday=1)
        make_entry(person, summer, name='夏季课', weekday=1, week_end=2)
        source = StoredEntriesSource()
        settings = TimetableSettings(person=person)
        # Sat, Sun (no term), Mon (week 1), Tue.
        span = DateSpan.load(date(2026, 9, 12), date(2026, 9, 15))
        occurrences = base.occurrences_between(source, person, span, settings)
        self.assertEqual([(o.title, o.date, o.week) for o in occurrences],
                         [('秋季课', date(2026, 9, 14), 1)])
        # 2026-12-28 is fall week 16 and summer week 1: the summer term owns it.
        span = DateSpan.load(date(2026, 12, 21), date(2026, 12, 28))
        occurrences = base.occurrences_between(source, person, span, settings)
        self.assertEqual([(o.title, o.date, o.week) for o in occurrences],
                         [('秋季课', date(2026, 12, 21), 15), ('夏季课', date(2026, 12, 28), 1)])
        span = DateSpan.load(date(2026, 9, 1), date(2026, 9, 13))
        self.assertEqual(base.occurrences_between(source, person, span, settings), [])
        settings.show_courses = False
        span = DateSpan.load(date(2026, 9, 14), date(2026, 9, 14))
        self.assertEqual(base.occurrences_between(source, person, span, settings), [])
