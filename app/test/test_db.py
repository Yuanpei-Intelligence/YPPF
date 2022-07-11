from django.test import TestCase
from django.contrib.auth.models import User
from django.contrib.auth import authenticate

from app.models import NaturalPerson


class DBTestCase(TestCase):
    """Another dumb to make sure the test db works.
    """

    def setUp(self):
        """set up db with user and np
        """
        john = User.objects.create_user(
            'john', 'lennon@thebeatles.com', 'johnpassword')
        bob = User.objects.create_user(
            'bob', 'bob@thebeatles.com', 'bobpassword')
        NaturalPerson.objects.create(person_id=john, name='john')
        NaturalPerson.objects.create(person_id=bob, name='bob')

    def test_user_auth(self):
        assert authenticate(username='john', password='secret') is None
        assert authenticate(username='bob', password='bobpassword') is not None

    def test_np_select_and_save(self):
        john = NaturalPerson.objects.get(name='john')
        john.nickname = 'J'
        john.save()
