"""
Receivers of ``pku_account`` signals; connected in
``AcademicRecordConfig.ready``. The dependency direction is
``academic_record`` → ``pku_account`` only.

Both receivers are idempotent deletions, which is what makes a signal
acceptable here: a repeated or duplicated delivery finds nothing to do.
"""
from __future__ import annotations

import logging

from app.models import NaturalPerson
from academic_record import services

__all__ = ['on_consent_changed', 'on_binding_deleted']

logger = logging.getLogger(__name__)


def _delete_stored_of_user(user_id: int, reason: str) -> None:
    person = NaturalPerson.objects.filter(person_id=user_id).first()
    if person is None:
        return
    deleted = services.delete_stored(person)
    if deleted:
        logger.info('%s of user #%s; %s stored grade rows removed',
                    reason, user_id, deleted)


def on_consent_changed(sender, *, account, field: str, granted: bool,
                       **kwargs) -> None:
    """
    Delete the person's stored grades when the ``grades`` consent is
    revoked. Other fields and grants are ignored.
    """
    if field != 'grades' or granted:
        return
    _delete_stored_of_user(account.user_id, 'grades consent revoked')


def on_binding_deleted(sender, *, instance, **kwargs) -> None:
    """
    ``post_delete`` of ``PkuAccount``: the consent record disappears with
    the binding, so the grades stored under it disappear as well.
    """
    _delete_stored_of_user(instance.user_id, 'PKU binding removed')
