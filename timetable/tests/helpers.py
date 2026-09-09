"""Small fixture helpers shared by the timetable tests."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.models import NaturalPerson
from generic.models import User
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
