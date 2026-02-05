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

        pools_info_dicts = frontend_dict.get('pools_info', [])

        # Serialize dictionaries directly - PoolSerializer handles dicts in to_representation
        serializer = PoolSerializer(pools_info_dicts, many=True)

        return {'pools_info': serializer.data}

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
        description="""
        根据ID获取单个特定奖池的详细信息，包括所有奖品、用户参与情况等。如果奖池有关联活动，用户必须已参加该活动才能查看。
        另外，此方法应当从所有奖池中获取对应id的奖池。因此在应用get_pools_and_items无法收到奖池数据(被过滤了)后，根据其代码手动构造奖池数据。
        """,
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

        # Check if user has access (activity participation requirement)
        from app.models import Participation
        if pool.activity_id:
            has_participated = Participation.objects.filter(
                activity=pool.activity_id,
                person=user.naturalperson,
                status=Participation.AttendStatus.ATTENDED
            ).exists()
            if not has_participated:
                raise NotFound("奖池不存在")

        # Try to get pool from filtered results first
        frontend_dict = {}
        get_pools_and_items(Pool.Type(pool_type), user, frontend_dict)
        pools_info = frontend_dict.get('pools_info', [])
        pool_data = next((p for p in pools_info if p['id'] == pk), None)

        # If not in filtered results, manually construct pool data
        if pool_data is None:
            from django.forms.models import model_to_dict
            from datetime import datetime
            from app.models import PoolRecord, PoolItem

            pool_data = model_to_dict(pool)
            if pool.start <= datetime.now() and (pool.end is None or pool.end >= datetime.now()):
                pool_data["status"] = 0
            else:
                pool_data["status"] = 1

            pool_data["capacity"] = pool.get_capacity()
            pool_items = list(pool.items.filter(prize__isnull=False).values(
                "id", "origin_num", "consumed_num", "exchange_price",
                "exchange_limit", "is_big_prize",
                "prize__name", "prize__more_info", "prize__stock",
                "prize__reference_price", "prize__image", "prize__id", "exchange_attributes",
            ))
            for item in pool_items:
                item["remain_num"] = item["origin_num"] - item["consumed_num"]
            pool_data["items"] = sorted(
                pool_items, key=lambda x: -x["remain_num"])

            if pool_type != Pool.Type.EXCHANGE:
                pool_data["my_entry_time"] = PoolRecord.objects.filter(
                    user=user, pool=pool).count()
                pool_data["records_num"] = PoolRecord.objects.filter(
                    pool=pool).count()
                if pool_type == Pool.Type.RANDOM:
                    for item in pool_items:
                        percent = (
                            100 * item["origin_num"] / pool_data["capacity"])
                        if percent == int(percent):
                            percent = int(percent)
                        elif round(percent, 1) != 0:
                            percent = round(percent, 1)
                        item["probability"] = percent
            else:
                for item in pool_items:
                    item["my_exchange_time"] = PoolRecord.objects.filter(
                        user=user, pool=pool, prize=item["prize__id"]).count()

            # Add results for ended lottery pools
            if pool_data["status"] == 1 and pool_type == Pool.Type.LOTTERY:
                big_prize_items = PoolItem.objects.filter(
                    pool=pool, is_big_prize=True).order_by("-prize__reference_price")
                normal_prize_items = PoolItem.objects.filter(
                    pool=pool, is_big_prize=False).order_by("-prize__reference_price")
                big_prizes_and_winners = []
                normal_prizes_and_winners = []

                for big_prize_item in big_prize_items:
                    big_prizes_and_winners.append({
                        "prize_name": big_prize_item.prize.name,
                        "prize_image": str(big_prize_item.prize.image) if big_prize_item.prize.image else ""
                    })
                    winner_names = list(PoolRecord.objects.filter(
                        pool=pool, prize=big_prize_item.prize).values_list("user__name", flat=True))
                    big_prizes_and_winners[-1]["winners"] = winner_names

                for normal_prize_item in normal_prize_items:
                    if normal_prize_item.is_empty:
                        continue
                    normal_prizes_and_winners.append({
                        "prize_name": normal_prize_item.prize.name,
                        "prize_image": str(normal_prize_item.prize.image) if normal_prize_item.prize.image else ""
                    })
                    winner_names = list(PoolRecord.objects.filter(
                        pool=pool, prize=normal_prize_item.prize).values_list("user__name", flat=True))
                    normal_prizes_and_winners[-1]["winners"] = winner_names

                pool_data["results"] = {
                    "big_prize_results": big_prizes_and_winners,
                    "normal_prize_results": normal_prizes_and_winners
                }

        # Serialize the pool data (dict or instance)
        # Pass instance=pool_data to treat it as validated data
        serializer = PoolSerializer(instance=pool_data)
        return Response(serializer.data)

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
