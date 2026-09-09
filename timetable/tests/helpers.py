"""Small fixture helpers shared by the timetable tests."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

from app.models import (
    Activity,
    Course,
    CourseParticipant,
    CourseTime,
    NaturalPerson,
    Organization,
    OrganizationType,
)
from Appointment.models import Appoint, Participant, Room
from generic.models import User
from utils.models.semester import Semester
from timetable.models import AcademicTerm, TimetableEntry

FIXTURES = Path(__file__).resolve().parent / 'fixtures'

# 2026-09-14 is a Monday.
WEEK1_MONDAY = date(2026, 9, 14)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


def portal_payload() -> dict:
    return json.loads(read_fixture('portal_course.json'))


def make_person(username: str = 'tt_student', name: str = '课表同学',
                usertype: str = User.Type.STUDENT) -> tuple[User, NaturalPerson]:
    user = User.objects.create_user(username, name, usertype, password='test',
                                    is_newuser=False)
    person = NaturalPerson.objects.create(
        user, name=name, identity=NaturalPerson.Identity.STUDENT)
    return user, person


def make_term(code: str = '26-27-1', week1_monday: date = WEEK1_MONDAY,
              total_weeks: int = 16, is_active: bool = True,
              name: str | None = None) -> AcademicTerm:
    return AcademicTerm.objects.create(
        code=code, name=name or f'{code} 学期', week1_monday=week1_monday,
        total_weeks=total_weeks, is_active=is_active)


def make_entry(person, term, *, name='测试课', weekday=1, start_section=1,
               end_section=2, week_start=1, week_end=16, parity=0,
               source=TimetableEntry.Source.PORTAL, external_key=None,
               **extra) -> TimetableEntry:
    start = term.section_time(start_section) if start_section else None
    end = term.section_time(end_section) if end_section else None
    fields = {
        'name': name,
        'weekday': weekday,
        'start_section': start_section,
        'end_section': end_section,
        'start_time': start[0] if start else extra.pop('start_time'),
        'end_time': end[1] if end else extra.pop('end_time'),
        'week_start': week_start,
        'week_end': week_end,
        'parity': parity,
    }
    fields.update(extra)
    return TimetableEntry.objects.create(
        person=person, term=term, source=source,
        external_key=external_key or TimetableEntry.new_manual_key(), **fields)


# --- fixtures of the live sources (书院课, activities, appointments) ---------

def make_organization(username: str = 'tt_org', name: str = '课表测试小组',
                      otype_id: int = 9301) -> tuple[Organization, NaturalPerson]:
    """An organization with its type and the teacher in charge (the examiner)."""
    teacher_user = User.objects.create_user(
        f'{username}_teacher', '审核老师', User.Type.TEACHER, password='pw')
    teacher = NaturalPerson.objects.create(
        teacher_user, name='审核老师', identity=NaturalPerson.Identity.TEACHER)
    org_type = OrganizationType.objects.create(
        otype_id=otype_id, otype_name=f'{name}类型', incharge=teacher,
        job_name_list=['负责人', '成员'])
    org_user = User.objects.create_user(username, name, User.Type.ORG, password='pw')
    org = Organization.objects.create(organization_id=org_user, oname=name, otype=org_type)
    return org, teacher


def make_activity(org: Organization, teacher: NaturalPerson, start: datetime,
                  hours: int = 2, **overrides) -> Activity:
    """A waiting activity of ``org`` starting at ``start`` (2026 fall by default)."""
    fields = {
        'title': f'活动 {start:%m%d}', 'organization_id': org,
        'examine_teacher': teacher, 'year': 2026,
        'semester': Semester.FALL, 'start': start,
        'end': start + timedelta(hours=hours),
        'location': 'Room A', 'status': Activity.Status.WAITING,
        'publish_time': start, 'apply_end': start,
    }
    fields.update(overrides)
    return Activity.objects.create(**fields)


def make_college_course(org: Organization, person: NaturalPerson, start: datetime,
                        *, name: str = '书院课测试', teacher: str = '书院老师',
                        classroom: str = 'Room B', year: int = 2026,
                        semester: Semester = Semester.FALL, cur_week: int = 0,
                        end_week: int = 16) -> tuple[Course, CourseTime]:
    """A 书院课 ``person`` selected successfully, with one weekly time from ``start``."""
    course = Course.objects.create(
        name=name, organization=org, year=year, semester=semester,
        type=Course.CourseType.INTELLECTUAL, status=Course.Status.SELECT_END,
        classroom=classroom, teacher=teacher)
    course_time = CourseTime.objects.create(
        course=course, start=start, end=start + timedelta(hours=1, minutes=50),
        cur_week=cur_week, end_week=end_week)
    CourseParticipant.objects.create(
        course=course, person=person, status=CourseParticipant.Status.SUCCESS)
    return course, course_time


def make_room(rid: str = 'B104T', title: str = 'B104 研讨/活动室') -> Room:
    return Room.objects.create(
        Rid=rid, Rtitle=title, Rmin=0, Rmax=10,
        Rstart=time(8, 0), Rfinish=time(22, 0), Rstatus=Room.Status.PERMITTED)


def make_appoint(user: User, start: datetime, *, room: Room | None = None,
                 usage: str = '', hours: int = 1,
                 status: int = Appoint.Status.APPOINTED) -> Appoint:
    """An appointment of ``user`` (as major student) starting at ``start``."""
    participant, _ = Participant.objects.get_or_create(Sid=user)
    if room is None:
        room = Room.objects.filter(Rid='B104T').first() or make_room()
    appoint = Appoint.objects.create(
        Room=room, Astart=start, Afinish=start + timedelta(hours=hours),
        Aneed_num=1, major_student=participant, Ausage=usage, Astatus=status)
    appoint.students.add(participant)
    return appoint
