"""Fixture helpers shared by the academic_record tests."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.models import NaturalPerson
from generic.models import User
from pku_account.config import PkuPortalConfig
from pku_account.extern.portal import PortalClient
from pku_account.models import PkuAccount
from pku_account.services import login_and_bind
from academic_record.models import GradeRecord
from academic_record.parsers import GradeRow, TermScores

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
PASSWORD = 'S3cret-Pa55!'
PKU_ID = '2100010001'
FETCHED_AT = datetime(2026, 9, 9, 12, 0, 0)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


def scores_payload() -> dict:
    """The nested ``retrScores.do`` shape (a fresh copy every call)."""
    return json.loads(read_fixture('portal_scores.json'))


def flat_payload(payload: dict | None = None) -> dict:
    """The same data flattened the way pkuhelper-web-score does it."""
    if payload is None:
        payload = scores_payload()
    rows = []
    for block in payload['cjxx']:
        if not isinstance(block, dict):
            continue
        for row in block['list']:
            if isinstance(row, dict):
                rows.append(dict(row, xnd=block['xnd'], xq=block['xq']))
    return {'cjxx': rows}


def make_person(username: str = 'ar_student', name: str = '成绩同学',
                usertype: str = User.Type.STUDENT) -> tuple[User, NaturalPerson]:
    user = User.objects.create_user(username, name, usertype, password='test',
                                    is_newuser=False)
    person = NaturalPerson.objects.create(
        user, name=name, identity=NaturalPerson.Identity.STUDENT)
    return user, person


def enable_portal(testcase) -> None:
    """Portal enabled with a throw-away Fernet key for the whole test."""
    for name, value in (
        ('enabled', True),
        ('session_key', Fernet.generate_key().decode()),
    ):
        patcher = patch.object(PkuPortalConfig, name, value)
        patcher.start()
        testcase.addCleanup(patcher.stop)


def fake_client(cookies: dict | None = None) -> PortalClient:
    return PortalClient.from_cookies(cookies or {'JSESSIONID': 'portal-session'})


def bind(user: User, pku_username: str = PKU_ID, **consents) -> PkuAccount:
    """A real binding with a stored session; IAAA is mocked."""
    with patch.object(PortalClient, 'login', return_value=fake_client()):
        return login_and_bind(user, pku_username, PASSWORD, **consents)


def make_row(term_code: str = '25-26-1', name: str = '课程', **overrides) -> GradeRow:
    fields = {
        'course_code': '00000000', 'class_no': '01', 'course_type': '专业必修',
        'credits': Decimal('2.0'), 'score': '85', 'score_numeric': 85.0,
        'gpa': 3.4, 'raw': {},
    }
    fields.update(overrides)
    return GradeRow(term_code=term_code, name=name, **fields)


def make_term(term_code: str, *rows: GradeRow) -> TermScores:
    return TermScores(term_code, list(rows))


def make_record(person: NaturalPerson, term_code: str = '25-26-1',
                name: str = '课程', fetched_at: datetime = FETCHED_AT,
                **overrides) -> GradeRecord:
    fields = {
        'course_code': '00000000', 'class_no': '01', 'course_type': '专业必修',
        'credits': Decimal('2.0'), 'score': '85', 'score_numeric': 85.0,
        'gpa': 3.4, 'raw': {},
    }
    fields.update(overrides)
    return GradeRecord.objects.create(
        person=person, term_code=term_code, name=name, fetched_at=fetched_at,
        **fields)
