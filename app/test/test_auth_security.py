from urllib.parse import urlencode

from django.conf import settings
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.template.loader import render_to_string
from django.test import (
    Client,
    RequestFactory,
    TestCase,
    override_settings,
)
from django.urls import include, path

from app.models import (
    NaturalPerson,
    Organization,
    OrganizationType,
    Position,
)
from generic.models import User
from utils.hasher import MyMD5Hasher


def csrf_sidebar(request):
    return render(
        request,
        "user_left_navbar.html",
        {"bar_display": {}},
    )


urlpatterns = [
    path("_test/csrf-sidebar/", csrf_sidebar),
    path("", include("boot.urls")),
]


@override_settings(ROOT_URLCONF="app.test.test_auth_security")
class LegacyMiniLoginRemovalTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "valid-password"
        cls.user = User.objects.create_user(
            "v14-user", "V14 User", User.Type.PERSON,
            password=cls.password, is_newuser=False,
        )
        cls.person = NaturalPerson.objects.create(cls.user, name="V14 User")
        cls.organization_type = OrganizationType.objects.create(
            otype_id=14015,
            otype_name="V14 Security Test",
            incharge=cls.person,
            job_name_list=["负责人", "成员"],
        )
        cls.organization_user = User.objects.create_user(
            "v14-org",
            "V14 Organization",
            User.Type.ORG,
            password=cls.password,
            is_newuser=False,
        )
        cls.organization = Organization.objects.create(
            organization_id=cls.organization_user,
            oname="V14 Review Org",
            otype=cls.organization_type,
        )
        Position.objects.create(
            person=cls.person,
            org=cls.organization,
            pos=0,
            is_admin=True,
        )

    def login_person(self, client=None):
        client = client or self.client
        client.force_login(self.user)
        session = client.session
        session["NP"] = self.user.username
        session["Incharge"] = [self.organization.oname]
        session.save()
        return client

    def csrf_client(self):
        client = self.login_person(Client(enforce_csrf_checks=True))
        response = client.get("/_test/csrf-sidebar/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(settings.CSRF_COOKIE_NAME, response.cookies)
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        return client, token

    def render_sidebar(self, template_name, session):
        request = RequestFactory().get("/")
        request.user = self.user
        request.session = session
        get_token(request)
        return render_to_string(
            template_name,
            {"bar_display": {}},
            request=request,
        )

    def test_old_predictable_token_cannot_create_session(self):
        token = MyMD5Hasher("wechat_login").encode(self.user.username)
        payload = {
            "username": self.user.username,
            "password": self.password,
            "secret_token": token,
        }
        for path in ("/minilogin", "/yppf/minilogin"):
            with self.subTest(path=path):
                self.client.logout()
                response = self.client.post(path, payload)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_redirects_only_to_safe_local_target(self):
        cases = (
            ("/inside?x=1", "/inside?x=1"),
            ("http://testserver/inside", "/welcome/"),
            ("//evil.example/phish", "/welcome/"),
            ("/\\evil.example/phish", "/welcome/"),
            ("https://evil.example/phish", "/welcome/"),
        )
        for target, expected in cases:
            with self.subTest(target=target):
                self.client.logout()
                query = urlencode({"origin": target})
                response = self.client.post(
                    f"/login/?{query}",
                    {"username": self.user.username, "password": self.password},
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], expected)

    def test_account_switch_redirects_only_to_safe_local_target(self):
        cases = (
            ("/inside", "/inside"),
            ("http://testserver/inside", "/welcome/"),
            ("//evil.example/phish", "/welcome/"),
            ("/\\evil.example/phish", "/welcome/"),
            ("https://evil.example/phish", "/welcome/"),
        )
        for target, expected in cases:
            with self.subTest(target=target):
                self.login_person()
                response = self.client.post(
                    "/shiftAccount/",
                    {"origin": target},
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], expected)

    def test_get_account_switch_does_not_change_principal(self):
        self.login_person()

        response = self.client.get(
            "/shiftAccount/",
            {"oname": self.organization.oname},
        )

        self.assertEqual(response.status_code, 405)
        self.assertEqual(
            self.client.session["_auth_user_id"],
            str(self.user.pk),
        )

    def test_account_switch_rejects_post_without_csrf(self):
        client = self.login_person(Client(enforce_csrf_checks=True))

        response = client.post(
            "/shiftAccount/",
            {"oname": self.organization.oname},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(client.session["_auth_user_id"], str(self.user.pk))

    def test_account_switch_accepts_csrf_protected_post(self):
        client, token = self.csrf_client()

        response = client.post(
            "/shiftAccount/",
            {
                "oname": self.organization.oname,
                "origin": "/inside",
                "csrfmiddlewaretoken": token,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/inside")
        self.assertEqual(
            client.session["_auth_user_id"],
            str(self.organization_user.pk),
        )

    def test_sidebars_render_account_switches_as_csrf_post_forms(self):
        user_sidebar = self.render_sidebar(
            "user_left_navbar.html",
            {"Incharge": [self.organization.oname]},
        )
        organization_sidebar = self.render_sidebar(
            "org_left_navbar.html",
            {
                "NP": self.user.username,
                "Incharge": [self.organization.oname],
            },
        )

        self.assertEqual(user_sidebar.count('action="/shiftAccount/"'), 1)
        self.assertEqual(organization_sidebar.count('action="/shiftAccount/"'), 2)
        for sidebar in (user_sidebar, organization_sidebar):
            self.assertNotIn("/shiftAccount/?oname=", sidebar)
            self.assertIn('method="post"', sidebar)
            self.assertIn('name="csrfmiddlewaretoken"', sidebar)
            self.assertIn(
                f'name="oname" value="{self.organization.oname}"',
                sidebar,
            )
