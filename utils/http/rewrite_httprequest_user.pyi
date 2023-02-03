from django.http import HttpRequest as _HttpRequest
from django.contrib.auth.models import AnonymousUser
from generic.models import User

class HttpRequest(_HttpRequest):
    '''An unauthenticated HTTP request.'''
    user: 'User | AnonymousUser'
    method: str

class UserRequest(HttpRequest):
    '''An authenticated HTTP request'''
    # `AnonymousUser` is usually useless, omit it to make
    # type annotation easier.
    user: User
