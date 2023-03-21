from typing import TypeVar

from django.db.models.base import Model
from django.db.models.manager import (
    RelatedManager as RelatedManager,
    ManyToManyRelatedManager as _ManyToManyRelatedManager,
)

__all__ = [
    'RelatedManager',
    'ManyRelatedManager',
]


_T = TypeVar("_T", bound=Model)

class ManyRelatedManager(_ManyToManyRelatedManager[_T, _T]):
    pass
