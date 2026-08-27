from urllib.parse import urlencode
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TestCase

from api.auth.ticket import create_webview_ticket
from generic.models import User
from utils.http.utils import safe_local_redirect_target


class SafeLocalRedirectTargetTestCase(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/", HTTP_HOST="testserver")

    def test_accepts_local_paths(self):
        for target in ("/inside?x=1", "/inside#fragment"):
            with self.subTest(target=target):
                self.assertEqual(
                    safe_local_redirect_target(self.request, target, "/fallback/"),
                    target,
                )

    def test_rejects_unsafe_or_ambiguous_targets(self):
        targets = (
            "https://evil.example/phish",
            "//evil.example/phish",
            "//testserver/phish",
            "/\\evil.example",
            "\\evil.example",
            "http://testserver/inside",
            "https://testserver/inside",
            "javascript:alert(1)",
            "inside",
            "",
            "   ",
            None,
        )
        for target in targets:
            with self.subTest(target=target):
                self.assertEqual(
                    safe_local_redirect_target(self.request, target, "/fallback/"),
                    "/fallback/",
                )

    def test_rejects_http_target_for_secure_request(self):
        request = RequestFactory().get(
            "/", HTTP_HOST="testserver", secure=True
        )

        self.assertEqual(
            safe_local_redirect_target(
                request, "http://testserver/inside", "/fallback/"
            ),
            "/fallback/",
        )

    def test_does_not_trust_unrecognized_request_host(self):
        request = RequestFactory().get("/", HTTP_HOST="evil.example")

        self.assertEqual(
            safe_local_redirect_target(
                request,
                "https://evil.example/phish",
                "/fallback/",
            ),
            "/fallback/",
        )


class WebviewRedirectSafetyTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "webview-v15", "Webview V15", User.Type.PERSON,
            password="pw", is_newuser=False,
        )

    def test_webview_redirects_only_to_safe_local_target(self):
        cases = (
            ("/inside?x=1", "/inside?x=1"),
            ("http://testserver/inside", "/"),
            ("//evil.example/phish", "/"),
            ("/\\evil.example/phish", "/"),
            ("https://evil.example/phish", "/"),
            ("javascript:alert(1)", "/"),
        )
        for target, expected in cases:
            with self.subTest(target=target):
                self.client.logout()
                query = urlencode({"ticket": "fresh", "to": target})
                with patch(
                    "generic.views.TicketAuthentication.authenticate",
                    return_value=(self.user, None),
                ):
                    response = self.client.get(f"/redirect/?{query}")
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], expected)
                self.assertEqual(
                    int(self.client.session["_auth_user_id"]), self.user.pk
                )

    def test_real_ticket_creates_one_session_only(self):
        ticket = create_webview_ticket(self.user.pk)
        query = urlencode({"ticket": ticket, "to": "/inside"})

        first = self.client.get(f"/redirect/?{query}")
        self.assertEqual(first.status_code, 302)
        self.assertEqual(first["Location"], "/inside")
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            self.user.pk,
        )

        self.client.logout()
        replay = self.client.get(f"/redirect/?{query}")
        self.assertEqual(replay.status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_webview_without_ticket_remains_bad_request(self):
        response = self.client.get("/redirect/?to=/inside")

        self.assertEqual(response.status_code, 400)
