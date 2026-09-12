'''
Models of the rollout app.

A :class:`Feature` is a runtime switch for one experimental capability and a
:class:`PreviewMember` is an account that opted in to try such features. The
evaluation rules live in :mod:`rollout.api`; see ``rollout/README.md``.
'''
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models

from generic.models import User
from app.models import NaturalPerson

__all__ = [
    'AUDIENCE_KEYS',
    'PERSON_AUDIENCE_KEYS',
    'validate_audience',
    'Feature',
    'PreviewMember',
]


# Audience keys and the scalar type of their values. Only `utype` describes
# every account; the other keys describe a natural person.
AUDIENCE_KEYS: dict[str, type] = {
    'utype': str,
    'identity': int,
    'status': int,
    'stu_grade': str,
}
PERSON_AUDIENCE_KEYS = frozenset({'identity', 'status', 'stu_grade'})

# Keys whose values must be one of the model choices, to catch typos early.
_AUDIENCE_CHOICES: dict[str, list[Any]] = {
    'utype': list(User.Type.values),
    'identity': list(NaturalPerson.Identity.values),
    'status': list(NaturalPerson.GraduateStatus.values),
}


def validate_audience(value: Any) -> None:
    '''
    Validate the JSON stored in :attr:`Feature.audience`.

    The value must be a dict whose keys come from :data:`AUDIENCE_KEYS` and
    whose values are non-empty lists of the declared scalar type. An empty dict
    targets nobody.

    :raises ValidationError: The value does not follow this schema.
    '''
    if not isinstance(value, dict):
        raise ValidationError('定向人群必须是 JSON 对象。')
    for key, items in value.items():
        if key not in AUDIENCE_KEYS:
            raise ValidationError(f'定向人群不支持字段「{key}」。')
        if not isinstance(items, list) or not items:
            raise ValidationError(f'定向人群字段「{key}」必须是非空列表。')
        expected = AUDIENCE_KEYS[key]
        # bool is a subclass of int, so it has to be rejected explicitly.
        if any(isinstance(item, bool) or not isinstance(item, expected)
               for item in items):
            raise ValidationError(
                f'定向人群字段「{key}」的取值应为 {expected.__name__}。')
        allowed = _AUDIENCE_CHOICES.get(key)
        if allowed is not None:
            unknown = [item for item in items if item not in allowed]
            if unknown:
                raise ValidationError(
                    f'定向人群字段「{key}」包含无效取值：{unknown}。')


class FeatureQuerySet(models.QuerySet):
    def live(self) -> 'FeatureQuerySet':
        '''Features that are not switched off.'''
        return self.exclude(stage=Feature.Stage.OFF)


class Feature(models.Model):
    '''
    One experimental capability released gradually.

    Stages widen access cumulatively, except ``OFF``, which disables the
    feature for everyone including the allow list:

    - ``INTERNAL``: ``allow_users`` only.
    - ``PREVIEW``: additionally preview channel members and ``audience``.
    - ``ROLLOUT``: additionally ``percent`` percent of logged-in accounts,
      chosen by a stable per-account bucket.
    - ``GA``: everyone, including anonymous visitors.

    ``key`` is referenced from code and the mini program and must not change
    once released.
    '''
    class Meta:
        verbose_name = '灰度功能'
        verbose_name_plural = verbose_name
        ordering = ['key']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(percent__lte=100),
                name='rollout_feature_percent_lte_100',
            ),
        ]

    class Stage(models.TextChoices):
        OFF = 'off', '关闭'
        INTERNAL = 'internal', '内测（仅白名单）'
        PREVIEW = 'preview', '体验（白名单、体验通道、定向人群）'
        ROLLOUT = 'rollout', '放量（体验范围之外再按比例）'
        GA = 'ga', '全量'

    key = models.SlugField(
        '功能标识', max_length=64, unique=True,
        help_text='代码和小程序里引用的标识，发布后不要修改',
    )
    name = models.CharField('功能名称', max_length=64)
    description = models.TextField(
        '功能说明', blank=True, default='',
        help_text='展示在体验通道页面：这个功能是什么、希望收到哪些反馈',
    )
    stage = models.CharField(
        '阶段', max_length=16, choices=Stage.choices, default=Stage.OFF)
    percent = models.PositiveSmallIntegerField(
        '放量比例', default=0, validators=[MaxValueValidator(100)],
        help_text='0 到 100，只在「放量」阶段生效；同一账号的结果固定不变',
    )
    allow_users = models.ManyToManyField(
        User, verbose_name='白名单', blank=True,
        related_name='rollout_allowed_features',
        help_text='开发组成员、提审测试号等；除「关闭」外的所有阶段都生效',
    )
    audience = models.JSONField(
        '定向人群', default=dict, blank=True, validators=[validate_audience],
        help_text=(
            '例如 {"status": [2]} 表示住宿辅导员；'
            '写多个字段时须全部满足，同一字段内任一取值即可'
        ),
    )
    owner = models.CharField('负责人', max_length=32, blank=True, default='')
    review_date = models.DateField(
        '复查日期', null=True, blank=True,
        help_text='到期时决定全量、继续体验或下线',
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    objects = FeatureQuerySet.as_manager()

    def __str__(self) -> str:
        return f'{self.name} ({self.key})'


class PreviewMember(models.Model):
    '''
    An account in the preview channel (体验通道).

    Members may use every feature in the ``PREVIEW`` or ``ROLLOUT`` stage.
    Active personal accounts join and leave through :mod:`rollout.api`;
    administrators may add or remove any account in the admin site.
    '''
    class Meta:
        verbose_name = '体验通道成员'
        verbose_name_plural = verbose_name

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='preview_membership',
        verbose_name='账号',
    )
    joined_at = models.DateTimeField('加入时间', auto_now_add=True)

    def __str__(self) -> str:
        return self.user.username
