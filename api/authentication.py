from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed


class StrictJWTAuthentication(JWTAuthentication):
    """
    Require JWT authentication.
    Missing token -> 401
    Invalid / expired token -> 401 (handled by parent)
    """

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            raise AuthenticationFailed(
                "Authentication credentials were not provided")

        return super().authenticate(request)
