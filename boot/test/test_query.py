# type: ignore
from django.test import SimpleTestCase, TestCase
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


class SQueryFunctionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.all().delete()
        cls.u1 = User.objects.create_user('11', 'a', password='111')
        cls.u2 = User.objects.create_user('22', 'b', password='222')
        cls.u3 = User.objects.create_user('33', 'a', password='333')
        cls.users = [cls.u1, cls.u2, cls.u3]
        
        person_datas = [
            [cls.u1, '1', '2018'],
            [cls.u2, '2', '2018'],
            [cls.u3, '3', '2019'],
        ]
        cls.p1, cls.p2, cls.p3 = (
            NaturalPerson.objects.create(person_id=u, name=name, stu_grade=grade)
            for u, name, grade in person_datas
        )

    def test_empty_field(self):
        '''测试空字段能否抛出异常'''
        with self.assertRaises(TypeError): sget([], 'a')
        with self.assertRaises(TypeError): sfilter([], 'a')
        with self.assertRaises(TypeError): sexclude([], 'a')
        with self.assertRaises(TypeError): svalues()
        with self.assertRaises(TypeError): svlist()
        with self.assertRaises(TypeError): qsvlist(User.objects.all())

    def test_get(self):
        '''测试`SQuery.sget`的功能'''
        self.assertEqual(sget(User.username, self.u1.username), self.u1)
        self.assertEqual(sget(User.id, self.u2.id), self.u2)
        with self.assertRaises(User.DoesNotExist):
            sget(User.username, '44')
        self.assertEqual(sget(NaturalPerson.name, self.p1.name), self.p1)
        self.assertEqual(sget(NaturalPerson.stu_grade, '2019'), self.p3)
        self.assertEqual(sget([NaturalPerson.person_id, User.username],
                              self.u1.username), self.p1)
        with self.assertRaises(NaturalPerson.MultipleObjectsReturned):
            sget(NaturalPerson.stu_grade, '2018')

    def test_filter(self):
        '''测试`SQuery.sfilter`的功能'''
        self.assertCountEqual(sfilter(User.name, 'a'), [self.u1, self.u3])
        self.assertCountEqual(sfilter(NaturalPerson.stu_grade, '2018'), [self.p1, self.p2])
        self.assertCountEqual(sfilter([NaturalPerson.person_id, User.name], 'a'),
                              [self.p1, self.p3])

    def test_exclude(self):
        '''测试`SQuery.sexclude`的功能'''
        self.assertCountEqual(sexclude(User.name, 'b'), [self.u1, self.u3])
        self.assertCountEqual(sexclude(NaturalPerson.stu_grade, '2018'), [self.p3])
        self.assertCountEqual(sexclude([NaturalPerson.person_id, User.name], 'a'),
                              [self.p2])

    def assertValuesEqual(self, qs1, qs2):
        '''测试QuerySet的值是否相等，由于QuerySet无法直接比较，因此需要转化为list'''
        self.assertEqual(type(qs1), type(qs2))
        self.assertListEqual(list(qs1), list(qs2))

    def test_values(self):
        '''测试`SQuery.svalues`的功能'''
        self.assertValuesEqual(User.objects.values('username'), svalues(User.username))
        self.assertValuesEqual(NaturalPerson.objects.values('name'), svalues(NaturalPerson.name))
        self.assertValuesEqual(svalues(NaturalPerson.person_id, NaturalPerson.name),
                               NaturalPerson.objects.values('person_id__name'))

    def test_values_list(self):
        '''测试`SQuery.svlist`的功能'''
        self.assertListEqual(svlist(User.username), ['11', '22', '33'])
        self.assertListEqual(svlist(NaturalPerson.person_id), [u.pk for u in self.users])
        self.assertListEqual(svlist(NaturalPerson.person_id, User.name), ['a', 'b', 'a'])
