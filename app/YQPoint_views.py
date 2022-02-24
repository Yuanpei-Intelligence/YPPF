'''待废弃'''
from app.views_dependency import *
from app.models import (
    Organization,
    YQPointDistribute,
    TransferRecord,
    Notification,
)
from app.forms import YQPointDistributionForm

from app.YQPoint_utils import (
    add_YQPoints_distribute,
    confirm_transaction,
    record2Display,
)
from app.notification_utils import notification_create
from app.wechat_send import publish_notification, WechatMessageLevel, WechatApp

from django.http import QueryDict
from django.db import transaction  # 原子化更改数据库



@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='YQPoint_views[myYQPoint]', record_user=True)
def myYQPoint(request):
    valid, user_type, html_display = utils.check_user_type(request.user)

    # 接下来处理POST相关的内容
    html_display["warn_code"] = 0
    if request.method == "POST":  # 发生了交易处理的事件
        try:  # 检查参数合法性
            post_args = request.POST.get("post_button")
            record_id, action = post_args.split("+")[0], post_args.split("+")[1]
            assert action in ["accept", "reject"]
            reject = action == "reject"
        except:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "交易遇到问题,请不要非法修改参数!"

        if html_display["warn_code"] == 0:  # 如果传入参数没有问题
            # 调用确认预约API
            context = confirm_transaction(request, record_id, reject)
            # 此时warn_code一定是1或者2，必定需要提示
            html_display["warn_code"] = context["warn_code"]
            html_display["warn_message"] = context["warn_message"]

    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True

    to_send_set = TransferRecord.objects.filter(
        proposer=request.user, status=TransferRecord.TransferStatus.WAITING
    )

    to_recv_set = TransferRecord.objects.filter(
        recipient=request.user, status=TransferRecord.TransferStatus.WAITING
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
def transaction_page(request, rid=None):
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True
    html_display['warn_code'] = 0

    try:
        user = User.objects.get(id=rid)
        recipient = utils.get_person_or_org(user)

    except:
        return redirect(
            "/welcome/?warn_code=1&warn_message=该用户不存在，无法实现转账!")
    if not hasattr(recipient, "organization_id") or user_type != "Organization":
        html_display = wrong("目前只支持小组向小组转账！")
    if request.user == user:
        html_display = wrong("不能向自己转账！")
    if html_display['warn_code']==1:
        if hasattr(recipient, "organization_id"):
            return redirect(
                "/orginfo/?name={name}&warn_code=1&warn_message={message}".format(
                    name=recipient.oname,
                    message=html_display['warn_message']))
        else:
            return  redirect(
                "/stuinfo/?name={name}&warn_code=1&warn_message={message}".format(
                    name=recipient.name,
                    message=html_display['warn_message']))
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # 如果希望前移，请联系YHT
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "Transaction"
    bar_display["navbar_name"] = "发起转账"

    # 获取名字
    _, _, context = utils.check_user_type(user)
    context = utils.get_sidebar_and_navbar(user, bar_display=context)
    name = recipient.oname
    context["name"] = name
    context["rid"] = rid
    context["YQPoint"] = me.YQPoint

    # 如果是post, 说明发起了一起转账
    # 到这里, rid没有问题, 接收方和发起方都已经确定
    if request.method == "POST":
        # 获取转账消息, 如果没有消息, 则为空
        transaction_msg = request.POST.get("msg", "")

        # 检查发起转账的数据
        try:
            amount = float(request.POST["amount"])
            assert amount > 0
            assert int(amount * 10) == amount * 10
        except:
            return redirect(message_url(wrong('非法的转账数量!')))

        # 到这里, 参数的合法性检查完成了, 接下来应该是检查发起人的账户, 够钱就转
        try:
            notification = None
            with transaction.atomic():
                # 首先锁定用户
                payer = (
                    Organization.objects.activated()
                        .select_for_update()
                        .get(organization_id=request.user)
                )

                # 接下来确定金额
                if payer.oname != YQP_ONAME and payer.YQPoint < amount:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = (
                            "现存元气值余额为"
                            + str(payer.YQPoint)
                            + ", 不足以发起额度为"
                            + str(amount)
                            + "的转账!"
                    )
                else:
                    payer.YQPoint -= amount
                    record = TransferRecord.objects.create(
                        proposer=request.user,
                        recipient=user,
                        amount=amount,
                        message=transaction_msg,
                        rtype=TransferRecord.TransferType.TRANSACTION
                    )
                    record.save()
                    payer.save()
                    warn_message = "成功发起向" + name + "的转账! 元气值将在对方确认后到账。"

                    content_msg = transaction_msg if transaction_msg else f'转账金额：{amount}'
                    notification = notification_create(
                        receiver=user,
                        sender=request.user,
                        typename=Notification.Type.NEEDDO,
                        title=Notification.Title.TRANSFER_CONFIRM,
                        content=content_msg,
                        URL="/myYQPoint/",
                        relate_TransferRecord=record,
                    )
            if notification is not None:
                publish_notification(
                    notification,
                    app=WechatApp.TRANSFER,
                    level=WechatMessageLevel.IMPORTANT,
                )
            return redirect("/myYQPoint/")

        except Exception as e:
            # print(e)
            html_display["warn_code"] = 1
            html_display["warn_message"] = "出现无法预料的问题, 请联系管理员!"


    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # 如果希望前移，请联系YHT
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "Transaction"
    bar_display["navbar_name"] = "发起转账"
    return render(request, "transaction_page.html", locals())



def all_YQPoint_distributions(request):
    '''
        一个页面，展现当前所有的YQPointDistribute类
    '''
    context = dict()
    context['YQPoint_distributions'] = YQPointDistribute.objects.all()
    return render(request, "YQP_distributions.html", context)


def YQPoint_distribution(request, dis_id):
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


def new_YQPoint_distribute(request):
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


def YQPoint_distributions(request):
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

