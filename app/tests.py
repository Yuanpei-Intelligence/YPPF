from django.test import TestCase
from django.conf import settings

# Create your tests here.
settings.configure()
from models import student

userinfo = student.objects.filter(username="1700016938")
print(userinfo)
