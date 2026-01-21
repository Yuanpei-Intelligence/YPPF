from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from drf_spectacular.extensions import OpenApiAuthenticationExtension


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


class WxJWTAuthenticationExt(OpenApiAuthenticationExtension):
    target_class = "api.authentication.WxJWTAuthentication"
    name = "WxJWT Authentication"

    def get_security_definition(self, auto_schema: 'AutoSchema'):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
