"""
Tests of the IAAA / portal clients. Every HTTP call is mocked at
``requests.Session.post`` / ``requests.Session.get``; nothing reaches
pku.edu.cn.
"""
from datetime import date
from unittest.mock import patch

import requests
from django.test import SimpleTestCase

from pku_account.extern import iaaa, portal
from pku_account.extern.iaaa import (
    CaptchaRequired,
    IaaaError,
    OtpRequired,
    PortalUnreachable,
    classify_iaaa_error,
    iaaa_login,
)
from pku_account.extern.portal import (
    PORTAL_COURSE_URL,
    PORTAL_SCORE_URL,
    PortalClient,
    PortalSessionExpired,
    guess_term_code,
)

USERNAME = '2100010001'
PASSWORD = 'S3cret-Pa55!'
LOGIN_PAGE = '<html><title>北京大学统一身份认证</title></html>'


class FakeResponse:
    """The subset of ``requests.Response`` used by the clients."""

    def __init__(self, *, status_code=200, json_data=None, text='', url=''):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.url = url
        self.history = []

    def json(self):
        if self._json is None:
            raise requests.exceptions.JSONDecodeError(
                'Expecting value', self.text, 0,
            )
        return self._json


def _iaaa_failure(msg, code='E01'):
    return FakeResponse(
        json_data={'success': False, 'errors': {'code': code, 'msg': msg}},
    )


class IaaaLoginTests(SimpleTestCase):
    def test_success_posts_expected_form_and_returns_token(self):
        seen = {}

        def fake_post(session, url, data=None, **kwargs):
            seen.update(url=url, data=data, **kwargs)
            return FakeResponse(json_data={'success': True, 'token': 'tok-1'})

        with patch.object(
            requests.Session, 'post', autospec=True, side_effect=fake_post,
        ):
            token = iaaa_login(iaaa.new_session(), USERNAME, PASSWORD,
                               timeout=7)

        self.assertEqual(token, 'tok-1')
        self.assertEqual(seen['url'], iaaa.IAAA_LOGIN_URL)
        self.assertEqual(seen['data']['appid'], 'portal2017')
        self.assertEqual(seen['data']['userName'], USERNAME)
        self.assertEqual(seen['data']['password'], PASSWORD)
        self.assertEqual(seen['data']['redirUrl'], iaaa.PORTAL_SSO)
        self.assertEqual(seen['timeout'], 7)
        referer = seen['headers']['Referer']
        self.assertTrue(referer.startswith(iaaa.IAAA_OAUTH_URL + '?'))
        self.assertIn('appID=portal2017', referer)
        # Header values must stay latin-1 encodable.
        referer.encode('latin-1')

    def test_wrong_password_raises_iaaa_error_without_secrets(self):
        with patch.object(
            requests.Session, 'post', autospec=True,
            return_value=_iaaa_failure('用户名或密码错误'),
        ):
            with self.assertLogs('pku_account.extern.iaaa', level='DEBUG') \
                    as logs, self.assertRaises(IaaaError) as ctx:
                iaaa_login(iaaa.new_session(), USERNAME, PASSWORD)

        error = ctx.exception
        self.assertEqual(error.code, 'E01')
        self.assertEqual(error.msg, '用户名或密码错误')
        self.assertNotIsInstance(error, (OtpRequired, CaptchaRequired))
        self.assertNotIn(PASSWORD, str(error))
        joined = '\n'.join(logs.output)
        self.assertNotIn(PASSWORD, joined)
        self.assertNotIn(USERNAME, joined)

    def test_captcha_and_otp_messages_are_classified(self):
        self.assertIsInstance(
            classify_iaaa_error('E02', '请输入验证码'), CaptchaRequired)
        self.assertIsInstance(
            classify_iaaa_error('E03', '需要进行二次验证'), OtpRequired)
        self.assertIsInstance(
            classify_iaaa_error('E04', '请输入短信验证码'), OtpRequired)
        self.assertIsInstance(
            classify_iaaa_error('E05', 'OTP code required'), OtpRequired)
        self.assertIsInstance(
            classify_iaaa_error('E06', '已开启双因素认证'), OtpRequired)
        plain = classify_iaaa_error('E01', '用户名或密码错误')
        self.assertIs(type(plain), IaaaError)

    def test_captcha_response_raises_captcha_required(self):
        with patch.object(
            requests.Session, 'post', autospec=True,
            return_value=_iaaa_failure('请输入验证码', code='E02'),
        ):
            with self.assertRaises(CaptchaRequired):
                iaaa_login(iaaa.new_session(), USERNAME, PASSWORD)

    def test_otp_response_raises_otp_required(self):
        with patch.object(
            requests.Session, 'post', autospec=True,
            return_value=_iaaa_failure('请进行二次验证', code='E03'),
        ):
            with self.assertRaises(OtpRequired):
                iaaa_login(iaaa.new_session(), USERNAME, PASSWORD)

    def test_network_failure_is_unreachable(self):
        for exc in (requests.ConnectionError('boom'), requests.Timeout('slow')):
            with self.subTest(exc=type(exc).__name__):
                with patch.object(
                    requests.Session, 'post', autospec=True, side_effect=exc,
                ):
                    with self.assertRaises(PortalUnreachable):
                        iaaa_login(iaaa.new_session(), USERNAME, PASSWORD)

    def test_server_error_is_unreachable(self):
        with patch.object(
            requests.Session, 'post', autospec=True,
            return_value=FakeResponse(status_code=502, text='bad gateway'),
        ):
            with self.assertRaises(PortalUnreachable):
                iaaa_login(iaaa.new_session(), USERNAME, PASSWORD)

    def test_non_json_answer_is_iaaa_error(self):
        with patch.object(
            requests.Session, 'post', autospec=True,
            return_value=FakeResponse(text=LOGIN_PAGE),
        ):
            with self.assertRaises(IaaaError) as ctx:
                iaaa_login(iaaa.new_session(), USERNAME, PASSWORD)
        self.assertEqual(ctx.exception.code, 'BAD_RESPONSE')


class PortalClientTests(SimpleTestCase):
    def test_login_establishes_portal_session(self):
        seen = {}

        def fake_get(session, url, **kwargs):
            seen.update(url=url, params=kwargs.get('params'))
            # What the SSO redirect chain leaves behind: the portal session
            # plus IAAA's own cookie, which must not be persisted.
            session.cookies.set('JSESSIONID', 'portal-session',
                                domain='portal.pku.edu.cn', path='/')
            session.cookies.set('iaaa_sid', 'iaaa-cookie',
                                domain='iaaa.pku.edu.cn', path='/')
            return FakeResponse(url=portal.PORTAL_BASE + '/index.jsp',
                                text='<html>portal</html>')

        with patch.object(
            requests.Session, 'post', autospec=True,
            return_value=FakeResponse(
                json_data={'success': True, 'token': 'tok-1'}),
        ), patch.object(
            requests.Session, 'get', autospec=True, side_effect=fake_get,
        ):
            client = PortalClient.login(USERNAME, PASSWORD)

        self.assertEqual(seen['url'], iaaa.PORTAL_SSO)
        self.assertEqual(seen['params']['token'], 'tok-1')
        self.assertIn('_rand', seen['params'])
        self.assertEqual(client.cookies(), {'JSESSIONID': 'portal-session'})

    def test_login_without_portal_cookie_is_unreachable(self):
        with patch.object(
            requests.Session, 'post', autospec=True,
            return_value=FakeResponse(
                json_data={'success': True, 'token': 'tok-1'}),
        ), patch.object(
            requests.Session, 'get', autospec=True,
            return_value=FakeResponse(url=portal.PORTAL_BASE + '/index.jsp'),
        ):
            with self.assertRaises(PortalUnreachable):
                PortalClient.login(USERNAME, PASSWORD)

    def test_login_propagates_iaaa_error_before_sso(self):
        with patch.object(
            requests.Session, 'post', autospec=True,
            return_value=_iaaa_failure('用户名或密码错误'),
        ), patch.object(requests.Session, 'get', autospec=True) as get:
            with self.assertRaises(IaaaError):
                PortalClient.login(USERNAME, PASSWORD)
        get.assert_not_called()

    def test_from_cookies_roundtrip(self):
        cookies = {'JSESSIONID': 'abc', 'route': 'r1'}
        self.assertEqual(PortalClient.from_cookies(cookies).cookies(), cookies)

    def test_get_course_info_returns_json(self):
        payload = {'success': True, 'remark': '', 'course': []}
        seen = {}

        def fake_get(session, url, **kwargs):
            seen.update(url=url, params=kwargs.get('params'))
            return FakeResponse(json_data=payload, url=url)

        with patch.object(
            requests.Session, 'get', autospec=True, side_effect=fake_get,
        ):
            client = PortalClient.from_cookies({'JSESSIONID': 'abc'})
            self.assertEqual(client.get_course_info('26-27-1'), payload)
        self.assertEqual(seen['url'], PORTAL_COURSE_URL)
        self.assertEqual(seen['params'], {'xndxq': '26-27-1'})

    def test_get_scores_returns_json(self):
        payload = {'cjxx': []}
        seen = {}

        def fake_get(session, url, **kwargs):
            seen.update(url=url, params=kwargs.get('params'))
            return FakeResponse(json_data=payload, url=url)

        with patch.object(
            requests.Session, 'get', autospec=True, side_effect=fake_get,
        ):
            client = PortalClient.from_cookies({'JSESSIONID': 'abc'})
            self.assertEqual(client.get_scores(), payload)
        self.assertEqual(seen['url'], PORTAL_SCORE_URL)
        self.assertIsNone(seen['params'])

    def test_html_login_page_means_session_expired(self):
        with patch.object(
            requests.Session, 'get', autospec=True,
            return_value=FakeResponse(text=LOGIN_PAGE, url=PORTAL_COURSE_URL),
        ):
            client = PortalClient.from_cookies({'JSESSIONID': 'stale'})
            with self.assertRaises(PortalSessionExpired):
                client.get_course_info('26-27-1')
            with self.assertRaises(PortalSessionExpired):
                client.get_scores()
            self.assertFalse(client.ping('26-27-1'))

    def test_redirect_to_iaaa_means_session_expired(self):
        redirected = FakeResponse(
            json_data={'unexpected': True},
            url='https://iaaa.pku.edu.cn/iaaa/oauth.jsp?appID=portal2017',
        )
        with patch.object(
            requests.Session, 'get', autospec=True, return_value=redirected,
        ):
            client = PortalClient.from_cookies({'JSESSIONID': 'stale'})
            with self.assertRaises(PortalSessionExpired):
                client.get_course_info('26-27-1')

    def test_network_failure_is_unreachable_and_ping_is_false(self):
        with patch.object(
            requests.Session, 'get', autospec=True,
            side_effect=requests.ConnectionError('boom'),
        ):
            client = PortalClient.from_cookies({'JSESSIONID': 'abc'})
            with self.assertRaises(PortalUnreachable):
                client.get_scores()
            self.assertFalse(client.ping())

    def test_server_error_is_unreachable(self):
        with patch.object(
            requests.Session, 'get', autospec=True,
            return_value=FakeResponse(status_code=503, url=PORTAL_SCORE_URL),
        ):
            client = PortalClient.from_cookies({'JSESSIONID': 'abc'})
            with self.assertRaises(PortalUnreachable):
                client.get_scores()

    def test_ping_true_when_portal_answers_json(self):
        with patch.object(
            requests.Session, 'get', autospec=True,
            return_value=FakeResponse(json_data={'success': True},
                                      url=PORTAL_COURSE_URL),
        ):
            client = PortalClient.from_cookies({'JSESSIONID': 'abc'})
            self.assertTrue(client.ping())

    def test_guess_term_code(self):
        self.assertEqual(guess_term_code(date(2026, 9, 9)), '26-27-1')
        self.assertEqual(guess_term_code(date(2027, 1, 5)), '26-27-1')
        self.assertEqual(guess_term_code(date(2027, 3, 1)), '26-27-2')
        self.assertEqual(guess_term_code(date(2027, 7, 15)), '26-27-3')
