'''Template context exposing feature switches.'''
from django.utils.functional import SimpleLazyObject

from rollout.api import enabled_features

__all__ = ['rollout_features']


def rollout_features(request) -> dict:
    '''
    Expose ``rollout_features`` to templates, evaluated on first use.

    ``{% if rollout_features.grades %}`` shows an entry only to accounts for
    which the feature is enabled. Pages that never read the variable do not
    query the database. Hiding an entry is not access control; gate the view
    with :func:`rollout.permissions.feature_required` as well.
    '''
    user = getattr(request, 'user', None)
    return {'rollout_features': SimpleLazyObject(lambda: enabled_features(user))}
