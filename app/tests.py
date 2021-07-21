from django.test import TestCase
from django.conf import settings

# Create your tests here.
settings.configure()
from models import NaturalPerson

userinfo = NaturalPerson.objects.filter(person_id="1700016938")
print(userinfo)
