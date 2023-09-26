from django.test import SimpleTestCase
from django.db.models import Q

from generic.models import User
from app.models import NaturalPerson, Organization, Position
from Appointment.models import Participant

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
        q3 = sq('a', 1)
        self.assertIsInstance(q3, Q)
        self.assertEqual(q3, Q(a=1))
        q4 = sq(['a'], 1)
        self.assertIsInstance(q4, Q)
        self.assertEqual(q4, Q(a=1))

    def test_concat(self):
        '''测试函数连接的功能'''
        self.assertEqual(f('a', 'b'), 'a__b')
        self.assertEqual(f('a', 'b', 'c_id'), 'a__b__c_id')
        self.assertEqual(f('user', 'name', 'in'), 'user__name__in')
        self.assertEqual(q('user', 'id', 'lt', value=1), Q(user__id__lt=1))
        self.assertEqual(lq(1, 'user', 'id', 'lt'), Q(user__id__lt=1))
        self.assertEqual(sq(['user', 'id', 'lt'], 2), Q(user__id__lt=2))



class SQueryFieldTest(SimpleTestCase):
    '''测试SQuery转化字段的功能'''

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

    def test_forward_relations(self):
        '''测试检测正向关系字段的功能'''
        self.assertEqual(f(NaturalPerson.person_id), 'person_id')
        self.assertEqual(f(NaturalPerson.person_id.field), 'person_id')
        self.assertEqual(f(Position.person), 'person')
        self.assertEqual(f(Position.person.field), 'person')
        self.assertEqual(f(NaturalPerson.unsubscribe_list), 'unsubscribe_list')
        self.assertEqual(f(NaturalPerson.unsubscribe_list.field), 'unsubscribe_list')

    def test_foreign_index(self):
        '''测试检测外键索引字段的功能'''
        self.assertEqual(f(NaturalPerson.person_id_id), 'person_id_id')
        self.assertEqual(f(Position.person_id), 'person_id')

    def test_reverse_relations(self):
        '''测试检测反向关系字段的功能'''
        self.assertEqual(f(User.naturalperson), 'naturalperson')
        self.assertEqual(f(Participant.appoint_list), 'appoint_list')

    def test_index_form(self):
        '''测试特殊形式的字段的功能'''
        self.assertEqual(f(Index(NaturalPerson.person_id)), 'person_id_id')
        self.assertEqual(f(Index(Position.person)), 'person_id')
        self.assertEqual(f(Index(NaturalPerson.unsubscribe_list)), 'unsubscribe_list')
        self.assertEqual(f(Index(Position.person_id)), 'person_id')
        self.assertEqual(f(Index(Position.person.field)), 'person_id')

    def test_forward_form(self):
        '''测试特殊形式的正向关系字段的功能'''
        self.assertEqual(f(Forward(User.naturalperson)), 'person_id')
        self.assertEqual(f(Forward(NaturalPerson.position_set)), 'person')
        self.assertEqual(f(Forward(Organization.unsubscribers)), 'unsubscribe_list')
        self.assertEqual(f(Forward(Position.person)), 'person')
        self.assertEqual(f(Forward(Position.person.field)), 'person')

    def test_reverse_form(self):
        '''测试特殊形式的反向关系字段的功能，不会因此跨越隐藏关系字段'''
        self.assertEqual(f(Reverse(NaturalPerson.person_id)), 'naturalperson')
        self.assertEqual(f(Reverse(Position.person)), 'position_set')
        self.assertEqual(f(Reverse(NaturalPerson.unsubscribe_list)), 'unsubscribers')
        self.assertEqual(f(Reverse(Participant.appoint_list)), 'appoint_list')
        self.assertEqual(f(Reverse(Position.person.field)), 'position_set')
        with self.assertRaises(ValueError):
            f(Reverse(Participant.Sid))
