from typing import Callable, Optional, TypeVar, overload, ParamSpec, Concatenate, TypeAlias
from utils.http.rewrite_httprequest_user import HttpRequest, UserRequest

from django.http.response import HttpResponseBase

_P = ParamSpec('_P')
_R = TypeVar('_R', bound=HttpRequest)
_RP  = TypeVar('_RP', bound=HttpResponseBase)
_View: TypeAlias = Callable[Concatenate[_R, _P], _RP]

# There are two ways of calling @login_required: @with(arguments) and @bare
@overload
def login_required(
    redirect_field_name: str = ...,
    login_url: Optional[str] = ...
) -> Callable[[_View[UserRequest, _P, _RP]], _View[HttpRequest, _P, _RP]]: ...

@overload
def login_required(
    function: _View[UserRequest, _P, _RP],
    redirect_field_name: str = ...,
    login_url: Optional[str] = ...
) -> _View[HttpRequest, _P, _RP]: ...
