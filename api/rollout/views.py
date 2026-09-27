"""
REST APIs for feature rollout and the preview channel.
"""
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import WxJWTAuthentication
from app.models import Organization
from feedback.models import FeedbackType
from rollout.api import (
    PreviewJoinDenied,
    evaluate_features,
    join_preview,
    leave_preview,
    preview_join_block,
    preview_membership,
)
from rollout.config import CONFIG
from rollout.models import Feature
from api.rollout.serializers import RolloutStateSerializer


# INTERNAL features are listed only for allow-listed accounts, and GA features
# are no longer experiments.
_PUBLIC_EXPERIMENT_STAGES = (Feature.Stage.PREVIEW, Feature.Stage.ROLLOUT)

_UNAUTHENTICATED_RESPONSE = OpenApiResponse(description="未登录或登录已过期")


def _feedback_routing() -> dict | None:
    # Preview feedback can only be sent once both the type and group exist.
    feedback_type = FeedbackType.objects.filter(
        name=CONFIG.feedback_type_name).first()
    org = (
        Organization.objects.select_related("otype")
        .filter(oname=CONFIG.feedback_org_name).first()
    )
    if feedback_type is None or org is None:
        return None
    return {
        "type_name": feedback_type.name,
        "org_type_name": org.otype.otype_name,
        "org_name": org.oname,
    }


def _rollout_state(user) -> dict:
    # Assemble the body shared by every endpoint of this module.
    decisions = evaluate_features(user)
    experiments = [
        {
            "key": decision.feature.key,
            "name": decision.feature.name,
            "description": decision.feature.description,
            "stage": decision.feature.stage,
            "enabled": decision.enabled,
            "reason": decision.reason.value if decision.reason is not None else None,
        }
        for decision in decisions
        if decision.feature.stage in _PUBLIC_EXPERIMENT_STAGES
        or (decision.feature.stage == Feature.Stage.INTERNAL and decision.enabled)
    ]
    membership = preview_membership(user)
    block = preview_join_block(user)
    return {
        # The account the state was evaluated for, so a client whose local
        # account is stale can refuse to store it under the wrong account.
        "account": user.username,
        "features": {
            decision.feature.key: True
            for decision in decisions if decision.enabled
        },
        "experiments": experiments,
        "preview": {
            "joined": membership is not None,
            "joined_at": membership.joined_at if membership is not None else None,
            "can_join": block is None,
            "join_block_code": block.code if block is not None else None,
            "join_block_message": block.message if block is not None else None,
        },
        "feedback": _feedback_routing(),
    }


def _state_response(user) -> Response:
    return Response(RolloutStateSerializer(_rollout_state(user)).data)


class RolloutStateView(APIView):
    """
    Rollout state of the current account.

    Any logged-in person or organization account may read which features are
    enabled for it, the experiments listed on the preview channel page, its
    preview channel membership and where preview feedback is sent. Nothing is
    mutated. Rules live in ``rollout.api``.
    """

    authentication_classes = [WxJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="获取当前账号的功能开关、体验中的功能、体验通道状态和体验反馈目标",
        responses={
            200: RolloutStateSerializer,
            401: _UNAUTHENTICATED_RESPONSE,
        },
        tags=["灰度"],
    )
    def get(self, request):
        return _state_response(request.user)


class PreviewMembershipView(APIView):
    """
    Join (POST) or leave (DELETE) the preview channel.

    Active personal accounts may join while the channel is open; any account
    may leave. Both actions are idempotent, mutate ``rollout.PreviewMember``
    and return the same body as ``RolloutStateView``.
    """

    authentication_classes = [WxJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="加入体验通道（重复加入没有影响），返回最新的灰度状态",
        request=None,
        responses={
            200: RolloutStateSerializer,
            401: _UNAUTHENTICATED_RESPONSE,
            403: OpenApiResponse(
                description=(
                    "当前账号不能加入体验通道，code 为 preview_closed、"
                    "preview_person_only 或 preview_inactive"
                ),
            ),
        },
        tags=["灰度"],
    )
    def post(self, request):
        try:
            join_preview(request.user)
        except PreviewJoinDenied as denied:
            raise PermissionDenied(detail={
                "code": denied.code,
                "message": denied.message,
                "errors": {},
            }) from denied
        return _state_response(request.user)

    @extend_schema(
        description="退出体验通道（未加入时没有影响），返回最新的灰度状态",
        request=None,
        responses={
            200: RolloutStateSerializer,
            401: _UNAUTHENTICATED_RESPONSE,
        },
        tags=["灰度"],
    )
    def delete(self, request):
        leave_preview(request.user)
        return _state_response(request.user)
