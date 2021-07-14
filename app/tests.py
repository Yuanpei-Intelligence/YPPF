from django.test import TestCase
from django.conf import settings
# Create your tests here.
settings.configure()
from models import NaturalPeople
userinfo = NaturalPeople.objects.filter(username='1700016938')
print(userinfo)