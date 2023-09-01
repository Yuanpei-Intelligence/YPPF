from datetime import date

from django.test import TestCase

from semester.models import Semester, SemesterType
from semester.api import semester_of


class GetCurrentSemester(TestCase):

    @classmethod
    def setUpTestData(cls):
        pass

    def test_exception(self):
        try:
            _ = semester_of(date.today())
            raise Exception('Should raise DoesNotExist')
        except Semester.DoesNotExist:
            pass

    def test_hit(self):
        ty = SemesterType.objects.create(ty_name='test')
        s1 = Semester.objects.create(
            year=2020, ty=ty, start_date=date(2020, 2, 1), end_date=date(2020, 6, 30))
        s2 = Semester.objects.create(
            year=2020, ty=ty, start_date=date(2020, 9, 1), end_date=date(2021, 1, 1))
        self.assertEqual(s1, semester_of(date(2020, 3, 1)))
        self.assertEqual(s1, semester_of(date(2020, 8, 20)))
        self.assertEqual(s2, semester_of(date(2021, 1, 15)))
