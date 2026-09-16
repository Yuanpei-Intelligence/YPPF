from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from Appointment.middleware import InstructionsReminderMiddleware
from Appointment.models import Participant
from Appointment.tests import _person
from dormitory.models import Agreement
from generic.models import User


class InstructionsTests(TestCase):
    def setUp(self):
        self.user, _ = _person('SREAD001', '阅读测试')
        self.participant = Participant.objects.create(Sid=self.user)
        self.client.force_login(self.user)
        self.status_url = reverse('Appointment:instructions_status')
        self.page_url = reverse('Appointment:instructions')
        self.confirm_url = reverse('Appointment:confirm_instructions')

    def sign(self):
        Agreement.objects.create(user=self.user)

    def test_all_four_agreement_and_reading_combinations(self):
        for signed in (False, True):
            for has_read in (False, True):
                with self.subTest(signed=signed, has_read=has_read):
                    Agreement.objects.filter(user=self.user).delete()
                    if signed:
                        self.sign()
                    self.participant.has_read_instructions = has_read
                    self.participant.save(update_fields=['has_read_instructions'])
                    self.assertEqual(self.client.get(self.status_url).json(), {
                        'needs_dormitory_agreement': not signed,
                        'needs_instructions': signed and not has_read,
                    })
                    page = self.client.get(self.page_url)
                    if not signed:
                        self.assertRedirects(page, '/dormitory/agreement/',
                                             fetch_redirect_response=False)
                    elif has_read:
                        self.assertContains(page, '您已确认阅读')
                    else:
                        self.assertContains(page, '我已阅读地下室使用规范')

    def test_dormitory_precedes_reading_and_blocks_confirmation(self):
        self.assertFalse(self.participant.has_read_instructions)
        with patch('Appointment.views.Participant.objects.filter') as query:
            response = self.client.get(self.status_url)
            query.assert_not_called()
        self.assertEqual(response.json(), {
            'needs_dormitory_agreement': True, 'needs_instructions': False,
        })
        for response in (self.client.get(self.page_url),
                         self.client.post(self.confirm_url)):
            self.assertRedirects(response, '/dormitory/agreement/',
                                 fetch_redirect_response=False)
        self.participant.refresh_from_db()
        self.assertFalse(self.participant.has_read_instructions)

    def test_reading_requires_explicit_confirmation(self):
        self.sign()
        self.assertTrue(self.client.get(self.status_url).json()['needs_instructions'])
        page = self.client.get(self.page_url)
        self.assertContains(page, '我已阅读地下室使用规范')
        self.assertContains(page, 'data-status-url=', count=1)
        self.assertContains(page, 'csrfmiddlewaretoken')
        self.participant.refresh_from_db()
        self.assertFalse(self.participant.has_read_instructions)
        self.assertEqual(self.client.get(self.confirm_url).status_code, 405)
        self.assertEqual(self.client.post(self.status_url).status_code, 405)
        for _ in range(2):
            self.assertRedirects(self.client.post(self.confirm_url), self.page_url)
        self.participant.refresh_from_db()
        self.assertTrue(self.participant.has_read_instructions)
        self.assertFalse(self.client.get(self.status_url).json()['needs_instructions'])
        self.assertContains(self.client.get(self.page_url), '您已确认阅读')

    def test_signing_existing_dormitory_form_then_reading_instructions(self):
        self.assertTrue(self.client.get(self.status_url).json()['needs_dormitory_agreement'])
        response = self.client.post('/dormitory/agreement/', {'confirm': 'yes'})
        self.assertRedirects(response, '/welcome', fetch_redirect_response=False)
        self.assertTrue(Agreement.objects.filter(user=self.user).exists())
        self.assertEqual(self.client.get(self.status_url).json(), {
            'needs_dormitory_agreement': False, 'needs_instructions': True,
        })
        self.client.get(self.page_url)
        self.client.post(self.confirm_url)
        self.assertEqual(self.client.get(self.status_url).json(), {
            'needs_dormitory_agreement': False, 'needs_instructions': False,
        })

    def test_no_participant_is_created_by_reading_or_status(self):
        self.sign()
        self.participant.delete()
        self.assertFalse(self.client.get(self.status_url).json()['needs_instructions'])
        self.assertNotContains(self.client.get(self.page_url), '我已阅读地下室使用规范')
        self.assertEqual(self.client.post(self.confirm_url).status_code, 404)
        self.assertFalse(Participant.objects.filter(Sid=self.user).exists())

    def test_confirmation_is_csrf_protected_and_scoped_to_session(self):
        self.sign()
        other, _ = _person('SREAD002', '另一账户')
        other_participant = Participant.objects.create(Sid=other)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.confirm_url).status_code, 403)
        client.get(self.page_url)
        token = client.cookies['csrftoken'].value
        response = client.post(self.confirm_url, {'Sid': other.username},
                               HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 302)
        self.participant.refresh_from_db()
        other_participant.refresh_from_db()
        self.assertTrue(self.participant.has_read_instructions)
        self.assertFalse(other_participant.has_read_instructions)

    def test_anonymous_invalid_and_onboarding_accounts(self):
        self.client.logout()
        for url in (self.status_url, self.page_url):
            self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.post(self.confirm_url).status_code, 302)
        self.client.force_login(self.user)
        self.user.utype = User.Type.UNAUTHORIZED
        self.user.save(update_fields=['utype'])
        self.assertRedirects(self.client.get(self.status_url), '/logout/',
                             fetch_redirect_response=False)
        self.user.utype = User.Type.STUDENT
        self.user.is_newuser = True
        self.user.save(update_fields=['utype', 'is_newuser'])
        self.assertRedirects(self.client.get(self.status_url), '/agreement/',
                             fetch_redirect_response=False)
        self.assertRedirects(self.client.post(self.confirm_url), '/agreement/',
                             fetch_redirect_response=False)

    def test_inactive_and_organization_accounts_keep_existing_agreement_rules(self):
        # 无需住宿协议的账户只要存在 Participant，仍可阅读并确认。
        self.user.active = False
        self.user.save(update_fields=['active'])
        self.assertEqual(self.client.get(self.status_url).json(), {
            'needs_dormitory_agreement': False, 'needs_instructions': True,
        })
        org = User.objects.create_user('OREAD001', '组织', User.Type.ORG,
                                       password='test', is_newuser=False)
        participant = Participant.objects.create(Sid=org)
        self.client.force_login(org)
        self.assertEqual(self.client.get(self.status_url).json(), {
            'needs_dormitory_agreement': False, 'needs_instructions': True,
        })
        self.assertEqual(self.client.post(self.confirm_url).status_code, 302)
        participant.refresh_from_db()
        self.assertTrue(participant.has_read_instructions)
        self.assertFalse(Agreement.objects.filter(user=org).exists())

    def test_missing_appointment_permission_does_not_block_reading_rules(self):
        self.sign()
        self.user.naturalperson.revoke_permission('underground_appointment')
        self.assertEqual(self.client.get(self.page_url).status_code, 200)
        self.assertEqual(self.client.post(self.confirm_url).status_code, 302)


class InstructionsMiddlewareTests(TestCase):
    def setUp(self):
        self.user, _ = _person('SREAD003', '页面测试')
        self.factory = RequestFactory()

    def apply(self, response, user=None, method='get'):
        request = getattr(self.factory, method)('/any/page/')
        request.user = self.user if user is None else user
        return InstructionsReminderMiddleware(lambda request: response)(request)

    def test_standalone_html_and_post_html_include_script_once(self):
        for method in ('get', 'post'):
            response = HttpResponse('<html><body>独立页面</body></html>')
            response['Content-Length'] = len(response.content)
            response = self.apply(response, method=method)
            self.assertContains(response, 'dorm_forcement.js', count=1)
            self.assertEqual(int(response['Content-Length']), len(response.content))

    def test_non_pages_and_anonymous_responses_are_unchanged(self):
        for response in (JsonResponse({'a': 1}),
                         HttpResponse('<body>error</body>', status=403),
                         HttpResponse('<div>fragment</div>'),
                         HttpResponse('<body>download</body>', headers={
                             'Content-Disposition': 'attachment'})):
            original = response.content
            self.assertEqual(self.apply(response).content, original)
        stream = StreamingHttpResponse(iter([b'<body>stream</body>']))
        self.assertIs(self.apply(stream), stream)
        page = HttpResponse('<body>login</body>')
        self.assertNotContains(self.apply(page, AnonymousUser()), 'dorm_forcement.js')
        self.user.is_newuser = True
        self.assertNotContains(self.apply(page), 'dorm_forcement.js')
