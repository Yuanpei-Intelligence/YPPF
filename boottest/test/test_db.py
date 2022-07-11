from django.test import TestCase
from django.contrib.auth.models import User
from django.contrib.auth import authenticate


class DBTestCase(TestCase):
    '''A dumb to make sure the test db works.'''

    @classmethod
    def setUpTestData(cls):
        '''set up db with user'''
        cls.users = {}
        cls.users['john'] = User.objects.create_user(
            'john', 'lennon@thebeatles.com', 'johnpassword')
        cls.users['bob'] = User.objects.create_user(
            'bob', 'bob@thebeatles.com', 'bobpassword')

    def setUp(self) -> None:
        pass

    def test_user_auth(self):
        self.assertIsNone(authenticate(username='john', password='secret'))
        self.assertIsNotNone(authenticate(username='bob', password='bobpassword'))

    def test_get_and_save(self):
        with self.assertRaises(Exception):
            User.objects.get(username='alice')
        john: User = User.objects.get(username='john')
        john.is_staff = True
        john.save()
        john.is_staff = False
        john.save()
