import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from app.utils import check_user_access
from birthboard.models import BirthboardRecord
from birthboard.utils import calculate_per_cost

__all__ = ['check_yqpoint']

logger = logging.getLogger(__name__)


@csrf_protect
@login_required(redirect_field_name='origin')
@check_user_access(redirect_url='/logout/')
@require_POST
def check_yqpoint(request):
    """
    返回当前登录用户本人的元气值余额及是否足够。
    出于隐私考虑，仅允许查询本人余额，不接受查询他人的用户名列表。
    若提供 record_id，则优先按记录中的 per_cost 作为所需值；否则按 mode 计算。
    """
    try:
        data = json.loads(request.body.decode())
        record_id = data.get('record_id')

        per = None
        if not request.user.is_person() or not request.user.active:
            return JsonResponse(
                {'ok': False, 'msg': 'permission denied'},
                status=403,
            )

        if record_id is not None:
            try:
                record_id = int(record_id)
                record = (
                    BirthboardRecord.objects.filter(
                        id=record_id,
                        participants__user=request.user,
                    )
                    .only('per_cost')
                    .first()
                )
                if record:
                    per = int(record.per_cost)
            except (TypeError, ValueError):
                per = None

        if per is None:
            mode = int(data.get('mode', 0))
            sender_count = data.get('sender_count', None)
            try:
                sender_count = int(sender_count)
            except (TypeError, ValueError):
                sender_count = None
            divisor = sender_count if sender_count and sender_count > 0 else 1
            per = calculate_per_cost(mode, divisor)

        user = request.user
        balance = getattr(user, 'YQpoint', 0)
        return JsonResponse({
            'ok': True,
            'result': {
                user.username: {
                    'balance': balance,
                    'enough': balance >= per,
                    'need': per,
                },
            },
        })
    except Exception:
        logger.exception('birthboard check_yqpoint failed')
        return JsonResponse({'ok': False, 'msg': 'request failed'}, status=400)
