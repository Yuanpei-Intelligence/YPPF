from django.middleware.csrf import CsrfViewMiddleware


class CsrfCookieMiddleware(CsrfViewMiddleware):
    """Set CSRF cookies requested by templates without globally validating.

    Session-authenticated mutations remain responsible for applying
    ``csrf_protect`` explicitly, as required by the project-wide convention.
    """

    def process_view(self, request, callback, callback_args, callback_kwargs):
        return None
