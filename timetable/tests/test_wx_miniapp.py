"""Tests of ``extern.wx_miniapp.send_subscribe_message`` (HTTP mocked)."""
from unittest.mock import MagicMock, patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from api.auth.wechat_api import WX_ACCESS_TOKEN_CACHE_KEY
from extern import wx_miniapp

TOKEN = 'TOKEN-SECRET-VALUE'


def _response(payload=None, status_code=200, json_error=False):
    response = MagicMock()
    response.status_code = status_code
    if json_error:
        response.json.side_effect = ValueError('no json')
    else:
        response.json.return_value = payload
    return response


class SendSubscribeMessageTests(SimpleTestCase):

    def setUp(self):
        patcher = patch('api.auth.wechat_api.get_wechat_access_token', return_value=TOKEN)
        self.get_token = patcher.start()
        self.addCleanup(patcher.stop)
        cache.delete(WX_ACCESS_TOKEN_CACHE_KEY)
        self.addCleanup(cache.delete, WX_ACCESS_TOKEN_CACHE_KEY)

    def send(self, payload=None, **kwargs):
        return wx_miniapp.send_subscribe_message(
            'OPENID-1', 'TPL-1', 'pages/timetable/index',
            {'thing1': '高数', 'time2': {'value': '2026年09月21日 08:00'}}, **kwargs)

    def test_success_payload(self):
        with patch('extern.wx_miniapp.requests.post',
                   return_value=_response({'errcode': 0, 'errmsg': 'ok', 'msgid': 1})) as post:
            result = self.send()
        self.assertEqual(result, (True, 0, 'ok'))
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], wx_miniapp.SUBSCRIBE_SEND_URL)
        self.assertEqual(kwargs['params'], {'access_token': TOKEN})
        self.assertEqual(kwargs['timeout'], wx_miniapp.REQUEST_TIMEOUT)
        self.assertEqual(kwargs['json'], {
            'touser': 'OPENID-1',
            'template_id': 'TPL-1',
            'page': 'pages/timetable/index',
            'data': {'thing1': {'value': '高数'},
                     'time2': {'value': '2026年09月21日 08:00'}},
            'miniprogram_state': 'formal',
            'lang': 'zh_CN',
        })

    def test_page_omitted_when_blank_and_state_forwarded(self):
        with patch('extern.wx_miniapp.requests.post',
                   return_value=_response({'errcode': 0})) as post:
            result = wx_miniapp.send_subscribe_message(
                'OPENID-1', 'TPL-1', '', {}, miniprogram_state='trial', lang='en_US')
        self.assertEqual(result, (True, 0, 'ok'))
        payload = post.call_args.kwargs['json']
        self.assertNotIn('page', payload)
        self.assertEqual(payload['miniprogram_state'], 'trial')
        self.assertEqual(payload['lang'], 'en_US')
        self.assertEqual(payload['data'], {})

    def test_user_refused_is_reported_not_raised(self):
        with patch('extern.wx_miniapp.requests.post',
                   return_value=_response({'errcode': 43101, 'errmsg': 'user refused'})), \
                self.assertLogs('extern.wx_miniapp', level='INFO') as logs:
            result = self.send()
        self.assertEqual(result, (False, 43101, 'user refused'))
        self.assertEqual(logs.records[0].levelname, 'INFO')
        output = '\n'.join(logs.output)
        self.assertNotIn(TOKEN, output)
        self.assertNotIn('OPENID-1', output)

    def test_invalid_access_token_clears_cache(self):
        for errcode in (40001, 42001):
            with self.subTest(errcode=errcode):
                cache.set(WX_ACCESS_TOKEN_CACHE_KEY, 'stale', 60)
                with patch('extern.wx_miniapp.requests.post',
                           return_value=_response({'errcode': errcode, 'errmsg': 'invalid'})), \
                        self.assertLogs('extern.wx_miniapp', level='WARNING'):
                    result = self.send()
                self.assertEqual(result, (False, errcode, 'invalid'))
                self.assertIsNone(cache.get(WX_ACCESS_TOKEN_CACHE_KEY))

    def test_other_errcodes_keep_cache(self):
        cache.set(WX_ACCESS_TOKEN_CACHE_KEY, 'fresh', 60)
        with patch('extern.wx_miniapp.requests.post',
                   return_value=_response({'errcode': 47003, 'errmsg': 'argument invalid'})), \
                self.assertLogs('extern.wx_miniapp', level='WARNING'):
            result = self.send()
        self.assertEqual(result, (False, 47003, 'argument invalid'))
        self.assertEqual(cache.get(WX_ACCESS_TOKEN_CACHE_KEY), 'fresh')

    def test_network_error_never_raises_or_leaks_token(self):
        error = requests.ConnectionError(f'boom {wx_miniapp.SUBSCRIBE_SEND_URL}?access_token={TOKEN}')
        with patch('extern.wx_miniapp.requests.post', side_effect=error), \
                self.assertLogs('extern.wx_miniapp', level='WARNING') as logs:
            result = self.send()
        self.assertEqual(result, (False, -1, 'request failed: ConnectionError'))
        self.assertNotIn(TOKEN, '\n'.join(logs.output))

    def test_non_json_response(self):
        with patch('extern.wx_miniapp.requests.post',
                   return_value=_response(status_code=502, json_error=True)), \
                self.assertLogs('extern.wx_miniapp', level='WARNING'):
            result = self.send()
        self.assertEqual(result, (False, -1, 'invalid response (HTTP 502)'))

    def test_token_unavailable(self):
        self.get_token.side_effect = ValueError('服务器未配置微信小程序')
        with patch('extern.wx_miniapp.requests.post') as post, \
                self.assertLogs('extern.wx_miniapp', level='WARNING'):
            result = self.send()
        self.assertEqual(result, (False, -1, '服务器未配置微信小程序'))
        post.assert_not_called()


def _image_response(content=b'\xff\xd8jpegdata', status_code=200,
                    content_type='image/jpeg'):
    response = MagicMock()
    response.status_code = status_code
    response.content = content
    response.headers = {'Content-Type': content_type}
    response.json.side_effect = ValueError('not json')
    return response


def _json_response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.content = b'{"errcode": 1}'
    response.headers = {'Content-Type': 'application/json; encoding=utf-8'}
    response.json.return_value = payload
    return response


class FetchMiniappCodeTests(SimpleTestCase):
    """``fetch_miniapp_code`` (README §8.5) with HTTP mocked."""

    def setUp(self):
        patcher = patch('api.auth.wechat_api.get_wechat_access_token', return_value=TOKEN)
        self.get_token = patcher.start()
        self.addCleanup(patcher.stop)
        cache.delete(WX_ACCESS_TOKEN_CACHE_KEY)
        self.addCleanup(cache.delete, WX_ACCESS_TOKEN_CACHE_KEY)

    def fetch(self, **kwargs):
        return wx_miniapp.fetch_miniapp_code('timetable', 'pages/timetable/index', **kwargs)

    def test_success_returns_image_bytes(self):
        with patch('extern.wx_miniapp.requests.post', return_value=_image_response()) as post:
            result = self.fetch()
        self.assertEqual(result, b'\xff\xd8jpegdata')
        args, kwargs = post.call_args
        self.assertEqual(args[0], wx_miniapp.WXACODE_UNLIMITED_URL)
        self.assertEqual(kwargs['params'], {'access_token': TOKEN})
        self.assertEqual(kwargs['timeout'], wx_miniapp.CODE_REQUEST_TIMEOUT)
        self.assertEqual(kwargs['json'], {
            'scene': 'timetable', 'page': 'pages/timetable/index', 'check_path': False,
            'env_version': 'release', 'width': 430})
        with patch('extern.wx_miniapp.requests.post', return_value=_image_response()) as post:
            self.fetch(env_version='trial', width=280, check_path=True)
        self.assertEqual(post.call_args.kwargs['json']['env_version'], 'trial')
        self.assertEqual(post.call_args.kwargs['json']['width'], 280)
        self.assertTrue(post.call_args.kwargs['json']['check_path'])

    def test_wechat_error_is_none_and_never_leaks_the_token(self):
        with patch('extern.wx_miniapp.requests.post',
                   return_value=_json_response({'errcode': 41030, 'errmsg': 'invalid page'})), \
                self.assertLogs('extern.wx_miniapp', level='WARNING') as logs:
            self.assertIsNone(self.fetch())
        output = '\n'.join(logs.output)
        self.assertIn('41030', output)
        self.assertNotIn(TOKEN, output)
        # A JSON body without a JSON content type is still recognised.
        response = _image_response(content=b'{"errcode": 45009, "errmsg": "quota"}',
                                   content_type='text/plain')
        response.json.side_effect = None
        response.json.return_value = {'errcode': 45009, 'errmsg': 'quota'}
        with patch('extern.wx_miniapp.requests.post', return_value=response), \
                self.assertLogs('extern.wx_miniapp', level='WARNING'):
            self.assertIsNone(self.fetch())

    def test_invalid_token_clears_cache(self):
        cache.set(WX_ACCESS_TOKEN_CACHE_KEY, 'stale', 60)
        with patch('extern.wx_miniapp.requests.post',
                   return_value=_json_response({'errcode': 40001, 'errmsg': 'invalid'})), \
                self.assertLogs('extern.wx_miniapp', level='WARNING'):
            self.assertIsNone(self.fetch())
        self.assertIsNone(cache.get(WX_ACCESS_TOKEN_CACHE_KEY))

    def test_network_http_and_token_failures(self):
        error = requests.ConnectionError(f'boom ?access_token={TOKEN}')
        with patch('extern.wx_miniapp.requests.post', side_effect=error), \
                self.assertLogs('extern.wx_miniapp', level='WARNING') as logs:
            self.assertIsNone(self.fetch())
        self.assertNotIn(TOKEN, '\n'.join(logs.output))
        with patch('extern.wx_miniapp.requests.post',
                   return_value=_image_response(content=b'', status_code=502)), \
                self.assertLogs('extern.wx_miniapp', level='WARNING'):
            self.assertIsNone(self.fetch())
        self.get_token.side_effect = ValueError('服务器未配置微信小程序')
        with patch('extern.wx_miniapp.requests.post') as post, \
                self.assertLogs('extern.wx_miniapp', level='WARNING'):
            self.assertIsNone(self.fetch())
        post.assert_not_called()
