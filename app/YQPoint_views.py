from generic.models import YQPointRecord
from app.views_dependency import *
from app.models import (
    Prize,
    Pool,
    PoolRecord,
)
from app.YQPoint_utils import (
    get_pools_and_items,
    buy_exchange_item,
    buy_lottery_pool,
    buy_random_pool,
)
from app.utils import get_sidebar_and_navbar

__all__ = [
    'myYQPoint',
    'myPrize',
    'showPools',
]


class myYQPoint(ProfileTemplateView):
    template_name = 'myYQPoint.html'
    page_name = '我的元气值'
    http_method_names = ['get']

    def prepare_get(self):
        html_display = {}
        my_messages.transfer_message_context(self.request.GET, html_display)
        html_display.update(YQPoint=self.request.user.YQpoint)
        self.extra_context.update(html_display=html_display)
        return self.get

    def get(self):
        YQPoint = self.request.user.YQpoint
        received_set = YQPointRecord.objects.filter(
            user=self.request.user,
        ).exclude(source_type=YQPointRecord.SourceType.CONSUMPTION).order_by("-time")

        send_set = YQPointRecord.objects.filter(
            user=self.request.user,
            source_type=YQPointRecord.SourceType.CONSUMPTION,
        ).order_by("-time")
        return self.render(YQPoint=YQPoint, received_set=received_set, send_set=send_set)



class myPrize(ProfileTemplateView):
    template_name = 'myPrize.html'
    page_name = '我的奖品'
    http_method_names = ['get']

    def prepare_get(self):
        html_display = {}
        my_messages.transfer_message_context(self.request.GET, html_display)
        self.extra_context.update(html_display=html_display)
        return self.get

    def get(self):
        lottery_set = PoolRecord.objects.filter(
            user=self.request.user,
            pool__type=Pool.Type.LOTTERY,
            status__in=[
                PoolRecord.Status.LOTTERING,
                PoolRecord.Status.NOT_LUCKY,
                PoolRecord.Status.UN_REDEEM],
        ).order_by("-time")

        exchange_set = PoolRecord.objects.filter(
            user=self.request.user,
            status__in=[
                PoolRecord.Status.UN_REDEEM,
                PoolRecord.Status.REDEEMED,
                PoolRecord.Status.OVERDUE],
        ).order_by("-status", "-time")
        return self.render(lottery_set=lottery_set, exchange_set=exchange_set)



@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def showPools(request: UserRequest) -> HttpResponse:
    """
    展示各种奖池的页面，可以通过POST请求发起兑换/抽奖/买盲盒

    :param request
    :type request: HttpRequest
    :return
    :rtype: HttpResponse
    """
    if request.user.is_org():
        return redirect(message_url(wrong("只有个人账号可以进入此页面！")))

    frontend_dict = {"exchange_pools_info": {},
                     "lottery_pools_info": {}, "random_pools_info": {}}
    frontend_dict["current_pool"] = -1 # 当前所在的tab
    # 2表示无效果，1表示开出空盒（谢谢参与），0表示开出奖品
    frontend_dict["random_pool_effect_code"] = 2

    # 用户是否处于活跃状态。已经毕业的用户只能查看奖池，不能参与兑换
    frontend_dict['active_user'] = request.user.active

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

    frontend_dict["my_YQpoint"] = request.user.YQpoint  # 元气值余额
    
    if frontend_dict["current_pool"] == -1:
        if len(frontend_dict["exchange_pools_info"]["pools_info"]):
            frontend_dict["current_pool"] = frontend_dict["exchange_pools_info"]["pools_info"][0]["id"]
        elif len(frontend_dict["lottery_pools_info"]["pools_info"]):
            frontend_dict["current_pool"] = frontend_dict["lottery_pools_info"]["pools_info"][0]["id"]
        elif len(frontend_dict["random_pools_info"]["pools_info"]):
            frontend_dict["current_pool"] = frontend_dict["random_pools_info"]["pools_info"][0]["id"]


    frontend_dict["bar_display"] = get_sidebar_and_navbar(
        request.user, "元气值商城")
    return render(request, "showPools.html", frontend_dict)
