import logging
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase

from app.log import ProfileLogger


class ProfileLoggerExceptionTestCase(SimpleTestCase):
    def test_secure_view_omits_post_and_query_values_from_alerts(self):
        post_secrets = ["password-v13", "token-v13", "identity-v13"]
        query_secret = "auth-v13-query-secret"
        request = RequestFactory().post(
            f"/failing-view/?auth={query_secret}",
            {
                "password": post_secrets[0],
                "token": post_secrets[1],
                "identity": post_secrets[2],
            },
        )
        request.user = AnonymousUser()
        logger = ProfileLogger("v13-test")
        logger.setLevel(logging.DEBUG)
        logger.set_debug_mode(False)

        @logger.secure_view()
        def failing_view(request):
            raise RuntimeError("view operation failed")

        with patch.object(logger, "_send_wechat") as send_wechat:
            with self.assertLogs(logger, level="ERROR") as captured:
                response = failing_view(request)

        local_message = "\n".join(captured.output)
        wechat_message = send_wechat.call_args.args[0]
        self.assertEqual(response.status_code, 302)
        for message in (local_message, wechat_message):
            self.assertIn("URL: /failing-view/", message)
            self.assertNotIn("auth=", message)
            self.assertIn("Method: POST", message)
            self.assertIn("Except RuntimeError: view operation failed", message)
            for value in (*post_secrets, query_secret):
                self.assertNotIn(value, message)

        self.assertIn("Traceback (most recent call last)", local_message)

    def test_secure_func_preserves_exception_chain_without_dumping_arguments(self):
        argument_secret = "feedback-v13-secret"
        exception_detail = "function operation failed"
        request = RequestFactory().post(
            "/feedback/",
            {"content": argument_secret},
        )
        logger = ProfileLogger("v13-secure-func-test")
        logger.setLevel(logging.DEBUG)
        logger.set_debug_mode(False)

        @logger.secure_func()
        def failing_func(info, *, password):
            try:
                raise ValueError("original failure")
            except ValueError as error:
                raise RuntimeError("function operation failed") from error

        with patch.object(logger, "_send_wechat") as send_wechat:
            with self.assertLogs(logger, level="ERROR") as captured:
                failing_func(request.POST, password="password-v13-secret")

        local_message = "\n".join(captured.output)
        wechat_message = send_wechat.call_args.args[0]
        for message in (local_message, wechat_message):
            self.assertNotIn(argument_secret, message)
            self.assertNotIn("password-v13-secret", message)
            self.assertIn(exception_detail, message)
            self.assertIn("Arg types: QueryDict", message)
            self.assertIn("Keyword names: password", message)
            self.assertIn("Except RuntimeError", message)
        self.assertIn("ValueError: original failure", local_message)
        self.assertIn("RuntimeError: function operation failed", local_message)
        self.assertIn("direct cause", local_message)
