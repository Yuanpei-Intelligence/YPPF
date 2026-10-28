import logging

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


class ExceptionLoggingTestCase(SimpleTestCase):
    def test_secure_func_logs_original_exception_and_preserves_raise_behavior(self):
        for raise_exc in (False, True):
            with self.subTest(raise_exc=raise_exc):
                logger = Logger('exception-details-test')
                logger.setLevel(logging.DEBUG)
                error = ValueError('invalid operation state')

                @logger.secure_func(raise_exc=raise_exc, fail_value='failed')
                def failing_func():
                    raise error

                with self.assertLogs(logger, level='ERROR') as captured:
                    if raise_exc:
                        with self.assertRaises(ValueError) as raised:
                            failing_func()
                        self.assertIs(raised.exception, error)
                    else:
                        self.assertEqual(failing_func(), 'failed')

                self.assertIs(captured.records[0].exc_info[1], error)
                message = '\n'.join(captured.output)
                self.assertIn('ValueError: invalid operation state', message)
                self.assertIn('failing_func', message)
