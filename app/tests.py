from django.test import TestCase
from django.conf import settings
# Create your tests here.
settings.configure()
from models import NaturalPerson
userinfo = NaturalPerson.objects.filter(pid='1700016938')
print(userinfo)