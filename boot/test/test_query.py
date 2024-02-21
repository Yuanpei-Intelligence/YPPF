# type: ignore
from django.test import SimpleTestCase, TestCase
from django.db.models import Q

from generic.models import User
from app.models import (
    NaturalPerson as Person,
    Organization as Org,
    Position as Position,
)
from Appointment.models import Participant

from utils.models.query import *

class SQueryTest(SimpleTestCase):
    '''测试SQuery的功能'''

    def test_transform(self):
        '''测试转换器的功能'''
        self.assertEqual(f('a'), 'a')
        self.assertEqual(q('a', value=1), Q(a=1))
        self.assertEqual(sq('a', 1), Q(a=1))
        self.assertEqual(sq(['a'], 1), Q(a=1))

    def test_concat(self):
        '''测试函数连接的功能'''
        self.assertEqual(f('a', 'b'), 'a__b')
        self.assertEqual(f('a', 'b', 'c_id'), 'a__b__c_id')
        self.assertEqual(f('user', 'name', 'in'), 'user__name__in')
        self.assertEqual(q('user', 'id', 'lt', value=1), Q(user__id__lt=1))
        self.assertEqual(sq(['user', 'id', 'lt'], 2), Q(user__id__lt=2))

    def test_multiple_query(self):
        '''测试多个查询的功能'''
        self.assertEqual(mq(), Q())
        self.assertEqual(mq('a', exact=True), Q(a__exact=True))
        mq1 = mq('val', lt=1, gt=0, isnull=False)
        self.assertEqual(mq1, Q(val__lt=1, val__gt=0, val__isnull=False))
        mq2 = mq('user', 'id', lt=1, isnull=False)
        self.assertEqual(mq2, Q(user__id__lt=1, user__id__isnull=False))
        self.assertEqual(mq('user', 'id', IN=[1, 2]), Q(user__id__in=[1, 2]))
        self.assertEqual(mq('user', 'id', In=[1, 2]), Q(user__id__in=[1, 2]))



class SQueryFieldTest(SimpleTestCase):
    '''测试SQuery转化字段的功能'''

    def test_normal_fields(self):
        '''测试检测普通字段的功能'''
        self.assertEqual(f(User.name.field), 'name')
        self.assertEqual(f(User.credit.field), 'credit')
        self.assertEqual(f(User.active.field), 'active')
        self.assertEqual(f(User.last_login.field), 'last_login')
        self.assertEqual(f(Person.avatar.field), 'avatar')

    def test_normal_descriptors(self):
        '''测试检测普通字段描述符的功能'''
        self.assertEqual(f(User.name), 'name')
        self.assertEqual(f(User.credit), 'credit')
        self.assertEqual(f(User.active), 'active')
        self.assertEqual(f(User.last_login), 'last_login')
        self.assertEqual(f(Person.avatar), 'avatar')

    def test_forward_relations(self):
        '''测试检测正向关系字段的功能'''
        self.assertEqual(f(Person.person_id), 'person_id')
        self.assertEqual(f(Person.person_id.field), 'person_id')
        self.assertEqual(f(Position.person), 'person')
        self.assertEqual(f(Position.person.field), 'person')
        self.assertEqual(f(Person.unsubscribe_list), 'unsubscribe_list')
        self.assertEqual(f(Person.unsubscribe_list.field), 'unsubscribe_list')

    def test_foreign_index(self):
        '''测试检测外键索引字段的功能'''
        self.assertEqual(f(Person.person_id_id), 'person_id_id')
        self.assertEqual(f(Position.person_id), 'person_id')

    def test_reverse_relations(self):
        '''测试检测反向关系字段的功能'''
        self.assertEqual(f(User.naturalperson), 'naturalperson')
        self.assertEqual(f(Participant.appoint_list), 'appoint_list')

    def test_index_form(self):
        '''测试特殊形式的字段的功能'''
        self.assertEqual(f(Index(Person.person_id)), 'person_id_id')
        self.assertEqual(f(Index(Position.person)), 'person_id')
        self.assertEqual(f(Index(Person.unsubscribe_list)), 'unsubscribe_list')
        self.assertEqual(f(Index(Position.person_id)), 'person_id')
        self.assertEqual(f(Index(Position.person.field)), 'person_id')

    def test_forward_form(self):
        '''测试特殊形式的正向关系字段的功能'''
        self.assertEqual(f(Forward(User.naturalperson)), 'person_id')
        self.assertEqual(f(Forward(Person.position_set)), 'person')
        self.assertEqual(f(Forward(Org.unsubscribers)), 'unsubscribe_list')
        self.assertEqual(f(Forward(Position.person)), 'person')
        self.assertEqual(f(Forward(Position.person.field)), 'person')

    def test_reverse_form(self):
        '''测试特殊形式的反向关系字段的功能，不会因此跨越隐藏关系字段'''
        self.assertEqual(f(Reverse(Person.person_id)), 'naturalperson')
        self.assertEqual(f(Reverse(Position.person)), 'position_set')
        self.assertEqual(f(Reverse(Person.unsubscribe_list)), 'unsubscribers')
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
        cls.uorg = User.objects.create_user('zz00000', 'org', password='333')
        
        person_datas = [
            [cls.u1, '1', '2018'],
            [cls.u2, '2', '2018'],
            [cls.u3, '3', '2019'],
        ]
        cls.p1, cls.p2, cls.p3 = (
            Person.objects.create(u, name=name, stu_grade=grade)
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
        self.assertEqual(sget(Person.name, self.p1.name), self.p1)
        self.assertEqual(sget(Person.stu_grade, '2019'), self.p3)
        self.assertEqual(sget([Person.person_id, User.username],
                              self.u1.username), self.p1)
        with self.assertRaises(Person.MultipleObjectsReturned):
            sget(Person.stu_grade, '2018')

    def test_filter(self):
        '''测试`SQuery.sfilter`的功能'''
        self.assertCountEqual(sfilter(User.name, 'a'), [self.u1, self.u3])
        self.assertCountEqual(sfilter(Person.stu_grade, '2018'), [self.p1, self.p2])
        self.assertCountEqual(sfilter([Person.person_id, User.name], 'a'),
                              [self.p1, self.p3])

    def test_exclude(self):
        '''测试`SQuery.sexclude`的功能'''
        self.assertCountEqual(sexclude(User.name, 'b'), [self.u1, self.u3, self.uorg])
        self.assertCountEqual(sexclude(Person.stu_grade, '2018'), [self.p3])
        self.assertCountEqual(sexclude([Person.person_id, User.name], 'a'),
                              [self.p2])

    def assertValuesEqual(self, qs1, qs2):
        '''测试QuerySet的值是否相等，由于QuerySet无法直接比较，因此需要转化为list'''
        self.assertEqual(type(qs1), type(qs2))
        self.assertListEqual(list(qs1), list(qs2))

    def test_values(self):
        '''测试`SQuery.svalues`的功能'''
        self.assertValuesEqual(User.objects.values('username'), svalues(User.username))
        self.assertValuesEqual(Person.objects.values('name'), svalues(Person.name))
        self.assertValuesEqual(svalues(Person.person_id, Person.name),
                               Person.objects.values('person_id__name'))

    def test_values_list(self):
        '''测试`SQuery.svlist`的功能'''
        self.assertListEqual(svlist(User.username), ['11', '22', '33', 'zz00000'])
        self.assertListEqual(svlist(Person.person_id), [u.pk for u in self.users])
        self.assertListEqual(svlist(Person.person_id, User.name), ['a', 'b', 'a'])

    def test_multiple_get(self):
        '''测试`SQuery.mget`的多个查询功能'''
        self.assertEqual(mget(Person.person_id, name='a', username='11'), self.p1)
        with self.assertRaises(Person.DoesNotExist):
            mget(Person.person_id, name='a', username='22')

    def test_multiple_filter(self):
        '''测试`SQuery.mfilter`的多个查询功能'''
        self.assertCountEqual(mfilter(User.id, gte=self.u2.id, lte=self.u3.id),
                              [self.u2, self.u3])
        self.assertFalse(mfilter(Person.person_id, id=self.p1.id, name='b'))
        self.assertCountEqual(mfilter(Person.person_id, User.name, startswith='b'),
                              [self.p2])

    def test_multiple_exclude(self):
        '''测试`SQuery.mexclude`的多个查询功能'''
        self.assertCountEqual(mexclude(User.id, gte=self.u2.id, lte=self.u3.id),
                              [self.u1, self.uorg])
        self.assertCountEqual(mexclude(Person.person_id, id=self.p1.id, name='b'),
                              [self.p1, self.p2, self.p3])
        self.assertCountEqual(mexclude(Person.person_id, User.name, exact='a'),
                              [self.p2])

    def test_reverse_form(self):
        '''测试`SQuery.Reverse`能否正确从另一侧模型管理器生成查询'''
        svalues(Person.unsubscribe_list)  # 检查能否处理延迟加载的关系
        self.assertListEqual(svlist(Reverse(Person.person_id), Person.name),
                             svlist(Person.name) + [None])
        self.assertEqual(sget(User.naturalperson, self.p1.id), self.u1)
        self.assertEqual(sget(Reverse(Person.person_id), self.p1), self.u1)
        self.assertEqual(sget([Reverse(Person.person_id), 'isnull'], True), self.uorg)
        self.assertCountEqual(sfilter([Reverse(Person.person_id), Person.stu_grade], 2018),
                              [self.u1, self.u2])
        self.assertCountEqual(sexclude(Reverse(Person.person_id), None), self.users)
