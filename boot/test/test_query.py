from django.test import SimpleTestCase
from django.db.models import Q

from app.models import *

from utils.models.query import *

class SQueryTest(SimpleTestCase):
    '''测试SQuery的功能'''

    def test_transform(self):
        '''测试转换器的功能'''
        self.assertEqual(f('a'), 'a')
        q1 = q('a', value=1)
        self.assertIsInstance(q1, Q)
        self.assertEqual(q1, Q(a=1))
        q2 = lq(1, 'a')
        self.assertIsInstance(q2, Q)
        self.assertEqual(q2, Q(a=1))

    def test_concat(self):
        '''测试函数连接的功能'''
        self.assertEqual(f('a', 'b'), 'a__b')
        self.assertEqual(f('a', 'b', 'c_id'), 'a__b__c_id')
        self.assertEqual(f('user', 'name', 'in'), 'user__name__in')
        self.assertEqual(q('user', 'id', 'lt', value=1), Q(user__id__lt=1))
        self.assertEqual(lq(1, 'user', 'id', 'lt'), Q(user__id__lt=1))

    def test_normal_fields(self):
        '''测试检测普通字段的功能'''
        self.assertEqual(f(User.name.field), 'name')
        self.assertEqual(f(User.credit.field), 'credit')
        self.assertEqual(f(User.active.field), 'active')
        self.assertEqual(f(User.last_login.field), 'last_login')
        self.assertEqual(f(NaturalPerson.avatar.field), 'avatar')

    def test_normal_descriptors(self):
        '''测试检测普通字段描述符的功能'''
        self.assertEqual(f(User.name), 'name')
        self.assertEqual(f(User.credit), 'credit')
        self.assertEqual(f(User.active), 'active')
        self.assertEqual(f(User.last_login), 'last_login')
        self.assertEqual(f(NaturalPerson.avatar), 'avatar')
