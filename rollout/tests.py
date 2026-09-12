'''
Tests for the rollout app: evaluation rules, audience validation, preview
channel membership, website guard, template context and the feedback setup
command. API behavior is tested in ``api/rollout/tests.py``.
'''
from io import StringIO
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.template import RequestContext, Template
from django.test import RequestFactory, TestCase

from generic.models import User
from app.models import NaturalPerson, Organization, OrganizationType
from feedback.models import FeedbackType
from rollout.api import (
    PreviewJoinDenied,
    Reason,
    enabled_features,
    evaluate_features,
    is_feature_enabled,
    join_preview,
    leave_preview,
    preview_join_block,
    rollout_bucket,
)
from rollout.config import CONFIG, RolloutConfig
from rollout.context_processors import rollout_features
from rollout.models import Feature, PreviewMember, validate_audience
from rollout.permissions import feature_required


Stage = Feature.Stage


def create_person(username: str, *, usertype=User.Type.STUDENT,
                  **person_fields) -> User:
    user = User.objects.create_user(
        username=username, name=username, usertype=usertype,
        password='testpass123')
    # NaturalPerson.name holds at most 10 characters.
    NaturalPerson.objects.create(user, name='测试用户', **person_fields)
    return user


def create_org_user(username: str) -> User:
    return User.objects.create_user(
        username=username, name=username, usertype=User.Type.ORG,
        password='testpass123')


def create_feature(key: str = 'demo', **fields) -> Feature:
    return Feature.objects.create(key=key, name=key, **fields)


class FeatureEvaluationTests(TestCase):
    def setUp(self):
        self.student = create_person('rollout-student', stu_grade='2026')
        self.counselor = create_person(
            'rollout-counselor',
            status=NaturalPerson.GraduateStatus.INSTRUCTOR)
        self.org_user = create_org_user('rollout-org')

    def test_unknown_key_is_disabled(self):
        self.assertFalse(is_feature_enabled(self.student, 'missing'))

    def test_off_disables_even_the_allow_list(self):
        feature = create_feature(stage=Stage.OFF)
        feature.allow_users.add(self.student)
        PreviewMember.objects.create(user=self.student)
        self.assertFalse(is_feature_enabled(self.student, 'demo'))
        self.assertEqual(enabled_features(self.student), {})

    def test_ga_is_enabled_for_everyone_including_anonymous(self):
        create_feature(stage=Stage.GA)
        for user in (self.student, self.org_user, AnonymousUser(), None):
            with self.subTest(user=user):
                self.assertTrue(is_feature_enabled(user, 'demo'))
        [decision] = evaluate_features(self.student)
        self.assertEqual(decision.reason, Reason.GA)

    def test_anonymous_only_gets_ga_features(self):
        for stage in (Stage.INTERNAL, Stage.PREVIEW, Stage.ROLLOUT):
            create_feature(key=f'demo-{stage}', stage=stage, percent=100,
                           audience={'utype': list(User.Type.values)})
        self.assertEqual(enabled_features(AnonymousUser()), {})
        self.assertEqual(enabled_features(None), {})

    def test_internal_only_allows_the_allow_list(self):
        feature = create_feature(
            stage=Stage.INTERNAL,
            audience={'status': [NaturalPerson.GraduateStatus.INSTRUCTOR]})
        feature.allow_users.add(self.student)
        PreviewMember.objects.create(user=self.counselor)

        [decision] = evaluate_features(self.student, [feature])
        self.assertEqual((decision.enabled, decision.reason),
                         (True, Reason.ALLOWLIST))
        # Neither membership nor a matching audience applies internally.
        self.assertFalse(is_feature_enabled(self.counselor, 'demo'))

    def test_preview_allows_members(self):
        create_feature(stage=Stage.PREVIEW)
        self.assertFalse(is_feature_enabled(self.student, 'demo'))

        PreviewMember.objects.create(user=self.student)
        [decision] = evaluate_features(self.student)
        self.assertEqual((decision.enabled, decision.reason),
                         (True, Reason.PREVIEW))

    def test_preview_allows_matching_audience(self):
        create_feature(
            stage=Stage.PREVIEW,
            audience={'status': [NaturalPerson.GraduateStatus.INSTRUCTOR]})
        [decision] = evaluate_features(self.counselor)
        self.assertEqual((decision.enabled, decision.reason),
                         (True, Reason.AUDIENCE))
        self.assertFalse(is_feature_enabled(self.student, 'demo'))

    def test_audience_requires_every_listed_key(self):
        feature = create_feature(
            stage=Stage.PREVIEW,
            audience={'identity': [NaturalPerson.Identity.STUDENT],
                      'stu_grade': ['2025']})
        self.assertFalse(is_feature_enabled(self.student, 'demo'))

        feature.audience['stu_grade'] = ['2025', '2026']
        feature.save()
        self.assertTrue(is_feature_enabled(self.student, 'demo'))

    def test_person_audience_never_matches_organizations(self):
        create_feature(stage=Stage.PREVIEW, audience={'identity': [0, 1]})
        self.assertFalse(is_feature_enabled(self.org_user, 'demo'))

    def test_utype_audience_matches_organizations(self):
        create_feature(stage=Stage.PREVIEW,
                       audience={'utype': [User.Type.ORG]})
        self.assertTrue(is_feature_enabled(self.org_user, 'demo'))
        self.assertFalse(is_feature_enabled(self.student, 'demo'))

    def test_preview_stage_ignores_percent(self):
        create_feature(stage=Stage.PREVIEW, percent=100)
        self.assertFalse(is_feature_enabled(self.student, 'demo'))

    def test_rollout_uses_the_stable_bucket(self):
        feature = create_feature(stage=Stage.ROLLOUT, percent=0)
        self.assertFalse(is_feature_enabled(self.student, 'demo'))

        bucket = rollout_bucket(self.student.username, 'demo')
        feature.percent = bucket
        feature.save()
        self.assertFalse(is_feature_enabled(self.student, 'demo'))

        feature.percent = bucket + 1
        feature.save()
        [decision] = evaluate_features(self.student)
        self.assertEqual((decision.enabled, decision.reason),
                         (True, Reason.ROLLOUT))

    def test_rollout_keeps_members_and_the_allow_list(self):
        feature = create_feature(stage=Stage.ROLLOUT, percent=0)
        PreviewMember.objects.create(user=self.student)
        feature.allow_users.add(self.counselor)
        self.assertTrue(is_feature_enabled(self.student, 'demo'))
        self.assertTrue(is_feature_enabled(self.counselor, 'demo'))

    def test_full_rollout_enables_every_logged_in_account(self):
        create_feature(stage=Stage.ROLLOUT, percent=100)
        self.assertTrue(is_feature_enabled(self.org_user, 'demo'))
        self.assertFalse(is_feature_enabled(AnonymousUser(), 'demo'))

    def test_unexpected_stored_stage_fails_closed(self):
        feature = create_feature(stage=Stage.PREVIEW)
        feature.allow_users.add(self.student)
        Feature.objects.filter(pk=feature.pk).update(stage='bogus')
        self.assertFalse(is_feature_enabled(self.student, 'demo'))

    def test_unknown_stored_audience_key_fails_closed(self):
        feature = create_feature(stage=Stage.PREVIEW)
        Feature.objects.filter(pk=feature.pk).update(
            audience={'unknown': ['x']})
        self.assertFalse(is_feature_enabled(self.student, 'demo'))
        self.assertFalse(is_feature_enabled(self.org_user, 'demo'))

    def test_bucket_is_deterministic_and_differs_between_features(self):
        self.assertEqual(rollout_bucket('u1', 'a'), rollout_bucket('u1', 'a'))
        buckets_a = [rollout_bucket(f'user{i}', 'a') for i in range(50)]
        buckets_b = [rollout_bucket(f'user{i}', 'b') for i in range(50)]
        self.assertTrue(all(0 <= bucket < 100 for bucket in buckets_a))
        self.assertNotEqual(buckets_a, buckets_b)

    def test_query_count_does_not_grow_with_features(self):
        for index in range(5):
            create_feature(key=f'demo-{index}', stage=Stage.PREVIEW,
                           audience={'identity': [1]})
        # Features, allow list, membership and person attributes.
        with self.assertNumQueries(4):
            result = enabled_features(self.student)
        self.assertEqual(len(result), 5)


class FeatureValidationTests(TestCase):
    def test_accepts_documented_keys(self):
        validate_audience({})
        validate_audience({
            'utype': [User.Type.STUDENT],
            'identity': [NaturalPerson.Identity.STUDENT],
            'status': [NaturalPerson.GraduateStatus.INSTRUCTOR],
            'stu_grade': ['2026'],
        })

    def test_rejects_malformed_audience(self):
        invalid_values = [
            [],
            {'unknown': [1]},
            {'identity': 1},
            {'identity': []},
            {'identity': ['1']},
            {'identity': [True]},
            {'status': [99]},
            {'utype': ['Robot']},
            {'stu_grade': [2026]},
        ]
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_audience(value)

    def test_full_clean_rejects_percent_above_100(self):
        feature = Feature(key='demo', name='demo', percent=101)
        with self.assertRaises(ValidationError):
            feature.full_clean()

    def test_database_rejects_percent_above_100(self):
        feature = create_feature()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Feature.objects.filter(pk=feature.pk).update(percent=101)


class PreviewMembershipTests(TestCase):
    def setUp(self):
        patcher = mock.patch.object(RolloutConfig, 'preview_open', True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.student = create_person('preview-student')
        self.org_user = create_org_user('preview-org')

    def test_person_joins_and_leaves_idempotently(self):
        self.assertIsNone(preview_join_block(self.student))
        first = join_preview(self.student)
        second = join_preview(self.student)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(PreviewMember.objects.count(), 1)

        self.assertTrue(leave_preview(self.student))
        self.assertFalse(leave_preview(self.student))

    def test_organization_cannot_join(self):
        with self.assertRaises(PreviewJoinDenied) as context:
            join_preview(self.org_user)
        self.assertEqual(context.exception.code, 'preview_person_only')
        self.assertFalse(PreviewMember.objects.exists())

    def test_inactive_person_cannot_join(self):
        self.student.active = False
        self.student.save(update_fields=['active'])
        with self.assertRaises(PreviewJoinDenied) as context:
            join_preview(self.student)
        self.assertEqual(context.exception.code, 'preview_inactive')

    def test_closed_channel_blocks_joining_but_not_leaving(self):
        PreviewMember.objects.create(user=self.student)
        with mock.patch.object(RolloutConfig, 'preview_open', False):
            with self.assertRaises(PreviewJoinDenied) as context:
                join_preview(self.student)
            self.assertEqual(context.exception.code, 'preview_closed')
            self.assertTrue(leave_preview(self.student))

    def test_member_added_by_administrator_can_leave(self):
        PreviewMember.objects.create(user=self.org_user)
        self.assertTrue(leave_preview(self.org_user))


class FeatureRequiredTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.student = create_person('guard-student')

        @feature_required('demo')
        def view(request):
            return HttpResponse('ok')
        self.view = view

    def _request(self):
        request = self.factory.get('/demo/')
        request.user = self.student
        return request

    def test_disabled_feature_raises_permission_denied(self):
        create_feature(stage=Stage.PREVIEW)
        with self.assertRaises(PermissionDenied):
            self.view(self._request())

    def test_enabled_feature_calls_the_view(self):
        feature = create_feature(stage=Stage.INTERNAL)
        feature.allow_users.add(self.student)
        self.assertEqual(self.view(self._request()).status_code, 200)


class RolloutFeaturesContextTests(TestCase):
    def setUp(self):
        self.student = create_person('context-student')
        create_feature(stage=Stage.GA)
        self.request = RequestFactory().get('/')
        self.request.user = self.student

    def test_features_are_evaluated_on_first_use(self):
        with self.assertNumQueries(0):
            context = rollout_features(self.request)
        with self.assertNumQueries(3):
            self.assertTrue(context['rollout_features']['demo'])

    def test_template_reads_enabled_and_missing_features(self):
        template = Template(
            '{% if rollout_features.demo %}on{% endif %}'
            '{% if rollout_features.missing %}bad{% endif %}'
        )
        self.assertEqual(template.render(RequestContext(self.request)), 'on')


class SetupPreviewFeedbackCommandTests(TestCase):
    def setUp(self):
        teacher_user = create_person(
            'setup-teacher', usertype=User.Type.TEACHER,
            identity=NaturalPerson.Identity.TEACHER)
        self.otype = OrganizationType.objects.create(
            otype_id=110,
            otype_name='项目组类型',
            incharge=NaturalPerson.objects.get(person_id=teacher_user),
            job_name_list=['成员'],
        )

    def _create_org(self, oname: str) -> Organization:
        user = create_org_user(f'setup-org-{Organization.objects.count()}')
        return Organization.objects.create(
            organization_id=user, oname=oname, otype=self.otype)

    def _call(self) -> str:
        output = StringIO()
        call_command('setup_preview_feedback', stdout=output)
        return output.getvalue()

    def test_missing_receiving_group_fails(self):
        with self.assertRaises(CommandError):
            self._call()
        self.assertFalse(FeedbackType.objects.filter(
            name=CONFIG.feedback_type_name).exists())

    def test_creates_type_with_next_id_and_is_idempotent(self):
        org = self._create_org(CONFIG.feedback_org_name)
        FeedbackType.objects.create(id=7, name='已有类型')

        self._call()
        created = FeedbackType.objects.get(name=CONFIG.feedback_type_name)
        self.assertEqual(created.id, 8)
        self.assertEqual(created.org, org)
        self.assertEqual(created.org_type, self.otype)
        self.assertEqual(created.flexible, FeedbackType.Flexible.ALL_DEFAULT)

        self._call()
        self.assertEqual(FeedbackType.objects.filter(
            name=CONFIG.feedback_type_name).count(), 1)

    def test_existing_type_pointing_elsewhere_fails(self):
        self._create_org(CONFIG.feedback_org_name)
        other = self._create_org('其他小组')
        FeedbackType.objects.create(
            id=1, name=CONFIG.feedback_type_name,
            org=other, org_type=self.otype)
        with self.assertRaises(CommandError):
            self._call()
