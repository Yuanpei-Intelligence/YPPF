from datetime import date

from django.test import TestCase

from semester.models import Semester, SemesterType
from semester.api import semester_of


class SemesterTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        type1 = SemesterType.objects.create(name='test1')
        s1 = Semester.objects.create(
            year=2020, type=type1, start_date=date(2020, 2, 1), end_date=date(2020, 6, 30))
        type2 = SemesterType.objects.create(name='test2')
        s2 = Semester.objects.create(
            year=2020, type=type2, start_date=date(2020, 9, 1), end_date=date(2021, 1, 1))
        cls.semesters = [s1, s2]

    def test_semester_api(self):
        # Test Exception
        try:
            _ = semester_of(date(2020, 1, 1))
            _ = semester_of(date(2020, 7, 1), allow_fallback=False)
            raise Exception('Should raise DoesNotExist')
        except Semester.DoesNotExist:
            pass

        s1, s2 = self.semesters
        # Test hit
        self.assertEqual(s1, semester_of(date(2020, 3, 1)))

        # Test fallback
        self.assertEqual(s1, semester_of(date(2020, 8, 20)))
        self.assertEqual(s2, semester_of(date(2021, 1, 15)))
