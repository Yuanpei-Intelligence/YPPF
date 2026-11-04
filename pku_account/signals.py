"""
Signals of the 北大账号 binding.

``consent_changed`` lets optional consumers (``academic_record`` today) react
to a consent decision without ``pku_account`` knowing them; the dependency
direction stays consumer → ``pku_account``. Receivers must be idempotent:
the signal is sent for every *explicit* decision, also when the flag
already had that value, and only after the surrounding transaction
committed (``transaction.on_commit``).

Keyword arguments of ``consent_changed``:

- ``account`` — the :class:`pku_account.models.PkuAccount`;
- ``field`` — ``'timetable'`` or ``'grades'``;
- ``granted`` — ``True`` when the consent was given, ``False`` when revoked.

``sender`` is the ``PkuAccount`` class.
"""
import django.dispatch

__all__ = ['CONSENT_FIELDS', 'consent_changed']

CONSENT_FIELDS = ('timetable', 'grades')

consent_changed = django.dispatch.Signal()
