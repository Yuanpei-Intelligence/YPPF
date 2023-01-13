"""
Generate fake records. Only used in dev & test.
"""

from django.conf import settings

# TODO: Change Settings
assert settings.DEBUG, 'Should not import fake_records in production env.'


def create_user():
    ...


def create_np():
    ...


def create_org_ty():
    ...


def create_org():
    ...


def create_activity():
    ...


def create_participant():
    ...


def create_all():
    ...
