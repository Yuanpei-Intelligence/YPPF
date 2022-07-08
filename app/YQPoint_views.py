'''待废弃'''
from app.views_dependency import *
from app.models import (
    NaturalPerson,
    Organization,
    YQPointDistribute,
    TransferRecord,
    Notification,
)
from app.forms import YQPointDistributionForm

from app.YQPoint_utils import (
    add_YQPoints_distribute,
    create_transfer_record,
    accept_transfer,
    reject_transfer,
    record2Display,
)
from app.notification_utils import notification_create
from app.wechat_send import publish_notification, WechatMessageLevel, WechatApp


from django.http import QueryDict
from django.db import transaction  # 原子化更改数据库



@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='YQPoint_views[myYQPoint]', record_user=True)
def myYQPoint(request: HttpRequest):
    valid, user_type, html_display = utils.check_user_type(request.user)
    # 获取可能的提示信息
    my_messages.transfer_message_context(request.GET, html_display)

    # 接下来处理POST相关的内容
    if request.method == "POST":  # 发生了交易处理的事件
        try:  # 检查参数合法性
            post_args = request.POST.get("post_button")
            record_id, action = post_args.split("+")[0], post_args.split("+")[1]
            assert action in ["accept", "reject"]
            reject = action == "reject"
        except:
            wrong("交易遇到问题, 请不要修改参数!", html_display)

        if html_display.get("warn_code") is None:  # 如果传入参数没有问题
            if reject:
                context = reject_transfer(record_id, request.user, notify=True)
            else:
                context = accept_transfer(record_id, request.user, notify=True)
            my_messages.transfer_message_context(context, html_display, normalize=False)

    html_display.update(
        YQPoint=utils.get_person_or_org(request.user, user_type).YQPoint,
    )

    to_send_set = TransferRecord.objects.filter(
        proposer=request.user,
        status=TransferRecord.TransferStatus.WAITING,
    )

    to_recv_set = TransferRecord.objects.filter(
        recipient=request.user,
        status=TransferRecord.TransferStatus.WAITING,
    )

    issued_send_set = TransferRecord.objects.filter(
        proposer=request.user,
        status__in=[
            TransferRecord.TransferStatus.ACCEPTED,
            TransferRecord.TransferStatus.REFUSED,
            # PENDING 目前只用于个人报名预报备活动时使用
            TransferRecord.TransferStatus.PENDING,
        ],
    )

    issued_recv_set = TransferRecord.objects.filter(
        recipient=request.user,
        status__in=[
            TransferRecord.TransferStatus.ACCEPTED,
            TransferRecord.TransferStatus.REFUSED,
        ],
    )

    # to_set 按照开始时间降序排列
    to_set = to_send_set.union(to_recv_set).order_by("-start_time")
    # issued_set 按照完成时间及降序排列
    # 这里应当要求所有已经issued的记录是有执行时间的
    issued_set = issued_send_set.union(issued_recv_set).order_by("-finish_time")

    to_list, amount = record2Display(to_set, request.user)
    issued_list, _ = record2Display(issued_set, request.user)
    send_list = []
    receive_list = []
    for item in issued_list:
        if item["obj_direct"] == "To  ":
            send_list.append(item)
        else:
            receive_list.append(item)

    show_table = {
        "obj": "对象",
        "time": "时间",
        "amount": "金额",
        "message": "留言",
        "status": "状态",
    }

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, "我的元气值")
    # 补充一些呈现信息
    # bar_display["title_name"] = "My YQPoint"
    # bar_display["navbar_name"] = "我的元气值"  #
    # bar_display["help_message"] = local_dict["help_message"]["我的元气值"]

    return render(request, "myYQPoint.html", locals())


# 用已有的搜索，加一个转账的想他转账的 field
# 调用的时候传一下 url 到 origin
# 搜索不希望出现学号，rid 为 User 的 index
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='YQPoint_views[transaction_page]', record_user=True)
def transaction_page(request: HttpRequest, rid=None):
    valid, user_type, html_display = utils.check_user_type(request.user)
    try:
        receive_user = User.objects.get(id=rid)
    except:
        return redirect(message_url("该用户不存在，无法实现转账!"))
    try:
        payer = utils.get_classified_user(request.user, user_type, activate=True)
        recipient = utils.get_classified_user(receive_user, activate=True)
    except:
        return redirect(message_url("只能在有效用户间转账!"))
    if recipient.get_type() != UTYPE_ORG:
        return redirect(message_url("目前仅支持向小组转账"))
    if request.user == receive_user:
        return redirect(message_url("请不要向自己转账"))

    # 获取转账相关信息，前端使用
    transaction_context = dict(
        avatar=recipient.get_user_ava(),
        return_url=recipient.get_absolute_url(),
        name=recipient.get_display_name(),
        YQPoint_limit=payer.YQPoint,
        message=request.GET.get('message', ''),
    )
    if request.GET.get('service') is not None:
        transaction_context.update(service=request.GET['service'])

    # 如果是post, 说明发起了一起转账
    # 到这里, rid没有问题, 接收方和发起方都已经确定
    if request.method == "POST":
        # 检查发起转账的数据
        try:
            amount = float(request.POST['amount'])
            assert amount > 0 and int(amount * 10) == amount * 10
        except:
            wrong('非法的转账数量!', html_display)
        try:
            service = int(request.POST.get('service', -1))
            assert TransferRecord.TransferType.is_valid_service(service)
        except:
            wrong('非法的服务编号!', html_display)
        if html_display.get(my_messages.CODE_FIELD, SUCCEED) != WRONG:
            # 函数检查元气值
            # 获取转账消息, 如果没有消息, 则为空
            context = create_transfer_record(
                request.user, receive_user, amount,
                transaction_msg=request.POST.get('msg', ''),
                service=service,
                accept='append' if user_type == UTYPE_PER else 'no',
            )
            return redirect(message_url(context, '/myYQPoint/'))


    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # 如果希望前移，请联系YHT
    bar_display = utils.get_sidebar_and_navbar(request.user, "发起转账")
    return render(request, "transaction_page.html", locals())



def all_YQPoint_distributions(request: HttpRequest):
    '''
        一个页面，展现当前所有的YQPointDistribute类
    '''
    context = dict()
    context['YQPoint_distributions'] = YQPointDistribute.objects.all()
    return render(request, "YQP_distributions.html", context)


def YQPoint_distribution(request: HttpRequest, dis_id):
    '''
        显示，也可以更改已经存在的YQPointDistribute类
        更改后，如果应用状态status为True，会完成该任务的注册
        如果之前有相同类型的实例存在，注册会失败！
    '''
    dis = YQPointDistribute.objects.get(id=dis_id)
    dis_form = YQPointDistributionForm(instance=dis)
    if request.method == 'POST':
        post_dict = QueryDict(request.POST.urlencode(), mutable=True)
        post_dict["start_time"] = post_dict["start_time"].replace("T", " ")
        dis_form = YQPointDistributionForm(post_dict, instance=dis)
        if dis_form.is_valid():
            dis_form.save()
            if dis.status == True:
                # 在这里注册scheduler
                try:
                    add_YQPoints_distribute(dis.type)
                except:
                    print("注册定时任务失败，可能是有多个status为Yes的实例")
    context = dict()
    context["dis"] = dis
    context["dis_form"] = dis_form
    context["start_time"] = str(dis.start_time).replace(" ", "T")
    return render(request, "YQP_distribution.html", context)


def new_YQPoint_distribute(request: HttpRequest):
    '''
        创建新的发放instance，如果status为True,会尝试注册
    '''
    if not request.user.is_superuser:
        message = "请先以超级账户登录后台后再操作！"
        return render(request, "debugging.html", {"message": message})
    dis = YQPointDistribute()
    dis_form = YQPointDistributionForm()
    if request.method == 'POST':
        post_dict = QueryDict(request.POST.urlencode(), mutable=True)
        post_dict["start_time"] = post_dict["start_time"].replace("T", " ")
        dis_form = YQPointDistributionForm(post_dict, instance=dis)
        print(dis_form)
        print(dis_form.is_valid())
        if dis_form.is_valid():
            print("valid")
            dis_form.save()
            if dis.status == True:
                # 在这里注册scheduler
                try:
                    add_YQPoints_distribute(dis.type)
                except:
                    print("注册定时任务失败，可能是有多个status为Yes的实例")
        return redirect("YQP_distributions")
    return render(request, "new_YQP_distribution.html", {"dis_form": dis_form})


def YQPoint_distributions(request: HttpRequest):
    if not request.user.is_superuser:
        message = "请先以超级账户登录后台后再操作！"
        return render(request, "debugging.html", {"message": message})
    dis_id = request.GET.get("dis_id", "")
    if dis_id == "":
        return all_YQPoint_distributions(request)
    elif dis_id == "new":
        return new_YQPoint_distribute(request)
    else:
        dis_id = int(dis_id)
        return YQPoint_distribution(request, dis_id)
