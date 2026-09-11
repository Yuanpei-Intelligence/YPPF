from datetime import datetime
from unittest.mock import Mock, patch

from django.test import RequestFactory, TestCase
from django.urls import reverse

from app import login_utils, auth_code_utils as code_utils, password_reset_utils as reset_utils
from app.models import LoginChallenge, NaturalPerson, PasswordResetChallenge
from extern import code_delivery
from generic.models import User


class DualCodeDeliveryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='dual-code-user', name='测试',
                                             password='Old-pass-123', utype=User.Type.PERSON)
        NaturalPerson.objects.create(self.user, name='测试', email='test@example.com')
        self.request = RequestFactory().post('/codeLogin/')
        self.request.META['CSRF_COOKIE'] = 'fixed-device'
        self.now = datetime(2026, 9, 11, 12)

    def test_one_login_code_for_both_channels(self):
        args = login_utils.prepare_login_delivery(self.request, self.user.username, now=self.now)
        self.assertEqual(LoginChallenge.objects.count(), 1)
        self.assertEqual(args[:4], (self.user.pk, self.user.username, '测试', 'test@example.com'))
        self.assertEqual(login_utils.consume_login_code(self.request, self.user.username, args[-1], now=self.now).pk, self.user.pk)

    def test_one_reset_code_for_both_channels(self):
        args = reset_utils.prepare_password_reset_delivery(self.request, self.user.username, now=self.now)
        self.assertEqual(PasswordResetChallenge.objects.count(), 1)
        self.assertTrue(reset_utils.reset_password_from_token(self.request, self.user.username, args[-1], 'New-pass-123', now=self.now))

    def test_absent_email_does_not_block_wechat_preparation(self):
        NaturalPerson.objects.filter(person_id=self.user).update(email='')
        self.assertIsNotNone(login_utils.prepare_login_delivery(self.request, self.user.username, now=self.now))
        self.assertIsNotNone(reset_utils.prepare_password_reset_delivery(self.request, self.user.username, now=self.now))

    def test_reset_missing_account_creates_no_code(self):
        self.assertIsNone(reset_utils.prepare_password_reset_delivery(self.request, 'missing', now=self.now))
        self.assertFalse(PasswordResetChallenge.objects.exists())

    def test_page_send_actions_prepare_once(self):
        def run(purpose, prepare):
            args = prepare()
            self.assertIsNotNone(args)
            code_delivery.deliver_code(purpose, "test-id", *args)
            return True
        with patch('app.login_views.queue_code_delivery', side_effect=run), patch('app.views.queue_code_delivery', side_effect=run), patch('extern.code_delivery.deliver_code') as deliver:
            for route, purpose in [('codeLogin', 'login'), ('forgetpw', 'password_reset')]:
                response = self.client.post(reverse(route), {'action': 'send', 'username': self.user.username})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(deliver.call_args.args[0], purpose)
                self.assertEqual(deliver.call_args.args[2], self.user.pk)
        self.assertEqual(LoginChallenge.objects.count(), 1)
        self.assertEqual(PasswordResetChallenge.objects.count(), 1)

    def test_no_channel_menu_on_either_page(self):
        for route in ('codeLogin', 'forgetpw'):
            response = self.client.get(reverse(route))
            self.assertNotContains(response, 'dropdown-menu')
            self.assertNotContains(response, 'data-toggle="dropdown"')

    def test_queue_rejection_does_not_generate_a_code(self):
        prepare = Mock()
        with patch('extern.code_delivery._delivery_slots.acquire', return_value=False), patch.object(code_delivery.logger, 'warning') as log:
            self.assertFalse(code_delivery.queue_code_delivery('login', prepare))
        prepare.assert_not_called()
        self.assertIn('queue_rejected', str(log.call_args))

    def test_provider_results_are_logged_per_channel_without_secrets(self):
        for purpose in ('login', 'password_reset'):
            with self.subTest(purpose=purpose), patch.object(code_delivery.CONFIG.email, 'url', 'https://mail.test'), patch.object(code_delivery.wechat_config, 'api_url', 'https://wechat.test'), patch('extern.code_delivery.send_code_email') as email, patch('extern.code_delivery.send_verify_code') as login, patch('extern.code_delivery.send_password_reset_token') as reset, patch.object(code_delivery.logger, 'info') as log:
                code_delivery.deliver_code(purpose, 'correlation-id', self.user.pk, self.user.username, '姓名', 'private@example.com', 'SECRET-CODE')
                email.assert_called_once_with('姓名', 'private@example.com', 'SECRET-CODE', title='登录' if purpose == 'login' else '密码重置')
                sender = login if purpose == 'login' else reset
                sender.assert_called_once_with(self.user.username, 'SECRET-CODE')
                other = reset if purpose == 'login' else login
                other.assert_not_called()
                self.assertEqual(log.call_count, 2)
                lines = '\n'.join(call.args[0] % call.args[1:] for call in log.call_args_list)
                self.assertIn('channel=email status=accepted', lines)
                self.assertIn('channel=wechat status=accepted', lines)
                for secret in ('SECRET-CODE', 'private@example.com', self.user.username, '姓名'):
                    self.assertNotIn(secret, lines)

    def test_email_failure_does_not_prevent_wechat(self):
        with patch.object(code_delivery.CONFIG.email, 'url', 'https://mail.test'), patch.object(code_delivery.wechat_config, 'api_url', 'https://wechat.test'), patch('extern.code_delivery.send_code_email', side_effect=RuntimeError('SECRET-CODE')), patch('extern.code_delivery.send_verify_code') as wechat, patch.object(code_delivery.logger, 'warning') as log:
            code_delivery.deliver_code('login', 'id', self.user.pk, self.user.username, '姓名', 'test@example.com', 'SECRET-CODE')
            wechat.assert_called_once()
            self.assertNotIn('SECRET-CODE', str(log.call_args))
            self.assertIn('RuntimeError', str(log.call_args))

    def test_wechat_failure_keeps_email_success(self):
        with patch.object(code_delivery.CONFIG.email, 'url', 'https://mail.test'), patch.object(code_delivery.wechat_config, 'api_url', 'https://wechat.test'), patch('extern.code_delivery.send_code_email') as email, patch('extern.code_delivery.send_password_reset_token', side_effect=RuntimeError('SECRET-CODE')), patch.object(code_delivery.logger, 'info') as info, patch.object(code_delivery.logger, 'warning') as warning:
            code_delivery.deliver_code('password_reset', 'id', self.user.pk, self.user.username, '姓名', 'test@example.com', 'SECRET-CODE')
            email.assert_called_once()
            self.assertEqual(info.call_count, 1)
            self.assertEqual(warning.call_count, 1)

    def test_invalid_email_and_unconfigured_wechat_are_logged_as_skipped(self):
        with patch.object(code_delivery.wechat_config, 'api_url', ''), patch('extern.code_delivery.send_code_email') as email, patch('extern.code_delivery.send_verify_code') as wechat, patch.object(code_delivery.logger, 'info') as log:
            code_delivery.deliver_code('login', 'id', self.user.pk, self.user.username, '姓名', '', 'SECRET-CODE')
            email.assert_not_called()
            wechat.assert_not_called()
            lines = '\n'.join(call.args[0] % call.args[1:] for call in log.call_args_list)
            self.assertIn('channel=email status=skipped reason=no_valid_email', lines)
            self.assertIn('channel=wechat status=skipped reason=not_configured', lines)

    def test_removed_channel_actions_do_not_send(self):
        with patch('app.login_views.queue_code_delivery') as login, patch('app.views.queue_code_delivery') as reset:
            for route in ('codeLogin', 'forgetpw'):
                for action in ('email', 'wechat'):
                    self.client.post(reverse(route), {'action': action, 'username': self.user.username})
            login.assert_not_called()
            reset.assert_not_called()
        self.assertFalse(LoginChallenge.objects.exists())
        self.assertFalse(PasswordResetChallenge.objects.exists())

    def test_queue_reserves_before_preparing_and_waits_for_worker(self):
        args = (self.user.pk, self.user.username, '测试', 'test@example.com', 'SECRET-CODE')
        events = []
        with patch.object(code_delivery._delivery_slots, 'acquire', side_effect=lambda **kwargs: events.append('reserved') or True), patch.object(code_delivery._delivery_slots, 'release') as release, patch.object(code_delivery._delivery_executor, 'submit') as submit, patch('extern.code_delivery.deliver_code') as deliver:
            def prepare():
                events.append('prepared')
                submit.assert_called_once()
                deliver.assert_not_called()
                return args
            self.assertTrue(code_delivery.queue_code_delivery('login', prepare))
            self.assertEqual(events, ['reserved', 'prepared'])
            worker, purpose, delivery_id, future = submit.call_args.args
            self.assertEqual(future.result(), args)
            deliver.assert_not_called()
            worker(purpose, delivery_id, future)
            deliver.assert_called_once_with('login', delivery_id, *args)
            release.assert_called_once_with()

    def test_executor_failure_does_not_prepare_and_releases_slot(self):
        prepare = Mock()
        with patch.object(code_delivery._delivery_slots, 'acquire', return_value=True), patch.object(code_delivery._delivery_slots, 'release') as release, patch.object(code_delivery._delivery_executor, 'submit', side_effect=RuntimeError):
            self.assertFalse(code_delivery.queue_code_delivery('login', prepare))
            prepare.assert_not_called()
            release.assert_called_once_with()

    def test_preparation_failure_unblocks_worker_without_logging_secrets(self):
        with patch.object(code_delivery._delivery_slots, 'acquire', return_value=True), patch.object(code_delivery._delivery_slots, 'release') as release, patch.object(code_delivery._delivery_executor, 'submit') as submit, patch('extern.code_delivery.deliver_code') as deliver, patch.object(code_delivery.logger, 'error') as log:
            with self.assertRaises(RuntimeError):
                code_delivery.queue_code_delivery('login', Mock(side_effect=RuntimeError('SECRET-CODE')))
            worker, purpose, delivery_id, future = submit.call_args.args
            self.assertIsNone(future.result())
            worker(purpose, delivery_id, future)
            release.assert_called_once_with()
            deliver.assert_not_called()
            self.assertNotIn('SECRET-CODE', str(log.call_args))

    def test_worker_failure_releases_slot_and_redacts_error(self):
        from concurrent.futures import Future
        future = Future()
        future.set_result((self.user.pk, self.user.username, '测试', 'test@example.com', 'SECRET-CODE'))
        with patch.object(code_delivery._delivery_slots, 'release') as release, patch('extern.code_delivery.deliver_code', side_effect=RuntimeError('SECRET-CODE')), patch.object(code_delivery.logger, 'error') as log:
            code_delivery._run_delivery('login', 'test-id', future)
            release.assert_called_once_with()
            self.assertNotIn('SECRET-CODE', str(log.call_args))
