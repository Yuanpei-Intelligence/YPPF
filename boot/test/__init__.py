import os
import django.apps

if not django.apps.apps.ready:
    os.environ['DJANGO_SETTINGS_MODULE'] = 'boot.settings'
    django.setup()
