from django.http import HttpRequest as _HttpRequest
from generic.models import User

class HttpRequest(_HttpRequest):
    # user: 'User | AnonymousUser'
    # `AnonymousUser` is usually useless, omit it to make
    # type annotation easier.
    user: User
