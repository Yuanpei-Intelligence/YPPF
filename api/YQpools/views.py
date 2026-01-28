"""
REST APIs for YQpools.
"""
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from django.db.models import CharField

from app.models import Pool
from app.YQPoint_utils import (
    get_pools_and_items,
    buy_exchange_item,
    buy_lottery_pool,
    buy_random_pool,
)
from generic.models import User
from api.authentication import WxJWTAuthentication
from api.YQpools.serializers import (
    PoolListSerializer,
    PoolSerializer,
    ExchangePurchaseSerializer,
    LotteryPurchaseSerializer,
    RandomPurchaseSerializer,
    YQPointBalanceSerializer,
)


class PoolsViewSet(viewsets.ViewSet):
    """
    ViewSet for managing YQPoint Mall pools.

    Provides endpoints for:
    - Listing all pools
    - Listing pools by type (EXCHANGE, LOTTERY, RANDOM)
    - Retrieving a specific pool with items
    - Purchasing from pools (exchange, lottery, random)
    - Getting user's YQPoint balance
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]
    queryset = Pool.objects.all()

    def _get_serialized_data(self, pool_type: Pool.Type):
        """Serialize pool data using the existing utility function."""
        user: User = self.request.user
        frontend_dict = {}

        get_pools_and_items(pool_type, user, frontend_dict)

        raw = {'pools_info': frontend_dict.get('pools_info', [])}

        return PoolListSerializer(raw).data

    @extend_schema(
        summary="获取兑换奖池列表",
        description="获取所有当前可用的兑换奖池及其奖品信息。只返回用户已参加关联活动的奖池（如果奖池有关联活动）。",
        responses={
            200: OpenApiResponse(
                response=PoolListSerializer,
                description="兑换奖池列表，包含每个奖池的详细信息、奖品列表、用户兑换次数等"
            ),
            401: OpenApiResponse(description="未认证或token无效"),
            403: OpenApiResponse(description="非个人账号或无权限访问"),
        },
        tags=['元气商城'],
    )
    @action(detail=False, methods=['get'], url_path='exchange')
    def exchange_pools(self, request):
        """Get all exchange pools."""
        return Response(self._get_serialized_data(Pool.Type.EXCHANGE))

    @extend_schema(
        summary="获取抽奖奖池列表",
        description="获取所有当前可用的抽奖奖池及其奖品信息。抽奖奖池在结束后1天内仍可见，包含抽奖结果。",
        responses={
            200: OpenApiResponse(
                response=PoolListSerializer,
                description="抽奖奖池列表，包含每个奖池的详细信息、用户参与次数、总参与次数、抽奖结果（如已结束）等"
            ),
            401: OpenApiResponse(description="未认证或token无效"),
            403: OpenApiResponse(description="非个人账号或无权限访问"),
        },
        tags=['元气商城'],
    )
    @action(detail=False, methods=['get'], url_path='lottery')
    def lottery_pools(self, request):
        """Get all lottery pools."""
        return Response(self._get_serialized_data(Pool.Type.LOTTERY))

    @extend_schema(
        summary="获取盲盒奖池列表",
        description="获取所有当前可用的盲盒奖池及其奖品信息。盲盒奖池包含每个奖品的概率信息。",
        responses={
            200: OpenApiResponse(
                response=PoolListSerializer,
                description="盲盒奖池列表，包含每个奖池的详细信息、奖品列表及概率、容量、用户参与次数等"
            ),
            401: OpenApiResponse(description="未认证或token无效"),
            403: OpenApiResponse(description="非个人账号或无权限访问"),
        },
        tags=['元气商城'],
    )
    @action(detail=False, methods=['get'], url_path='random')
    def random_pools(self, request):
        """Get all random (blind box) pools."""
        return Response(self._get_serialized_data(Pool.Type.RANDOM))

    @extend_schema(
        summary="获取所有奖池",
        description="一次性获取所有类型的奖池（兑换、抽奖、盲盒）。返回三个独立的列表，每个列表包含对应类型的所有可用奖池。",
        responses={
            200: OpenApiResponse(
                description="所有奖池信息",
                response={
                    "type": "object",
                    "properties": {
                        "exchange_pools": {
                            "type": "object",
                            "properties": {
                                "pools_info": {
                                    "type": "array",
                                    "items": {"type": "object"}
                                }
                            }
                        },
                        "lottery_pools": {
                            "type": "object",
                            "properties": {
                                "pools_info": {
                                    "type": "array",
                                    "items": {"type": "object"}
                                }
                            }
                        },
                        "random_pools": {
                            "type": "object",
                            "properties": {
                                "pools_info": {
                                    "type": "array",
                                    "items": {"type": "object"}
                                }
                            }
                        },
                    },
                },
            ),
            401: OpenApiResponse(description="未认证或token无效"),
            403: OpenApiResponse(description="非个人账号或无权限访问"),
        },
        tags=['元气商城'],
    )
    def list(self, request):
        """Get all pools of all types."""
        return Response({
            'exchange_pools': self._get_serialized_data(Pool.Type.EXCHANGE),
            'lottery_pools': self._get_serialized_data(Pool.Type.LOTTERY),
            'random_pools': self._get_serialized_data(Pool.Type.RANDOM),
        })

    @extend_schema(
        summary="获取单个奖池信息",
        description="根据ID获取单个特定奖池的详细信息，包括所有奖品、用户参与情况等。如果奖池有关联活动，用户必须已参加该活动才能查看。",
        responses={
            200: OpenApiResponse(
                response=PoolSerializer,
                description="单个奖池的完整信息，包括所有字段和奖品列表"
            ),
            401: OpenApiResponse(description="未认证或token无效"),
            403: OpenApiResponse(description="非个人账号、无权限访问或未参加关联活动"),
            404: OpenApiResponse(description="奖池不存在或已过期不可用"),
        },
        tags=['元气商城'],
    )
    def retrieve(self, request, pk: int):
        """Get a specific pool by ID."""
        try:
            pool = Pool.objects.get(id=pk)
        except Pool.DoesNotExist:
            raise NotFound("奖池不存在")

        user: User = request.user
        pool_type: CharField = pool.type
        frontend_dict = {}
        get_pools_and_items(Pool.Type(pool_type), user, frontend_dict)

        # 从结果中找到特定奖池
        pools_info = frontend_dict.get('pools_info', [])
        pool_data = next((p for p in pools_info if p['id'] == pk), None)

        if pool_data is None:
            raise NotFound("奖池不存在")

        return Response(PoolSerializer(pool_data).data)

    @extend_schema(
        summary="兑换奖品",
        description="从兑换奖池中购买指定奖品。需要足够的元气值，奖品未售罄，且未达到单人兑换上限。如果奖品需要属性（如尺寸、颜色），必须在attributes中提供。",
        request=ExchangePurchaseSerializer,
        responses={
            200: OpenApiResponse(
                description="兑换成功",
                response={
                    "type": "object",
                    "properties": {
                        "succeed": {"type": "boolean", "description": "是否成功"},
                        "message": {"type": "string", "description": "响应消息"},
                    },
                },
            ),
            400: OpenApiResponse(
                description="请求错误",
                response={
                    "type": "object",
                    "properties": {
                        "succeed": {"type": "boolean", "example": False},
                        "message": {
                            "type": "string",
                            "examples": [
                                "您的元气值不足，兑换失败!",
                                "奖品已售罄!",
                                "您兑换该奖品的次数已达上限!",
                                "请填写完整的兑换信息!",
                            ],
                        },
                    },
                },
            ),
            401: OpenApiResponse(description="未认证或token无效"),
            403: OpenApiResponse(description="非个人账号、无权限或未参加关联活动"),
            404: OpenApiResponse(description="奖品不存在"),
        },
        tags=['元气商城'],
    )
    @action(detail=False, methods=['post'], url_path='exchange/purchase')
    def buy_exchange(self, request):
        """Purchase an item from an exchange pool."""
        serializer = ExchangePurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        poolitem_id = str(serializer.validated_data['poolitem_id'])
        attributes = serializer.validated_data.get('attributes', {})

        context = buy_exchange_item(request.user, poolitem_id, attributes)

        # Convert MESSAGECONTEXT to API response
        response_data = {
            'succeed': context.get('warn_code', 0) == 2,
            'message': context.get('warn_message', ''),
        }

        if response_data['succeed']:
            return Response(response_data, status=status.HTTP_200_OK)
        else:
            return Response(response_data, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="购买抽奖",
        description="购买抽奖奖池的抽奖机会。需要足够的元气值，且未达到单人参与次数上限。抽奖结果将在奖池结束后统一公布。",
        request=LotteryPurchaseSerializer,
        responses={
            200: OpenApiResponse(
                description="购买成功",
                response={
                    "type": "object",
                    "properties": {
                        "succeed": {"type": "boolean", "description": "是否成功"},
                        "message": {
                            "type": "string",
                            "description": "响应消息，成功时提示可在抽奖结束后查看结果",
                        },
                    },
                },
            ),
            400: OpenApiResponse(
                description="请求错误",
                response={
                    "type": "object",
                    "properties": {
                        "succeed": {"type": "boolean", "example": False},
                        "message": {
                            "type": "string",
                            "examples": [
                                "您的元气值不足，兑换失败!",
                                "您在本奖池中抽奖的次数已达上限!",
                                "抽奖已结束!",
                            ],
                        },
                    },
                },
            ),
            401: OpenApiResponse(description="未认证或token无效"),
            403: OpenApiResponse(description="非个人账号、无权限或未参加关联活动"),
            404: OpenApiResponse(description="奖池不存在"),
        },
        tags=['元气商城'],
    )
    @action(detail=False, methods=['post'], url_path='lottery/purchase')
    def purchase_lottery(self, request):
        """Purchase a lottery ticket."""
        serializer = LotteryPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pool_id = str(serializer.validated_data['pool_id'])

        context = buy_lottery_pool(request.user, pool_id)

        response_data = {
            'succeed': context.get('warn_code', 0) == 2,
            'message': context.get('warn_message', ''),
        }

        if response_data['succeed']:
            return Response(response_data, status=status.HTTP_200_OK)
        else:
            return Response(response_data, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="购买盲盒",
        description="购买盲盒奖池的盲盒。立即开盒并返回结果。可能开出奖品或空盒，空盒会获得元气值补偿。需要足够的元气值，且未达到单人参与次数上限。",
        request=RandomPurchaseSerializer,
        responses={
            200: OpenApiResponse(
                description="购买成功",
                response={
                    "type": "object",
                    "properties": {
                        "succeed": {"type": "boolean", "description": "是否成功"},
                        "message": {"type": "string", "description": "响应消息"},
                        "prize_id": {
                            "type": "integer",
                            "nullable": True,
                            "description": "获得的奖品ID，空盒时为null",
                        },
                        "effect_code": {
                            "type": "integer",
                            "description": "效果代码：0=开出奖品，1=开出空盒，2=无效果",
                            "enum": [0, 1, 2],
                        },
                        "compensate_YQPoint": {
                            "type": "integer",
                            "description": "空盒补偿的元气值，非空盒时为0",
                        },
                    },
                },
            ),
            400: OpenApiResponse(
                description="请求错误",
                response={
                    "type": "object",
                    "properties": {
                        "succeed": {"type": "boolean", "example": False},
                        "message": {
                            "type": "string",
                            "examples": [
                                "您的元气值不足，兑换失败!",
                                "您兑换这款盲盒的次数已达上限!",
                                "盲盒已售罄!",
                            ],
                        },
                        "prize_id": {"type": "integer", "nullable": True, "example": None},
                        "effect_code": {"type": "integer", "example": 2},
                        "compensate_YQPoint": {"type": "integer", "example": 0},
                    },
                },
            ),
            401: OpenApiResponse(description="未认证或token无效"),
            403: OpenApiResponse(description="非个人账号、无权限或未参加关联活动"),
            404: OpenApiResponse(description="奖池不存在"),
        },
        tags=['元气商城'],
    )
    @action(detail=False, methods=['post'], url_path='random/purchase')
    def purchase_random(self, request):
        """Purchase a random box."""
        serializer = RandomPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pool_id = str(serializer.validated_data['pool_id'])

        context, prize_id, effect_code = buy_random_pool(request.user, pool_id)

        response_data = {
            'succeed': context.get('warn_code', 0) == 2,
            'message': context.get('warn_message', ''),
            'prize_id': prize_id if prize_id != -1 else None,
            'effect_code': effect_code,
            'compensate_YQPoint': 0
        }

        # 如果获得元气值补偿，则提取元气值补偿数值，并添加到响应数据中
        if '获得' in response_data['message'] and '元气值补偿' in response_data['message']:
            compen_str = response_data['message'][17:-7]
            response_data['compensate_YQPoint'] = int(compen_str)

        if response_data['succeed']:
            return Response(response_data, status=status.HTTP_200_OK)
        else:
            return Response(response_data, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="获取元气值余额",
        description="获取当前认证用户的元气值（YQPoint）余额。元气值可用于兑换奖品、购买抽奖和盲盒。",
        responses={
            200: OpenApiResponse(
                response=YQPointBalanceSerializer,
                description="用户的元气值余额"
            ),
            401: OpenApiResponse(description="未认证或token无效"),
        },
        tags=['元气商城'],
    )
    @action(detail=False, methods=['get'], url_path='balance')
    def balance(self, request):
        """Get user's YQPoint balance."""
        serializer = YQPointBalanceSerializer(
            {'YQpoint': request.user.YQpoint})
        return Response(serializer.data)
