from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.authentication import BaseAuthentication
from drf_spectacular.extensions import OpenApiAuthenticationExtension

from api.auth.ticket import consume_webview_ticket
from generic.models import User


class WxJWTAuthentication(JWTAuthentication):
    """
    Require JWT authentication.
    Missing token -> 401
    
    We will use this authentication for every endpoint except for 
    /wx/login and /wx/bind.
    By default, JWTAuthentication + session authentication will
    treat requests without a token as "annonymous user", which is 
    considered authenticated, and return a 403 (Fobidden).
    To seperate from that case, we will use this custom authenticator,
    which will return a 401 (Unauthorized) instead.
    """

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            raise AuthenticationFailed(
                "Authentication credentials were not provided")

        return super().authenticate(request)


class TicketAuthentication(BaseAuthentication):
    """
    One-time ticket authentication for webview redirect.
    Reads ticket from query param `ticket`, validates it, and atomically
    consumes its digest-only database row.
    Used by /redirect/?ticket=xxx&to=... to avoid passing JWT in URL.
    """

    def authenticate(self, request):
        ticket = request.GET.get("ticket")
        if not ticket:
            return None
        user_id = consume_webview_ticket(ticket)
        if user_id is None:
            raise AuthenticationFailed("invalid or expired ticket")
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise AuthenticationFailed("invalid ticket")
        return (user, None)


class WxJWTAuthenticationExt(OpenApiAuthenticationExtension):
    target_class = "api.authentication.WxJWTAuthentication"
    name = "WxJWT Authentication"

    def get_security_definition(self, auto_schema: 'AutoSchema'):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
