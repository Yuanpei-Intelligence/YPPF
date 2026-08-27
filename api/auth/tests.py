import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from unittest.mock import patch

from django.core import signing
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework.test import APIClient

from app.models import NaturalPerson
from api.auth.binding import (
    BINDING_CREDENTIAL_PURPOSE,
    BINDING_CREDENTIAL_VERSION,
    BINDING_SIGNING_SALT,
    issue_binding_credential,
)
from api.config import CONFIG
from generic.models import (
    PendingWechatBinding,
    User,
    UserWechatProfile,
)


urlpatterns = [
    path("api/", include("api.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
]


def assert_api_error(testcase, response, expected_status, expected_code):
    """Assert the shared mini-program API error contract."""

    testcase.assertEqual(response.status_code, expected_status)
    payload = response.json()
    testcase.assertEqual(set(payload), {'code', 'message', 'errors'})
    testcase.assertEqual(payload['code'], expected_code)
    testcase.assertIsInstance(payload['message'], str)
    testcase.assertIsInstance(payload['errors'], dict)
    for field_errors in payload['errors'].values():
        testcase.assertIsInstance(field_errors, list)
        for item in field_errors:
            testcase.assertEqual(set(item), {'code', 'message'})
    return payload


def concurrent_bind(barrier, payload):
    close_old_connections()
    try:
        client = APIClient()
        barrier.wait()
        return client.post(
            "/api/v2/auth/wx/bind/", payload, format="json"
        ).status_code
    finally:
        close_old_connections()


def concurrent_post(barrier, path, payload):
    close_old_connections()
    try:
        client = APIClient()
        barrier.wait()
        return client.post(path, payload, format="json").status_code
    except Exception as exc:
        return exc
    finally:
        close_old_connections()


@override_settings(ROOT_URLCONF="api.auth.tests")
class WechatBindingSchemaTestCase(TestCase):
    def test_schema_describes_one_time_binding_credential(self):
        response = self.client.get(
            "/api/schema/",
            HTTP_ACCEPT="application/vnd.oai.openapi+json",
        )
        self.assertEqual(response.status_code, 200)
        schema = response.data
        login = schema["paths"]["/api/v2/auth/wx/login/"]["post"]
        bind = schema["paths"]["/api/v2/auth/wx/bind/"]["post"]

        for operation in (login, bind):
            self.assertIn("one-time", operation["description"])
            self.assertIn(
                "signed_openid_ttl_minutes",
                operation["description"],
            )
            self.assertIn("默认 5 次", operation["description"])

        login_properties = login["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["properties"]
        self.assertEqual(
            set(login_properties),
            {
                "status",
                "token",
                "token_type",
                "username",
                "name",
                "account_id",
                "signed_openid",
                "expires_in",
            },
        )
        bind_properties = bind["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["properties"]
        self.assertEqual(
            set(bind_properties),
            {
                "status",
                "token",
                "token_type",
                "username",
                "account_id",
                "expires_in",
            },
        )
        credential = schema["components"]["schemas"]["WxBind"][
            "properties"
        ]["signed_openid"]
        self.assertIn("One-time", credential["description"])


class WechatBindingIssuanceTestCase(TestCase):
    def test_issue_stores_only_nonce_digest_with_expiry(self):
        now = datetime(2026, 8, 17, 12, 0)
        with patch("api.auth.binding.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = now
            credential = issue_binding_credential("openid-v18")

        signed_payload = signing.TimestampSigner(
            salt=BINDING_SIGNING_SALT
        ).unsign(
            credential,
            max_age=CONFIG.signed_openid_ttl_minutes * 60,
        )
        payload = json.loads(signed_payload)
        self.assertEqual(payload["v"], BINDING_CREDENTIAL_VERSION)
        self.assertEqual(payload["purpose"], BINDING_CREDENTIAL_PURPOSE)
        nonce = payload["nonce"]
        pending = PendingWechatBinding.objects.get()
        self.assertEqual(pending.openid, "openid-v18")
        self.assertEqual(
            pending.nonce_digest,
            hashlib.sha256(nonce.encode()).hexdigest(),
        )
        self.assertNotEqual(pending.nonce_digest, nonce)
        self.assertNotIn(nonce, pending.openid)
        self.assertEqual(pending.failed_attempts, 0)
        self.assertEqual(
            pending.expires_at,
            now + timedelta(minutes=CONFIG.signed_openid_ttl_minutes),
        )

    def test_issue_cleans_expired_rows_and_keeps_unexpired_rows(self):
        now = datetime(2026, 8, 17, 12, 0)
        expired = PendingWechatBinding.objects.create(
            nonce_digest="e" * 64,
            openid="expired",
            expires_at=now - timedelta(seconds=1),
        )
        unexpired = PendingWechatBinding.objects.create(
            nonce_digest="u" * 64,
            openid="unexpired",
            expires_at=now + timedelta(seconds=1),
        )
        with patch("api.auth.binding.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = now
            issue_binding_credential("openid-v18")
        self.assertFalse(PendingWechatBinding.objects.filter(pk=expired.pk).exists())
        self.assertTrue(PendingWechatBinding.objects.filter(pk=unexpired.pk).exists())

    def test_issue_cleans_at_most_one_expired_batch(self):
        now = datetime(2026, 8, 17, 12, 0)
        batch_size = 100
        expired_digests = [
            f"{index:064x}" for index in range(batch_size + 1)
        ]
        PendingWechatBinding.objects.bulk_create(
            [
                PendingWechatBinding(
                    nonce_digest=nonce_digest,
                    openid=f"expired-{index}",
                    expires_at=now - timedelta(seconds=1),
                )
                for index, nonce_digest in enumerate(expired_digests)
            ]
        )

        with patch("api.auth.binding.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = now
            issue_binding_credential("openid-v18")

        remaining_expired = list(
            PendingWechatBinding.objects.filter(expires_at__lte=now)
            .order_by("nonce_digest")
            .values_list("nonce_digest", flat=True)
        )
        self.assertEqual(remaining_expired, [expired_digests[-1]])
        self.assertEqual(PendingWechatBinding.objects.count(), 2)
        self.assertTrue(
            PendingWechatBinding.objects.filter(openid="openid-v18").exists()
        )

    def test_issue_rolls_back_cleanup_when_creation_fails(self):
        now = datetime(2026, 8, 17, 12, 0)
        expired = PendingWechatBinding.objects.create(
            nonce_digest="e" * 64,
            openid="expired",
            expires_at=now - timedelta(seconds=1),
        )
        with patch("api.auth.binding.datetime") as mocked_datetime, patch(
            "api.auth.binding.PendingWechatBinding.objects.create",
            side_effect=RuntimeError("create failed"),
        ):
            mocked_datetime.now.return_value = now
            with self.assertRaisesRegex(RuntimeError, "create failed"):
                issue_binding_credential("openid-v18")
        self.assertTrue(PendingWechatBinding.objects.filter(pk=expired.pk).exists())


class WechatBindingApiTestCase(TestCase):
    def setUp(self):
        self.password = "valid-v18-password"
        self.user = User.objects.create_user(
            "v18-user", "V18 User", User.Type.PERSON,
            password=self.password, is_newuser=False,
        )
        NaturalPerson.objects.create(self.user, name="V18 User")

    def issue(self, openid="openid-v18"):
        with patch(
            "api.auth.views._fetch_openid_from_wechat",
            return_value=(openid, None),
        ):
            response = self.client.post(
                "/api/v2/auth/wx/login/", {"code": "fresh-code"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "unbound")
        return response.json()["signed_openid"]

    def bind(self, credential, username=None, password=None):
        return self.client.post("/api/v2/auth/wx/bind/", {
            "signed_openid": credential,
            "username": username or self.user.username,
            "password": password or self.password,
        })

    def test_forged_credential_is_rejected(self):
        assert_api_error(
            self,
            self.bind("forged"),
            400,
            'auth.binding_rejected',
        )

    def test_wrong_purpose_credential_is_rejected(self):
        nonce = "wrong-purpose-v18-nonce"
        PendingWechatBinding.objects.create(
            nonce_digest=hashlib.sha256(nonce.encode()).hexdigest(),
            openid="openid-v18-wrong-purpose",
            expires_at=datetime.now() + timedelta(minutes=10),
        )
        payload = json.dumps(
            {
                "v": BINDING_CREDENTIAL_VERSION,
                "purpose": "webview_ticket",
                "nonce": nonce,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        credential = signing.TimestampSigner(
            salt=BINDING_SIGNING_SALT
        ).sign(payload)

        response = self.bind(credential)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(PendingWechatBinding.objects.exists())
        self.assertFalse(UserWechatProfile.objects.exists())

    def test_expired_database_credential_is_deleted_and_rejected(self):
        credential = self.issue()
        fixed_now = datetime(2100, 1, 1, 12, 0)
        PendingWechatBinding.objects.update(
            expires_at=fixed_now - timedelta(seconds=1)
        )
        with patch("api.auth.binding.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = fixed_now
            response = self.bind(credential)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PendingWechatBinding.objects.exists())

    def test_expired_signature_is_rejected_while_database_row_is_fresh(self):
        credential = self.issue()
        PendingWechatBinding.objects.update(
            expires_at=datetime(2100, 1, 1, 12, 0)
        )
        signer_now = (
            time.time()
            + CONFIG.signed_openid_ttl_minutes * 60
            + 1
        )
        with patch(
            "django.core.signing.time.time",
            return_value=signer_now,
        ):
            response = self.bind(credential)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(PendingWechatBinding.objects.exists())
        self.assertFalse(UserWechatProfile.objects.exists())

    def test_success_consumes_credential_and_replay_fails(self):
        credential = self.issue()
        first = self.bind(credential)
        second = self.bind(credential)
        self.assertEqual(first.status_code, 200)
        payload = first.json()
        self.assertEqual(
            set(payload),
            {
                "status",
                "token",
                "token_type",
                "username",
                "account_id",
                "expires_in",
            },
        )
        self.assertEqual(payload["status"], "bound")
        self.assertEqual(payload["token_type"], "Bearer")
        self.assertEqual(payload["username"], self.user.username)
        self.assertEqual(payload["account_id"], self.user.username)
        self.assertEqual(
            payload["expires_in"],
            CONFIG.token_expire_minutes * 60,
        )
        token = AccessToken(payload["token"])
        self.assertEqual(token["sub"], str(self.user.pk))
        self.assertEqual(token["username"], self.user.username)
        self.assertEqual(token["name"], self.user.name)
        self.assertEqual(token["account_id"], self.user.username)
        self.assertEqual(token["scope"], "wx_miniapp")
        self.assertEqual(
            token["exp"] - token["iat"],
            CONFIG.token_expire_minutes * 60,
        )
        self.assertEqual(second.status_code, 400)
        self.assertFalse(PendingWechatBinding.objects.exists())
        self.assertEqual(UserWechatProfile.objects.get().openid, "openid-v18")

    def test_credential_issued_after_expired_cleanup_can_bind(self):
        expired = PendingWechatBinding.objects.create(
            nonce_digest="e" * 64,
            openid="expired-openid",
            expires_at=datetime.now() - timedelta(seconds=1),
        )

        credential = self.issue()
        response = self.bind(credential)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            PendingWechatBinding.objects.filter(pk=expired.pk).exists()
        )
        self.assertEqual(
            UserWechatProfile.objects.get(user=self.user).openid,
            "openid-v18",
        )

    def test_five_failed_passwords_exhaust_credential(self):
        credential = self.issue()
        for attempt in range(5):
            response = self.bind(credential, password="wrong-password")
            payload = assert_api_error(
                self,
                response,
                401,
                'auth.invalid_credentials',
            )
            self.assertIn('username', payload['errors'], attempt)
            self.assertIn('password', payload['errors'], attempt)
        pending = PendingWechatBinding.objects.get()
        self.assertEqual(pending.failed_attempts, 5)
        self.assertEqual(self.bind(credential).status_code, 400)
        self.assertFalse(UserWechatProfile.objects.exists())

    def test_reissue_preserves_openid_failures_and_lockout(self):
        first_credential = self.issue()
        for attempt in range(4):
            response = self.bind(
                first_credential,
                password="wrong-password",
            )
            self.assertEqual(response.status_code, 401, attempt)

        second_credential = self.issue()
        pending = PendingWechatBinding.objects.get()
        self.assertEqual(pending.failed_attempts, 4)
        self.assertEqual(self.bind(first_credential).status_code, 400)
        self.assertEqual(
            self.bind(
                second_credential,
                password="wrong-password",
            ).status_code,
            401,
        )

        with patch(
            "api.auth.views._fetch_openid_from_wechat",
            return_value=("openid-v18", None),
        ):
            blocked = self.client.post(
                "/api/v2/auth/wx/login/",
                {"code": "another-fresh-code"},
            )
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(PendingWechatBinding.objects.count(), 1)
        self.assertEqual(
            PendingWechatBinding.objects.get().failed_attempts,
            5,
        )
        self.assertEqual(self.bind(second_credential).status_code, 400)

    def test_failure_response_and_logs_do_not_disclose_secrets(self):
        openid = "openid-v18-log-secret"
        credential = self.issue(openid)
        password = "wrong-v18-log-secret-password"
        records = []

        class CaptureHandler(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = CaptureHandler()
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            response = self.bind(credential, password=password)
        finally:
            root_logger.removeHandler(handler)

        self.assertEqual(response.status_code, 401)
        observed = response.content.decode() + "\n" + "\n".join(
            record.getMessage() for record in records
        )
        self.assertNotIn(openid, observed)
        self.assertNotIn(credential, observed)
        self.assertNotIn(password, observed)

    def test_existing_profile_is_not_rebound(self):
        UserWechatProfile.objects.create(
            user=self.user,
            openid="existing-openid",
        )
        credential = self.issue("new-openid")
        self.assertEqual(self.bind(credential).status_code, 400)
        self.assertEqual(self.user.wx_profile.openid, "existing-openid")

    def test_organization_account_is_rejected(self):
        organization_user = User.objects.create_user(
            "v18-org",
            "V18 Organization",
            User.Type.ORG,
            password=self.password,
            is_newuser=False,
        )
        credential = self.issue("openid-v18-org")
        response = self.bind(
            credential,
            username=organization_user.username,
        )
        payload = assert_api_error(
            self,
            response,
            400,
            'auth.binding_rejected',
        )
        self.assertIn("username", payload['errors'])
        self.assertTrue(PendingWechatBinding.objects.exists())
        self.assertFalse(UserWechatProfile.objects.exists())

    def test_unsupported_account_type_is_rejected(self):
        unsupported_user = User.objects.create_user(
            "v18-special",
            "V18 Special",
            User.Type.SPECIAL,
            password=self.password,
            is_newuser=False,
        )
        credential = self.issue("openid-v18-special")
        response = self.bind(
            credential,
            username=unsupported_user.username,
        )
        payload = assert_api_error(
            self,
            response,
            400,
            'auth.binding_rejected',
        )
        self.assertIn("username", payload['errors'])
        self.assertTrue(PendingWechatBinding.objects.exists())
        self.assertFalse(UserWechatProfile.objects.exists())

    def test_openid_bound_after_issuance_is_rejected_and_consumed(self):
        openid = "openid-v18-prebound"
        credential = self.issue(openid)
        other_user = User.objects.create_user(
            "v18-prebound-user",
            "Prebound",
            User.Type.PERSON,
            password=self.password,
            is_newuser=False,
        )
        NaturalPerson.objects.create(other_user, name="Prebound")
        UserWechatProfile.objects.create(
            user=other_user,
            openid=openid,
        )
        response = self.bind(credential)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(UserWechatProfile.objects.count(), 1)
        self.assertEqual(UserWechatProfile.objects.get().user, other_user)
        self.assertFalse(PendingWechatBinding.objects.exists())


class WechatBindingConcurrencyTestCase(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.password = "valid-v18-password"
        self.user = User.objects.create_user(
            "v18-race-a", "V18 Race A", User.Type.PERSON,
            password=self.password, is_newuser=False,
        )
        NaturalPerson.objects.create(self.user, name="V18 Race A")
        self.other_user = User.objects.create_user(
            "v18-race-b", "V18 Race B", User.Type.PERSON,
            password=self.password, is_newuser=False,
        )
        NaturalPerson.objects.create(self.other_user, name="V18 Race B")

    def issue(self, openid):
        with patch(
            "api.auth.views._fetch_openid_from_wechat",
            return_value=(openid, None),
        ):
            response = APIClient().post(
                "/api/v2/auth/wx/login/",
                {"code": "fresh-code"},
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        return response.json()["signed_openid"]

    def run_race(self, credential, usernames):
        barrier = Barrier(2)
        payloads = [
            {
                "signed_openid": credential,
                "username": username,
                "password": self.password,
            }
            for username in usernames
        ]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(concurrent_bind, barrier, payload)
                for payload in payloads
            ]
        return [future.result() for future in futures]

    def run_request_race(self, requests):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    concurrent_post,
                    barrier,
                    path,
                    payload,
                )
                for path, payload in requests
            ]
        return [future.result() for future in futures]

    def run_profile_create_race(self, requests):
        create_barrier = Barrier(2, timeout=10)
        create_profile = UserWechatProfile.objects.create

        def synchronized_create(*args, **kwargs):
            create_barrier.wait()
            return create_profile(*args, **kwargs)

        with patch(
            "api.auth.binding.UserWechatProfile.objects.create",
            side_effect=synchronized_create,
        ):
            return self.run_request_race(requests)

    def assert_single_winner(self, statuses, openid):
        self.assertEqual(statuses.count(200), 1)
        self.assertNotIn(500, statuses)
        self.assertEqual(
            UserWechatProfile.objects.filter(openid=openid).count(), 1
        )
        self.assertFalse(PendingWechatBinding.objects.exists())

    def test_same_user_same_credential_has_one_winner(self):
        openid = "openid-v18-race-same"
        credential = self.issue(openid)
        statuses = self.run_race(
            credential, [self.user.username, self.user.username]
        )
        self.assert_single_winner(statuses, openid)

    def test_different_users_same_credential_have_one_winner(self):
        openid = "openid-v18-race-different"
        credential = self.issue(openid)
        statuses = self.run_race(
            credential, [self.user.username, self.other_user.username]
        )
        self.assert_single_winner(statuses, openid)

    def test_distinct_credentials_same_openid_have_one_winner(self):
        openid = "openid-v18-race-shared-openid"
        credentials = [self.issue(openid), self.issue(openid)]
        requests = [
            (
                "/api/v2/auth/wx/bind/",
                {
                    "signed_openid": credentials[0],
                    "username": self.user.username,
                    "password": self.password,
                },
            ),
            (
                "/api/v2/auth/wx/bind/",
                {
                    "signed_openid": credentials[1],
                    "username": self.other_user.username,
                    "password": self.password,
                },
            ),
        ]
        outcomes = self.run_request_race(requests)
        self.assertCountEqual(outcomes, [200, 400])
        self.assertEqual(UserWechatProfile.objects.count(), 1)
        self.assertEqual(UserWechatProfile.objects.get().openid, openid)
        self.assertFalse(PendingWechatBinding.objects.exists())

    def test_concurrent_issuance_shares_one_openid_ledger(self):
        openid = "openid-v18-race-issuance"
        requests = [
            (
                "/api/v2/auth/wx/login/",
                {"code": f"issuer-code-{index}"},
            )
            for index in range(2)
        ]
        with patch(
            "api.auth.views._fetch_openid_from_wechat",
            return_value=(openid, None),
        ):
            outcomes = self.run_request_race(requests)

        self.assertEqual(outcomes, [200, 200])
        pending = PendingWechatBinding.objects.get(openid=openid)
        self.assertEqual(pending.failed_attempts, 0)

    def test_distinct_openids_same_user_have_one_winner(self):
        openids = (
            "openid-v18-race-user-first",
            "openid-v18-race-user-second",
        )
        credentials = [self.issue(openid) for openid in openids]
        requests = [
            (
                "/api/v2/auth/wx/bind/",
                {
                    "signed_openid": credential,
                    "username": self.user.username,
                    "password": self.password,
                },
            )
            for credential in credentials
        ]
        outcomes = self.run_profile_create_race(requests)
        self.assertCountEqual(outcomes, [200, 400])
        self.assertEqual(UserWechatProfile.objects.count(), 1)
        self.assertIn(UserWechatProfile.objects.get().openid, openids)
        self.assertFalse(PendingWechatBinding.objects.exists())

    def test_expired_redemption_racing_issuance_has_controlled_outcomes(self):
        for attempt in range(25):
            expired_openid = f"openid-v18-expired-race-{attempt}"
            credential = self.issue(expired_openid)
            PendingWechatBinding.objects.filter(
                openid=expired_openid
            ).update(expires_at=datetime.now() - timedelta(seconds=1))
            issuer_openid = f"openid-v18-issuer-race-{attempt}"
            requests = [
                (
                    "/api/v2/auth/wx/login/",
                    {"code": f"issuer-code-{attempt}"},
                ),
                (
                    "/api/v2/auth/wx/bind/",
                    {
                        "signed_openid": credential,
                        "username": self.user.username,
                        "password": self.password,
                    },
                ),
            ]
            with patch(
                "api.auth.views._fetch_openid_from_wechat",
                return_value=(issuer_openid, None),
            ):
                outcomes = self.run_request_race(requests)
            self.assertEqual(outcomes, [200, 400], (attempt, outcomes))
            PendingWechatBinding.objects.all().delete()
