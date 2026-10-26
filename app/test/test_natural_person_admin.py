"""Regression coverage for natural-person creation in Django admin."""

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from app.admin import NaturalPersonAdmin
from app.models import NaturalPerson
from generic.models import User


class NaturalPersonAdminTests(TestCase):
    """Exercise the actual admin add form and submission."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('admin-test', 'Admin')
        cls.user = User.objects.create_user(
            'person-test', 'Person', User.Type.PERSON,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_add_page(self):
        """The add page renders before a person exists."""
        response = self.client.get(reverse('admin:app_naturalperson_add'))
        self.assertEqual(response.status_code, 200)

    def test_create_person(self):
        """A valid admin submission persists the profile and account ID."""
        url = reverse('admin:app_naturalperson_add')
        add_page = self.client.get(url)
        data = {
            'person_id': self.user.pk,
            'name': 'Person',
            'identity': NaturalPerson.Identity.STUDENT,
            'status': NaturalPerson.GraduateStatus.UNDERGRADUATED,
            'wechat_receive_level': NaturalPerson.ReceiveLevel.MORE,
            'active_score': 0,
            'select_course': 'on',
            'gain_credit': 'on',
            '_save': 'Save',
        }
        for inline in add_page.context['inline_admin_formsets']:
            prefix = inline.formset.prefix
            data[f'{prefix}-TOTAL_FORMS'] = 0
            data[f'{prefix}-INITIAL_FORMS'] = 0
        response = self.client.post(url, data)
        if response.status_code == 200:
            self.fail(response.context['adminform'].form.errors)
        self.assertEqual(response.status_code, 302)
        person = NaturalPerson.objects.get(person_id=self.user)
        self.assertEqual(person.name, 'Person')
        self.assertEqual(person.stu_id_dbonly, self.user.username)
        self.assertEqual(person.permissions, {
            'select_course': True,
            'underground_appointment': False,
            'gain_credit': True,
        })

    def test_save_without_commit_does_not_write(self):
        """Editing permissions respects the ModelForm deferred-save contract."""
        person = NaturalPerson.objects.create(self.user, name='Person')
        person.permissions = {'select_course': False, 'other_permission': True}
        person.save(update_fields=['permissions'])
        request = RequestFactory().get('/')
        request.user = self.admin
        form_class = NaturalPersonAdmin(NaturalPerson, admin.site).get_form(
            request, person,
        )
        form = form_class(data={
            'person_id': self.user.pk,
            'name': 'Person',
            'identity': person.identity,
            'status': person.status,
            'wechat_receive_level': person.wechat_receive_level,
            'active_score': 0,
            'select_course': 'on',
        }, instance=person)
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertNumQueries(0):
            edited = form.save(commit=False)
        stored = NaturalPerson.objects.get(pk=person.pk)
        self.assertFalse(stored.permissions['select_course'])
        edited.save()
        person.refresh_from_db()
        self.assertTrue(person.permissions['select_course'])
        self.assertTrue(person.permissions['other_permission'])

    def test_set_permission_saves_by_default(self):
        """Existing callers still persist permission changes immediately."""
        person = NaturalPerson.objects.create(self.user, name='Person')
        person.set_permission('select_course', False)
        person.refresh_from_db()
        self.assertIs(person.permissions['select_course'], False)

    def test_set_permission_can_defer_new_person_save(self):
        """Deferred permission changes work before the profile has a primary key."""
        person = NaturalPerson(person_id=self.user, name='Person')
        with self.assertNumQueries(0):
            person.set_permission('select_course', True, defer_save=True)
        self.assertIsNone(person.pk)
        self.assertIs(person.permissions['select_course'], True)
        person.save()
        person.refresh_from_db()
        self.assertIs(person.permissions['select_course'], True)
