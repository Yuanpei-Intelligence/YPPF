from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase

from record.log.logger import Logger


class RequestLoggingTestCase(SimpleTestCase):
    def test_format_request_omits_post_and_query_values(self):
        post_secrets = ["pw-v13-secret", "token-v13-secret", "code-v13-secret"]
        query_secret = "auth-v13-query-secret"
        request = RequestFactory().post(
            f"/submit-sensitive/?source=test&auth={query_secret}",
            {
                "password": post_secrets[0],
                "token": post_secrets[1],
                "code": post_secrets[2],
            },
        )
        request.user = AnonymousUser()

        message = Logger.format_request(request)

        self.assertIn("URL: /submit-sensitive/", message)
        self.assertNotIn("source=test", message)
        self.assertNotIn("auth=", message)
        self.assertIn("Method: POST", message)
        self.assertNotIn("Data:", message)
        for value in (*post_secrets, query_secret):
            self.assertNotIn(value, message)
