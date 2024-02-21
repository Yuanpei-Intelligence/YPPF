from django.test import TestCase

from app.models import *

class MigrateTest(TestCase):
    '''Another dumb to make sure the test db works.'''
    @classmethod
    def setUpTestData(cls):
        cls.john = User.objects.create_user(
            'john', 'john', password='johnpassword')

    def test_migrate(self):
        NaturalPerson.objects.create(self.john, name='john')
