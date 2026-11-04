"""
Tests of the IAAA / portal clients. Every HTTP call is mocked at
``requests.Session.post`` / ``requests.Session.get``; nothing reaches
pku.edu.cn.
"""
from unittest.mock import patch
from urllib.parse import urlencode

import requests
from django.test import SimpleTestCase

from pku_account.extern import iaaa, portal
from pku_account.extern.iaaa import (
    CaptchaRequired,
    IaaaError,
    OtpRequired,
    PortalUnreachable,
    check_second_factor,
    classify_iaaa_error,
    iaaa_login,
)
from pku_account.extern.portal import (
    PORTAL_COURSE_URL,
    PORTAL_SCORE_URL,
    PORTAL_TERMS_URL,
    PortalClient,
    PortalSessionExpired,
)

USERNAME = '2100010001'
PASSWORD = 'S3cret-Pa55!'
LOGIN_PAGE = '<html><title>北京大学统一身份认证</title></html>'
NO_SECOND_FACTOR = {'success': True, 'authenMode': '否', 'isMobileAuthen': False}
# The public-query application verified with a real account on 2026-09-10.
PUBLIC_QUERY = 'https://portal.pku.edu.cn/publicQuery'


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
        self.assertEqual(seen['data']['appid'], 'portalPublicQuery')
        self.assertEqual(seen['data']['userName'], USERNAME)
        self.assertEqual(seen['data']['password'], PASSWORD)
        self.assertEqual(seen['data']['redirUrl'], f'{PUBLIC_QUERY}/ssoLogin.do')
        self.assertEqual(iaaa.PORTAL_SSO, f'{PUBLIC_QUERY}/ssoLogin.do')
        self.assertEqual(seen['timeout'], 7)
        referer = seen['headers']['Referer']
        self.assertTrue(referer.startswith(iaaa.IAAA_OAUTH_URL + '?'))
        self.assertIn('appID=portalPublicQuery', referer)
        self.assertIn(urlencode({'appName': '校内信息门户公共查询'}), referer)
        # Header values must stay latin-1 encodable.
        referer.encode('latin-1')

    def test_another_application(self):
        seen = {}

        def fake_post(session, url, data=None, **kwargs):
            seen.update(data=data, **kwargs)
            return FakeResponse(json_data={'success': True, 'token': 'tok-2'})

        redir = 'http://elective.pku.edu.cn:80/elective2008/ssoLogin.do'
        with patch.object(
            requests.Session, 'post', autospec=True, side_effect=fake_post,
        ):
            token = iaaa_login(iaaa.new_session(), USERNAME, PASSWORD,
                               appid='syllabus', redir_url=redir,
                               app_name='学生选课系统')

        self.assertEqual(token, 'tok-2')
        self.assertEqual((seen['data']['appid'], seen['data']['redirUrl']),
                         ('syllabus', redir))
        referer = seen['headers']['Referer']
        self.assertIn('appID=syllabus', referer)
        self.assertIn(urlencode({'appName': '学生选课系统'}), referer)
        self.assertIn(urlencode({'redirectUrl': redir}), referer)

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


class SecondFactorPrecheckTests(SimpleTestCase):
    def test_no_second_factor_passes_and_sends_expected_query(self):
        seen = {}

        def fake_get(session, url, **kwargs):
            seen.update(url=url, params=kwargs.get('params'),
                        timeout=kwargs.get('timeout'))
            return FakeResponse(json_data=NO_SECOND_FACTOR)

        with patch.object(
            requests.Session, 'get', autospec=True, side_effect=fake_get,
        ):
            self.assertEqual(check_second_factor(
                iaaa.new_session(), 'portalPublicQuery', USERNAME, timeout=3), '否')

        self.assertEqual(seen['url'], 'https://iaaa.pku.edu.cn/iaaa/isMobileAuthen.do')
        self.assertEqual(seen['params']['appId'], 'portalPublicQuery')
        self.assertEqual(seen['params']['userName'], USERNAME)
        self.assertIn('_rand', seen['params'])
        self.assertEqual(seen['timeout'], 3)

    def test_another_mode_is_logged_not_raised(self):
        # Advisory until the meaning of the modes is verified from the campus
        # server: the login request decides whether a second factor is needed.
        with patch.object(
            requests.Session, 'get', autospec=True,
            return_value=FakeResponse(
                json_data={'success': True, 'authenMode': 'OTP'}),
        ):
            with self.assertLogs('pku_account.extern.iaaa', level='INFO') as logs:
                mode = check_second_factor(iaaa.new_session(), 'syllabus', USERNAME)
        self.assertEqual(mode, 'OTP')
        self.assertIn('second factor', '\n'.join(logs.output))
        self.assertNotIn(USERNAME, '\n'.join(logs.output))

    def test_unusable_answers_are_ignored(self):
        answers = [
            FakeResponse(text=LOGIN_PAGE),
            FakeResponse(json_data={'success': True}),
            FakeResponse(json_data={'success': True, 'authenMode': ' '}),
            FakeResponse(json_data=['OTP']),
            requests.ConnectionError('boom'),
        ]
        for answer in answers:
            with self.subTest(answer=repr(getattr(answer, '_json', answer))):
                if isinstance(answer, Exception):
                    mocked = {'side_effect': answer}
                else:
                    mocked = {'return_value': answer}
                with patch.object(requests.Session, 'get', autospec=True,
                                  **mocked):
                    self.assertIsNone(check_second_factor(
                        iaaa.new_session(), 'portalPublicQuery', USERNAME))


class PortalClientTests(SimpleTestCase):
    def test_login_establishes_portal_session(self):
        calls = []
        posted = {}

        def fake_post(session, url, data=None, **kwargs):
            posted.update(data)
            return FakeResponse(json_data={'success': True, 'token': 'tok-1'})

        def fake_get(session, url, **kwargs):
            calls.append((url, kwargs.get('params')))
            if url == iaaa.IAAA_AUTHEN_MODE_URL:
                return FakeResponse(json_data=NO_SECOND_FACTOR)
            # What the SSO redirect chain leaves behind: the portal session
            # plus IAAA's own cookie, which must not be persisted.
            session.cookies.set('JSESSIONID', 'portal-session',
                                domain='portal.pku.edu.cn', path='/')
            session.cookies.set('iaaa_sid', 'iaaa-cookie',
                                domain='iaaa.pku.edu.cn', path='/')
            return FakeResponse(url=portal.PORTAL_BASE + '/',
                                text='<html>portal</html>')

        with patch.object(
            requests.Session, 'post', autospec=True, side_effect=fake_post,
        ), patch.object(
            requests.Session, 'get', autospec=True, side_effect=fake_get,
        ):
            client = PortalClient.login(USERNAME, PASSWORD)

        self.assertEqual([url for url, _ in calls],
                         [iaaa.IAAA_AUTHEN_MODE_URL, f'{PUBLIC_QUERY}/ssoLogin.do'])
        self.assertEqual(calls[0][1]['appId'], 'portalPublicQuery')
        self.assertEqual(calls[1][1]['token'], 'tok-1')
        self.assertIn('_rand', calls[1][1])
        self.assertEqual(posted['appid'], 'portalPublicQuery')
        self.assertEqual(client.cookies(), {'JSESSIONID': 'portal-session'})

    def test_precheck_second_factor_is_advisory_and_iaaa_decides(self):
        with patch.object(
            requests.Session, 'post', autospec=True,
            return_value=_iaaa_failure('请输入手机令牌二次验证码'),
        ) as post, patch.object(
            requests.Session, 'get', autospec=True,
            return_value=FakeResponse(
                json_data={'success': True, 'authenMode': 'OTP'}),
        ):
            with self.assertRaises(OtpRequired):
                PortalClient.login(USERNAME, PASSWORD)
        post.assert_called_once()

    def test_login_without_portal_cookie_is_unreachable(self):
        with patch.object(
            requests.Session, 'post', autospec=True,
            return_value=FakeResponse(
                json_data={'success': True, 'token': 'tok-1'}),
        ), patch.object(
            requests.Session, 'get', autospec=True,
            return_value=FakeResponse(url=portal.PORTAL_BASE + '/'),
        ):
            with self.assertRaises(PortalUnreachable):
                PortalClient.login(USERNAME, PASSWORD)

    def test_login_propagates_iaaa_error_before_sso(self):
        with patch.object(
            requests.Session, 'post', autospec=True,
            return_value=_iaaa_failure('用户名或密码错误'),
        ), patch.object(
            requests.Session, 'get', autospec=True,
            return_value=FakeResponse(json_data=NO_SECOND_FACTOR),
        ) as get:
            with self.assertRaises(IaaaError):
                PortalClient.login(USERNAME, PASSWORD)
        self.assertEqual([call.args[1] for call in get.call_args_list],
                         [iaaa.IAAA_AUTHEN_MODE_URL])

    def test_from_cookies_roundtrip(self):
        cookies = {'JSESSIONID': 'abc', 'route': 'r1'}
        self.assertEqual(PortalClient.from_cookies(cookies).cookies(), cookies)

    def test_export_keeps_cookie_paths(self):
        # publicQuery's SSO leaves JSESSIONID at "/" and at "/publicQuery"
        # (verified with a real account on 2026-09-10); both must survive.
        client = PortalClient()
        client._session.cookies.set('JSESSIONID', 'root-session', domain='portal.pku.edu.cn', path='/')
        client._session.cookies.set('JSESSIONID', 'pq-session', domain='portal.pku.edu.cn',
                                    path='/publicQuery')
        client._session.cookies.set('iaaa_sid', 'x', domain='iaaa.pku.edu.cn', path='/')
        exported = client.export_cookies()
        self.assertEqual(
            sorted((item['name'], item['value'], item['path']) for item in exported),
            [('JSESSIONID', 'pq-session', '/publicQuery'), ('JSESSIONID', 'root-session', '/')])

        restored = PortalClient.from_cookies(exported)
        jar = restored._session.cookies
        self.assertEqual(
            sorted((cookie.value, cookie.path) for cookie in jar if cookie.name == 'JSESSIONID'),
            [('pq-session', '/publicQuery'), ('root-session', '/')])
        # A request to a publicQuery endpoint carries the publicQuery session.
        request = requests.Request('GET', portal.PORTAL_COURSE_URL).prepare()
        jar_header = requests.cookies.get_cookie_header(jar, request)
        self.assertIn('JSESSIONID=pq-session', jar_header)

    def test_from_cookies_skips_malformed_items(self):
        restored = PortalClient.from_cookies([{'name': '', 'value': 'x'}, 'junk',
                                              {'name': 'route', 'value': 'r1'}])
        self.assertEqual(restored.cookies(), {'route': 'r1'})

    def _fetch(self, method, payload, *args):
        seen = {}

        def fake_get(session, url, **kwargs):
            seen.update(url=url, params=kwargs.get('params'))
            return FakeResponse(json_data=payload, url=url)

        with patch.object(
            requests.Session, 'get', autospec=True, side_effect=fake_get,
        ):
            client = PortalClient.from_cookies({'JSESSIONID': 'abc'})
            self.assertEqual(getattr(client, method)(*args), payload)
        return seen

    def test_get_terms_returns_json(self):
        payload = {'success': True, 'nowXnxq': {'xndxq': '26-27-1'},
                   'xndxq': [{'xndxq': '26-27-1'}, {'xndxq': '25-26-3'}]}
        seen = self._fetch('get_terms', payload)
        self.assertEqual(seen['url'], PORTAL_TERMS_URL)
        self.assertEqual(seen['url'],
                         f'{PUBLIC_QUERY}/ctrl/topic/myCourseTable/getXndXqList.do')
        self.assertIsNone(seen['params'])

    def test_get_course_info_returns_json(self):
        payload = {'success': True, 'remark': '', 'course': []}
        seen = self._fetch('get_course_info', payload, '26-27-1')
        self.assertEqual(seen['url'], PORTAL_COURSE_URL)
        self.assertEqual(seen['url'],
                         f'{PUBLIC_QUERY}/ctrl/topic/myCourseTable/getCourseInfo.do')
        self.assertEqual(seen['params'], {'xndxq': '26-27-1'})

    def test_get_scores_returns_json(self):
        payload = {'success': True, 'xslb': 'bks', 'cjxx': []}
        seen = self._fetch('get_scores', payload)
        self.assertEqual(seen['url'], PORTAL_SCORE_URL)
        self.assertEqual(seen['url'], f'{PUBLIC_QUERY}/ctrl/topic/myScore/retrScores.do')
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
            with self.assertRaises(PortalSessionExpired):
                client.get_terms()
            self.assertFalse(client.ping())

    def test_401_means_session_expired(self):
        with patch.object(
            requests.Session, 'get', autospec=True,
            return_value=FakeResponse(status_code=401,
                                      json_data={'success': False},
                                      url=PORTAL_COURSE_URL),
        ):
            client = PortalClient.from_cookies({'JSESSIONID': 'stale'})
            with self.assertRaises(PortalSessionExpired):
                client.get_course_info('26-27-1')
            self.assertFalse(client.ping())

    def test_redirect_to_iaaa_means_session_expired(self):
        redirected = FakeResponse(
            json_data={'unexpected': True},
            url='https://iaaa.pku.edu.cn/iaaa/oauth.jsp?appID=portalPublicQuery',
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

    def test_ping_asks_for_the_term_list(self):
        seen = []

        def fake_get(session, url, **kwargs):
            seen.append(url)
            return FakeResponse(json_data={'success': True}, url=url)

        with patch.object(
            requests.Session, 'get', autospec=True, side_effect=fake_get,
        ):
            client = PortalClient.from_cookies({'JSESSIONID': 'abc'})
            self.assertTrue(client.ping())
        self.assertEqual(seen, [PORTAL_TERMS_URL])
