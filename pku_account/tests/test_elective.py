"""
Tests of the course-selection (elective) client. Every HTTP call is mocked at
``requests.Session.get`` / ``requests.Session.post``; nothing reaches
pku.edu.cn.
"""
from unittest.mock import patch
from urllib.parse import urlencode

import requests
from django.test import SimpleTestCase

from pku_account.extern import iaaa
from pku_account.extern.elective import (
    ELECTIVE_BASE,
    ELECTIVE_HELP_URL,
    ELECTIVE_RESULTS_URL,
    ELECTIVE_SSO,
    ElectiveClient,
)
from pku_account.extern.iaaa import PortalUnreachable
from pku_account.extern.portal import PortalEndpointMissing, PortalSessionExpired

USERNAME = '2100010001'
PASSWORD = 'S3cret-Pa55!'
TOKEN = 'tok-elective-1'
SESSION_ID = 'elective-session-value'
SIDA = '0123456789abcdef0123456789abcdef'
NO_SECOND_FACTOR = {'success': True, 'authenMode': '否'}
LOGIN_PAGE = '<html><title>北京大学统一身份认证</title></html>'
# A help text may quote the time-out message; only the results page is judged by it.
HELP_PAGE = '<html><body>选课帮助：如提示“会话超时”，请重新登录。</body></html>'
CHOOSER_PAGE = (
    '<html><body><div id="div1">主 修</div><div id="div2">辅 双</div>'
    f'<a href="/elective2008/ssoLogin.do?sida={SIDA}&amp;sttp=bzx">主修</a>'
    f'<a href="/elective2008/ssoLogin.do?sida={SIDA}&amp;sttp=bfx">辅双</a>'
    '</body></html>')
RESULTS_HEADER = (
    '<table class="datagrid"><tr class="datagrid-header">'
    '<th>课程号</th><th>课程名</th><th>课程类别</th><th>学分</th><th>周学时</th>'
    '<th>教师</th><th>班号</th><th>开课单位</th><th>教室信息</th><th>选课结果</th>'
    '<th>IP地址</th><th>操作时间</th></tr>')
RESULTS_PAGE = (
    RESULTS_HEADER
    + '<tr class="datagrid-even"><td>00130201</td><td>示例课程</td><td>专业必修</td>'
    '<td>5</td><td>4</td><td>教师甲</td><td>01</td><td>示例学院</td>'
    '<td>1~16周 每周周一1~2节 理教306</td><td>已选上</td><td>-</td><td>-</td></tr></table>')
TIMEOUT_PAGE = '<html><body>您尚未登录或者会话超时,请重新登录.</body></html>'


class FakeResponse:
    """The subset of ``requests.Response`` used by the client."""

    def __init__(self, *, status_code=200, json_data=None, text='', url=''):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.url = url
        self.history = []

    def json(self):
        if self._json is None:
            raise requests.exceptions.JSONDecodeError('Expecting value', self.text, 0)
        return self._json


def _set_session_cookie(session):
    session.cookies.set('JSESSIONID', SESSION_ID, domain='elective.pku.edu.cn', path='/')


class ElectiveLoginTests(SimpleTestCase):

    def setUp(self):
        self.gets = []
        self.posts = []

    def login(self, page, *, authen=NO_SECOND_FACTOR):
        """``ElectiveClient.login`` with the site answering ``page(session, url, params)``."""

        def fake_post(session, url, data=None, **kwargs):
            self.posts.append((url, data, kwargs.get('headers')))
            return FakeResponse(json_data={'success': True, 'token': TOKEN})

        def fake_get(session, url, **kwargs):
            params = kwargs.get('params') or {}
            self.gets.append((url, params, kwargs.get('headers')))
            if url == iaaa.IAAA_AUTHEN_MODE_URL:
                return FakeResponse(json_data=authen)
            return page(session, url, params)

        with patch.object(requests.Session, 'post', autospec=True, side_effect=fake_post), \
                patch.object(requests.Session, 'get', autospec=True, side_effect=fake_get):
            return ElectiveClient.login(USERNAME, PASSWORD)

    def sso_calls(self):
        return [(params, headers) for url, params, headers in self.gets if url == ELECTIVE_SSO]

    def test_plain_login(self):
        def page(session, url, params):
            _set_session_cookie(session)
            return FakeResponse(url=ELECTIVE_HELP_URL, text=HELP_PAGE)

        with self.assertNoLogs('pku_account.extern', level='DEBUG'):
            client = self.login(page)

        self.assertIsInstance(client, ElectiveClient)
        ((url, data, headers),) = self.posts
        self.assertEqual(url, iaaa.IAAA_LOGIN_URL)
        self.assertEqual((data['appid'], data['userName'], data['password']),
                         ('syllabus', USERNAME, PASSWORD))
        self.assertEqual(data['redirUrl'], 'http://elective.pku.edu.cn:80/elective2008/ssoLogin.do')
        referer = headers['Referer']
        self.assertIn('appID=syllabus', referer)
        self.assertIn(urlencode({'appName': '学生选课系统'}), referer)
        referer.encode('latin-1')
        self.assertEqual([url for url, _, _ in self.gets],
                         [iaaa.IAAA_AUTHEN_MODE_URL,
                          'https://elective.pku.edu.cn/elective2008/ssoLogin.do'])
        self.assertEqual(self.gets[0][1]['appId'], 'syllabus')
        ((params, sso_headers),) = self.sso_calls()
        self.assertEqual(params['token'], TOKEN)
        self.assertIn('_rand', params)
        self.assertEqual(sso_headers, {'Referer': 'https://elective.pku.edu.cn/elective2008/'})

    def test_dual_degree_student_continues_as_main_degree(self):
        def page(session, url, params):
            if 'token' in params:
                return FakeResponse(url=ELECTIVE_SSO, text=CHOOSER_PAGE)
            _set_session_cookie(session)
            return FakeResponse(url=ELECTIVE_HELP_URL, text=HELP_PAGE)

        self.assertIsInstance(self.login(page), ElectiveClient)
        first, second = self.sso_calls()
        self.assertIn('token', first[0])
        self.assertEqual(second, ({'sida': SIDA, 'sttp': 'bzx'}, {'Referer': ELECTIVE_SSO}))

    def test_precheck_second_factor_does_not_block_the_login(self):
        # Advisory only: IAAA's answer to the login decides (see iaaa.check_second_factor).
        def page(session, url, params):
            _set_session_cookie(session)
            return FakeResponse(url=ELECTIVE_HELP_URL, text=HELP_PAGE)

        client = self.login(page, authen={'success': True, 'authenMode': 'OTP'})
        self.assertIsInstance(client, ElectiveClient)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(len(self.sso_calls()), 1)

    def test_login_failures(self):
        def no_cookie(session, url, params):
            return FakeResponse(url=ELECTIVE_HELP_URL, text=HELP_PAGE)

        def sent_back_to_iaaa(session, url, params):
            _set_session_cookie(session)
            return FakeResponse(url='https://iaaa.pku.edu.cn/iaaa/oauth.jsp?appID=syllabus',
                                text=LOGIN_PAGE)

        def unknown_category(session, url, params):
            _set_session_cookie(session)
            return FakeResponse(url=ELECTIVE_SSO, text='<html>用户选课类别ERR</html>')

        def network_down(session, url, params):
            raise requests.ConnectionError('boom')

        def sso_removed(session, url, params):
            return FakeResponse(status_code=404, url=ELECTIVE_SSO, text='<html>404</html>')

        cases = [(no_cookie, PortalUnreachable), (sent_back_to_iaaa, PortalUnreachable),
                 (unknown_category, PortalUnreachable), (network_down, PortalUnreachable),
                 (sso_removed, PortalEndpointMissing)]
        for page, error in cases:
            with self.subTest(page=page.__name__):
                with self.assertLogs('pku_account.extern.elective', level='WARNING') as logs, \
                        self.assertRaises(error) as ctx:
                    self.login(page)
                if error is PortalUnreachable:
                    self.assertNotIsInstance(ctx.exception, PortalEndpointMissing)
                shown = '\n'.join(logs.output) + str(ctx.exception)
                for secret in (PASSWORD, TOKEN, SESSION_ID):
                    self.assertNotIn(secret, shown)


class ElectiveResultsTests(SimpleTestCase):

    def fetch(self, answers):
        """``get_results_html`` with the site answering from ``answers`` (URL → response or error)."""
        self.calls = []

        def fake_get(session, url, **kwargs):
            self.calls.append((url, kwargs.get('headers')))
            answer = answers[url]
            if isinstance(answer, Exception):
                raise answer
            return answer

        with patch.object(requests.Session, 'get', autospec=True, side_effect=fake_get):
            return ElectiveClient().get_results_html()

    @staticmethod
    def help_page():
        return FakeResponse(url=ELECTIVE_HELP_URL, text=HELP_PAGE)

    def test_results_page_with_and_without_rows(self):
        self.assertEqual(ELECTIVE_HELP_URL, 'https://elective.pku.edu.cn/elective2008/edu/pku/'
                                            'stu/elective/controller/help/HelpController.jpf')
        self.assertEqual(ELECTIVE_RESULTS_URL, 'https://elective.pku.edu.cn/elective2008/edu/pku/'
                                               'stu/elective/controller/electiveWork/showResults.do')
        for page in (RESULTS_PAGE, RESULTS_HEADER + '</table>'):
            with self.subTest(rows=page.count('datagrid-even')):
                html = self.fetch({
                    ELECTIVE_HELP_URL: self.help_page(),
                    ELECTIVE_RESULTS_URL: FakeResponse(url=ELECTIVE_RESULTS_URL, text=page),
                })
                self.assertEqual(html, page)
                self.assertEqual(self.calls, [(ELECTIVE_HELP_URL, None),
                                              (ELECTIVE_RESULTS_URL, {'Referer': ELECTIVE_HELP_URL})])

    def test_expired_session(self):
        cases = {
            'redirect to IAAA': {
                ELECTIVE_HELP_URL: FakeResponse(
                    url='https://iaaa.pku.edu.cn/iaaa/oauth.jsp?appID=syllabus', text=LOGIN_PAGE)},
            'HTTP 401': {ELECTIVE_HELP_URL: FakeResponse(status_code=401, url=ELECTIVE_HELP_URL)},
            'redirect to a login page': {
                ELECTIVE_HELP_URL: self.help_page(),
                ELECTIVE_RESULTS_URL: FakeResponse(url=f'{ELECTIVE_BASE}/login.jsp',
                                                   text='<html>登录</html>')},
            'time-out page': {
                ELECTIVE_HELP_URL: self.help_page(),
                ELECTIVE_RESULTS_URL: FakeResponse(url=ELECTIVE_RESULTS_URL, text=TIMEOUT_PAGE)},
        }
        for name, answers in cases.items():
            with self.subTest(name):
                with self.assertRaises(PortalSessionExpired):
                    self.fetch(answers)

    def test_missing_page_is_endpoint_missing(self):
        with self.assertLogs('pku_account.extern.elective', level='WARNING') as logs:
            with self.assertRaises(PortalEndpointMissing) as ctx:
                self.fetch({
                    ELECTIVE_HELP_URL: self.help_page(),
                    ELECTIVE_RESULTS_URL: FakeResponse(status_code=404, url=ELECTIVE_RESULTS_URL,
                                                       text='<html>404</html>'),
                })
        self.assertIsInstance(ctx.exception, PortalUnreachable)
        self.assertNotIsInstance(ctx.exception, PortalSessionExpired)
        self.assertTrue(any(
            'elective endpoint answered 404: '
            '/elective2008/edu/pku/stu/elective/controller/electiveWork/showResults.do' in line
            for line in logs.output))

    def test_unreachable(self):
        for answer in (requests.Timeout('slow'), FakeResponse(status_code=502, url=ELECTIVE_HELP_URL)):
            with self.subTest(answer=type(answer).__name__):
                with self.assertLogs('pku_account.extern.elective', level='WARNING'):
                    with self.assertRaises(PortalUnreachable) as ctx:
                        self.fetch({ELECTIVE_HELP_URL: answer})
                self.assertNotIsInstance(ctx.exception, PortalEndpointMissing)
