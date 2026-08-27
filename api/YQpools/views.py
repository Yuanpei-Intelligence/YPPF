"""
REST APIs for YQpools.
"""
from datetime import datetime
import re

from django.db.models import CharField
from django.forms.models import model_to_dict
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse

from app.YQPoint_utils import (
    get_pools_and_items,
    buy_exchange_item,
    buy_lottery_pool,
    buy_random_pool,
)
from app.models import Participation, Pool, PoolItem, PoolRecord
from generic.models import User
from api.authentication import WxJWTAuthentication
from api.exceptions import (
    APIError,
    APIErrorResponseSerializer,
    StandardizedExceptionHandlerMixin,
)
from api.YQpools.serializers import (
    AllPoolsResponseSerializer,
    PoolListSerializer,
    PoolSerializer,
    ExchangePurchaseSerializer,
    LotteryPurchaseSerializer,
    RandomPurchaseSerializer,
    PurchaseResponseSerializer,
    RandomPurchaseResponseSerializer,
    YQPointBalanceSerializer,
)


def error_response(description: str) -> OpenApiResponse:
    return OpenApiResponse(
        response=APIErrorResponseSerializer,
        description=description,
    )


def _raise_purchase_error(
    message: str,
    *,
    missing_code: str,
) -> None:
    """Translate a legacy domain message into a stable API failure."""

    if "不存在" in message:
        code = missing_code
        status_code = status.HTTP_404_NOT_FOUND
        errors = None
    elif "元气值不足" in message:
        code = "yqpools.insufficient_balance"
        status_code = status.HTTP_400_BAD_REQUEST
        errors = None
    elif "售罄" in message:
        code = "yqpools.sold_out"
        status_code = status.HTTP_409_CONFLICT
        errors = None
    elif "未开始" in message:
        code = "yqpools.not_started"
        status_code = status.HTTP_409_CONFLICT
        errors = None
    elif "已结束" in message:
        code = "yqpools.ended"
        status_code = status.HTTP_409_CONFLICT
        errors = None
    elif "次数" in message and "上限" in message:
        code = "yqpools.limit_reached"
        status_code = status.HTTP_400_BAD_REQUEST
        errors = None
    elif "兑换信息" in message:
        code = "yqpools.invalid_attributes"
        status_code = status.HTTP_400_BAD_REQUEST
        errors = {
            "attributes": [{"code": "invalid", "message": message}],
        }
    elif "已毕业" in message:
        code = "yqpools.account_inactive"
        status_code = status.HTTP_403_FORBIDDEN
        errors = None
    elif "活动限定" in message:
        code = "yqpools.activity_required"
        status_code = status.HTTP_403_FORBIDDEN
        errors = None
    else:
        code = "yqpools.purchase_rejected"
        status_code = status.HTTP_400_BAD_REQUEST
        errors = None

    raise APIError(
        code=code,
        message=message or "购买请求未通过。",
        status_code=status_code,
        errors=errors,
    )


class PoolsViewSet(StandardizedExceptionHandlerMixin, viewsets.ViewSet):
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

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.is_person():
            raise PermissionDenied("元气商城仅支持个人账号。")

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
            401: error_response("未认证或令牌无效"),
            403: error_response("仅个人账号可访问元气商城"),
            500: error_response("服务器暂时无法处理请求"),
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
            401: error_response("未认证或令牌无效"),
            403: error_response("仅个人账号可访问元气商城"),
            500: error_response("服务器暂时无法处理请求"),
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
            401: error_response("未认证或令牌无效"),
            403: error_response("仅个人账号可访问元气商城"),
            500: error_response("服务器暂时无法处理请求"),
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
            200: AllPoolsResponseSerializer,
            401: error_response("未认证或令牌无效"),
            403: error_response("仅个人账号可访问元气商城"),
            500: error_response("服务器暂时无法处理请求"),
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
            401: error_response("未认证或令牌无效"),
            403: error_response("仅个人账号可访问元气商城"),
            404: error_response("奖池不存在或对当前用户不可见"),
            500: error_response("服务器暂时无法处理请求"),
        },
        tags=['元气商城'],
    )
    def retrieve(self, request, pk: int):
        """Get a specific pool by ID."""
        try:
            pool = Pool.objects.get(id=pk)
        except Pool.DoesNotExist as exc:
            raise NotFound("奖池不存在。") from exc

        user: User = request.user
        pool_type: CharField = pool.type

        # Check if user has access (activity participation requirement)
        if pool.activity_id:
            has_participated = Participation.objects.filter(
                activity=pool.activity_id,
                person=user.naturalperson,
                status=Participation.AttendStatus.ATTENDED
            ).exists()
            if not has_participated:
                raise NotFound("奖池不存在。")

        # Try to get pool from filtered results first
        frontend_dict = {}
        get_pools_and_items(Pool.Type(pool_type), user, frontend_dict)
        pools_info = frontend_dict.get('pools_info', [])
        pool_data = next((p for p in pools_info if p['id'] == pk), None)

        # If not in filtered results, manually construct pool data
        if pool_data is None:
            pool_data = model_to_dict(pool)
            now = datetime.now()
            if pool.start <= now and (pool.end is None or pool.end >= now):
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
                response=PurchaseResponseSerializer,
            ),
            400: error_response("参数错误或购买条件不满足"),
            401: error_response("未认证或令牌无效"),
            403: error_response("账号或活动资格不允许购买"),
            404: error_response("奖品不存在"),
            409: error_response("奖池状态冲突或奖品售罄"),
            500: error_response("服务器暂时无法处理请求"),
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

        message = str(context.get('warn_message', ''))
        if context.get('warn_code', 0) != 2:
            _raise_purchase_error(
                message,
                missing_code="yqpools.prize_not_found",
            )
        return Response(
            {'succeed': True, 'message': message},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="购买抽奖",
        description="购买抽奖奖池的抽奖机会。需要足够的元气值，且未达到单人参与次数上限。抽奖结果将在奖池结束后统一公布。",
        request=LotteryPurchaseSerializer,
        responses={
            200: OpenApiResponse(
                description="购买成功",
                response=PurchaseResponseSerializer,
            ),
            400: error_response("参数错误或购买条件不满足"),
            401: error_response("未认证或令牌无效"),
            403: error_response("账号或活动资格不允许购买"),
            404: error_response("奖池不存在"),
            409: error_response("奖池状态冲突"),
            500: error_response("服务器暂时无法处理请求"),
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

        message = str(context.get('warn_message', ''))
        if context.get('warn_code', 0) != 2:
            _raise_purchase_error(
                message,
                missing_code="yqpools.pool_not_found",
            )
        return Response(
            {'succeed': True, 'message': message},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="购买盲盒",
        description="购买盲盒奖池的盲盒。立即开盒并返回结果。可能开出奖品或空盒，空盒会获得元气值补偿。需要足够的元气值，且未达到单人参与次数上限。",
        request=RandomPurchaseSerializer,
        responses={
            200: OpenApiResponse(
                description="购买成功",
                response=RandomPurchaseResponseSerializer,
            ),
            400: error_response("参数错误或购买条件不满足"),
            401: error_response("未认证或令牌无效"),
            403: error_response("账号或活动资格不允许购买"),
            404: error_response("奖池不存在"),
            409: error_response("奖池状态冲突或盲盒售罄"),
            500: error_response("服务器暂时无法处理请求"),
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

        message = str(context.get('warn_message', ''))
        if context.get('warn_code', 0) != 2:
            _raise_purchase_error(
                message,
                missing_code="yqpools.pool_not_found",
            )

        response_data = {
            'succeed': True,
            'message': message,
            'prize_id': prize_id if prize_id != -1 else None,
            'effect_code': effect_code,
            'compensate_YQPoint': 0
        }

        compensation = re.search(r"获得(\d+)点元气值补偿", message)
        if compensation:
            response_data['compensate_YQPoint'] = int(compensation.group(1))

        return Response(response_data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="获取元气值余额",
        description="获取当前认证用户的元气值（YQPoint）余额。元气值可用于兑换奖品、购买抽奖和盲盒。",
        responses={
            200: OpenApiResponse(
                response=YQPointBalanceSerializer,
                description="用户的元气值余额"
            ),
            401: error_response("未认证或令牌无效"),
            403: error_response("仅个人账号可访问元气商城"),
            500: error_response("服务器暂时无法处理请求"),
        },
        tags=['元气商城'],
    )
    @action(detail=False, methods=['get'], url_path='balance')
    def balance(self, request):
        """Get user's YQPoint balance."""
        serializer = YQPointBalanceSerializer(
            {'YQpoint': request.user.YQpoint})
        return Response(serializer.data)
