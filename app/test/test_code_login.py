from datetime import datetime, timedelta
from threading import Barrier, Thread
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.db import close_old_connections
from django.test import Client, RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse

from app import login_utils, auth_code_utils as code_utils, password_reset_utils as reset_utils
from app.models import LoginChallenge, NaturalPerson
from generic.models import User


class CodeLoginTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 11, 12)
        self.user = User.objects.create_user(username='code-student', name='测试', password='Old-pass-123',
                                             utype=User.Type.STUDENT, is_newuser=False)
        NaturalPerson.objects.create(self.user, name='测试', email='test@example.com')
        self.request = RequestFactory().post('/codeLogin/')
        self.request.META['CSRF_COOKIE'] = 'fixed-device'

    def issue(self):
        return login_utils.prepare_login_delivery(self.request, self.user.username, now=self.now)[-1]

    def consume(self, code, **kwargs):
        return login_utils.consume_login_code(self.request, self.user.username, code,
                                               now=kwargs.get('now', self.now))

    def test_login_and_reset_cannot_exchange_codes_and_do_not_supersede_each_other(self):
        code = self.issue()
        reset = reset_utils.create_password_reset_token(self.request, self.user, now=self.now)
        self.assertNotEqual(code, reset)
        self.assertIsNone(self.consume(reset))
        self.assertFalse(reset_utils.reset_password_from_token(self.request, self.user.username,
                                                         code, 'New-pass-123', now=self.now))
        self.assertEqual(self.consume(code).pk, self.user.pk)
        self.assertTrue(reset_utils.reset_password_from_token(self.request, self.user.username,
                                                        reset, 'New-pass-123', now=self.now))

    def test_cross_purpose_collision_is_retried_both_directions(self):
        with patch('app.auth_code_utils.secrets.randbelow', return_value=42):
            self.assertEqual(self.issue(), '000042')
        with patch('app.auth_code_utils.secrets.randbelow', side_effect=[42, 43]):
            reset = reset_utils.create_password_reset_token(self.request, self.user, now=self.now)
        self.assertEqual(reset, '000043')
        with patch('app.auth_code_utils.secrets.randbelow', side_effect=[43, 44]):
            self.assertEqual(self.issue(), '000044')

    def test_reissue_and_replay(self):
        first = self.issue()
        second = self.issue()
        self.assertIsNone(self.consume(first))
        self.assertIsNotNone(self.consume(second))
        self.assertIsNone(self.consume(second))

    def test_expiry_and_password_change(self):
        code = self.issue()
        self.assertIsNone(self.consume(code, now=self.now + timedelta(seconds=code_utils.CODE_SECONDS)))
        self.user.set_password('Changed-pass-123')
        self.user.save(update_fields=['password'])
        self.assertIsNone(self.consume(code))

    def test_failed_attempt_limit(self):
        code = self.issue()
        wrong = '000000' if code != '000000' else '000001'
        for _ in range(5):
            self.assertIsNone(self.consume(wrong))
        self.assertIsNone(self.consume(code))
        self.assertEqual(LoginChallenge.objects.get().failed_attempts, 5)

    def test_account_scope_and_invalid_recipient(self):
        code = self.issue()
        self.assertIsNone(login_utils.consume_login_code(self.request, 'missing', code, now=self.now))
        NaturalPerson.objects.filter(person_id=self.user).update(email='')
        replacement = login_utils.prepare_login_delivery(self.request, self.user.username, now=self.now)[-1]
        self.assertIsNotNone(self.consume(replacement))

    def test_request_limits_are_shared_with_reset(self):
        for _ in range(3):
            self.issue()
        self.assertIsNone(login_utils.prepare_login_delivery(self.request, self.user.username, now=self.now))
        self.assertFalse(code_utils.check_request_rate(self.request, self.user.username, now=self.now))

    def test_get_csrf_methods_and_separate_buttons(self):
        client = Client(enforce_csrf_checks=True)
        response = client.get(reverse('codeLogin'))
        self.assertContains(response, '登录验证码')
        self.assertNotContains(response, 'name="new_password"')
        self.assertContains(response, 'history.replaceState')
        self.assertContains(response, 'data-code-prefill')
        self.assertContains(response, 'data-code-prefill-focus')
        html = response.content.decode()
        self.assertRegex(html, r'<input[^>]+id="code"[^>]+data-code-prefill>')
        self.assertRegex(html, r'<button[^>]+id="login-submit"[^>]+data-code-prefill-focus>')
        self.assertLess(html.index('history.replaceState'), html.index('<script src='))
        self.assertEqual(client.post(reverse('codeLogin'), {'action': 'send', 'username': self.user.username}).status_code, 403)
        self.assertEqual(client.put(reverse('codeLogin'),
            HTTP_X_CSRFTOKEN=client.cookies[settings.CSRF_COOKIE_NAME].value).status_code, 405)
        html = client.get(reverse('login')).content.decode()
        self.assertIn('href="/codeLogin/"', html)
        self.assertIn('<a href="/forgetpw/">忘记密码？</a>', html)

    def test_view_login_persists_session_and_still_requires_old_password(self):
        code = self.issue()
        with patch('app.login_utils.datetime') as clock:
            clock.now.return_value = self.now
            response = self.client.post(reverse('codeLogin') + '?origin=//evil.example/', {
                'username': self.user.username, 'action': 'login', 'code': code})
        self.assertEqual(response.url, reverse('welcome'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
        self.assertNotIn('forgetpw', self.client.session)
        response = self.client.post(reverse('modpw'), {'pw': 'Wrong-pass-123', 'new': 'New-pass-123'})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Old-pass-123'))

    def test_new_user_continues_agreement_and_initial_password_flow(self):
        self.user.is_newuser = True
        self.user.save(update_fields=['is_newuser'])
        code = self.issue()
        with patch('app.login_utils.datetime') as clock:
            clock.now.return_value = self.now
            response = self.client.post(reverse('codeLogin'), {
                'username': self.user.username, 'action': 'login', 'code': code})
        self.assertEqual(response.url, reverse('modpw'))
        self.assertEqual(self.client.get(response.url).url, '/agreement/')
        self.client.post(reverse('userAgreement'), {'confirm': 'yes'})
        response = self.client.post(reverse('modpw'), {'pw': 'New-pass-123', 'new': 'New-pass-123'})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_newuser)
        self.assertTrue(self.user.check_password('New-pass-123'))

    @patch('app.login_views.queue_code_delivery')
    def test_missing_and_valid_account_receive_same_message(self, queue):
        for username in [self.user.username, 'missing']:
            response = self.client.post(reverse('codeLogin'), {'username': username, 'action': 'send'})
            self.assertContains(response, '若账号及联系方式有效')
        self.assertEqual(queue.call_count, 2)

    def test_cleanup(self):
        self.issue()
        code_utils.cleanup_code_state(now=self.now + timedelta(days=3))
        self.assertFalse(LoginChallenge.objects.exists())

    @patch('extern.wechat.send_wechat')
    def test_wechat_login_message_does_not_enter_scheduler(self, send):
        from extern.wechat import send_verify_code
        send_verify_code(self.user.username, '123456')
        args, kwargs = send.call_args
        self.assertIn('登录验证码', args[2])
        link = urlsplit(kwargs['url'])
        self.assertEqual(link.path, '/codeLogin/')
        self.assertEqual(link.query, '')
        self.assertEqual(parse_qs(link.fragment), {
            'username': [self.user.username], 'token': ['123456'],
        })
        self.assertFalse(kwargs['multithread'])
        self.assertTrue(kwargs['raise_on_failure'])

    @patch('extern.wechat.send_wechat')
    def test_wechat_login_link_encodes_account_and_preserves_leading_zeros(self, send):
        from extern.wechat import send_verify_code
        send_verify_code('学生+test&name', '000042')
        link = urlsplit(send.call_args.kwargs['url'])
        self.assertEqual(link.query, '')
        self.assertEqual(parse_qs(link.fragment), {
            'username': ['学生+test&name'], 'token': ['000042'],
        })

    @patch('extern.code_email.requests.post')
    def test_email_login_message_has_distinct_purpose(self, post):
        import json
        from extern.code_email import send_code_email
        post.return_value.json.return_value = {'status': 200}
        send_code_email('测试', 'test@example.com', '123456', title='登录')
        payload = json.loads(post.call_args.args[1])
        self.assertEqual(payload['subject'], 'YPPF登录')
        self.assertIn('登录验证码', payload['content'])
        self.assertNotIn('密码重置', payload['content'])


class CodeLoginConcurrencyTests(TransactionTestCase):
    def test_only_one_concurrent_consumer_succeeds(self):
        user = User.objects.create_user(username='concurrent-login', name='测试', password='Old-pass-123', utype=User.Type.PERSON)
        NaturalPerson.objects.create(user, name='测试', email='test@example.com')
        now = datetime(2026, 9, 11, 12)
        request = RequestFactory().post('/codeLogin/')
        request.META['CSRF_COOKIE'] = 'fixed-device'
        code = login_utils.prepare_login_delivery(request, user.username, now=now)[-1]
        barrier = Barrier(2)
        results, errors = [], []
        def consume():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                results.append(login_utils.consume_login_code(request, user.username, code, now=now) is not None)
            except Exception as error:
                errors.append(error)
            finally:
                close_old_connections()
        threads = [Thread(target=consume) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [False, True])
