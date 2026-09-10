"""
A removed portal endpoint (HTTP 404 with a live session) must not look like an
expired session: on 2026-09-10 the portal dropped the course and score
endpoints, and treating the 404 page as "log in again" sent students into a
re-login loop. HTTP is mocked; nothing reaches pku.edu.cn.
"""
from unittest.mock import patch

import requests
from django.test import SimpleTestCase

from pku_account.extern.iaaa import PortalUnreachable
from pku_account.extern.portal import (
    PORTAL_COURSE_URL,
    PortalClient,
    PortalEndpointMissing,
    PortalSessionExpired,
)

NOT_FOUND_PAGE = '<!DOCTYPE html><html><head><title>404</title></head></html>'


class _Response:
    def __init__(self, status_code, text, url):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.history = []

    def json(self):
        raise requests.exceptions.JSONDecodeError('Expecting value', self.text, 0)


class PortalEndpointMissingTests(SimpleTestCase):

    def test_404_is_endpoint_missing_not_session_expired(self):
        response = _Response(404, NOT_FOUND_PAGE, PORTAL_COURSE_URL)
        with patch.object(requests.Session, 'get', autospec=True, return_value=response), \
                self.assertLogs('pku_account.extern.portal', level='WARNING') as logs:
            client = PortalClient.from_cookies({'SESSION': 'live'})
            with self.assertRaises(PortalEndpointMissing) as ctx:
                client.get_course_info('26-27-1')
            with self.assertRaises(PortalEndpointMissing):
                client.get_scores()
            self.assertFalse(client.ping('26-27-1'))
        self.assertNotIsInstance(ctx.exception, PortalSessionExpired)
        # Callers that handle PortalUnreachable keep the session and answer 503.
        self.assertIsInstance(ctx.exception, PortalUnreachable)
        self.assertIn('粘贴导入', str(ctx.exception))
        self.assertTrue(any('portal endpoint answered 404: /portal2017/bizcenter/course/getCourseInfo.do'
                            in line for line in logs.output))
        self.assertFalse(any('live' in line for line in logs.output))

    def test_login_page_still_means_session_expired(self):
        response = _Response(200, '<html><title>北京大学统一身份认证</title></html>', PORTAL_COURSE_URL)
        with patch.object(requests.Session, 'get', autospec=True, return_value=response):
            client = PortalClient.from_cookies({'SESSION': 'stale'})
            with self.assertRaises(PortalSessionExpired):
                client.get_course_info('26-27-1')
