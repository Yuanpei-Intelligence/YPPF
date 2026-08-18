import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import connection
from django.test import Client, TestCase, TransactionTestCase

from app.models import (
    NaturalPerson,
    Organization,
    OrganizationType,
    Position,
    Semester,
)
from boot.config import GLOBAL_CONFIG
from generic.models import User


URL = '/saveShowPositionStatus'


def _person(username: str, name: str) -> tuple[User, NaturalPerson]:
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
    return user, person


class SaveShowPositionStatusTest(TestCase):
    def setUp(self):
        self.user_a, self.person_a = _person('A000001', '用户甲')
        self.user_b, self.person_b = _person('A000002', '用户乙')
        teacher_user, teacher = _person('T000001', '教师')
        teacher.identity = NaturalPerson.Identity.TEACHER
        teacher.save()
        self.year = GLOBAL_CONFIG.acadamic_year
        otype = OrganizationType.objects.create(
            otype_id=9101,
            otype_name='V03类型',
            incharge=teacher,
            job_name_list=['负责人', '成员'],
        )
        org_a_user = User.objects.create_user(
            'org_v03_a', '组织甲', User.Type.ORG,
            password='test', is_newuser=False,
        )
        org_b_user = User.objects.create_user(
            'org_v03_b', '组织乙', User.Type.ORG,
            password='test', is_newuser=False,
        )
        self.org_a = Organization.objects.create(
            organization_id=org_a_user, oname='组织甲', otype=otype,
        )
        self.org_b = Organization.objects.create(
            organization_id=org_b_user, oname='组织乙', otype=otype,
        )
        self.org_user = org_a_user
        # 甲在组织甲任管理员，在组织乙任普通成员
        self.admin_pos = Position.objects.create(
            person=self.person_a, org=self.org_a, pos=0,
            is_admin=True, show_post=True, year=self.year,
            semester=Semester.ANNUAL,
        )
        self.own_pos = Position.objects.create(
            person=self.person_a, org=self.org_b, pos=10,
            is_admin=False, show_post=True, year=self.year,
            semester=Semester.ANNUAL,
        )
        self.victim_pos = Position.objects.create(
            person=self.person_b, org=self.org_a, pos=10,
            is_admin=False, show_post=True, year=self.year,
            semester=Semester.ANNUAL,
        )
        self.departed_pos = Position.objects.create(
            person=self.person_a, org=self.org_a, pos=10,
            is_admin=False, show_post=True, year=self.year - 1,
            semester=Semester.ANNUAL, status=Position.Status.DEPART,
        )
        self.history_pos = Position.objects.create(
            person=self.person_b, org=self.org_b, pos=10,
            is_admin=False, show_post=True, year=self.year - 1,
            semester=Semester.ANNUAL,
        )

    def _post(self, payload, user=None, client=None, **kwargs):
        http = client if client is not None else self.client
        if user is not None:
            http.force_login(user)
        return http.post(
            URL,
            data=json.dumps(payload),
            content_type='application/json',
            **kwargs,
        )

    def test_owner_can_toggle_own_position(self):
        self.client.force_login(self.user_a)
        response = self._post({'id': self.own_pos.id, 'status': False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'success': True})
        self.own_pos.refresh_from_db()
        self.assertFalse(self.own_pos.show_post)
        response = self._post({'id': self.own_pos.id, 'status': True})
        self.assertEqual(response.status_code, 200)
        self.own_pos.refresh_from_db()
        self.assertTrue(self.own_pos.show_post)

    def test_same_status_is_idempotent(self):
        self.client.force_login(self.user_a)
        response = self._post({'id': self.own_pos.id, 'status': True})
        self.assertEqual(response.json(), {'success': True})
        self.own_pos.refresh_from_db()
        self.assertTrue(self.own_pos.show_post)

    def test_cannot_modify_other_user_position(self):
        self.client.force_login(self.user_a)
        response = self._post({'id': self.victim_pos.id, 'status': False})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {'success': False})
        self.victim_pos.refresh_from_db()
        self.assertTrue(self.victim_pos.show_post)

    def test_cannot_modify_departed_or_history_position(self):
        self.client.force_login(self.user_a)
        response = self._post({'id': self.departed_pos.id, 'status': False})
        self.assertEqual(response.status_code, 404)
        self.departed_pos.refresh_from_db()
        self.assertTrue(self.departed_pos.show_post)
        response = self._post({'id': self.history_pos.id, 'status': False})
        self.assertEqual(response.status_code, 404)
        self.history_pos.refresh_from_db()
        self.assertTrue(self.history_pos.show_post)

    def test_admin_cannot_modify_others_or_own_admin_post(self):
        self.client.force_login(self.user_a)
        response = self._post({'id': self.admin_pos.id, 'status': False})
        self.assertEqual(response.status_code, 404)
        self.admin_pos.refresh_from_db()
        self.assertTrue(self.admin_pos.show_post)
        response = self._post({'id': self.victim_pos.id, 'status': False})
        self.assertEqual(response.status_code, 404)
        self.victim_pos.refresh_from_db()
        self.assertTrue(self.victim_pos.show_post)

    def test_org_account_forbidden(self):
        self.client.force_login(self.org_user)
        response = self._post({'id': self.own_pos.id, 'status': False})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {'success': False})
        self.own_pos.refresh_from_db()
        self.assertTrue(self.own_pos.show_post)

    def test_unauthenticated_rejected(self):
        response = self._post({'id': self.own_pos.id, 'status': False})
        self.assertEqual(response.status_code, 302)
        self.own_pos.refresh_from_db()
        self.assertTrue(self.own_pos.show_post)

    def test_invalid_account_rejected(self):
        special = User.objects.create_user(
            'special_v03', '特殊', User.Type.SPECIAL,
            password='test', is_newuser=False,
        )
        self.client.force_login(special)
        response = self._post({'id': self.own_pos.id, 'status': False})
        self.assertEqual(response.status_code, 302)
        self.own_pos.refresh_from_db()
        self.assertTrue(self.own_pos.show_post)

    def test_missing_and_unknown_id_same_404(self):
        self.client.force_login(self.user_a)
        missing = self._post({'id': 999999, 'status': False})
        forbidden = self._post({'id': self.victim_pos.id, 'status': False})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(forbidden.status_code, 404)
        self.assertEqual(missing.json(), forbidden.json())
        self.victim_pos.refresh_from_db()
        self.assertTrue(self.victim_pos.show_post)

    def test_invalid_payload_returns_400(self):
        self.client.force_login(self.user_a)
        cases = [
            b'not-json',
            json.dumps(['id', True]),
            json.dumps({'id': 'abc', 'status': True}),
            json.dumps({'status': True}),
            json.dumps({'id': self.own_pos.id}),
            json.dumps({'id': self.own_pos.id, 'status': 'false'}),
            json.dumps({'id': self.own_pos.id, 'status': 0}),
        ]
        for body in cases:
            with self.subTest(body=body):
                if isinstance(body, str):
                    body = body.encode()
                response = self.client.post(
                    URL, data=body, content_type='application/json',
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {'success': False})
        self.own_pos.refresh_from_db()
        self.assertTrue(self.own_pos.show_post)

    def test_get_not_allowed(self):
        self.client.force_login(self.user_a)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 405)
        self.own_pos.refresh_from_db()
        self.assertTrue(self.own_pos.show_post)

    def test_csrf_missing_or_wrong_token_forbidden(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user_a)
        page = csrf_client.get('/orginfo/', {'name': self.org_b.oname})
        self.assertEqual(page.status_code, 200)
        payload = json.dumps({'id': self.own_pos.id, 'status': False})
        missing = csrf_client.post(
            URL, data=payload, content_type='application/json',
        )
        self.assertEqual(missing.status_code, 403)
        wrong = csrf_client.post(
            URL, data=payload, content_type='application/json',
            HTTP_X_CSRFTOKEN='invalid',
        )
        self.assertEqual(wrong.status_code, 403)
        self.own_pos.refresh_from_db()
        self.assertTrue(self.own_pos.show_post)

    def test_csrf_valid_token_still_enforces_object_scope(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user_a)
        page = csrf_client.get('/orginfo/', {'name': self.org_b.oname})
        self.assertEqual(page.status_code, 200)
        token = csrf_client.cookies['csrftoken'].value
        denied = csrf_client.post(
            URL,
            data=json.dumps({'id': self.victim_pos.id, 'status': False}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(denied.status_code, 404)
        allowed = csrf_client.post(
            URL,
            data=json.dumps({'id': self.own_pos.id, 'status': False}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(allowed.status_code, 200)
        self.own_pos.refresh_from_db()
        self.assertFalse(self.own_pos.show_post)
        self.victim_pos.refresh_from_db()
        self.assertTrue(self.victim_pos.show_post)


class SaveShowPositionStatusConcurrencyTest(TransactionTestCase):
    def setUp(self):
        self.user_a, self.person_a = _person('C000001', '并发甲')
        self.user_b, self.person_b = _person('C000002', '并发乙')
        teacher_user, teacher = _person('C00000T', '并发教师')
        teacher.identity = NaturalPerson.Identity.TEACHER
        teacher.save()
        otype = OrganizationType.objects.create(
            otype_id=9102,
            otype_name='V03并发类型',
            incharge=teacher,
            job_name_list=['负责人', '成员'],
        )
        org_user = User.objects.create_user(
            'org_v03_c', '并发组织', User.Type.ORG,
            password='test', is_newuser=False,
        )
        org = Organization.objects.create(
            organization_id=org_user, oname='并发组织', otype=otype,
        )
        year = GLOBAL_CONFIG.acadamic_year
        self.own_pos = Position.objects.create(
            person=self.person_a, org=org, pos=10,
            is_admin=False, show_post=True, year=year,
            semester=Semester.ANNUAL,
        )
        self.other_pos = Position.objects.create(
            person=self.person_b, org=org, pos=10,
            is_admin=False, show_post=True, year=year,
            semester=Semester.ANNUAL,
        )

    def test_concurrent_updates_stay_in_scope(self):
        barrier = Barrier(2)

        def _toggle(user, position_id, status):
            client = Client()
            client.force_login(user)
            barrier.wait(timeout=5)
            try:
                return client.post(
                    URL,
                    data=json.dumps({'id': position_id, 'status': status}),
                    content_type='application/json',
                ).status_code
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            own = pool.submit(_toggle, self.user_a, self.own_pos.id, False)
            other = pool.submit(
                _toggle, self.user_a, self.other_pos.id, False,
            )
            own_status = own.result(timeout=10)
            other_status = other.result(timeout=10)
        self.assertEqual(own_status, 200)
        self.assertEqual(other_status, 404)
        self.own_pos.refresh_from_db()
        self.other_pos.refresh_from_db()
        self.assertFalse(self.own_pos.show_post)
        self.assertTrue(self.other_pos.show_post)
