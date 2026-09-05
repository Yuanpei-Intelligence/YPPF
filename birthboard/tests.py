from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from django.utils import timezone
from django.core.management import call_command
from django.urls import reverse

import os
from datetime import datetime, timedelta
from unittest.mock import patch

from birthboard.models import BirthboardRecord, BirthboardParticipant, BirthboardRejectedIssue, ChangeRecord
from birthboard.utils import calculate_per_cost
from birthboard.views import _deduct_and_mark_paid, _reject_record_by_admin, _refund_paid_participants_and_terminate
from birthboard.reminder import (
    _first_reminder_times,
    _second_reminder_times,
    _send_approval_reminder,
    schedule_first_approval_reminders,
    cancel_approval_reminders,
)
from birthboard import jobs as bb_jobs
from birthboard import views as bb_views
from generic.models import YQPointRecord


User = get_user_model()


class BirthboardUtilsTests(TestCase):
	def test_calculate_per_cost_basic(self):
		self.assertEqual(calculate_per_cost(0, 2), 18)
		self.assertEqual(calculate_per_cost(1, 3), 20)

	def test_calculate_per_cost_never_undercharges_total(self):
		for sender_count in range(1, 21):
			per_sender = calculate_per_cost(0, sender_count)
			self.assertGreaterEqual(per_sender * sender_count, 35)

	def test_calculate_per_cost_min_floor(self):
		# 35 / 20 rounds up to 2, which is also the configured minimum.
		self.assertEqual(calculate_per_cost(0, 20), 2)

	def test_calculate_per_cost_invalid_mode(self):
		# invalid mode falls back to mode 0
		self.assertEqual(calculate_per_cost(999, 2), 18)


class BirthboardViewHelperTests(TestCase):
	def setUp(self):
		self.sender = User.objects.create_user(username="sender", name="Sender", password="test")
		self.receiver = User.objects.create_user(username="receiver", name="Receiver", password="test")
		self.sender.YQpoint = 50
		self.sender.save(update_fields=["YQpoint"])

	def _create_record_with_participant(self, participant_status=BirthboardParticipant.Status.WAIT):
		image = SimpleUploadedFile("test.jpg", b"fake-image", content_type="image/jpeg")
		record = BirthboardRecord.objects.create(
			receiver_username=self.receiver.username,
			receiver_name=self.receiver.username,
			date="2026-04-20",
			mode=0,
			per_cost=10,
			image=image,
			is_anonymous=False,
			status=BirthboardRecord.Status.WAITING_CONFIRM,
		)
		participant = BirthboardParticipant.objects.create(
			record=record,
			user=self.sender,
			role=BirthboardParticipant.Role.SENDER,
			is_initiator=True,
			cost=10,
			status=participant_status,
		)
		return record, participant

	def test_deduct_and_mark_paid_success(self):
		_, participant = self._create_record_with_participant()

		result = _deduct_and_mark_paid(self.sender, participant, 10)

		self.assertTrue(result)
		participant.refresh_from_db()
		self.sender.refresh_from_db()
		self.assertEqual(participant.status, BirthboardParticipant.Status.PAID)
		self.assertIsNotNone(participant.action_time)
		self.assertEqual(self.sender.YQpoint, 40)
		self.assertEqual(YQPointRecord.objects.filter(user=self.sender, delta=-10, source="birthboard").count(), 1)

	def test_deduct_and_mark_paid_insufficient(self):
		_, participant = self._create_record_with_participant()

		result = _deduct_and_mark_paid(self.sender, participant, 1000)

		self.assertFalse(result)
		participant.refresh_from_db()
		self.sender.refresh_from_db()
		self.assertEqual(participant.status, BirthboardParticipant.Status.WAIT)
		self.assertEqual(self.sender.YQpoint, 50)
		self.assertEqual(YQPointRecord.objects.filter(user=self.sender, source="birthboard").count(), 0)

	def test_reject_record_by_admin_updates_existing_issue(self):
		record, _ = self._create_record_with_participant()
		record.status = BirthboardRecord.Status.WAITING_APPROVE
		record.save(update_fields=['status'])
		BirthboardRejectedIssue.objects.create(
			record=record,
			reasons='低俗恶搞',
			detail='first',
		)

		_reject_record_by_admin(record, ["敏感引战"], "second")

		record.refresh_from_db()
		self.assertEqual(record.status, BirthboardRecord.Status.TERMINATED_BY_ADMIN)
		self.assertEqual(BirthboardRejectedIssue.objects.filter(record=record).count(), 1)
		issue = BirthboardRejectedIssue.objects.get(record=record)
		self.assertEqual(issue.reasons, "敏感引战")
		self.assertEqual(issue.detail, "second")

	def test_reject_record_by_admin_refuses_nonreviewable_state(self):
		record, _ = self._create_record_with_participant()

		with self.assertRaises(ValueError):
			_reject_record_by_admin(record, ['低俗恶搞'], 'invalid state')

		record.refresh_from_db()
		self.assertEqual(
			record.status,
			BirthboardRecord.Status.WAITING_CONFIRM,
		)
		self.assertFalse(
			BirthboardRejectedIssue.objects.filter(record=record).exists()
		)

	def test_refund_paid_participants_and_terminate_logs_change(self):
		record, participant = self._create_record_with_participant(participant_status=BirthboardParticipant.Status.PAID)
		self.sender.YQpoint = 40
		self.sender.save(update_fields=["YQpoint"])

		_refund_paid_participants_and_terminate(
			record,
			actor=self.sender,
			action=ChangeRecord.Action.ABORT,
			detail={"scope": "initiator_abort"},
		)

		record.refresh_from_db()
		participant.refresh_from_db()
		self.sender.refresh_from_db()
		self.assertEqual(record.status, BirthboardRecord.Status.TERMINATED)
		self.assertEqual(participant.status, BirthboardParticipant.Status.REFUNDED)
		self.assertEqual(self.sender.YQpoint, 50)
		self.assertEqual(ChangeRecord.objects.filter(record=record, action=ChangeRecord.Action.ABORT).count(), 1)
		change = ChangeRecord.objects.get(record=record, action=ChangeRecord.Action.ABORT)
		self.assertEqual(change.actor, self.sender)
		self.assertEqual(change.before_status, BirthboardRecord.Status.WAITING_CONFIRM)
		self.assertEqual(change.after_status, BirthboardRecord.Status.TERMINATED)
		self.assertEqual(change.detail.get("scope"), "initiator_abort")


class BirthboardNightlyJobsTests(TestCase):
	def setUp(self):
		cache.delete(bb_jobs._BB_UPDATE_LOCK_KEY)
		self.img1 = SimpleUploadedFile("test1.jpg", b"fake-image-1", content_type="image/jpeg")
		self.img2 = SimpleUploadedFile("test2.jpg", b"fake-image-2", content_type="image/jpeg")

	def tearDown(self):
		cache.delete(bb_jobs._BB_UPDATE_LOCK_KEY)

	@patch("playwright.sync_api.sync_playwright")
	@patch("birthboard.web_controller._run_update_cycle")
	@patch("birthboard.web_controller.open_and_login")
	def test_nightly_update_2345_transitions_and_calls_update_cycle(
		self, mock_open, mock_update, mock_playwright,
	):
		mock_open.return_value = (object(), object())
		ok_outcome = type("Outcome", (), {"ok": True, "result": True})()
		mock_update.return_value = (object(), object(), ok_outcome)
		now = timezone.now()
		today = timezone.localtime(now).date() if timezone.is_aware(now) else now.date()
		target_date = today + timedelta(days=1)

		rec_start = BirthboardRecord.objects.create(
			receiver_username="r1",
			receiver_name="r1",
			date=target_date,
			mode=0,
			per_cost=1,
			image=self.img1,
			status=BirthboardRecord.Status.READY,
		)
		rec_finish = BirthboardRecord.objects.create(
			receiver_username="r2",
			receiver_name="r2",
			date=target_date - timedelta(days=3),
			mode=1,
			per_cost=1,
			image=self.img2,
			status=BirthboardRecord.Status.ONGOING,
		)

		bb_jobs.birthboard_nightly_update_2345()

		rec_start.refresh_from_db()
		rec_finish.refresh_from_db()
		self.assertEqual(rec_start.status, BirthboardRecord.Status.ONGOING)
		self.assertEqual(rec_finish.status, BirthboardRecord.Status.FINISHED)

		self.assertEqual(mock_update.call_count, 2)
		stop_kwargs = mock_update.call_args_list[0].kwargs
		start_kwargs = mock_update.call_args_list[1].kwargs
		self.assertEqual(stop_kwargs["up_image_name"], [])
		self.assertIn(
			os.path.abspath(rec_finish.image.path),
			stop_kwargs["del_image_name"],
		)
		self.assertEqual(start_kwargs["del_image_name"], [])
		self.assertIn(
			os.path.abspath(rec_start.image.path),
			start_kwargs["up_image_name"],
		)

	@patch("playwright.sync_api.sync_playwright")
	@patch("birthboard.web_controller._run_update_cycle")
	@patch("birthboard.web_controller.open_and_login")
	def test_nightly_update_reverts_transitions_on_failure(
		self, mock_open, mock_update, mock_playwright,
	):
		# 屏幕更新失败：已推进的记录回退，避免数据库与外部屏幕永久不一致
		mock_open.return_value = (object(), object())
		fail_outcome = type("Outcome", (), {"ok": False, "error": "boom"})()
		mock_update.return_value = (object(), object(), fail_outcome)

		now = timezone.now()
		today = timezone.localtime(now).date() if timezone.is_aware(now) else now.date()
		target_date = today + timedelta(days=1)

		rec_start = BirthboardRecord.objects.create(
			receiver_username="r1",
			receiver_name="r1",
			date=target_date,
			mode=0,
			per_cost=1,
			image=self.img1,
			status=BirthboardRecord.Status.READY,
		)
		rec_finish = BirthboardRecord.objects.create(
			receiver_username="r2",
			receiver_name="r2",
			date=target_date - timedelta(days=3),
			mode=1,
			per_cost=1,
			image=self.img2,
			status=BirthboardRecord.Status.ONGOING,
		)

		bb_jobs.birthboard_nightly_update_2345()

		rec_start.refresh_from_db()
		rec_finish.refresh_from_db()
		self.assertEqual(rec_start.status, BirthboardRecord.Status.READY)  # 已回退
		self.assertEqual(rec_finish.status, BirthboardRecord.Status.ONGOING)  # 已回退

	def test_0005_retry_targets_current_date_without_duplicate_reminder(self):
		retry_date = datetime(2026, 9, 2).date()
		with patch(
			'birthboard.jobs._today_local_date',
			return_value=retry_date,
		), patch(
			'birthboard.jobs.birthboard_nightly_update_2345'
		) as mock_update:
			bb_jobs.birthboard_nightly_retry_0005()

		mock_update.assert_called_once_with(
			target_date=retry_date,
			send_starting_reminder=False,
		)


class BirthboardAutoTerminateStaleTests(TestCase):
	@patch("birthboard.jobs._today_local_date", return_value=datetime(2026, 8, 28).date())
	def test_terminates_stale_waiting_and_refunds(self, mock_today):
		# 投放日已过但仍未 READY 的灯牌 → 自动终止并退款
		sender = User.objects.create_user(username="stale_sender", name="StaleSender", password="test")
		sender.YQpoint = 100
		sender.save(update_fields=["YQpoint"])
		img = SimpleUploadedFile("stale.jpg", b"fake", content_type="image/jpeg")
		record = BirthboardRecord.objects.create(
			receiver_username="stale_receiver",
			receiver_name="stale_receiver",
			date=datetime(2026, 8, 27).date(),
			mode=0,
			per_cost=10,
			image=img,
			status=BirthboardRecord.Status.WAITING_APPROVE,
		)
		BirthboardParticipant.objects.create(
			record=record, user=sender, role=BirthboardParticipant.Role.SENDER,
			is_initiator=True, cost=10, status=BirthboardParticipant.Status.PAID,
		)
		bb_jobs.birthboard_auto_terminate_stale_waiting()
		record.refresh_from_db()
		self.assertEqual(record.status, BirthboardRecord.Status.TERMINATED)
		sender.refresh_from_db()
		self.assertEqual(sender.YQpoint, 110)  # 退款 10
		paid_part = record.participants.get(role=BirthboardParticipant.Role.SENDER)
		self.assertEqual(paid_part.status, BirthboardParticipant.Status.REFUNDED)

	@patch("birthboard.jobs._today_local_date", return_value=datetime(2026, 8, 28).date())
	def test_keeps_ready_and_future_records(self, mock_today):
		# 已 READY 或未来日期的记录不受影响
		img = SimpleUploadedFile("stale2.jpg", b"fake", content_type="image/jpeg")
		ready = BirthboardRecord.objects.create(
			receiver_username="r_ready", receiver_name="r_ready",
			date=datetime(2026, 8, 27).date(), mode=0, per_cost=1, image=img,
			status=BirthboardRecord.Status.READY,
		)
		future = BirthboardRecord.objects.create(
			receiver_username="r_future", receiver_name="r_future",
			date=datetime(2026, 9, 1).date(), mode=0, per_cost=1, image=img,
			status=BirthboardRecord.Status.WAITING_APPROVE,
		)
		bb_jobs.birthboard_auto_terminate_stale_waiting()
		ready.refresh_from_db()
		future.refresh_from_db()
		self.assertEqual(ready.status, BirthboardRecord.Status.READY)
		self.assertEqual(future.status, BirthboardRecord.Status.WAITING_APPROVE)


class BirthboardLockCoordinationTests(TestCase):
	def setUp(self):
		cache.delete(bb_views._BB_UPDATE_LOCK_KEY)
		self.img = SimpleUploadedFile("test3.jpg", b"fake-image-3", content_type="image/jpeg")

	def tearDown(self):
		cache.delete(bb_views._BB_UPDATE_LOCK_KEY)

	def test_handle_revoke_respects_lock(self):
		sender = User.objects.create_user(username="lock_sender", name="Lock Sender", password="test")
		rec = BirthboardRecord.objects.create(
			receiver_username="x",
			receiver_name="x",
			date=timezone.now().date(),
			mode=0,
			per_cost=1,
			image=self.img,
			status=BirthboardRecord.Status.READY,
		)
		BirthboardParticipant.objects.create(
			record=rec, user=sender,
			role=BirthboardParticipant.Role.SENDER, is_initiator=True, cost=1,
			status=BirthboardParticipant.Status.WAIT,
		)

		cache.set(bb_views._BB_UPDATE_LOCK_KEY, True, timeout=300)
		self.assertEqual(bb_views._handle_revoke(str(rec.id), actor=sender), "locked")
		rec.refresh_from_db()
		self.assertEqual(rec.status, BirthboardRecord.Status.READY)

		cache.delete(bb_views._BB_UPDATE_LOCK_KEY)
		self.assertEqual(bb_views._handle_revoke(str(rec.id), actor=sender), "ok")
		rec.refresh_from_db()
		self.assertEqual(rec.status, BirthboardRecord.Status.CANCELED)

	def test_revoke_rejected_for_non_owner(self):
		# 越权撤销回归测试：非发起人/寿星不能撤销他人投放
		owner = User.objects.create_user(username="owner", name="Owner", password="test")
		outsider = User.objects.create_user(username="outsider", name="Outsider", password="test")
		rec = BirthboardRecord.objects.create(
			receiver_username=owner.username,
			receiver_name=owner.username,
			date=timezone.now().date(),
			mode=0,
			per_cost=1,
			image=self.img,
			status=BirthboardRecord.Status.READY,
		)
		BirthboardParticipant.objects.create(
			record=rec, user=owner,
			role=BirthboardParticipant.Role.SENDER, is_initiator=True, cost=1,
			status=BirthboardParticipant.Status.WAIT,
		)
		self.assertEqual(bb_views._handle_revoke(str(rec.id), actor=outsider), "forbidden")
		rec.refresh_from_db()
		self.assertEqual(rec.status, BirthboardRecord.Status.READY)

	def test_revoke_rechecks_lock_after_record_serialization(self):
		sender = User.objects.create_user(
			username='late_lock_sender',
			name='Late Lock Sender',
			password='test',
		)
		rec = BirthboardRecord.objects.create(
			receiver_username='x',
			receiver_name='x',
			date=timezone.now().date(),
			mode=0,
			per_cost=1,
			image=self.img,
			status=BirthboardRecord.Status.READY,
		)
		BirthboardParticipant.objects.create(
			record=rec,
			user=sender,
			role=BirthboardParticipant.Role.SENDER,
			is_initiator=True,
			cost=1,
			status=BirthboardParticipant.Status.PAID,
		)

		with patch(
			'birthboard.views._display_update_is_locked',
			side_effect=[False, True],
		):
			result = bb_views._handle_revoke(str(rec.pk), actor=sender)

		self.assertEqual(result, 'locked')
		rec.refresh_from_db()
		self.assertEqual(rec.status, BirthboardRecord.Status.READY)


class LockUiIntegrationTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username="tester", name="Tester", password="test")
		self.approver = User.objects.create_user(username="approver", name="Approver", password="test")
		User.objects.filter(pk__in=[self.user.pk, self.approver.pk]).update(
			utype=User.Type.STUDENT, is_newuser=False
		)
		from birthboard.models import BirthboardApprover, BirthboardContract
		BirthboardApprover.objects.create(user=self.approver, is_active=True)
		BirthboardContract.objects.create(user=self.user, signed=True)
		BirthboardContract.objects.create(user=self.approver, signed=True)

	def test_confirm_page_hides_revoke_action_when_locked(self):
		self.client.login(username="tester", password="test")
		img = SimpleUploadedFile("img.jpg", b"img", content_type="image/jpeg")
		rec = BirthboardRecord.objects.create(
			receiver_username=self.user.username,
			receiver_name=self.user.username,
			date=timezone.now().date(),
			mode=0,
			per_cost=1,
			image=img,
			status=BirthboardRecord.Status.READY,
		)
		BirthboardParticipant.objects.create(
			record=rec,
			user=self.user,
			role=BirthboardParticipant.Role.SENDER,
			is_initiator=True,
			cost=1,
			status=BirthboardParticipant.Status.PAID,
		)
		# set lock
		from django.core.cache import cache
		lock_key = "birthboard:update_in_progress"
		cache.set(lock_key, True, timeout=300)
		self.addCleanup(cache.delete, lock_key)

		resp = self.client.get(
			reverse('birthboard_confirm') + '?tab=participation',
			HTTP_REFERER='/birthboard/',
		)
		content = resp.content.decode('utf-8')
		self.assertIn('系统同步中，无法操作', content)
		self.assertNotIn(
			f'onclick="showRevokeModal(\'{rec.pk}\')"',
			content,
		)

	def test_confirm_form_includes_csrf_token(self):
		"""确认扣款表单必须携带 CSRF token，否则 csrf_protect 会拒绝提交（403）。"""
		self.client.login(username="tester", password="test")
		img = SimpleUploadedFile("img_csrf.jpg", b"img", content_type="image/jpeg")
		rec = BirthboardRecord.objects.create(
			receiver_username="someone",
			receiver_name="someone",
			date=timezone.now().date(),
			mode=0,
			per_cost=5,
			image=img,
			status=BirthboardRecord.Status.WAITING_CONFIRM,
		)
		BirthboardParticipant.objects.create(
			record=rec, user=self.user,
			role=BirthboardParticipant.Role.SENDER, is_initiator=False, cost=5,
			status=BirthboardParticipant.Status.WAIT,
		)
		resp = self.client.get(
			reverse('birthboard_confirm') + '?tab=participation',
			HTTP_REFERER='/birthboard/',
		)
		self.assertEqual(resp.status_code, 200)
		content = resp.content.decode('utf-8')
		self.assertIn('id="confirm-form-%d"' % rec.id, content)
		# confirm-form 内部必须包含 csrfmiddlewaretoken 隐藏字段
		start = content.index('id="confirm-form-%d"' % rec.id)
		end = content.index('确认扣款', start)
		self.assertIn('csrfmiddlewaretoken', content[start:end])

	def test_approve_page_shows_only_one_pending_request(self):
		self.client.login(username="approver", password="test")
		img1 = SimpleUploadedFile("img2.jpg", b"img2", content_type="image/jpeg")
		img2 = SimpleUploadedFile("img3.jpg", b"img3", content_type="image/jpeg")
		rec1 = BirthboardRecord.objects.create(
			receiver_username="someone1",
			receiver_name="someone1",
			date=timezone.now().date(),
			mode=0,
			per_cost=1,
			image=img1,
			status=BirthboardRecord.Status.WAITING_APPROVE,
		)
		BirthboardRecord.objects.filter(pk=rec1.pk).update(created_at=timezone.now() - timedelta(minutes=5))
		rec2 = BirthboardRecord.objects.create(
			receiver_username="someone2",
			receiver_name="someone2",
			date=timezone.now().date(),
			mode=0,
			per_cost=1,
			image=img2,
			status=BirthboardRecord.Status.WAITING_APPROVE,
		)
		resp = self.client.get(reverse('birthboard_approve'))
		content = resp.content.decode('utf-8')
		self.assertIn('someone2', content)
		self.assertIn('初审通过', content)
		# 待审核卡片按创建时间倒序，只挑最新一条作为当前审核对象
		current = resp.context['current_activity']
		self.assertIsNotNone(current)
		self.assertEqual(current['record'].pk, rec2.pk)

	def test_approve_page_shows_empty_state_when_no_pending(self):
		self.client.login(username="approver", password="test")
		resp = self.client.get(reverse('birthboard_approve'))
		content = resp.content.decode('utf-8')
		self.assertIn('无需燕牌 暂德清闲', content)

	def test_approve_page_mobile_renders_for_mobile_ua(self):
		# 移动端 UA 渲染手机版审核页，且功能元素齐全
		self.client.login(username="approver", password="test")
		resp = self.client.get(
			reverse('birthboard_approve'),
			HTTP_USER_AGENT='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
		)
		self.assertEqual(resp.status_code, 200)
		content = resp.content.decode('utf-8')
		self.assertIn('viewport', content)  # 移动模板特征
		self.assertIn('审核标准', content)
		self.assertIn('全部投放', content)


class BirthboardNightlySimulationCommandTests(TestCase):
	@patch("birthboard.jobs.birthboard_nightly_update_2345")
	def test_simulation_command_runs_job(self, mock_2345):
		call_command("simulate_birthboard_nightly_update")
		mock_2345.assert_called_once()


class BirthboardApprovalReminderTests(TestCase):
	"""审核提醒的排期时间与调度测试。"""

	def _make_record(self, date="2026-08-19"):
		image = SimpleUploadedFile("test.jpg", b"fake-image", content_type="image/jpeg")
		return BirthboardRecord.objects.create(
			receiver_username="receiver",
			receiver_name="receiver",
			date=datetime.strptime(date, "%Y-%m-%d").date(),
			mode=0,
			per_cost=10,
			image=image,
			status=BirthboardRecord.Status.WAITING_APPROVE,
		)

	# ---- 时间计算 ----

	def test_first_reminder_times_full(self):
		record = self._make_record("2026-08-19")
		now = datetime(2026, 8, 10, 0, 0)
		times = _first_reminder_times(record, now)
		# D-5/D-4 每天 9:00、14:00 共 4 个；D-3~D-1 每天 9:00~23:00 共 45 个
		self.assertEqual(len(times), 49)
		self.assertIn(datetime(2026, 8, 14, 9, 0), times)
		self.assertIn(datetime(2026, 8, 15, 14, 0), times)
		self.assertIn(datetime(2026, 8, 18, 23, 0), times)

	def test_first_reminder_times_filters_past(self):
		record = self._make_record("2026-08-19")
		now = datetime(2026, 8, 18, 12, 0)
		times = _first_reminder_times(record, now)
		self.assertEqual(len(times), 11)  # 只剩 D-1 13:00~23:00
		self.assertTrue(all(t > now for t in times))

	def test_second_reminder_times_full(self):
		record = self._make_record("2026-08-19")
		now = datetime(2026, 8, 15, 0, 0)  # 早于 D-2
		times = _second_reminder_times(record, now)
		# D-2 9:00、14:00 + D-1 9:00~23:00 共 15 个 = 17 个
		self.assertEqual(len(times), 17)
		self.assertIn(datetime(2026, 8, 17, 9, 0), times)
		self.assertIn(datetime(2026, 8, 17, 14, 0), times)
		self.assertIn(datetime(2026, 8, 18, 23, 0), times)

	def test_second_reminder_times_skips_past_when_late(self):
		record = self._make_record("2026-08-19")
		now = datetime(2026, 8, 17, 10, 0)  # D-2 当天进入二审
		times = _second_reminder_times(record, now)
		# 跳过 D-2 9:00，保留 D-2 14:00 + D-1 15 个 = 16 个
		self.assertNotIn(datetime(2026, 8, 17, 9, 0), times)
		self.assertIn(datetime(2026, 8, 17, 14, 0), times)
		self.assertEqual(len(times), 16)

	# ---- 发送幂等 ----

	@patch("birthboard.notify.notify_approval_reminder")
	def test_send_approval_reminder_skips_when_not_pending(self, mock_notify):
		record = self._make_record("2026-08-19")
		record.status = BirthboardRecord.Status.READY
		record.save(update_fields=["status"])
		_send_approval_reminder(record.id, "first")
		mock_notify.assert_not_called()

	@patch("birthboard.notify.notify_approval_reminder")
	def test_send_approval_reminder_skips_when_first_already_done(self, mock_notify):
		record = self._make_record("2026-08-19")
		record.first_approved = True
		record.save(update_fields=["first_approved"])
		_send_approval_reminder(record.id, "first")
		mock_notify.assert_not_called()

	@patch("birthboard.notify.notify_approval_reminder")
	def test_send_approval_reminder_calls_notify_when_pending(self, mock_notify):
		record = self._make_record("2026-08-19")
		_send_approval_reminder(record.id, "first")
		mock_notify.assert_called_once()
		args, _ = mock_notify.call_args
		self.assertEqual(args[0].id, record.id)
		self.assertEqual(args[1], "first")

	# ---- 调度/撤回 ----

	@patch("birthboard.reminder.ScheduleAdder")
	@patch("birthboard.reminder._first_reminder_times", return_value=[datetime(2026, 8, 14, 9, 0)])
	def test_schedule_first_approval_reminders(self, mock_times, mock_adder):
		record = self._make_record("2026-08-19")
		schedule_first_approval_reminders(record)
		mock_adder.assert_called_once()
		_, kwargs = mock_adder.call_args
		self.assertEqual(kwargs["run_time"], datetime(2026, 8, 14, 9, 0))
		self.assertEqual(kwargs["id"], f"birthboard_approve_remind_{record.id}_first_202608140900")

	@patch("birthboard.reminder.remove_job")
	def test_cancel_approval_reminders(self, mock_remove):
		record = self._make_record("2026-08-19")
		job = type("Job", (), {"id": f"birthboard_approve_remind_{record.id}_first_202608140900"})()
		with patch("birthboard.reminder.scheduler.get_jobs", return_value=[job]):
			cancel_approval_reminders(record, stage="first")
		mock_remove.assert_called_once_with(job.id)


class BirthboardConcurrencyFixTests(TestCase):
	"""并发修复回归测试：付款/确认/中止/审批在并发状态下的行为。"""

	def setUp(self):
		self.sender = User.objects.create_user(username="sender", name="Sender", password="test")
		self.receiver = User.objects.create_user(username="receiver", name="Receiver", password="test")
		self.sender.YQpoint = 100
		self.sender.save(update_fields=["YQpoint"])
		# 普通用户需完成 onboarding 且为有效账号，避免 check_user_access 重定向阻断页面流程
		User.objects.filter(pk__in=[self.sender.pk, self.receiver.pk]).update(
			utype=User.Type.STUDENT, is_newuser=False
		)
		from birthboard.models import BirthboardContract
		BirthboardContract.objects.create(user=self.sender, signed=True)
		BirthboardContract.objects.create(user=self.receiver, signed=True)

	def _make_record(self, status, receiver_username=None):
		image = SimpleUploadedFile("test.jpg", b"fake-image", content_type="image/jpeg")
		receiver_username = receiver_username or self.receiver.username
		return BirthboardRecord.objects.create(
			receiver_username=receiver_username,
			receiver_name=receiver_username,
			date=timezone.now().date(),
			mode=0,
			per_cost=10,
			image=image,
			status=status,
		)

	def test_payment_rejected_after_revoke(self):
		# A stale payment page cannot charge after the record was cancelled.
		record = self._make_record(BirthboardRecord.Status.CANCELED)
		participant = BirthboardParticipant.objects.create(
			record=record, user=self.sender,
			role=BirthboardParticipant.Role.SENDER, is_initiator=True, cost=10,
			status=BirthboardParticipant.Status.WAIT,
		)
		self.client.force_login(self.sender)
		resp = self.client.post(reverse("birthboard_confirm"), {
			"tab": "participation", "record_id": str(record.id),
		})
		self.assertEqual(resp.status_code, 302)
		self.assertIn('error=concurrency', resp['Location'])  # 并发拒绝携带弹窗信号
		self.sender.refresh_from_db()
		participant.refresh_from_db()
		self.assertEqual(self.sender.YQpoint, 100)  # 未扣款
		self.assertEqual(participant.status, BirthboardParticipant.Status.WAIT)  # 未付款

	def test_receiver_confirm_ignored_after_termination(self):
		# A stale receiver page cannot revive a cancelled record.
		record = self._make_record(BirthboardRecord.Status.CANCELED)
		BirthboardParticipant.objects.create(
			record=record, user=self.sender,
			role=BirthboardParticipant.Role.SENDER, is_initiator=True, cost=10,
			status=BirthboardParticipant.Status.WAIT,
		)
		receiver_part = BirthboardParticipant.objects.create(
			record=record, user=self.receiver,
			role=BirthboardParticipant.Role.RECEIVER, is_initiator=False, cost=0,
			status=BirthboardParticipant.Status.WAIT,
		)
		self.client.force_login(self.receiver)
		resp = self.client.post(reverse("birthboard_confirm"), {
			"tab": "received", "record_id": str(record.id),
		})
		self.assertEqual(resp.status_code, 302)
		self.assertIn('error=concurrency', resp['Location'])  # 并发拒绝携带弹窗信号
		record.refresh_from_db()
		receiver_part.refresh_from_db()
		self.assertEqual(record.status, BirthboardRecord.Status.CANCELED)
		self.assertEqual(receiver_part.status, BirthboardParticipant.Status.WAIT)

	def test_abort_rejected_during_sync_lock(self):
		# 23:45-24:00 同步窗口内，中止必须被拒绝且不退款
		record = self._make_record(BirthboardRecord.Status.WAITING_APPROVE)
		sender_part = BirthboardParticipant.objects.create(
			record=record, user=self.sender,
			role=BirthboardParticipant.Role.SENDER, is_initiator=True, cost=10,
			status=BirthboardParticipant.Status.PAID,
		)
		self.client.force_login(self.sender)
		cache.set(bb_views._BB_UPDATE_LOCK_KEY, True, timeout=300)
		try:
			resp = self.client.post(reverse("birthboard_confirm"), {
				"tab": "participation", "abort_id": str(record.id),
			})
		finally:
			cache.delete(bb_views._BB_UPDATE_LOCK_KEY)
		self.assertEqual(resp.status_code, 302)
		self.assertIn('error=concurrency', resp['Location'])  # 并发拒绝携带弹窗信号
		record.refresh_from_db()
		sender_part.refresh_from_db()
		self.assertEqual(record.status, BirthboardRecord.Status.WAITING_APPROVE)
		self.assertEqual(sender_part.status, BirthboardParticipant.Status.PAID)

	def test_second_approve_not_repeated(self):
		# 终审：第一个终审通过后置 READY，第二个重复终审不再推进/覆盖
		from birthboard.models import BirthboardApprover, BirthboardContract, BirthboardSecondApprover
		first = User.objects.create_user(username="first_a", name="FirstA", password="test")
		second = User.objects.create_user(username="second_a", name="SecondA", password="test")
		User.objects.filter(username__in=["first_a", "second_a"]).update(
			utype=User.Type.STUDENT, is_newuser=False
		)
		BirthboardApprover.objects.create(user=first, is_active=True)
		BirthboardSecondApprover.objects.create(user=second, is_active=True)
		BirthboardContract.objects.create(user=second, signed=True)
		record = self._make_record(BirthboardRecord.Status.WAITING_APPROVE)
		record.first_approved = True
		record.first_approver = first
		record.save(update_fields=["first_approved", "first_approver"])
		log_count = ChangeRecord.objects.filter(record=record).count()

		with patch("birthboard.views.schedule_first_approval_reminders"), \
		     patch("birthboard.views.schedule_second_approval_reminders"), \
		     patch("birthboard.views.cancel_approval_reminders"):
			self.client.force_login(second)
			resp1 = self.client.post(reverse("birthboard_approve"), {
				"action": "approve", "record_id": str(record.id),
			})
			self.assertEqual(resp1.status_code, 302)
			record.refresh_from_db()
			self.assertEqual(record.status, BirthboardRecord.Status.READY)
			self.assertEqual(record.second_approver, second)

			# 第二次重复终审：记录已 READY，不再产生新的审核日志
			resp2 = self.client.post(reverse("birthboard_approve"), {
				"action": "approve", "record_id": str(record.id),
			})
			self.assertEqual(resp2.status_code, 302)
			self.assertEqual(
				ChangeRecord.objects.filter(record=record).count(),
				log_count + 1,
			)

	def test_second_approve_rejected_during_sync_lock(self):
		# 23:45-24:00 同步窗口内，终审必须被拒绝，避免产生错过当夜投放的新 READY
		from birthboard.models import BirthboardApprover, BirthboardContract, BirthboardSecondApprover
		first = User.objects.create_user(username="first_b", name="FirstB", password="test")
		second = User.objects.create_user(username="second_b", name="SecondB", password="test")
		User.objects.filter(username__in=["first_b", "second_b"]).update(
			utype=User.Type.STUDENT, is_newuser=False
		)
		BirthboardApprover.objects.create(user=first, is_active=True)
		BirthboardSecondApprover.objects.create(user=second, is_active=True)
		BirthboardContract.objects.create(user=second, signed=True)
		record = self._make_record(BirthboardRecord.Status.WAITING_APPROVE)
		record.first_approved = True
		record.first_approver = first
		record.save(update_fields=["first_approved", "first_approver"])
		self.client.force_login(second)
		cache.set(bb_views._BB_UPDATE_LOCK_KEY, True, timeout=300)
		try:
			with patch("birthboard.views.schedule_first_approval_reminders"), \
			     patch("birthboard.views.schedule_second_approval_reminders"), \
			     patch("birthboard.views.cancel_approval_reminders"):
				resp = self.client.post(reverse("birthboard_approve"), {
					"action": "approve", "record_id": str(record.id),
				})
		finally:
			cache.delete(bb_views._BB_UPDATE_LOCK_KEY)
		self.assertEqual(resp.status_code, 302)
		self.assertIn('error=concurrency', resp['Location'])
		record.refresh_from_db()
		self.assertEqual(record.status, BirthboardRecord.Status.WAITING_APPROVE)
		self.assertIsNone(record.second_approver)

	def test_image_filename_counter_increments(self):
		# 存储名不得暴露原文件名，并使用不可预测标识避免被枚举
		from datetime import date as ddate
		submit = datetime(2026, 8, 28, 10, 30)
		img1 = SimpleUploadedFile("orig.jpg", b"fake", content_type="image/jpeg")
		with patch('birthboard.views.secrets.token_hex', return_value='a' * 32):
			name1 = bb_views._generate_birthboard_image_filename(
				img1,
				ddate(2026, 8, 28),
				submit_time=submit,
			)
		self.assertEqual(name1, f"20260828_{'a' * 32}.jpg")
		self.assertNotIn('orig', name1)


class BirthboardLikeTests(TestCase):
	"""制作名单点赞量接口测试。"""

	def setUp(self):
		self.user = User.objects.create_user(username="liker", name="Liker", password="test")
		self.user.utype = User.Type.STUDENT
		self.user.is_newuser = False
		self.user.save(update_fields=["utype", "is_newuser"])
		from birthboard.models import BirthboardContract
		BirthboardContract.objects.create(user=self.user, signed=True)
		self.client.login(username="liker", password="test")

	def test_like_count_initial_zero(self):
		"""初始累计点赞量为 0。"""
		resp = self.client.get("/birthboard/api/like_count/")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.json()["count"], 0)

	def test_like_add_increments_and_accumulates(self):
		"""点赞接口每次 +1，并跨请求累积。"""
		self.assertEqual(self.client.post("/birthboard/api/like_add/").json()["count"], 1)
		self.assertEqual(self.client.post("/birthboard/api/like_add/").json()["count"], 2)
		resp = self.client.get("/birthboard/api/like_count/")
		self.assertEqual(resp.json()["count"], 2)

	def test_like_requires_login(self):
		"""未登录访问点赞接口应被重定向。"""
		self.client.logout()
		resp = self.client.get("/birthboard/api/like_count/")
		self.assertEqual(resp.status_code, 302)


class BirthboardReminderSeenTests(TestCase):
	"""今日提醒已读标记（服务端去重）接口测试。"""

	def setUp(self):
		self.user = User.objects.create_user(username="reminder_user", name="提醒测试", password="test")
		self.user.utype = User.Type.STUDENT
		self.user.is_newuser = False
		self.user.save(update_fields=["utype", "is_newuser"])
		from birthboard.models import BirthboardContract
		BirthboardContract.objects.create(user=self.user, signed=True)
		self.client.login(username="reminder_user", password="test")

	def test_mark_seen_creates_record(self):
		"""POST happy 后创建已读记录，重复标记不重复。"""
		from birthboard.models import BirthboardReminderSeen
		resp = self.client.post("/birthboard/api/reminder_seen/", {"type": "happy"})
		self.assertEqual(resp.status_code, 200)
		self.assertTrue(resp.json()["ok"])
		self.assertEqual(BirthboardReminderSeen.objects.count(), 1)
		self.client.post("/birthboard/api/reminder_seen/", {"type": "happy"})
		self.assertEqual(BirthboardReminderSeen.objects.count(), 1)

	def test_invalid_type_rejected(self):
		"""无效 type 返回 400。"""
		resp = self.client.post("/birthboard/api/reminder_seen/", {"type": "other"})
		self.assertEqual(resp.status_code, 400)

	def test_requires_login(self):
		"""未登录访问应被重定向。"""
		self.client.logout()
		resp = self.client.post("/birthboard/api/reminder_seen/", {"type": "happy"})
		self.assertEqual(resp.status_code, 302)

	def test_today_reminders_reflect_seen(self):
		"""标记 seen 后 _get_today_entry_reminders 返回 seen=True。"""
		from birthboard.models import BirthboardReminderSeen
		self.assertFalse(bb_views._get_today_entry_reminders(self.user)["seen"]["happy"])
		now = timezone.localtime(timezone.now()) if timezone.is_aware(timezone.now()) else timezone.now()
		BirthboardReminderSeen.objects.create(
			user=self.user, date=now.date(), reminder_type="happy"
		)
		self.assertTrue(bb_views._get_today_entry_reminders(self.user)["seen"]["happy"])


class ContributorOrgsConfigTests(TestCase):
	"""制作名单配置（birthboard.contributor_orgs）的结构校验。"""

	def test_contributor_orgs_config_structure(self):
		import json
		from boot.config import absolute_path

		with open(absolute_path('./config_template.json'), encoding='utf8') as f:
			orgs = json.load(f)['birthboard']['contributor_orgs']
		self.assertIsInstance(orgs, list)
		self.assertTrue(orgs, "contributor_orgs 不应为空，至少包含一个组织")
		for org in orgs:
			self.assertIsInstance(org["name"], str)
			self.assertTrue(org["name"])
			self.assertIsInstance(org["columns"], list)
			for col in org["columns"]:
				self.assertIsInstance(col, list)
				self.assertTrue(all(isinstance(name, str) and name for name in col))


class BirthboardCheckYqpointTests(TestCase):
	"""check_yqpoint 只允许查询本人余额。"""

	def setUp(self):
		self.user = User.objects.create_user(username="me_cq", name="MeCq", password="test")
		self.user.utype = User.Type.STUDENT
		self.user.is_newuser = False
		self.user.YQpoint = 42
		self.user.save(update_fields=["utype", "is_newuser", "YQpoint"])
		self.other = User.objects.create_user(username="other_cq", name="OtherCq", password="test")
		self.other.YQpoint = 999
		self.other.save(update_fields=["YQpoint"])
		self.client.force_login(self.user)

	def test_only_returns_self_balance(self):
		# 传入他人用户名列表，接口也只返回本人余额，不泄露他人
		import json
		resp = self.client.post(
			reverse("check_yqpoint"),
			data=json.dumps({"senders": ["other_cq", "me_cq"], "mode": 0, "sender_count": 1}),
			content_type="application/json",
		)
		self.assertEqual(resp.status_code, 200)
		data = resp.json()
		self.assertTrue(data["ok"])
		self.assertIn("me_cq", data["result"])
		self.assertNotIn("other_cq", data["result"])
		self.assertEqual(data["result"]["me_cq"]["balance"], 42)


class BirthboardSecurityRegressionTests(TestCase):
    """Server-side checks must remain effective without the page JavaScript."""

    def setUp(self):
        from birthboard.models import BirthboardContract

        self.creator = User.objects.create_user(
            username='secure_creator',
            name='Creator',
            password='test',
            usertype=User.Type.STUDENT,
        )
        self.receiver = User.objects.create_user(
            username='secure_receiver',
            name='Receiver',
            password='test',
            usertype=User.Type.STUDENT,
        )
        self.other = User.objects.create_user(
            username='secure_other',
            name='Other',
            password='test',
            usertype=User.Type.STUDENT,
        )
        User.objects.filter(
            pk__in=[self.creator.pk, self.receiver.pk, self.other.pk]
        ).update(is_newuser=False, active=True)
        self.creator.YQpoint = 40
        self.creator.save(update_fields=['YQpoint'])
        BirthboardContract.objects.create(
            user=self.creator,
            signed=True,
        )
        self.client.force_login(self.creator)

    def _image(self, name='poster.png'):
        from io import BytesIO
        from PIL import Image

        image_bytes = BytesIO()
        Image.new('RGB', (2, 2), color='white').save(
            image_bytes,
            format='PNG',
        )
        return SimpleUploadedFile(
            name,
            image_bytes.getvalue(),
            content_type='image/png',
        )

    def _record(self, status):
        return BirthboardRecord.objects.create(
            receiver_username=self.receiver.username,
            receiver_name=self.receiver.name,
            date=timezone.now().date() + timedelta(days=7),
            mode=0,
            per_cost=10,
            image=self._image(),
            status=status,
        )

    def test_page_context_does_not_expose_other_balances(self):
        self.other.YQpoint = 987654
        self.other.save(update_fields=['YQpoint'])

        response = self.client.get(reverse('birthboard'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('yqpoints', response.context['json_context'])
        self.assertNotContains(response, '987654')

    def test_form_requires_creator_in_sender_list(self):
        from birthboard.forms import BirthboardForm

        form = BirthboardForm(
            data={
                'receiver': self.receiver.pk,
                'senders': [self.other.pk],
                'date': '2026-09-10',
                'mode': '0',
            },
            files={'image': self._image()},
            user=self.creator,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('senders', form.errors)

    def test_sender_cannot_reject_after_waiting_stage(self):
        record = self._record(BirthboardRecord.Status.READY)
        participant = BirthboardParticipant.objects.create(
            record=record,
            user=self.creator,
            role=BirthboardParticipant.Role.SENDER,
            is_initiator=False,
            cost=10,
            status=BirthboardParticipant.Status.WAIT,
        )

        response = self.client.post(
            reverse('birthboard_confirm'),
            {'tab': 'participation', 'reject_id': record.pk},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('error=concurrency', response['Location'])
        record.refresh_from_db()
        participant.refresh_from_db()
        self.assertEqual(record.status, BirthboardRecord.Status.READY)
        self.assertEqual(participant.status, BirthboardParticipant.Status.WAIT)

    def test_initiator_cannot_refund_after_approval(self):
        record = self._record(BirthboardRecord.Status.READY)
        participant = BirthboardParticipant.objects.create(
            record=record,
            user=self.creator,
            role=BirthboardParticipant.Role.SENDER,
            is_initiator=True,
            cost=10,
            status=BirthboardParticipant.Status.PAID,
        )

        response = self.client.post(
            reverse('birthboard_confirm'),
            {'tab': 'participation', 'abort_id': record.pk},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('error=concurrency', response['Location'])
        record.refresh_from_db()
        participant.refresh_from_db()
        self.creator.refresh_from_db()
        self.assertEqual(record.status, BirthboardRecord.Status.READY)
        self.assertEqual(participant.status, BirthboardParticipant.Status.PAID)
        self.assertEqual(self.creator.YQpoint, 40)

    def test_initiator_can_abort_and_refund_before_review(self):
        record = self._record(BirthboardRecord.Status.WAITING_CONFIRM)
        participant = BirthboardParticipant.objects.create(
            record=record,
            user=self.creator,
            role=BirthboardParticipant.Role.SENDER,
            is_initiator=True,
            cost=10,
            status=BirthboardParticipant.Status.PAID,
        )

        response = self.client.post(
            reverse('birthboard_confirm'),
            {'tab': 'participation', 'abort_id': record.pk},
        )

        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        participant.refresh_from_db()
        self.creator.refresh_from_db()
        self.assertEqual(record.status, BirthboardRecord.Status.TERMINATED)
        self.assertEqual(
            participant.status,
            BirthboardParticipant.Status.REFUNDED,
        )
        self.assertEqual(self.creator.YQpoint, 50)

    def test_seen_state_requires_post(self):
        from birthboard.models import BirthboardConfirmSeen

        response = self.client.get(
            f"{reverse('birthboard_confirm')}?tab=finished&mark_seen=1"
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            BirthboardConfirmSeen.objects.filter(user=self.creator).exists()
        )

    def test_poster_requires_record_relationship(self):
        from birthboard.models import BirthboardContract

        record = self._record(BirthboardRecord.Status.WAITING_CONFIRM)
        BirthboardParticipant.objects.create(
            record=record,
            user=self.creator,
            role=BirthboardParticipant.Role.SENDER,
            is_initiator=True,
            cost=10,
            status=BirthboardParticipant.Status.PAID,
        )
        url = reverse(
            'birthboard_image',
            args=[record.pk, 'image'],
        )

        allowed_response = self.client.get(url)
        self.assertEqual(allowed_response.status_code, 200)
        self.assertEqual(
            allowed_response['Cache-Control'],
            'private, no-store',
        )
        b''.join(allowed_response.streaming_content)

        BirthboardContract.objects.create(user=self.other, signed=True)
        self.client.force_login(self.other)
        denied_response = self.client.get(url)
        self.assertEqual(denied_response.status_code, 404)


class BirthboardReviewEnforcementTests(TestCase):
    """Human review must be independent and enforce the written policy."""

    def setUp(self):
        from birthboard.models import (
            BirthboardApprover,
            BirthboardContract,
            BirthboardSecondApprover,
        )

        self.initiator = User.objects.create_user(
            username='review_initiator',
            name='Initiator',
            password='test',
            usertype=User.Type.STUDENT,
        )
        self.reviewer = User.objects.create_user(
            username='reviewer_both',
            name='Reviewer',
            password='test',
            usertype=User.Type.STUDENT,
        )
        User.objects.filter(
            pk__in=[self.initiator.pk, self.reviewer.pk]
        ).update(is_newuser=False, active=True)
        self.initiator.YQpoint = 40
        self.initiator.save(update_fields=['YQpoint'])
        BirthboardContract.objects.create(
            user=self.initiator,
            signed=True,
        )
        BirthboardContract.objects.create(
            user=self.reviewer,
            signed=True,
        )
        BirthboardApprover.objects.create(user=self.reviewer)
        BirthboardSecondApprover.objects.create(user=self.reviewer)
        self.client.force_login(self.reviewer)

    def _record(self, status=BirthboardRecord.Status.WAITING_APPROVE):
        record = BirthboardRecord.objects.create(
            receiver_username='review_receiver',
            receiver_name='Receiver',
            date=timezone.now().date() + timedelta(days=7),
            mode=0,
            per_cost=10,
            image=SimpleUploadedFile(
                'review.jpg',
                b'fake-image',
                content_type='image/jpeg',
            ),
            status=status,
        )
        BirthboardParticipant.objects.create(
            record=record,
            user=self.initiator,
            role=BirthboardParticipant.Role.SENDER,
            is_initiator=True,
            cost=10,
            status=BirthboardParticipant.Status.PAID,
        )
        return record

    def test_same_account_cannot_complete_both_reviews(self):
        record = self._record()
        record.first_approved = True
        record.first_approver = self.reviewer
        record.save(update_fields=['first_approved', 'first_approver'])

        response = self.client.post(
            reverse('birthboard_approve'),
            {'action': 'approve', 'record_id': record.pk},
        )

        self.assertEqual(response.status_code, 403)
        record.refresh_from_db()
        self.assertEqual(
            record.status,
            BirthboardRecord.Status.WAITING_APPROVE,
        )
        self.assertIsNone(record.second_approver)

    def test_rejection_reason_is_validated_server_side(self):
        record = self._record()

        response = self.client.post(
            reverse('birthboard_approve'),
            {
                'action': 'reject',
                'record_id': record.pk,
                'reasons': ['forged-reason'],
                'detail': '',
            },
        )

        self.assertEqual(response.status_code, 400)
        record.refresh_from_db()
        self.assertEqual(
            record.status,
            BirthboardRecord.Status.WAITING_APPROVE,
        )

    def test_pre_display_rejection_refunds_paid_senders(self):
        record = self._record()

        response = self.client.post(
            reverse('birthboard_approve'),
            {
                'action': 'reject',
                'record_id': record.pk,
                'reasons': ['低俗恶搞'],
                'detail': '违规位置',
            },
        )

        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        participant = record.participants.get(
            role=BirthboardParticipant.Role.SENDER,
        )
        self.initiator.refresh_from_db()
        self.assertEqual(
            record.status,
            BirthboardRecord.Status.TERMINATED_BY_ADMIN,
        )
        self.assertEqual(
            participant.status,
            BirthboardParticipant.Status.REFUNDED,
        )
        self.assertEqual(self.initiator.YQpoint, 50)

    def test_ongoing_violation_creates_durable_takedown_and_restriction(self):
        from birthboard.models import BirthboardContract

        record = self._record(BirthboardRecord.Status.ONGOING)

        response = self.client.post(
            reverse('birthboard_approve'),
            {
                'action': 'reject',
                'record_id': record.pk,
                'reasons': ['诋毁侮辱隐私'],
                'detail': '含个人隐私',
                'restrict': '1',
            },
        )

        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        restriction = BirthboardContract.objects.get(user=self.initiator)
        self.assertTrue(record.display_takedown_pending)
        self.assertIsNotNone(restriction.restricted_until)
        self.assertGreater(restriction.restricted_until, datetime.now())
        self.initiator.refresh_from_db()
        self.assertEqual(self.initiator.YQpoint, 40)

    def test_finished_violation_restricts_without_takedown_or_refund(self):
        from birthboard.models import BirthboardContract

        record = self._record(BirthboardRecord.Status.FINISHED)

        response = self.client.post(
            reverse('birthboard_approve'),
            {
                'action': 'reject',
                'record_id': record.pk,
                'reasons': ['诋毁侮辱隐私'],
                'detail': '投放结束后发现含个人隐私',
                'restrict': '1',
            },
        )

        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        restriction = BirthboardContract.objects.get(user=self.initiator)
        self.assertEqual(
            record.status,
            BirthboardRecord.Status.TERMINATED_BY_ADMIN,
        )
        self.assertFalse(record.display_takedown_pending)
        self.assertIsNotNone(restriction.restricted_until)
        self.initiator.refresh_from_db()
        self.assertEqual(self.initiator.YQpoint, 40)

    def test_ongoing_violation_without_restrict_keeps_no_restriction(self):
        from birthboard.models import BirthboardContract

        record = self._record(BirthboardRecord.Status.ONGOING)

        response = self.client.post(
            reverse('birthboard_approve'),
            {
                'action': 'reject',
                'record_id': record.pk,
                'reasons': ['诋毁侮辱隐私'],
                'detail': '含个人隐私',
            },
        )

        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        restriction = BirthboardContract.objects.get(user=self.initiator)
        self.assertTrue(record.display_takedown_pending)
        self.assertIsNone(restriction.restricted_until)


class BirthboardDisplayRetryTests(TestCase):
    """Display synchronization keeps durable state and handles empty runs."""

    def setUp(self):
        cache.delete(bb_jobs._BB_UPDATE_LOCK_KEY)

    def tearDown(self):
        cache.delete(bb_jobs._BB_UPDATE_LOCK_KEY)

    @patch('playwright.sync_api.sync_playwright')
    def test_nightly_job_skips_browser_when_nothing_changes(
        self,
        mock_playwright,
    ):
        bb_jobs.birthboard_nightly_update_2345()

        mock_playwright.assert_not_called()

    @patch('playwright.sync_api.sync_playwright')
    @patch('birthboard.web_controller._run_update_cycle')
    @patch('birthboard.web_controller.open_and_login')
    def test_successful_takedown_clears_pending_flag(
        self,
        mock_open,
        mock_update,
        mock_playwright,
    ):
        from unittest.mock import Mock

        browser = Mock()
        page = Mock()
        mock_open.return_value = (browser, page)
        outcome = type('Outcome', (), {'ok': True})()
        mock_update.return_value = (browser, page, outcome)
        record = BirthboardRecord.objects.create(
            receiver_username='retry_receiver',
            receiver_name='Retry Receiver',
            date=timezone.now().date(),
            mode=0,
            per_cost=10,
            image=SimpleUploadedFile(
                'retry.jpg',
                b'fake-image',
                content_type='image/jpeg',
            ),
            status=BirthboardRecord.Status.TERMINATED_BY_ADMIN,
            display_takedown_pending=True,
        )

        result = bb_jobs.attempt_pending_takedown(record.pk)

        self.assertTrue(result)
        record.refresh_from_db()
        self.assertFalse(record.display_takedown_pending)


class BirthboardDisplayWorkflowTests(TestCase):
    """Takedown failures are isolated and block later uploads."""

    def test_mixed_cycle_attempts_every_takedown_before_stopping(self):
        from birthboard import web_controller

        attempted_labels = []

        def fake_run_step(*, browser, page, label, **kwargs):
            attempted_labels.append(label)
            return browser, page, web_controller.StepOutcome(
                label=label,
                ok=label != '从播单删除-生日三联',
                retryable=True,
                error=(
                    'simulated failure'
                    if label == '从播单删除-生日三联'
                    else None
                ),
            )

        with patch.object(
            web_controller,
            '_run_step_with_restart',
            side_effect=fake_run_step,
        ):
            _, _, outcome = web_controller._run_update_cycle(
                playwright=object(),
                browser=object(),
                page=object(),
                url='https://display.invalid/',
                username='user',
                password='password',
                up_image_name=['new.png'],
                del_image_name=['old.png'],
            )

        self.assertEqual(
            attempted_labels,
            [
                '从播单删除-生日三联',
                '从播单删除-1号横屏',
                '删除素材库',
            ],
        )
        self.assertFalse(outcome.ok)


class BirthboardNotifySenderTests(TestCase):
    """birthboard 通知发件人：config 驱动，ensure_birthboard_sender 幂等创建。"""

    def _ensure_sender(self) -> None:
        """测试库先补最小 OrganizationType，再运行 ensure 命令。"""
        from app.models import OrganizationType
        OrganizationType.objects.get_or_create(
            otype_id=31999,
            defaults={
                'otype_name': 'birthboard 测试类型',
                'job_name_list': ['成员'],
            },
        )
        call_command('ensure_birthboard_sender')

    def test_ensure_command_creates_sender_idempotently(self) -> None:
        from generic.models import User
        from app.models import Organization
        self._ensure_sender()
        self.assertTrue(
            User.objects.filter(username='yppf_birthboard').exists())
        self.assertEqual(
            Organization.objects.filter(oname='生日灯牌').count(), 1)
        # 重复运行应保持幂等：不报错、不重复创建
        call_command('ensure_birthboard_sender')
        self.assertEqual(
            Organization.objects.filter(oname='生日灯牌').count(), 1)

    def test_sender_missing_raises_loudly(self) -> None:
        from birthboard import notify
        # 官方号缺失属于配置/部署错误，应显式抛错而不是静默失败
        self.assertFalse(
            User.objects.filter(username='yppf_birthboard').exists())
        with self.assertRaises(LookupError):
            notify._sender_user()

    def test_broadcast_started_notifies_with_birthboard_sender(self) -> None:
        from datetime import date
        from birthboard import notify
        from app.models import Notification
        self._ensure_sender()
        receiver = User.objects.create_user(
            username='bb_recv_sender_test', name='接收人')
        mock_record = type('_Rec', (), {
            'receiver_name': '测试寿星',
            'date': date.today(),
        })()
        with patch.object(
            notify, '_recipient_users', return_value=[receiver]
        ), patch(
            'app.notification_utils.publish_notifications', return_value=True
        ):
            notify.notify_broadcast_started(mock_record)
        note = Notification.objects.filter(
            title='生日祝福投放已开始', receiver=receiver).first()
        self.assertIsNotNone(note)
        self.assertEqual(note.sender.username, 'yppf_birthboard')
        self.assertEqual(note.sender.name, '生日灯牌')

    def test_approval_reminder_skips_disabled_reminder_approver(self) -> None:
        """reminder_enabled=False 的审核员不收重复提醒，但仍不影响其审核资格。"""
        from datetime import date
        from birthboard import notify
        from birthboard.models import BirthboardApprover
        from app.models import Notification
        self._ensure_sender()
        # 两名都“活跃”的审核员：A 开重复提醒、B 关重复提醒
        user_a = User.objects.create_user(username='bb_appr_a', name='审核A')
        user_b = User.objects.create_user(username='bb_appr_b', name='审核B')
        BirthboardApprover.objects.create(
            user=user_a, is_active=True, reminder_enabled=True)
        BirthboardApprover.objects.create(
            user=user_b, is_active=True, reminder_enabled=False)
        mock_record = type('_Rec', (), {
            'receiver_name': '测试寿星',
            'date': date.today(),
        })()
        with patch(
            'app.notification_utils.publish_notifications', return_value=True
        ):
            notify.notify_approval_reminder(mock_record, 'first')
        self.assertTrue(Notification.objects.filter(
            title='生日祝福投放待初审', receiver=user_a).exists())
        self.assertFalse(Notification.objects.filter(
            title='生日祝福投放待初审', receiver=user_b).exists())
