from app.utils_dependency import *
from app.models import (
    NaturalPerson,
    Position,
    Organization,
    OrganizationType,
    ModifyPosition,
    Notification,
    ModifyOrganization,
    Wishes,
)
from app.notification_utils import (
    notification_create,
    bulk_notification_create,
    notification_status_change,
)
from app.wechat_send import (
    publish_notifications,
    WechatApp,
    WechatMessageLevel,
)
from app.utils import (
    get_person_or_org,
    random_code_init,
    if_image,
)

from datetime import datetime, timedelta

from django.db.models import Q
from django.contrib.auth.models import User

__all__ = [
    'find_max_oname',
    'accept_modifyorg_submit',
    'check_neworg_request',
    'update_org_application',
    'update_pos_application',
    'make_relevant_notification',
    'send_message_check',
]


def find_max_oname():
    '''查询小组代号的最大值+1 用于modifyOrganization()函数，新建小组'''
    organizations = Organization.objects.filter(
        organization_id__username__startswith="zz"
    ).order_by("-organization_id__username")
    max_org = organizations[0]
    max_oname = str(max_org.organization_id.username)
    max_oname = int(max_oname[2:]) + 1
    prefix = "zz"
    max_oname = prefix + str(max_oname).zfill(5)
    return max_oname


def accept_modifyorg_submit(application): #同意申请，假设都是合法操作
    # 新建一系列东西
    username = find_max_oname()
    user = User.objects.create(username=username)
    password = random_code_init(user.id)
    user.set_password(password)
    user.save()
    org = Organization.objects.create(organization_id=user,
                                      oname=application.oname,
                                      otype=application.otype,
                                      YQPoint=0.0,
                                      introduction=application.introduction,
                                      avatar=application.avatar)

    for person in NaturalPerson.objects.all():
        org.unsubscribers.add(person)
    org.save()
    charger = get_person_or_org(application.pos)
    pos = Position.objects.create(person=charger,
                                  org=org,
                                  pos=0,
                                  status=Position.Status.INSERVICE,
                                  is_admin=True)
    # 修改申请状态
    ModifyOrganization.objects.filter(id=application.id).update(
        status=ModifyOrganization.Status.CONFIRMED)
    Wishes.objects.create(text=f"{org.otype.otype_name}“{org.oname}”刚刚成立啦！快点去关注一下吧！")


def check_neworg_request(request, org=None):
    '''检查neworg request参数的合法性, 用在modifyorganization函数中'''
    context = dict()
    context["warn_code"] = 0
    oname = str(request.POST["oname"])
    if len(oname) >= 32:
        return wrong("小组的名字不能超过32字")
    if oname == "":
        return wrong("小组的名字不能为空")
    if org is not None and oname == org.oname:
        if (
            len(
                ModifyOrganization.objects.exclude(
                    status=ModifyOrganization.Status.CANCELED
                )
                .exclude(status=ModifyOrganization.Status.REFUSED)
                .filter(oname=oname)
            )
            > 1
            or len(Organization.objects.filter(oname=oname)) != 0
        ):
            context["warn_code"] = 1
            context["warn_message"] = "小组的名字不能与正在申请的或者已存在的小组的名字重复"
            return context
    else:
        if (
            len(
                ModifyOrganization.objects.exclude(
                    status=ModifyOrganization.Status.CANCELED
                )
                .exclude(status=ModifyOrganization.Status.REFUSED)
                .filter(oname=oname)
            )
            != 0
            or len(Organization.objects.filter(oname=oname)) != 0
        ):
            context["warn_code"] = 1
            context["warn_message"] = "小组的名字不能与正在申请的或者已存在的小组的名字重复"
            return context

    try:
        otype = str(request.POST.get("otype"))
        context["otype"] = OrganizationType.objects.get(otype_name=otype)
    except:
        context["warn_code"] = 1
        # user can't see it . we use it for debugging
        context["warn_message"] = "数据库没有小组的所在类型，请联系管理员！"
        return context

    context["avatar"] = request.FILES.get("avatar")
    if context["avatar"] is not None:
        if if_image(context["avatar"]) == 1:
            context["warn_code"] = 1
            context["warn_message"] = "小组的头像应当为图片格式！"
            return context

    context["oname"] = oname  # 小组名字
    # 小组类型，必须有
    context["pos"] = request.user  # 负责人，必须有滴
    context["introduction"] = str(request.POST.get("introduction", ""))  # 小组介绍，可能为空

    context["application"] = str(request.POST.get("application", ""))  # 申请理由

    if context["application"] == "":
        context["warn_code"] = 1
        context["warn_message"] = "申请理由不能为空"
    return context


def update_org_application(application, me, request):
    '''
    修改成员申请状态的操作函数, application为修改的对象，可以为None
    me为操作者
    info为前端POST字典
    返回值为context, warn_code = 1表示失败, 2表示成功; 错误信息在context["warn_message"]
    如果成功context会返回update之后的application,
    '''
    # 关于这个app和我的关系已经完成检查
    # 确定info中有post_type且不为None

    # 首先上锁
    with transaction.atomic():
        info = request.POST
        if application is not None:
            application = ModifyOrganization.objects.select_for_update().get(id=application.id)
            user_type = 'pos' if me.person_id == application.pos else 'incharge'
        else:
            user_type = 'pos'
        # 首先确定申请状态
        post_type = info.get("post_type")
        feasible_post = ["new_submit", "modify_submit",
                         "cancel_submit", "accept_submit", "refuse_submit"]
        if post_type not in feasible_post:
            return wrong("申请状态异常！")

        # 接下来确定访问的老师 和 个人是否在干分内的事
        if (user_type == "pos" and feasible_post.index(post_type) >= 3) or (
                user_type == "incharge" and feasible_post.index(post_type) <= 2):
            return wrong("您无权进行此操作. 如有疑惑, 请联系管理员")

        if feasible_post.index(post_type) <= 2: # 个人操作，新建、修改、删除

            # 如果是取消申请
            if post_type == "cancel_submit":
                if not application.is_pending():    # 如果不在pending状态, 可能是重复点击
                    return wrong("该申请已经完成或被取消!")
                # 接下来可以进行取消操作
                ModifyOrganization.objects.filter(id=application.id).update(
                    status=ModifyOrganization.Status.CANCELED)
                context = succeed("成功取消小组" + application.oname + "的申请!")
                context["application_id"] = application.id
                return context
            else:
                # 无论是新建还是修改, 都需要检查所有参数的合法性
                context = check_neworg_request(request, application)
                if context['warn_code'] == 1:
                    return context

                otype = OrganizationType.objects.get(otype_name=info.get('otype'))

                # 写入数据库
                if post_type == 'new_submit':
                    application = ModifyOrganization.objects.create(
                        oname=info.get('oname'),
                        otype=otype,
                        pos=me.person_id,
                        introduction=info.get('introduction'),
                        application=info.get('application')
                    )
                    if context["avatar"] is not None:
                        application.avatar = context['avatar'];
                        application.save()
                    context = succeed(
                        "成功发起小组“" + info.get("oname") +
                        "”的新建申请，请耐心等待" + str(otype.incharge.name) + "老师审核!")
                    context['application_id'] = application.id
                    return context
                else: # modify_submit
                    if not application.is_pending():
                        return wrong("不能修改状态不为“申请中”的申请！")
                    # 如果是修改申请, 不能够修改小组类型
                    if application.otype != otype:
                        return wrong("修改申请时不允许修改小组类型。如确需修改，请取消后重新申请!")
                    if (application.oname == info.get("oname")
                            and application.introduction == info.get('introduction')
                            and application.avatar == info.get('avatar', None)
                            and application.application == info.get('application')):
                        return wrong("没有检测到修改！")
                    # 至此可以发起修改
                    ModifyOrganization.objects.filter(id=application.id).update(
                        oname=info.get('oname'),
                        #otype=OrganizationType.objects.get(otype_name=info.get('otype')),
                        introduction=info.get('introduction'),
                        application=info.get('application'))
                    if context["avatar"] is not None:
                        application.avatar = context['avatar']
                        application.save()
                    context = succeed("成功修改小组“" + info.get('oname') + "”的新建申请!")
                    context["application_id"] = application.id
                    return context
        else: # 是老师审核的操作, 通过\拒绝
            # 已经确定 me == application.otype.inchage 了
            # 只需要确定状态是否匹配
            if not application.is_pending():
                return wrong("无法操作, 该申请已经完成或被取消!")
            # 否则，应该直接完成状态修改
            if post_type == "refuse_submit":
                ModifyOrganization.objects.filter(id=application.id).update(
                    status=ModifyOrganization.Status.REFUSED)
                context = succeed(
                    "成功拒绝来自"
                    + NaturalPerson.objects.get(person_id=application.pos).name
                    + "的申请!")
                context["application_id"] = application.id
                return context
            else:   # 通过申请
                '''
                    注意，在这个申请发起、修改的时候，都应该保证这条申请的合法地位
                    例如不存在冲突申请、职位的申请是合理的等等
                    否则就不应该通过这条创建
                '''
                try:
                    with transaction.atomic():
                        accept_modifyorg_submit(application)
                        context = succeed(
                            "成功通过来自"
                             + NaturalPerson.objects.get(person_id=application.pos).name
                             + "的申请!")
                        context["application_id"] = application.id
                        return context
                except:
                    return wrong("出现系统意料之外的行为，请联系管理员处理!")


def update_pos_application(application, me, user_type, applied_org, info):
    '''
    修改成员申请状态的操作函数, application为修改的对象，可以为None
    me为操作者
    info为前端POST字典
    返回值为context, warn_code = 1表示失败, 2表示成功; 错误信息在context["warn_message"]
    如果成功context会返回update之后的application,
    '''
    # 关于这个application与我的关系已经完成检查
    # 确定info中有post_type且不是None

    # 首先上锁
    with transaction.atomic():
        if application is not None:
            application = ModifyPosition.objects.select_for_update().get(id=application.id)

        # 首先确定申请状态
        post_type = info.get("post_type")
        feasible_post = ["new_submit", "modify_submit",
                         "cancel_submit", "accept_submit", "refuse_submit"]
        if post_type not in feasible_post:
            return wrong("申请状态异常！")

        # 接下来确定访问的个人/小组是不是在做分内的事情
        if (user_type == "Person" and feasible_post.index(post_type) >= 3) or (
                user_type == "Organization" and feasible_post.index(post_type) <= 2):
            return wrong("您无权进行此操作. 如有疑惑, 请联系管理员")

        if feasible_post.index(post_type) <= 2:  # 是个人的操作, 新建\修改\删除

            # 访问者一定是个人
            try:
                assert user_type == "Person"
            except:
                return wrong("访问者身份异常！")

            # 如果是取消申请
            if post_type == "cancel_submit":
                if not application.is_pending():    # 如果不在pending状态, 可能是重复点击
                    return wrong("该申请已经完成或被取消!")
                # 接下来可以进行取消操作
                ModifyPosition.objects.filter(id=application.id).update(
                    status=ModifyPosition.Status.CANCELED)
                context = succeed("成功取消向" + applied_org.oname + "的申请!")
                context["application_id"] = application.id
                return context

            else:
                # 无论是新建还是修改, 都应该根据申请类别、申请职务和申请理由进行审核
                # 申请理由
                apply_reason = info.get("apply_reason")
                if apply_reason is None or apply_reason == "":
                    return wrong("申请失败, 申请理由或陈述不能为空!")

                # 申请类别和职务
                # 讨论申请的类别，抓取错误
                apply_type = info.get("apply_type")
                if apply_type == "加入小组":
                    # 此时应该满足的条件是不存在对应的在职职位
                    if Position.objects.activated().filter(
                            person=me, org=applied_org).exists():
                        return wrong("加入已存在的小组！")

                    apply_pos_name = str(info.get('apply_pos'))
                    apply_pos = applied_org.otype.get_pos_from_str(apply_pos_name)
                elif apply_type == "退出小组":
                    if not Position.objects.activated().filter(
                            person=me, org=applied_org).exists():
                        return wrong("退出小组出错, 请联系管理员!")
                    managers = Position.objects.activated().filter(
                        org=applied_org, is_admin=True)
                    if len(managers) == 1 and managers[0].person == me:
                        return wrong("作为小组唯一的老大，你不能退出！")
                    # 退出小组不应该有apply_pos
                    apply_pos = None
                elif apply_type == "修改职位":
                    try:
                        cur_position = Position.objects.activated().get(person=me, org=applied_org)
                        apply_pos_name = str(info.get('apply_pos'))
                        apply_pos = cur_position.org.otype.get_pos_from_str(
                            apply_pos_name)
                        assert apply_pos != cur_position.pos
                    except:
                        return wrong("修改职位出错！")
                else:  # 非法操作
                    return wrong("检测到恶意的申请操作. 如有疑惑，请联系管理员!")

                # 如果是新建申请, 则应该意味着me+applied_org的pending申请目前不存在
                if post_type == "new_submit":
                    if len(ModifyPosition.objects.filter(
                        person=me, status=ModifyPosition.Status.PENDING
                    )) >= 3:
                        return wrong("审核中的成员变动申请的数目不能超过三个！")
                    if ModifyPosition.objects.filter(
                        person=me, org=applied_org, status=ModifyPosition.Status.PENDING
                    ).exists():
                        return wrong("向该小组的申请已存在，请不要重复申请！")
                    # 至此可以新建申请, 创建一个空申请
                    application = ModifyPosition.objects.create(
                        pos=apply_pos,
                        person=me,
                        org=applied_org,
                        apply_type=apply_type,
                        reason=apply_reason,
                        )
                    context = succeed("成功发起向" + applied_org.oname + "的申请!")
                    context["application_id"] = application.id
                    return context

                else:  # post_type == "modify_submit":
                    # 如果是修改申请的话, 状态应该是pending
                    if not application.is_pending():
                        return wrong("不可以修改状态不为申请中的申请!")
                    # 修改申请的状态应该有所变化
                    if application.reason == apply_reason and \
                            application.apply_type == apply_type and \
                            application.pos == apply_pos:
                        return wrong("没有检测到修改!")
                    # 至此可以发起修改
                    ModifyPosition.objects.filter(id=application.id).update(
                        pos=apply_pos, reason=apply_reason, apply_type=apply_type)
                    context = succeed("成功修改向" + applied_org.oname + "的申请!")
                    context["application_id"] = application.id
                    return context

        else: # 是小组的操作, 通过\拒绝
            # 已经确定 me == application.org 了
            # 只需要确定状态是否匹配
            if not application.is_pending():
                return wrong("无法操作, 该申请已经完成或被取消!")
            # 否则，应该直接完成状态修改
            if post_type == "refuse_submit":
                ModifyPosition.objects.filter(id=application.id).update(
                    status=ModifyPosition.Status.REFUSED)
                context = succeed("成功拒绝来自" + application.person.name + "的申请!")
                context["application_id"] = application.id
                return context
            else:   # 通过申请
                '''
                    注意，在这个申请发起、修改的时候，都应该保证这条申请的合法地位
                    例如不存在冲突申请、职位的申请是合理的等等
                    否则就不应该通过这条创建
                '''
                try:
                    application.accept_submit()
                    context = succeed("成功通过来自" + application.person.name + "的申请!")
                    context["application_id"] = application.id
                    return context
                except:
                    return wrong("出现系统意料之外的行为，请联系管理员处理!")


@log.except_captured(source='org_utils[make_relevant_notification]')
def make_relevant_notification(application, info):
    '''
    对一个已经完成的申请, 构建相关的通知和对应的微信消息, 将有关的事务设为已完成
    如果有错误，则不应该是用户的问题，需要发送到管理员处解决
    '''
    # 考虑不同post_type的信息发送行为
    post_type = info.get("post_type")
    feasible_post = [
        "new_submit",
        "modify_submit",
        "cancel_submit",
        "accept_submit",
        "refuse_submit",
    ]

    # 统一该函数：判断application的类型
    application_type = type(application)
    # 准备呈现使用的变量与信息

    # 先准备一些复杂变量(只是为了写起来方便所以先定义，不然一大个插在后面的操作里很丑)
    if application_type == ModifyPosition:
        try:
            position_name = application.org.otype.get_name(application.pos)  # 职位名称
        except:
            position_name = "退出小组"
    elif application_type == ModifyOrganization:
        apply_person = NaturalPerson.objects.get(person_id=application.pos)
        inchage_person = application.otype.incharge
        try:
            new_org = Organization.objects.get(oname=application.oname)
        except:
            new_org = None

    # 准备创建notification需要的构件：发送方、接收方、发送内容、通知类型、通知标题、URL、关联外键
    if application_type == ModifyPosition:
        if post_type == 'new_submit':
            content = f'{application.person.name}发起小组成员变动申请，职位申请：{position_name}，请审核~'
        elif post_type == 'modify_submit':
            content = f'{application.person.name}修改了成员申请信息，请审核~'
        elif post_type == 'cancel_submit':
            content = f'{application.person.name}取消了成员申请信息。'
        elif post_type == 'accept_submit':
            content = f'恭喜，您申请的成员变动：{application.org.oname}，审核已通过！申请职位：{position_name}。'
        elif post_type == 'refuse_submit':
            content = f'抱歉，您申请的成员变动：{application.org.oname}，审核未通过！申请职位：{position_name}。'
        else:
            raise NotImplementedError
        applyer_id = application.person.person_id
        applyee_id = application.org.organization_id
        not_type = Notification.Title.POSITION_INFORM
        URL = f'/modifyPosition/?pos_id={application.id}'
    elif application_type == ModifyOrganization:
        if post_type == 'new_submit':
            content = f'{apply_person.name}发起新建小组申请，新建小组：{application.oname}，请审核～'
        elif post_type == 'modify_submit':
            content = f'{apply_person.name}修改了小组申请信息，请审核～'
        elif post_type == 'cancel_submit':
            content = f'{apply_person.name}取消了小组{application.oname}的申请。'
        elif post_type == 'accept_submit':
            content = (
                f'恭喜，您申请的小组：{application.oname}，审核已通过！'
                f'小组编号为{new_org.organization_id.username}，'
                f'初始密码为{random_code_init(new_org.organization_id.id)}，'
                '请尽快登录修改密码。登录方式：(1)在负责人账户点击左侧「切换账号」；'
                '(2)从登录页面用小组编号或小组名称以及密码登录。'
                '你可以把小组的主页转发到微信群或朋友圈，邀请更多朋友订阅关注。'
                '这样大家就能及时收到活动消息啦！使用愉快～'
            )
        elif post_type == 'refuse_submit':
            content = f'抱歉，您申请的小组：{application.oname}，审核未通过！'
        else:
            raise NotImplementedError
        applyer_id = apply_person.person_id
        applyee_id = inchage_person.person_id
        not_type = Notification.Title.NEW_ORGANIZATION
        URL = f'/modifyOrganization/?org_id={application.id}'

    sender = applyer_id if feasible_post.index(post_type) < 3 else applyee_id
    receiver = applyee_id if feasible_post.index(post_type) < 3 else applyer_id
    typename = (Notification.Type.NEEDDO
                if post_type == 'new_submit'
                else Notification.Type.NEEDREAD)
    title = Notification.Title.VERIFY_INFORM if post_type != 'accept_submit' else not_type
    relate_instance = application if post_type == 'new_submit' else None
    publish_to_wechat = True
    publish_kws = {'app': WechatApp.AUDIT}
    publish_kws['level'] = (WechatMessageLevel.IMPORTANT
                            if post_type != 'cancel_submit'
                            else WechatMessageLevel.INFO)
    # TODO cancel是否要发送notification？是否发送微信？

    # 正式创建notification
    notification_create(
        receiver=receiver,
        sender=sender,
        typename=typename,
        title=title,
        content=content,
        URL=URL,
        relate_instance=relate_instance,
        publish_to_wechat=publish_to_wechat,
        publish_kws=publish_kws,
    )

    # 对于处理类通知的完成(done)，修改状态
    # 这里的逻辑保证：所有的处理类通知的生命周期必须从“成员发起”开始，从“取消”“通过”“拒绝”结束。
    if feasible_post.index(post_type) >= 2:
        notification_status_change(
            application.relate_notifications.get(status=Notification.Status.UNDONE).id
        )


@log.except_captured(source='org_utils[send_message_check]')
def send_message_check(me, request):
    # 已经检查了我的类型合法，并且确认是post
    # 设置默认量
    receiver_type = request.POST.get('receiver_type', None)
    url = request.POST.get('url', "")
    content = request.POST.get('content', "")
    title = request.POST.get('title', "")

    if receiver_type is None:
        return wrong("发生了意想不到的错误：未接收到您选择的发送者类型！请联系管理员~")

    if len(content) == 0:
        return wrong("请填写通知的内容！")
    elif len(content) > 225:
        return wrong("通知的长度不能超过225个字！你超过了！")

    if len(title) == 0:
        return wrong("不能不写通知的标题！补起来！")
    elif len(title) > 10:
        return wrong("通知的标题不能超过10个字！不然发出来的通知会很丑！")

    if len(url) == 0:
        url = None
    else:
        try:
            if url[0:4].upper() != "HTTP":
                return wrong("URL应当以http或https开头！")
        except:
            return wrong("请输入正确的链接地址！")

    not_list = []
    sender = me.organization_id
    status = Notification.Status.UNDONE
    title = title
    content = content
    typename = Notification.Type.NEEDREAD
    URL = url
    before_time = datetime.now() - timedelta(minutes=1)
    after_time = datetime.now() + timedelta(minutes=1)
    recent_notifi = Notification.objects.filter(
        sender=sender, title=title).filter(
            Q(start_time__gte=before_time)
            & Q(start_time__lte=after_time))
    if len(recent_notifi) > 0:
        return wrong("您1min前发送过相同的通知，请不要短时间内重复发送相同的通知！")

    try:
        if receiver_type == "订阅用户":
            receivers = NaturalPerson.objects.activated().exclude(
                id__in=me.unsubscribers.all()).select_related('person_id')
            receivers = [receiver.person_id for receiver in receivers]
        else:   # 检查过逻辑了，不可能是其他的
            receivers = NaturalPerson.objects.activated().filter(
                id__in=me.position_set.values_list('person_id', flat=True)
                ).select_related('person_id')
            receivers = [receiver.person_id for receiver in receivers]

        # 创建通知
        success, bulk_identifier = bulk_notification_create(
                receivers=receivers,
                sender=sender,
                typename=typename,
                title=title,
                content=content,
                URL=URL,
                publish_to_wechat=False,
            )
        assert success
    except:
        return wrong("创建通知的时候出现错误！请联系管理员！")
    try:
        wechat_kws = {}
        if receiver_type == "订阅用户":
            wechat_kws['app'] = WechatApp.TO_SUBSCRIBER
        else:   # 小组成员
            wechat_kws['app'] = WechatApp.TO_MEMBER
        wechat_kws['filter_kws'] = {'bulk_identifier': bulk_identifier}
        assert publish_notifications(**wechat_kws)
    except:
        return wrong("发送微信的过程出现错误！请联系管理员！")

    return succeed(f"成功创建知晓类消息，发送给所有的{receiver_type}了!")
