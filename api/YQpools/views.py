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
        description="获取所有当前可用的兑换奖池及其奖品信息",
        responses={
            200: OpenApiResponse(description="所有兑换奖池信息"),
            403: OpenApiResponse(description="非个人账号或无权限"),
        },
        tags=['元气商城'],
    )
    @action(detail=False, methods=['get'], url_path='exchange')
    def exchange_pools(self, request):
        """Get all exchange pools."""
        return Response(self._get_serialized_data(Pool.Type.EXCHANGE))

    @extend_schema(
        summary="获取抽奖奖池列表",
        description="获取所有当前可用的抽奖奖池及其奖品信息",
        responses={
            200: OpenApiResponse(description="所有抽奖奖池列表"),
            403: OpenApiResponse(description="非个人账号或无权限"),
        },
        tags=['元气商城'],
    )
    @action(detail=False, methods=['get'], url_path='lottery')
    def lottery_pools(self, request):
        """Get all lottery pools."""
        return Response(self._get_serialized_data(Pool.Type.LOTTERY))

    @extend_schema(
        summary="获取盲盒奖池列表",
        description="获取所有当前可用的盲盒奖池及其奖品信息",
        responses={
            200: OpenApiResponse(description="所有盲盒奖池列表"),
            403: OpenApiResponse(description="非个人账号或无权限"),
        },
        tags=['元气商城'],
    )
    @action(detail=False, methods=['get'], url_path='random')
    def random_pools(self, request):
        """Get all random (blind box) pools."""
        return Response(self._get_serialized_data(Pool.Type.RANDOM))

    @extend_schema(
        summary="获取所有奖池",
        description="一次性获取所有类型的奖池（兑换、抽奖、盲盒）",
        responses={
            200: OpenApiResponse(
                description="所有奖池信息",
            ),
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
        description="根据ID获取单个特定奖池的详细信息",
        responses={
            200: OpenApiResponse(description="单个奖池信息"),
            404: OpenApiResponse(description="奖池不存在"),
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
        description="从兑换奖池中购买指定奖品",
        parameters=[
            # TODO
        ],
        responses={
            200: OpenApiResponse(
                description="兑换奖品响应",
            ),
            400: OpenApiResponse(description="请求错误（如元气值不足、已售罄等）"),
            404: OpenApiResponse(description="奖品不存在"),
            403: OpenApiResponse(description="无权限或未参加活动"),
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
        description="购买抽奖奖池的抽奖机会",
        parameters=[
            # TODO
        ],
        responses={
            200: OpenApiResponse(
                description="购买抽奖响应",
            ),
            400: OpenApiResponse(description="请求错误（如元气值不足、次数达上限等）"),
            404: OpenApiResponse(description="奖池不存在"),
            403: OpenApiResponse(description="无权限或未参加活动"),
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
        description="购买盲盒奖池的盲盒",
        parameters=[
            # TODO
        ],
        responses={
            200: OpenApiResponse(
                description="购买盲盒响应"
            ),
            400: OpenApiResponse(description="请求错误（如元气值不足、次数达上限等）"),
            404: OpenApiResponse(description="奖池不存在"),
            403: OpenApiResponse(description="无权限或未参加活动"),
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
        description="获取当前用户的元气值余额",
        responses={
            200: OpenApiResponse(description="元气值余额"),
        },
        tags=['元气商城'],
    )
    @action(detail=False, methods=['get'], url_path='balance')
    def balance(self, request):
        """Get user's YQPoint balance."""
        serializer = YQPointBalanceSerializer(
            {'YQpoint': request.user.YQpoint})
        return Response(serializer.data)
