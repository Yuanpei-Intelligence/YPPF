from app.views_dependency import *
from app.models import (
    Prize,
    Pool,
    PoolItem,
    PoolRecord,
)
from app.YQPoint_utils import (
    get_pools_and_items,
    buy_exchange_item,
    buy_lottery_pool,
    buy_random_pool,
)
from app.utils import (
    check_user_type,
    get_sidebar_and_navbar,
    get_person_or_org,
)

__all__ = [
    'showPools'
]


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='YQPoint_views[showPrize]', record_user=True)
def showPools(request: HttpRequest) -> HttpResponse:
    """
    展示各种奖池的页面，可以通过POST请求发起兑换/抽奖/买盲盒

    :param request
    :type request: HttpRequest
    :return
    :rtype: HttpResponse
    """
    valid, user_type, _ = check_user_type(request.user)
    if user_type == UTYPE_ORG:
        return redirect(message_url(wrong("只有个人账号可以进入此页面！")))

    frontend_dict = {"exchange_pools_info": {},
                     "lottery_pools_info": {}, "random_pools_info": {}}
    frontend_dict["current_pool"] = -1 # 当前所在的tab
    # 2表示无效果，1表示开出空盒（谢谢参与），0表示开出奖品
    frontend_dict["random_pool_effect_code"] = 2

    # POST表明发起兑换/抽奖/买盲盒
    if request.method == "POST" and request.POST:
        if request.POST.get('submit_exchange', '') != '':
            context = buy_exchange_item(
                request.user, poolitem_id=request.POST['submit_exchange'])
            my_messages.transfer_message_context(
                context, frontend_dict, normalize=True)
            frontend_dict["current_pool"] = int(request.POST["pool_id"])
        elif request.POST.get('submit_lottery', '') != '':
            context = buy_lottery_pool(
                request.user, pool_id=request.POST['submit_lottery'])
            my_messages.transfer_message_context(
                context, frontend_dict, normalize=True)
            frontend_dict["current_pool"] = int(request.POST["submit_lottery"])
        elif request.POST.get('submit_random', '') != '':
            context, prize_id, frontend_dict["random_pool_effect_code"] = buy_random_pool(
                request.user, pool_id=request.POST['submit_random'])
            my_messages.transfer_message_context(
                context, frontend_dict, normalize=True)
            if prize_id != -1:  # 表明成功购买了一个盲盒
                prize = Prize.objects.get(id=prize_id)
                # 供前端展示盲盒开出的结果
                frontend_dict["random_pool_effect_name"] = prize.name
                frontend_dict["random_pool_effect_image"] = prize.image
            frontend_dict["current_pool"] = int(request.POST["submit_random"])

    get_pools_and_items(Pool.Type.EXCHANGE, request.user,
                        frontend_dict["exchange_pools_info"])
    get_pools_and_items(Pool.Type.LOTTERY, request.user,
                        frontend_dict["lottery_pools_info"])  # 这里包含结束一天以内的
    get_pools_and_items(Pool.Type.RANDOM, request.user,
                        frontend_dict["random_pools_info"])

    frontend_dict["my_YQpoint"] = User.objects.get(
        id=request.user.id).YQpoint  # 元气值余额，因为可能刚刚改过，有必要重新读一下User表
    
    if frontend_dict["current_pool"] == -1:
        if len(frontend_dict["exchange_pools_info"]["pools_info"]):
            frontend_dict["current_pool"] = frontend_dict["exchange_pools_info"]["pools_info"][0]["id"]
        elif len(frontend_dict["lottery_pools_info"]["pools_info"]):
            frontend_dict["current_pool"] = frontend_dict["lottery_pools_info"]["pools_info"][0]["id"]
        elif len(frontend_dict["random_pools_info"]["pools_info"]):
            frontend_dict["current_pool"] = frontend_dict["random_pools_info"]["pools_info"][0]["id"]


    frontend_dict["bar_display"] = get_sidebar_and_navbar(
        request.user, "元气值兑换与抽奖")
    return render(request, "showPools.html", frontend_dict)
