"""
Shapes of publicQuery ``myCourseTable/getCourseInfo.do`` answers seen with a
real account on 2026-09-10 that the course-table fixtures do not cover.
"""
from django.test import SimpleTestCase

from timetable.sources import pku_parsers


class PublicQueryCourseInfoPayloadTests(SimpleTestCase):

    def test_success_without_course_list_is_an_empty_table(self):
        # A term without a timetable (a graduate without classes): no "course"
        # key, only a message that reads like an error.
        payload = {'success': True, 'message': '获取个人课表信息失败'}
        self.assertEqual(pku_parsers.parse_portal_course_json(payload), [])

    def test_unrecognised_payloads_still_raise(self):
        with self.assertRaises(ValueError):
            pku_parsers.parse_portal_course_json({'message': '无 success 标记'})
        with self.assertRaises(ValueError):
            pku_parsers.parse_portal_course_json({'success': False, 'message': '失败'})
        with self.assertRaises(ValueError):
            pku_parsers.parse_portal_course_json({'success': True, 'course': 'not a list'})
