"""
REST APIs for organization (group) subscription management.

Converted from app/views.py:subscribeOrganization and saveSubscribeStatus.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import NotFound, PermissionDenied
from drf_spectacular.utils import extend_schema, OpenApiResponse
from django.db import transaction

from api.authentication import WxJWTAuthentication
from api.exceptions import (
    APIErrorResponseSerializer,
    StandardizedExceptionHandlerMixin,
)
from api.org.serializers import (
    SubscriptionListResponseSerializer,
    SubscribeStatusUpdateSerializer,
    OrganizationWithSubscribeSerializer,
    SubscriptionUpdateResponseSerializer,
)
from app.models import Organization, OrganizationType
from app.utils import get_person_or_org


def error_response(description: str) -> OpenApiResponse:
    return OpenApiResponse(
        response=APIErrorResponseSerializer,
        description=description,
    )


class SubscriptionListView(StandardizedExceptionHandlerMixin, APIView):
    """
    List all organizations grouped by type with subscription status.

    This API returns all active organizations along with the current user's
    subscription status for each organization.
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="获取小组订阅列表",
        description="获取所有激活的小组列表，按类型分组，包含当前用户的订阅状态",
        responses={
            200: OpenApiResponse(
                response=SubscriptionListResponseSerializer,
                description="小组订阅列表"
            ),
            401: error_response("未认证或令牌无效"),
            405: error_response("请求方法不受支持"),
            500: error_response("服务器暂时无法处理请求"),
        },
        tags=["小组"],
    )
    def get(self, request):
        user = request.user
        is_person = user.is_person()
        readonly = not is_person

        me = get_person_or_org(user)

        # Get all organization types ordered by otype_id descending
        organization_types = list(
            OrganizationType.objects.all().order_by('-otype_id')
        )

        # Get all active organizations with prefetch
        organizations = list(
            Organization.objects.activated()
            .select_related('otype', 'organization_id')
        )

        # Get unsubscribe set for the current user
        if is_person:
            unsubscribe_set = set(
                me.unsubscribe_list.values_list(
                    'organization_id__username', flat=True
                )
            )
        else:
            # For organization accounts, show all as unsubscribed
            unsubscribe_set = set(
                Organization.objects.values_list(
                    'organization_id__username', flat=True
                )
            )

        # Group organizations by type
        otype_infos_dict = {otype: [] for otype in organization_types}
        for org in organizations:
            otype_infos_dict[org.otype].append(org)

        # Serialize the data
        serializer_context = {
            'request': request,
            'unsubscribe_set': unsubscribe_set,
        }

        result = []
        for otype in organization_types:
            orgs = otype_infos_dict[otype]
            org_serializer = OrganizationWithSubscribeSerializer(
                orgs, many=True, context=serializer_context
            )
            result.append({
                'otype_id': otype.otype_id,
                'otype_name': otype.otype_name,
                'allow_unsubscribe': otype.allow_unsubscribe,
                'organizations': org_serializer.data,
            })

        return Response({
            'is_person': is_person,
            'readonly': readonly,
            'organization_types': result,
        })


class SubscriptionUpdateView(StandardizedExceptionHandlerMixin, APIView):
    """
    Update subscription status for an organization or organization type.

    Allows users to subscribe/unsubscribe from:
    - A single organization (by username)
    - All organizations of a specific type (by otype_id)
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="更新小组订阅状态",
        description=(
            "更新用户对小组的订阅状态。可以通过 'id' 指定单个小组用户名，"
            "或通过 'otype' 指定小组类型 ID 进行批量操作。"
        ),
        request=SubscribeStatusUpdateSerializer,
        responses={
            200: OpenApiResponse(
                description="订阅状态更新成功",
                response=SubscriptionUpdateResponseSerializer,
            ),
            400: error_response("请求参数错误"),
            401: error_response("未认证或令牌无效"),
            403: error_response("当前账号不支持该订阅操作"),
            404: error_response("小组或小组类型不存在"),
            405: error_response("请求方法不受支持"),
            500: error_response("服务器暂时无法处理请求"),
        },
        tags=["小组"],
    )
    def post(self, request):
        if not request.user.is_person():
            raise PermissionDenied("小组账号不支持订阅操作")

        serializer = SubscribeStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        subscribe = data['status']  # True = subscribe, False = unsubscribe

        with transaction.atomic():
            me = get_person_or_org(request.user, update=True)

            if 'id' in data:
                # Subscribe/unsubscribe a single organization
                org_username = data['id']
                try:
                    org = Organization.objects.select_for_update().get(
                        organization_id__username=org_username
                    )
                except Organization.DoesNotExist as exc:
                    raise NotFound("小组不存在。") from exc

                if subscribe:
                    me.unsubscribe_list.remove(org)
                    message = f"成功订阅 {org.oname}"
                else:
                    if not org.otype.allow_unsubscribe:
                        raise PermissionDenied("该类型的小组不允许取消订阅。")
                    me.unsubscribe_list.add(org)
                    message = f"成功取消订阅 {org.oname}"

            elif 'otype' in data:
                # Subscribe/unsubscribe all organizations of a type
                otype_id = data['otype']
                try:
                    otype = OrganizationType.objects.select_for_update().get(
                        otype_id=otype_id
                    )
                except OrganizationType.DoesNotExist as exc:
                    raise NotFound("小组类型不存在。") from exc

                org_list = Organization.objects.filter(
                    otype__otype_id=otype_id)

                if subscribe:
                    # Remove all organizations of this type from unsubscribe list
                    unsubscribed_list = me.unsubscribe_list.filter(
                        otype__otype_id=otype_id
                    )
                    for org in unsubscribed_list:
                        me.unsubscribe_list.remove(org)
                    message = f"成功订阅所有 {otype.otype_name} 类型的小组"
                else:
                    if not otype.allow_unsubscribe:
                        raise PermissionDenied("该类型的小组不允许取消订阅。")
                    # Add all organizations of this type to unsubscribe list
                    for org in org_list:
                        me.unsubscribe_list.add(org)
                    message = f"成功取消订阅所有 {otype.otype_name} 类型的小组"

        return Response({
            "success": True,
            "message": message,
        }, status=status.HTTP_200_OK)
