"""
Serializers (schema) for the rollout API.
"""
from rest_framework import serializers

from rollout.api import Reason
from rollout.models import Feature


class ExperimentSerializer(serializers.Serializer):
    """A feature listed on the preview channel page."""

    key = serializers.CharField(help_text="功能标识")
    name = serializers.CharField(help_text="功能名称")
    description = serializers.CharField(help_text="功能说明")
    stage = serializers.ChoiceField(
        choices=Feature.Stage.choices, help_text="灰度阶段")
    enabled = serializers.BooleanField(help_text="当前账号能否使用")
    reason = serializers.ChoiceField(
        choices=[(reason.value, reason.value) for reason in Reason],
        allow_null=True,
        help_text="可以使用的原因；不能使用时为 null",
    )


class PreviewStateSerializer(serializers.Serializer):
    """Preview channel membership of the current account."""

    joined = serializers.BooleanField(help_text="是否已加入体验通道")
    joined_at = serializers.DateTimeField(allow_null=True, help_text="加入时间")
    can_join = serializers.BooleanField(help_text="能否自助加入体验通道")
    join_block_code = serializers.CharField(
        allow_null=True,
        help_text="不能加入的原因代码：preview_closed / preview_person_only / preview_inactive",
    )
    join_block_message = serializers.CharField(
        allow_null=True, help_text="不能加入的原因说明")


class FeedbackRoutingSerializer(serializers.Serializer):
    """Where preview feedback is sent."""

    type_name = serializers.CharField(help_text="反馈类型名称")
    org_type_name = serializers.CharField(help_text="接收小组类型名称")
    org_name = serializers.CharField(help_text="接收小组名称")


class RolloutStateSerializer(serializers.Serializer):
    """Rollout state of the current account."""

    account = serializers.CharField(
        help_text="这份状态所属账号的 username；客户端据此核对，避免把开关记到另一个账号名下",
    )
    features = serializers.DictField(
        child=serializers.BooleanField(),
        help_text="当前账号可以使用的功能，键为功能标识；未列出的功能不可用",
    )
    experiments = ExperimentSerializer(many=True, help_text="体验中的功能")
    preview = PreviewStateSerializer(help_text="体验通道状态")
    feedback = FeedbackRoutingSerializer(
        allow_null=True, help_text="体验反馈的发送目标；未配置时为 null")
