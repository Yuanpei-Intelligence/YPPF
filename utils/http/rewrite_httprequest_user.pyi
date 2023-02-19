from django.http import HttpRequest as _HttpRequest
from django.http.request import QueryDict as _QueryDict
from django.contrib.auth.models import AnonymousUser
from generic.models import User

class QueryDict(_QueryDict):
    # Actually str | []
    def __getitem__(self, key: str) -> str: ...

class HttpRequest(_HttpRequest):
    '''An unauthenticated HTTP request.'''
    user: 'User | AnonymousUser'
    method: str
    GET: QueryDict
    POST: QueryDict

class UserRequest(HttpRequest):
    '''An authenticated HTTP request'''
    # `AnonymousUser` is usually useless, omit it to make
    # type annotation easier.
    user: User
