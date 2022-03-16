from app.views_dependency import *
from app.models import (
    NaturalPerson,
    Position,
    Organization,
    OrganizationType,
    OrganizationTag,
    ModifyPosition,
    ModifyOrganization,
)
from app.org_utils import (
    update_org_application,
    update_pos_application,
    make_relevant_notification,
    send_message_check,
    get_tags,
)
from app.comment_utils import addComment, showComment
from app.utils import (
    get_person_or_org,
)

import json
from django.db import transaction

__all__ = [
    'showNewOrganization',
    'modifyOrganization',
    'showPosition',
    'saveShowPositionStatus',
    'modifyPosition',
    'sendMessage',
]


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='org_views[showNewOrganization]', record_user=True)
def showNewOrganization(request: HttpRequest):
    """
    YWolfeee: modefied on Aug 24 1:33 a.m. UTC-8
    新建小组的聚合界面
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type == "Organization":
        html_display["warn_code"] = 1
        html_display["warn_message"] = "请不要使用小组账号申请新小组！"
        return redirect("/welcome/" +
                        "?warn_code=1&warn_message={warn_message}".format(
                            warn_message=html_display["warn_message"]))

    me = get_person_or_org(request.user, user_type)

    # 拉取我负责管理申请的小组，这部分由我审核
    charge_org = ModifyOrganization.objects.filter(otype__in=me.incharge.all()).values_list("id",flat=True)

    # 拉去由我发起的申请，这部分等待审核
    applied_org = ModifyOrganization.objects.filter(pos=request.user).values_list("id",flat=True)
    all_instances = ModifyOrganization.objects.filter(id__in = list(set(charge_org) | set(applied_org)))
    # 排序整合，用于前端呈现
    all_instances = {
        "undone": all_instances.filter(status=ModifyOrganization.Status.PENDING).order_by("-modify_time", "-time"),
        "done"  : all_instances.exclude(status=ModifyOrganization.Status.PENDING).order_by("-modify_time", "-time")
    }

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="新建小组账号")
    return render(request, "neworganization_show.html", locals())


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='org_views[modifyOrganization]', record_user=True)
def modifyOrganization(request: HttpRequest):
    # YWolfeee: 重构小组申请页面 Aug 24 12:30 UTC-8
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = get_person_or_org(request.user)  # 获取自身
    if user_type == "Organization":
        html_display["warn_code"] = 1
        html_display["warn_message"] = "请不要使用小组账号申请新小组！"
        return redirect("/welcome/" +
                        "?warn_code=1&warn_message={warn_message}".format(
                            warn_message=html_display["warn_message"]))

    # ———————————————— 读取可能存在的申请 为POST和GET做准备 ————————————————

    # 设置application为None, 如果非None则自动覆盖
    application = None

    # 根据是否有newid来判断是否是第一次
    org_id = request.GET.get("org_id", None)

    # 获取前端页面中可能存在的提示
    try:
        if request.GET.get("warn_code", None) is not None:
            html_display["warn_code"] = int(request.GET.get("warn_code"))
            html_display["warn_message"] = request.GET.get("warn_message")
    except:
        pass

    if org_id is not None: # 如果存在对应申请
        try:    # 尝试获取已经新建的Position
            application = ModifyOrganization.objects.get(id = org_id)
            # 接下来检查是否有权限check这个条目
            # 至少应该是申请人或者审核老师
            assert (application.pos == request.user) or (application.otype.incharge == me)
        except: #恶意跳转
            html_display["warn_code"] = 1
            html_display["warn_message"] = "您没有权限访问该网址！"
            return redirect("/welcome/" +
                            "?warn_code=1&warn_message={warn_message}".format(
                                warn_message=html_display["warn_message"]))
        is_new_application = False # 前端使用量, 表示是老申请还是新的

    else:
        # 如果不存在id, 是一个新建小组页面。
        # 已保证小组不可能访问，任何人都可以发起新建小组。
        application = None
        is_new_application = True

    '''
        至此，如果是新申请那么application为None，否则为对应申请
        application = None只有在个人新建申请的时候才可能出现，对应位is_new_application
        接下来POST
    '''

    # ———————— Post操作，分为申请变更以及添加评论   ————————

    if request.method == "POST":
        # 如果是状态变更
        if request.POST.get("post_type", None) is not None:

            # 主要操作函数，更新申请状态 TODO
            context = update_org_application(application, me, request)

            if context["warn_code"] == 2:   # 成功修改申请
                # 回传id 防止意外的锁操作
                application = ModifyOrganization.objects.get(id = context["application_id"])
                is_new_application = False #状态变更
                if request.POST.get("post_type") == "new_submit":
                    # 重要！因为该界面没有org_id，重新渲染新建界面
                    #is_new_application = True
                    # YWolfeee 不理解
                    pass

                # 处理通知相关的操作，并根据情况发送微信
                # 默认需要成功,失败也不是用户的问题，直接给管理员报错 TODO
                try:
                    make_relevant_notification(application, request.POST)
                except:
                    raise NotImplementedError

            elif context["warn_code"] != 1: # 没有返回操作提示
                raise NotImplementedError("处理小组申请中出现未预见状态，请联系管理员处理！")


        else:   # 如果是新增评论
            # 权限检查
            allow_comment = True if (not is_new_application) and (
                application.is_pending()) else False
            if not allow_comment:   # 存在不合法的操作
                return redirect(message_url(wrong('存在不合法操作,请与管理员联系!')))
            context = addComment(request, application, \
                application.otype.incharge.person_id if me.person_id == application.pos \
                    else application.pos)

        # 准备用户提示量
        # html_display["warn_code"] = context["warn_code"]
        # html_display["warn_message"] = context["warn_message"]
        # warn_code, warn_message = context["warn_code"], context["warn_message"]

        # 为了保证稳定性，完成POST操作后同意全体回调函数，进入GET状态
        if application is None:
            return redirect(message_url(context, '/modifyOrganization/'))
        else:
            return redirect(message_url(context, f'/modifyOrganization/?org_id={application.id}'))

    # ———————— 完成Post操作, 接下来开始准备前端呈现 ————————

    # 首先是写死的前端量
    org_type_list = {
        w:{
            'value'   : str(w),
            'display' : str(w)+"(负责老师:"+str(w.incharge)+")",  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for w in OrganizationType.objects.all()
    }

    '''
        个人：可能是初次申请或者是修改申请
        小组：可能是审核申请
        # TODO 也可能是两边都想自由的查看这个申请
        区别：
            (1) 整个表单允不允许修改和评论
            (2) 变量的默认值[可以全部统一做]
    '''

    # (1) 是否允许修改&允许评论
    # 用户写表格?
    allow_form_edit = True if (
                is_new_application or (application.pos == me.person_id and application.is_pending())) else False
    # 小组审核?
    allow_audit_submit = True if (not is_new_application) and (
                application.is_pending()) and (application.otype.incharge == me) else False
    # 评论区?
    allow_comment = True if (not is_new_application) and (application.is_pending()) \
                    else False

    # (2) 表单变量的默认值

    # 首先禁用一些选项

    # 评论区
    commentable = allow_comment
    comments = showComment(application) if application is not None else None
    # 用于前端展示
    apply_person = me if is_new_application else NaturalPerson.objects.get(person_id=application.pos)
    app_avatar_path = apply_person.get_user_ava()
    org_avatar_path = utils.get_user_ava(application, "Organization")
    org_types = OrganizationType.objects.order_by("-otype_id").all()  # 当前小组类型，前端展示需要
    former_img = Organization().get_user_ava()
    all_tags = list(OrganizationTag.objects.all())
    org_tags = []
    if not is_new_application:
        org_type_list[application.otype]['selected'] = True
        org_tags = get_tags(application.tags)

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="小组申请详情")
    return render(request, "modify_organization.html", locals())


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='org_views[showPosition]', record_user=True)
def showPosition(request: HttpRequest):
    '''
    成员的聚合界面
    '''
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = get_person_or_org(request.user)

    # 查看成员聚合页面：拉取个人或小组相关的申请
    if user_type == "Person":
        #shown_instances = ModifyPosition.objects.filter(person=me)
        all_instances = {
            "undone": ModifyPosition.objects.filter(person=me, status=ModifyPosition.Status.PENDING).order_by('-modify_time', '-time'),
            "done": ModifyPosition.objects.filter(person=me).exclude(status=ModifyPosition.Status.PENDING).order_by('-modify_time', '-time')
        }
        all_org = Organization.objects.activated().exclude(
            id__in = all_instances["undone"].values_list("org_id",flat=True))
    else:
        all_instances = {
            "undone": ModifyPosition.objects.filter(org=me,status=ModifyPosition.Status.PENDING).order_by('-modify_time', '-time'),
            "done": ModifyPosition.objects.filter(org=me).exclude(status=ModifyPosition.Status.PENDING).order_by('-modify_time', '-time')
        }
    #shown_instances = shown_instances.order_by('-modify_time', '-time')
    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="成员申请")
    return render(request, 'showPosition.html', locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='org_views[saveShowPositionStatus]', record_user=True)
def saveShowPositionStatus(request: HttpRequest):
    valid, user_type, html_display = utils.check_user_type(request.user)

    me = get_person_or_org(request.user, user_type)
    params = json.loads(request.body.decode("utf-8"))

    with transaction.atomic():
        try:
            position = Position.objects.select_for_update().get(id=params["id"])
        except:
            return JsonResponse({"success":False})
        if params["status"]:
            position.show_post = True
        else:
            org = position.org
            if len(Position.objects.filter(
                    is_admin=True,
                    org=org)) == 1 and position.pos == 0:  # 非法前端量修改
                return JsonResponse({"success": False})
            position.show_post = False
        position.save()
    return JsonResponse({"success": True})


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='org_views[modifyPosition]', record_user=True)
def modifyPosition(request: HttpRequest):
    # YWolfeee: 重构成员申请页面 Aug 24 12:30 UTC-8
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = get_person_or_org(request.user)  # 获取自身

    # 前端使用量user_type，表示观察者是小组还是个人

    # ———————————————— 读取可能存在的申请 为POST和GET做准备 ————————————————

    # 设置application为None, 如果非None则自动覆盖
    application = None

    # 根据是否有newid来判断是否是第一次
    position_id = request.GET.get("pos_id", None)
    if position_id is not None: # 如果存在对应小组
        try:
            application = ModifyPosition.objects.get(id = position_id)
            # 接下来检查是否有权限check这个条目
            # 至少应该是申请人或者被申请小组之一
            if user_type == "Person" and application.person != me:
                # 尝试获取已经新建的Position
                html_display = utils.user_login_org(request,application.org)
                if html_display['warn_code']==1:
                    return redirect(
                        "/welcome/" +
                        "?warn_code=1&warn_message={warn_message}".format(
                            warn_message=html_display["warn_message"]))
                else:
                    #防止后边有使用，因此需要赋值
                    user_type = "Organization"
                    request.user=application.org.organization_id
                    me = application.org
            assert (application.org == me) or (application.person == me)
        except: #恶意跳转
            html_display["warn_code"] = 1
            html_display["warn_message"] = "您没有权限访问该网址！"
            return redirect("/welcome/" +
                            "?warn_code=1&warn_message={warn_message}".format(
                                warn_message=html_display["warn_message"]))
        is_new_application = False # 前端使用量, 表示是老申请还是新的
        applied_org = application.org

    else:   # 如果不存在id, 默认应该传入org_name参数
        org_name = request.GET.get("org_name", None)
        try:
            applied_org = Organization.objects.activated().get(oname=org_name)
            assert user_type == "Person" # 只有个人能看到这个新建申请的界面

        except:
            # 非法的名字, 出现恶意修改参数的情况
            html_display["warn_code"] = 1
            html_display["warn_message"] = "网址遭到篡改，请检查网址的合法性或尝试重新进入成员申请页面"
            return redirect("/welcome/" +
                            "?warn_code=1&warn_message={warn_message}".format(
                                warn_message=html_display["warn_message"]))

        # 查找已经存在的审核中的申请
        try:
            application = ModifyPosition.objects.get(
                org = applied_org, person = me, status = ModifyPosition.Status.PENDING)
            is_new_application = False # 如果找到, 直接跳转老申请
        except:
            is_new_application = True

    '''
        至此，如果是新申请那么application为None，否则为对应申请
        application = None只有在个人新建申请的时候才可能出现，对应位is_new_application
        applied_org为对应的小组
        接下来POST
    '''

    # ———————— Post操作，分为申请变更以及添加评论   ————————

    if request.method == "POST":
        # 如果是状态变更
        if request.POST.get("post_type", None) is not None:

            # 主要操作函数，更新申请状态
            context = update_pos_application(application, me, user_type,
                    applied_org, request.POST)

            if context["warn_code"] == 2:   # 成功修改申请
                # 回传id 防止意外的锁操作
                application = ModifyPosition.objects.get(id = context["application_id"])
                is_new_application = False  #状态变更

                # 处理通知相关的操作，并根据情况发送微信
                # 默认需要成功,失败也不是用户的问题，直接给管理员报错
                make_relevant_notification(application, request.POST)

            elif context["warn_code"] != 1: # 没有返回操作提示
                raise NotImplementedError("处理成员申请中出现未预见状态，请联系管理员处理！")


        else:   # 如果是新增评论
            # 权限检查
            allow_comment = True if (not is_new_application) and (
                application.is_pending()) else False
            if not allow_comment:   # 存在不合法的操作
                return redirect(
                    "/welcome/?warn_code=1&warn_message=存在不合法操作,请与管理员联系!")
            context = addComment(request, application, application.org.organization_id if user_type == 'Person' else application.person.person_id)

        # 准备用户提示量
        html_display["warn_code"] = context["warn_code"]
        html_display["warn_message"] = context["warn_message"]

    # ———————— 完成Post操作, 接下来开始准备前端呈现 ————————

    # 首先是写死的前端量
    # 申请的职务类型, 对应ModifyPosition.ApplyType
    apply_type_list = {
        w:{
                    # 对应的status设置, 属于ApplyType
            'display' : str(w),  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for w in ModifyPosition.ApplyType
    }
    # 申请的职务等级
    position_name_list = [
        {
            'display' : applied_org.otype.get_name(i),  #名称
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False,   # 是否默认选中这个量
        }
        for i in range(applied_org.otype.get_length())
    ]

    '''
        个人：可能是初次申请或者是修改申请
        小组：可能是审核申请
        # TODO 也可能是两边都想自由的查看这个申请
        区别：
            (1) 整个表单允不允许修改和评论
            (2) 变量的默认值[可以全部统一做]
    '''

    # (1) 是否允许修改&允许评论
    # 用户写表格?
    allow_form_edit = True if (user_type == "Person") and (
                is_new_application or application.is_pending()) else False
    # 小组审核?
    allow_audit_submit = True if (not user_type == "Person") and (not is_new_application) and (
                application.is_pending()) else False
    # 评论区?
    allow_comment = True if (not is_new_application) and (application.is_pending()) \
                    else False

    # (2) 表单变量的默认值

    # 首先禁用一些选项

    # 评论区
    commentable = allow_comment
    comments = showComment(application) if application is not None else None
    # 用于前端展示：如果是新申请，申请人即“me”，否则从application获取。
    apply_person = me if is_new_application else application.person
    app_avatar_path = apply_person.get_user_ava()
    org_avatar_path = applied_org.get_user_ava()
    # 获取个人与小组[在当前学年]的关系
    current_pos_list = Position.objects.current().filter(person=apply_person, org=applied_org)
    # 应当假设只有至多一个类型

    # 检查该同学是否已经属于这个小组
    whether_belong = True if len(current_pos_list) and \
        current_pos_list[0].status == Position.Status.INSERVICE else False
    if whether_belong:
        # 禁用掉加入小组
        apply_type_list[ModifyPosition.ApplyType.JOIN]['disabled'] = True
        # 禁用掉修改职位中的自己的那个等级
        position_name_list[current_pos_list[0].get_pos_number()]["disabled"] = True
        #current_pos_name = applied_org.otype.get_name(current_pos_list[0].pos)
    else:   #不属于小组, 只能选择加入小组
        apply_type_list[ModifyPosition.ApplyType.WITHDRAW]['disabled'] = True
        apply_type_list[ModifyPosition.ApplyType.TRANSFER]['disabled'] = True

    # TODO: 设置默认值
    if not is_new_application:
        apply_type_list[application.apply_type]['selected'] = True
        if application.pos is not None:
            position_name_list[application.pos]['selected'] = True
        #未通过时，不能修改，但是需要呈现变量。
        if application.status != ModifyPosition.Status.PENDING:  # 未通过
            apply_type_list[application.apply_type]['disabled'] = False
            if not application.apply_type == ModifyPosition.ApplyType.WITHDRAW:
                position_name_list[application.pos]["disabled"] = False
    else:
        position_name_list[-1]['selected'] = True   # 默认选中pos最低的！

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="成员申请详情")
    return render(request, "modify_position.html", locals())


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='org_views[sendMessage]', record_user=True)
def sendMessage(request: HttpRequest):
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = get_person_or_org(request.user)  # 获取自身
    if user_type == "Person":
        html_display["warn_code"] = 1
        html_display["warn_message"] = "只有小组账号才能发送通知！"
        return redirect("/welcome/" +
                        "?warn_code=1&warn_message={warn_message}".format(
                            warn_message=html_display["warn_message"]))

    if request.method == "POST":
        # 合法性检查
        context = send_message_check(me,request)

        # 准备用户提示量
        html_display["warn_code"] = context["warn_code"]
        html_display["warn_message"] = context["warn_message"]


    # 前端展示量
    receiver_type_list = {
        w:{
            'display' : w,  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for w in ['订阅用户','小组成员','推广消息']
    }

    # 设置默认量
    if request.POST.get('receiver_type', None) is not None:
        receiver_type_list[request.POST.get('receiver_type')]['selected'] = True
    if request.POST.get('url', None) is not None:
        url = request.POST.get('url', None)
    if request.POST.get('content', None) is not None:
        content = request.POST.get('content', None)
    if request.POST.get('title', None) is not None:
        title = request.POST.get('title', None)

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="信息发送中心")
    return render(request, "sendMessage.html", locals())
