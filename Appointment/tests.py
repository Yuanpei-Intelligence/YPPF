from datetime import datetime, timedelta, time
from unittest.mock import patch
from urllib.parse import unquote

from django.test import Client, TestCase
from django.urls import reverse

from app.models import NaturalPerson, Organization, OrganizationType
from Appointment.models import Appoint, LongTermAppoint, Participant, Room, User
from Appointment.utils.web_func import get_hour_time


def _person(username: str, name: str, *, grant_underground: bool = True):
    user = User.objects.create_user(
        username,
        name,
        User.Type.STUDENT,
        password='test',
        is_newuser=False,
    )
    person = NaturalPerson.objects.create(
        user,
        name=name,
        identity=NaturalPerson.Identity.STUDENT,
        status=NaturalPerson.GraduateStatus.UNDERGRADUATED,
    )
    if grant_underground:
        person.grant_permission('underground_appointment')
    else:
        person.revoke_permission('underground_appointment')
    return user, person


class CheckoutSidIdorTest(TestCase):
    """V19：POST /underground/check_out 不得信任客户端 Sid/Sname。"""

    def setUp(self):
        self.attacker_user, _ = _person('S100001', '攻击者甲')
        self.victim_user, _ = _person('S100002', '受害者乙')
        self.attacker = Participant.objects.create(Sid=self.attacker_user)
        self.victim = Participant.objects.create(Sid=self.victim_user)
        self.room = Room.objects.create(
            Rid='B104T',
            Rtitle='B104 研讨/活动室',
            Rmin=0,
            Rmax=10,
            Rstart=time(8, 0),
            Rfinish=time(22, 0),
            Rstatus=Room.Status.PERMITTED,
        )
        start = datetime.now().replace(
            hour=20, minute=0, second=0, microsecond=0,
        ) + timedelta(days=2)
        self.startid = (start.hour - self.room.Rstart.hour) * 2
        starttime, _ = get_hour_time(self.room, self.startid)
        endtime, _ = get_hour_time(self.room, self.startid + 1)
        self.checkout_url = reverse('Appointment:checkout_appoint')
        self.slot_query = {
            'Rid': self.room.Rid,
            'weekday': start.strftime('%a'),
            'startid': str(self.startid),
            'endid': str(self.startid),
        }
        self.slot = {
            **self.slot_query,
            'year': str(start.year),
            'month': str(start.month),
            'day': str(start.day),
            'starttime': starttime,
            'endtime': endtime,
        }
        self.base_form = {
            **self.slot,
            'non_yp_num': '0',
            'Ausage': 'V19 测试',
            'announcement': '',
        }
        patchers = [
            patch(
                'Appointment.appoint.manage.set_scheduler',
                return_value=True,
            ),
            patch(
                'Appointment.appoint.manage.set_appoint_reminder',
                return_value=True,
            ),
            patch(
                'Appointment.appoint.manage.notify_appoint',
                return_value=True,
            ),
            patch('Appointment.appoint.manage.unlock_achievement'),
            patch('Appointment.views._notify_longterm_review'),
        ]
        self.mocks = [p.start() for p in patchers]
        self.addCleanup(lambda: [p.stop() for p in patchers])
        self.notify_mock = self.mocks[2]

    def _post(self, extra=None, client=None, **overrides):
        data = dict(self.base_form)
        if extra:
            data.update(extra)
        data.update(overrides)
        http = client if client is not None else self.client
        return http.post(self.checkout_url, data=data)

    def _assert_success_redirect(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertIn('成功', unquote(response.url))

    def _assert_only_attacker_appoint(self):
        self.assertEqual(
            Appoint.objects.filter(major_student=self.victim).count(), 0,
        )
        appoint = Appoint.objects.get()
        self.assertEqual(appoint.major_student_id, self.attacker.pk)
        students = list(appoint.students.all())
        self.assertIn(self.attacker, students)
        self.assertNotIn(self.victim, students)
        return appoint

    def test_own_sid_creates_for_current_user(self):
        self.client.force_login(self.attacker_user)
        response = self._post(
            Sid=self.attacker.get_id(), Sname=self.attacker.name,
        )
        self._assert_success_redirect(response)
        appoint = self._assert_only_attacker_appoint()
        self.notify_mock.assert_called()
        notified = self.notify_mock.call_args[0][0]
        self.assertEqual(notified.pk, appoint.pk)
        self.assertEqual(notified.major_student_id, self.attacker.pk)

    def test_post_other_sid_cannot_create_for_victim(self):
        self.client.force_login(self.attacker_user)
        response = self._post(
            Sid=self.victim.get_id(), Sname=self.victim.name,
        )
        self._assert_success_redirect(response)
        appoint = self._assert_only_attacker_appoint()
        notified = self.notify_mock.call_args[0][0]
        self.assertEqual(notified.major_student_id, self.attacker.pk)
        self.assertNotEqual(notified.major_student_id, self.victim.pk)
        self.assertEqual(appoint.pk, notified.pk)

    def test_missing_empty_or_unknown_sid_stays_current_user(self):
        self.client.force_login(self.attacker_user)
        cases = [
            {},
            {'Sid': '', 'Sname': self.victim.name},
            {'Sid': 'S999999', 'Sname': '不存在'},
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                Appoint.objects.all().delete()
                self.notify_mock.reset_mock()
                response = self._post(extra)
                self._assert_success_redirect(response)
                self._assert_only_attacker_appoint()

    def test_sname_swap_does_not_change_initiator(self):
        self.client.force_login(self.attacker_user)
        response = self._post(
            Sid=self.attacker.get_id(), Sname=self.victim.name,
        )
        self._assert_success_redirect(response)
        self._assert_only_attacker_appoint()

    def test_get_does_not_create_appointment(self):
        self.client.force_login(self.attacker_user)
        response = self.client.get(self.checkout_url, self.slot_query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Appoint.objects.count(), 0)
        body = response.content.decode()
        self.assertNotIn('name="Sid"', body)
        self.assertNotIn("name='Sid'", body)
        self.assertNotIn('name="Sname"', body)

    def test_unauthenticated_post_creates_nothing(self):
        response = self._post(
            Sid=self.victim.get_id(), Sname=self.victim.name,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/'))
        self.assertEqual(Appoint.objects.count(), 0)

    def test_no_underground_permission_creates_nothing(self):
        blocked_user, _ = _person(
            'S100003', '无权限丙', grant_underground=False,
        )
        Participant.objects.create(Sid=blocked_user)
        self.client.force_login(blocked_user)
        response = self._post(
            Sid=self.victim.get_id(), Sname=self.victim.name,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Appoint.objects.count(), 0)

    def test_csrf_rejected_without_or_with_bad_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.attacker_user)
        get_response = csrf_client.get(self.checkout_url, self.slot_query)
        self.assertEqual(get_response.status_code, 200)
        missing = csrf_client.post(self.checkout_url, self.base_form)
        self.assertEqual(missing.status_code, 403)
        bad = csrf_client.post(
            self.checkout_url,
            {**self.base_form, 'csrfmiddlewaretoken': 'invalid'},
        )
        self.assertEqual(bad.status_code, 403)
        self.assertEqual(Appoint.objects.count(), 0)

    def test_csrf_valid_token_still_binds_session_user(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.attacker_user)
        get_response = csrf_client.get(self.checkout_url, self.slot_query)
        self.assertEqual(get_response.status_code, 200)
        token = csrf_client.cookies['csrftoken'].value
        response = csrf_client.post(self.checkout_url, {
            **self.base_form,
            'Sid': self.victim.get_id(),
            'Sname': self.victim.name,
            'csrfmiddlewaretoken': token,
        })
        self._assert_success_redirect(response)
        self._assert_only_attacker_appoint()

    def test_longterm_initiator_stays_session_user(self):
        self.attacker.longterm = True
        self.attacker.save(update_fields=['longterm'])
        self.client.force_login(self.attacker_user)
        response = self._post(
            Sid=self.victim.get_id(),
            Sname=self.victim.name,
            longterm='on',
            times='1',
            interval='1',
            start_week='0',
        )
        self._assert_success_redirect(response)
        appoint = self._assert_only_attacker_appoint()
        longterm = LongTermAppoint.objects.get()
        self.assertEqual(longterm.applicant_id, self.attacker.pk)
        self.assertEqual(longterm.appoint_id, appoint.pk)

    def test_org_account_cannot_impersonate_person(self):
        incharge = NaturalPerson.objects.get(person_id=self.attacker_user)
        otype = OrganizationType.objects.create(
            otype_id=9001,
            otype_name='测试类型',
            incharge=incharge,
            job_name_list=['负责人', '成员'],
        )
        org_user = User.objects.create_user(
            'org_a', '组织甲', User.Type.ORG,
            password='test', is_newuser=False,
        )
        Organization.objects.create(
            organization_id=org_user, oname='组织甲', otype=otype,
        )
        org_part = Participant.objects.create(Sid=org_user)
        self.client.force_login(org_user)
        response = self._post(
            Sid=self.victim.get_id(), Sname=self.victim.name,
        )
        self._assert_success_redirect(response)
        self.assertEqual(
            Appoint.objects.filter(major_student=self.victim).count(), 0,
        )
        appoint = Appoint.objects.get()
        self.assertEqual(appoint.major_student_id, org_part.pk)
