'''
Public interface of the rollout app.

Other applications decide whether an account may use an experimental feature
only through these functions, so the website, the mini-program API, templates
and scheduled jobs apply the same rules. See ``rollout/README.md``.
'''
import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable

from boot.config import GLOBAL_CONFIG
from generic.models import User
from app.models import NaturalPerson, Organization
from rollout.config import CONFIG
from rollout.models import Feature, PreviewMember, PERSON_AUDIENCE_KEYS

__all__ = [
    'Reason',
    'FeatureDecision',
    'PreviewJoinDenied',
    'rollout_bucket',
    'evaluate_features',
    'enabled_features',
    'is_feature_enabled',
    'preview_membership',
    'preview_join_block',
    'join_preview',
    'leave_preview',
    'preview_feedback_routing_errors',
]


class Reason(StrEnum):
    '''Why a feature is enabled for an account.'''
    GA = 'ga'
    ALLOWLIST = 'allowlist'
    PREVIEW = 'preview'
    AUDIENCE = 'audience'
    ROLLOUT = 'rollout'


@dataclass(frozen=True)
class FeatureDecision:
    '''The result of evaluating one feature for one account.

    ``reason`` is ``None`` exactly when ``enabled`` is ``False``.
    '''
    feature: Feature
    enabled: bool
    reason: Reason | None


class PreviewJoinDenied(Exception):
    '''
    An account may not join the preview channel.

    ``code`` is a stable machine-readable identifier documented in
    ``rollout/README.md``; ``message`` can be shown to the user.
    '''

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def rollout_bucket(username: str, feature_key: str) -> int:
    '''
    Return the stable rollout bucket of an account, in ``range(100)``.

    The bucket depends on the global hash salt, the feature key and the
    username. One account always gets the same bucket for a feature, while
    different features sample different cohorts. Changing the salt reshuffles
    every rollout.
    '''
    source = f'{GLOBAL_CONFIG.salt}:{feature_key}:{username}'.encode()
    digest = hashlib.sha256(source).digest()
    return int.from_bytes(digest[:8], 'big') % 100


def _audience_matches(audience: dict[str, list[Any]], user: User,
                      person_attrs: dict[str, Any] | None) -> bool:
    # All listed keys must match; values inside one key are alternatives.
    if not audience:
        return False
    for key, allowed in audience.items():
        if key == 'utype':
            actual = user.utype
        elif person_attrs is None:
            return False
        else:
            actual = person_attrs.get(key)
        if actual not in allowed:
            return False
    return True


def _decide(feature: Feature, user: User, *, allowed: bool, is_member: bool,
            person_attrs: dict[str, Any] | None) -> FeatureDecision:
    # The order of the checks defines the reported reason; it is documented in
    # rollout/README.md and must stay in sync with it.
    stage = feature.stage
    if stage == Feature.Stage.GA:
        return FeatureDecision(feature, True, Reason.GA)
    if stage not in (Feature.Stage.INTERNAL, Feature.Stage.PREVIEW,
                     Feature.Stage.ROLLOUT):
        # OFF, and any unexpected stored value, fails closed.
        return FeatureDecision(feature, False, None)
    if allowed:
        return FeatureDecision(feature, True, Reason.ALLOWLIST)
    if stage == Feature.Stage.INTERNAL:
        return FeatureDecision(feature, False, None)
    if is_member:
        return FeatureDecision(feature, True, Reason.PREVIEW)
    if _audience_matches(feature.audience, user, person_attrs):
        return FeatureDecision(feature, True, Reason.AUDIENCE)
    if (stage == Feature.Stage.ROLLOUT
            and rollout_bucket(user.username, feature.key) < feature.percent):
        return FeatureDecision(feature, True, Reason.ROLLOUT)
    return FeatureDecision(feature, False, None)


def evaluate_features(user: User | Any | None,
                      features: Iterable[Feature] | None = None,
                      ) -> list[FeatureDecision]:
    '''
    Evaluate features for an account.

    The number of queries does not depend on the number of features.

    :param user: The current account; ``None`` or an anonymous user only gets
        ``GA`` features.
    :param features: Features to evaluate, defaulting to every feature that is
        not switched off.
    :return: One decision per feature, in the given order.
    '''
    if features is None:
        features = Feature.objects.live()
    features = list(features)
    if not features:
        return []

    if user is None or not user.is_authenticated:
        return [
            FeatureDecision(feature, feature.stage == Feature.Stage.GA,
                            Reason.GA if feature.stage == Feature.Stage.GA else None)
            for feature in features
        ]

    allowed_ids = set(
        Feature.allow_users.through.objects
        .filter(user_id=user.pk, feature_id__in=[f.pk for f in features])
        .values_list('feature_id', flat=True)
    )
    is_member = PreviewMember.objects.filter(user_id=user.pk).exists()
    person_attrs = None
    needs_person = any(
        isinstance(feature.audience, dict)
        and PERSON_AUDIENCE_KEYS.intersection(feature.audience)
        for feature in features
    )
    if needs_person and user.is_person():
        person_attrs = (
            NaturalPerson.objects
            .filter(person_id=user)
            .values('identity', 'status', 'stu_grade')
            .first()
        )
    return [
        _decide(feature, user, allowed=feature.pk in allowed_ids,
                is_member=is_member, person_attrs=person_attrs)
        for feature in features
    ]


def enabled_features(user: User | Any | None) -> dict[str, bool]:
    '''
    Return ``{key: True}`` for every feature enabled for the account.

    Disabled features are omitted, so callers treat a missing key as disabled.
    '''
    return {
        decision.feature.key: True
        for decision in evaluate_features(user)
        if decision.enabled
    }


def is_feature_enabled(user: User | Any | None, feature_key: str) -> bool:
    '''
    Return whether one feature is enabled for the account.

    A key without a :class:`Feature` row is disabled, so code may reference a
    feature before an administrator creates it.
    '''
    feature = Feature.objects.filter(key=feature_key).first()
    if feature is None:
        return False
    return evaluate_features(user, [feature])[0].enabled


def preview_membership(user: User) -> PreviewMember | None:
    '''Return the preview channel membership of the account, if any.'''
    return PreviewMember.objects.filter(user_id=user.pk).first()


def preview_join_block(user: User) -> PreviewJoinDenied | None:
    '''
    Return why the account may not join the preview channel by itself.

    Only active personal accounts may join, and only while the channel is open.
    Administrators can still add any account in the admin site.

    :return: The reason, or ``None`` when the account may join.
    '''
    if not CONFIG.preview_open:
        return PreviewJoinDenied('preview_closed', '体验通道暂未开放加入。')
    if not user.is_person():
        return PreviewJoinDenied(
            'preview_person_only', '只有个人账号可以加入体验通道。')
    if not user.active:
        return PreviewJoinDenied(
            'preview_inactive', '当前账号已毕业或离职，不能加入体验通道。')
    return None


def join_preview(user: User) -> PreviewMember:
    '''
    Add the account to the preview channel. Joining twice has no effect.

    :raises PreviewJoinDenied: The account may not join by itself.
    '''
    denied = preview_join_block(user)
    if denied is not None:
        raise denied
    member, _ = PreviewMember.objects.get_or_create(user=user)
    return member


def leave_preview(user: User) -> bool:
    '''
    Remove the account from the preview channel.

    Leaving is always allowed, including for accounts added by an
    administrator.

    :return: Whether the account was a member.
    '''
    deleted, _ = PreviewMember.objects.filter(user_id=user.pk).delete()
    return deleted > 0


def preview_feedback_routing_errors(type_name: str | None, otype_name: str,
                                    org_name: str) -> dict[str, str]:
    '''
    Check that feedback about an experimental feature keeps its routing.

    Feedback with a ``feature_key`` must use the configured preview feedback
    type and receiving group. Every entry point that writes the type or the
    receiving group of such feedback — the mini-program API and the website —
    must call this. Empty ``otype_name`` or ``org_name`` are accepted because
    drafts may omit them; submission requires both separately.

    :param type_name: Name of the feedback type, or ``None`` when unknown.
    :param otype_name: Name of the receiving group type, possibly empty.
    :param org_name: Name of the receiving group, possibly empty.
    :return: Error message by field name (``type``, ``otype``, ``org``);
        empty when the routing is valid.
    '''
    errors: dict[str, str] = {}
    expected_type = CONFIG.feedback_type_name
    expected_org = CONFIG.feedback_org_name
    if type_name != expected_type:
        errors['type'] = f'体验反馈的类型须为「{expected_type}」。'
    if org_name and org_name != expected_org:
        errors['org'] = f'体验反馈只能发给「{expected_org}」。'
    elif otype_name:
        expected_otype = (
            Organization.objects.filter(oname=expected_org)
            .values_list('otype__otype_name', flat=True)
            .first()
        )
        if otype_name != expected_otype:
            errors['otype'] = f'体验反馈的接收小组类型须与「{expected_org}」一致。'
    return errors
