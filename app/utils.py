from django.db import transaction
from app.models import (
    NaturalPerson,
    Organization,
    OrganizationType,
    Position,
    Notification,
    ModifyOrganization,
    Activity,
    Help,
    Reimbursement,
    ModifyPosition,
    Participant,
    OrganizationType
)
from django.contrib.auth.models import User
from django.dispatch.dispatcher import receiver
from django.contrib import auth
from django.shortcuts import redirect
from django.conf import settings
from boottest import local_dict
from datetime import datetime, timedelta
from functools import wraps
import re
import imghdr
import string
import random
import xlwt
from io import BytesIO
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
def check_user_access(redirect_url="/logout/"):
    """
    Decorator for views that checks that the user is valid, redirecting
    to specific url if necessary. Then it checks that the user is not
    first time login, redirecting to the modify password page otherwise.
    """

    def actual_decorator(view_function):
        @wraps(view_function)
        def _wrapped_view(request, *args, **kwargs):
            valid, user_type, html_display = check_user_type(request.user)
            if not valid:
                return redirect(redirect_url)

            isFirst = get_person_or_org(request.user, user_type).first_time_login
            # 如果是首次登陆，会跳转到密码修改的页面
            if isFirst:
                return redirect("/modpw/")

            return view_function(request, *args, **kwargs)

        return _wrapped_view

    return actual_decorator


def get_person_or_org(user, user_type=None):
    if user_type is None:
        if hasattr(user, "naturalperson"):
            return user.naturalperson
        else:
            return user.organization
    return (
        NaturalPerson.objects.get(person_id=user)
        if user_type == "Person"
        else Organization.objects.get(organization_id=user)
    )


# YWolfeee, Aug 16
# check_user_type只是获得user的类型，其他用于呈现html_display的内容全部转移到get_siderbar_and_navbar中
# 同步开启一个html_display，方便拓展前端逻辑的呈现
def check_user_type(user):
    html_display = {}
    if user.is_superuser:
        return False, "", html_display
    if user.username[:2] == "zz":
        user_type = "Organization"
        html_display["user_type"] = user_type
    else:
        user_type = "Person"
        html_display["user_type"] = user_type

    return True, user_type, html_display


def get_user_ava(obj, user_type):
    try:
        ava = obj.avatar
    except:
        ava = ""
    if not ava:
        if user_type == "Person":
            return settings.MEDIA_URL + "avatar/person_default.jpg"
        else:
            return settings.MEDIA_URL + "avatar/org_default.png"
    else:
        return settings.MEDIA_URL + str(ava)


def get_user_wallpaper(person, user_type):
    if user_type == "Person":
        return settings.MEDIA_URL + (str(person.wallpaper) or "wallpaper/person_wall_default.jpg")
    else:
        return settings.MEDIA_URL + (str(person.wallpaper) or "wallpaper/org_wall_default.jpg")

# 获取左边栏的内容，is_myself表示是否是自己, person表示看的人
def get_user_left_navbar(person, is_myself, html_display):
    # assert (
    #        "is_myself" in html_display.keys()
    # ), "Forget to tell the website whether this is the user itself!"
    raise NotImplementedError(
        "old left_navbar function has been abandoned, please use `get_sidebar_and_navbar` instead!"
    )
    html_display["underground_url"] = local_dict["url"]["base_url"]

    my_org_id_list = Position.objects.activated().filter(person=person).filter(pos=0)
    html_display["my_org_list"] = [w.org for w in my_org_id_list]  # 我管理的组织
    html_display["my_org_len"] = len(html_display["my_org_list"])
    return html_display


def get_org_left_navbar(org, is_myself, html_display):
    # assert (
    #        "is_myself" in html_display.keys()
    # ), "Forget to tell the website whether this is the user itself!"
    raise NotImplementedError(
        "old left_navbar function has been abandoned, please use `get_sidebar_and_navbar` instead!"
    )
    html_display["switch_org_name"] = org.oname
    html_display["underground_url"] = local_dict["url"]["base_url"]
    html_display["org"] = org
    return html_display


# YWolfeee Aug 16
# 修改left siderbar的逻辑，统一所有个人和所有组织的左边栏，不随界面而改变
# 这个函数负责统一get sidebar和navbar的内容，解决了信箱条数显示的问题
# user对象是request.user对象直接转移
# 内容存储在bar_display中
# Attention: 本函数请在render前的最后时刻调用

# added by syb, 8.23:
# 在函数中添加了title_name和navbar_name参数，根据这两个参数添加帮助信息
# 现在最推荐的调用方式是：在views的函数中，写
# bar_display = utils.get_sidebar_and_navbar(user, title_name, navbar_name)
def get_sidebar_and_navbar(user, navbar_name="", title_name="", bar_display=None):
    if bar_display is None:
        bar_display = {}  # 默认参数只会初始化一次，所以不应该设置为{}
    me = get_person_or_org(user)  # 获得对应的对象
    _, user_type, _ = check_user_type(user)
    bar_display["user_type"] = user_type

    # 接下来填补各种前端呈现信息

    # 头像
    bar_display["avatar_path"] = get_user_ava(me, user_type)

    # 信箱数量
    bar_display["mail_num"] = Notification.objects.filter(
        receiver=user, status=Notification.Status.UNDONE
    ).count()

    if user_type == "Person":
        bar_display["profile_name"] = "个人主页"
        bar_display["profile_url"] = "/stuinfo/"
        bar_display["name"] = me.name
        bar_display["person_type"] = me.identity

        # 个人需要地下室跳转
        bar_display["underground_url"] = local_dict["url"]["base_url"]

        # 个人所管理的组织列表
        my_org_id_list = Position.objects.activated().filter(person=me).filter(pos=0)
        bar_display["my_org_list"] = [w.org for w in my_org_id_list]  # 我管理的组织
        bar_display["my_org_len"] = len(bar_display["my_org_list"])

    else:
        bar_display["profile_name"] = "组织主页"
        bar_display["profile_url"] = "/orginfo/"

    bar_display["navbar_name"] = navbar_name
    # title_name默认与navbar_name相同
    bar_display["title_name"] = title_name if title_name else navbar_name

    if navbar_name != "":
        try:
            bar_display["help_message"] = local_dict["help_message"].get(
                navbar_name, ""
            )
        except:
            bar_display["help_message"] = ""
        try:
            bar_display["help_paragraphs"] = Help.objects.get(title=navbar_name).content
        except:
            bar_display["help_paragraphs"] = ""

    return bar_display



# 检查发起活动的request的合法性
def check_ac_request(request):
    # oid的获取
    context = dict()
    context["warn_code"] = 0

    try:
        assert request.POST["edit"] == "True"
        edit = True
    except:
        edit = False


def url_check(arg_url):
    if settings.DEBUG:  # DEBUG默认通过
        return True
    if arg_url is None:
        return True
    if re.match("^/[^/?]*/", arg_url):  # 相对地址
        return True
    for url in local_dict["url"].values():
        base = re.findall("^https?://[^/]*/?", url)[0]
        # print('base:', base)
        if re.match(base, arg_url):
            return True
    return False


# 允许进行 cross site 授权时，return True
def check_cross_site(request, arg_url):
    if arg_url is None:
        return True
    # 这里 base_url 最好可以改一下
    appointment = local_dict["url"]["base_url"]
    appointment_base = re.findall("^https?://[^/]*/", appointment)[0]
    if re.match(appointment_base, arg_url):
        valid, user_type, html_display = check_user_type(request.user)
        if not valid or user_type == "Organization":
            return False
    return True


def get_url_params(request, html_display):
    full_path = request.get_full_path()
    if "?" in full_path:
        params = full_path.split["?"][1]
        params = params.split["&"]
        for param in params:
            key, value = param.split["="][0], param.split["="][1]
            if key not in html_display.keys():  # 禁止覆盖
                html_display[key] = value

# 检查neworg request参数的合法性 ,用在modifyorganization函数中
def check_neworg_request(request, org=None):
    context = dict()
    context["warn_code"] = 0
    oname = str(request.POST["oname"])
    if len(oname) >= 32:
        return wrong("组织的名字不能超过32字")
    if oname == "":
        return wrong("组织的名字不能为空")
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
            context["warn_message"] = "组织的名字不能与正在申请的或者已存在的组织的名字重复"
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
            context["warn_message"] = "组织的名字不能与正在申请的或者已存在的组织的名字重复"
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
            context["warn_message"] = "组织的头像应当为图片格式！"
            return context

    context["oname"] = oname  # 组织名字
    # 组织类型，必须有
    context["pos"] = request.user  # 负责人，必须有滴
    context["introduction"] = str(request.POST.get("introduction", ""))  # 组织介绍，可能为空

    context["application"] = str(request.POST.get("application", ""))  # 申请理由

    if context["application"] == "":
        context["warn_code"] = 1
        context["warn_message"] = "申请理由不能为空"
    return context
# 检查neworg request参数的合法性 ,用在modifyoranization函数中

def check_newpos_request(request,prepos=None):

    context = dict()
    context['warn_code'] = 0
    if prepos is None:
        oname = str(request.POST['oname'])
    else:
        oname = prepos.position.org.oname
    context['apply_pos'] = int(request.POST.get('apply_pos',10))
    context['apply_type'] = str(request.POST.get('apply_type',"加入组织"))
    if len(oname) >= 32:
        context['warn_code'] = 1
        context['warn_msg'] = "组织的名字不能超过32字节"
        return context
    if oname=="":
        context['warn_code'] = 1
        context['warn_msg'] = "组织的名字不能为空"
        return context
    
    context['oname'] = oname  # 组织名字

    context["application"] = str(request.POST.get("application", ""))  # 申请理由

    if context["application"] == "":
        context["warn_code"] = 1
        context["warn_msg"] = "申请理由不能为空"
    return context


# 查询组织代号的最大值+1 用于modifyOrganization()函数，新建组织
def find_max_oname():
    organizations = Organization.objects.filter(
        organization_id__username__startswith="zz"
    ).order_by("-organization_id__username")
    max_org = organizations[0]
    max_oname = str(max_org.organization_id.username)
    max_oname = int(max_oname[2:]) + 1
    prefix = "zz"
    max_oname = prefix + str(max_oname).zfill(5)
    return max_oname


# 判断是否为图片
def if_image(image):
    if image == None:
        return 0
    imgType_list = {"jpg", "bmp", "png", "jpeg", "rgb", "tif"}

    if imghdr.what(image) in imgType_list:
        return 2  # 为图片
    return 1  # 不是图片


# 用于新建组织时，生成6位随机密码
def random_code_init(seed):
    b = string.digits + string.ascii_letters  # 构建密码池
    password = ""
    random.seed(seed)
    for i in range(0, 6):
        password = password + random.choice(b)
    return password


def get_captcha(request, username, valid_seconds=None, more_info=False):
    '''
    noexcept
    - username: 学号/组织号, 不一定对应request.user(此时应尚未登录)
    - valid_seconds: float or None, None表示不设置有效期
    ->captcha: str | (captcha, expired, old) if more_info
    '''
    expired = False
    captcha = request.session.get("captcha", "")
    old = captcha
    received_user = request.session.get("received_user", "")
    valid_from = request.session.get("captcha_create_time", "")
    if len(captcha) != 6 or username != received_user:
        old = ""
        expired = True
    elif valid_seconds is not None:
        try:
            valid_from = datetime.strptime(valid_from, "%Y-%m-%d %H:%M")
            assert datetime.utcnow() <= valid_from + timedelta(seconds=valid_seconds)
        except:
            expired = True
    if expired:
        # randint包含端点，randrange不包含
        captcha = random.randrange(1000000)
        captcha = f"{captcha:06}"
    return (captcha, expired, old) if more_info else captcha

def set_captcha_session(request, username, captcha):
    '''noexcept'''
    utcnow = datetime.utcnow()
    request.session["received_user"] = username
    request.session["captcha_create_time"] = utcnow.strftime("%Y-%m-%d %H:%M:%S")
    request.session["captcha"] = captcha

def clear_captcha_session(request):
    '''noexcept'''
    request.session.pop("captcha")
    request.session.pop("captcha_create_time")  # 验证码只能登录一次
    request.session.pop("received_user")        # 成功登录后不再保留


def notifications_create(
    receivers,
    sender,
    typename,
    title,
    content,
    URL=None,
    relate_TransferRecord=None,
    *,
    publish_to_wechat=False,
):
    """
        批量创建通知
    """
    notifications = [
        Notification(
            receiver=receiver,
            sender=sender,
            typename=typename,
            title=title,
            content=content,
            URL=URL,
            relate_TransferRecord=relate_TransferRecord,
        )
        for receiver in receivers
    ]
    Notification.objects.bulk_create(notifications)


def set_nperson_quota_to(quota):
    """
        后台设定所有自然人的元气值为一特定值，这个值就是每月的限额
        给所有用户发送通知
    """
    activated_npeople = NaturalPerson.objects.activated()
    activated_npeople.update(quota=quota)
    notification_content = f"学院已经将大家的元气值配额重新设定为{quota},祝您使用愉快！"
    title = Notification.Title.VERIFY_INFORM
    YPcollege = Organization.objects.get(oname="元培学院")
    notifications_create(
        activated_npeople,
        YPcollege,
        Notification.Type.NEEDREAD,
        title,
        notification_content,
    )
    return

def check_account_setting(request,user_type):
    if user_type == 'Person':
        html_display = dict()
        attr_dict = dict()

        html_display['warn_code'] = 0
        html_display['warn_message'] = ""

        attr_dict['biography'] = request.POST["aboutBio"]
        attr_dict['telephone'] = request.POST["tel"]
        attr_dict['email'] = request.POST["email"]
        attr_dict['stu_major'] = request.POST["major"]
        #attr_dict['stu_grade'] = request.POST['grade'] 用户无法填写
        #attr_dict['stu_class'] = request.POST['class'] 用户无法填写
        attr_dict['stu_dorm'] = request.POST['dorm']
        attr_dict['ava'] = request.FILES.get("avatar")
        attr_dict['gender'] = request.POST['gender']
        attr_dict['birthday'] = request.POST['birthday']
        attr_dict['wallpaper'] = request.FILES.get("wallpaper")

        show_dict = dict()

        # show_dict['show_nickname'] = request.POST.get(
        #     'show_nickname') == 'on'
        show_dict['show_gender'] = request.POST.get('show_gender') == 'on'
        show_dict['show_birthday'] = request.POST.get('show_birthday') == 'on'
        show_dict['show_tel'] = request.POST.get('show_tel') == 'on'
        show_dict['show_email'] = request.POST.get('show_email') == 'on'
        show_dict['show_major'] = request.POST.get('show_major') == 'on'
        show_dict['show_dorm'] = request.POST.get('show_dorm') == 'on'

        # 合法性检查
        """if len(attr_dict['nickname']) > 20:
            html_display['warn_code'] = 1
            html_display['warn_message'] += "输入的昵称过长，不能超过20个字符哦！" 
        """

        if len(attr_dict['biography']) > 1024:
            html_display['warn_code'] = 1
            html_display['warn_message'] += "输入的简介过长，不能超过1024个字符哦！"
        
        if len(attr_dict['stu_major']) > 25:
            html_display['warn_code'] = 1
            html_display['warn_message'] += "输入的专业过长，不能超过25个字符哦！"

        if len(attr_dict['stu_dorm']) > 6:
            html_display['warn_code'] = 1
            html_display['warn_message'] += "输入的宿舍过长，不能超过6个字符哦！"
    else:
        html_display = dict()
        attr_dict = dict()
        show_dict = dict()
        html_display['warn_code'] = 0
        html_display['warn_message'] = ""
        attr_dict['introduction'] = request.POST['introduction']
    return attr_dict, show_dict, html_display

#获取未报销的活动
def get_unreimb_activity(org):
    """
    用于views.py&reimbursement_utils.py
    注意：默认传入参数org类型为Organization
    """
    reimbursed_act_ids = (
        Reimbursement.objects.all()
            .exclude(
            status=Reimbursement.ReimburseStatus.CANCELED  # 未取消报销的
            # 未被拒绝的
        )
            .exclude(status=Reimbursement.ReimburseStatus.REFUSED)
            .values_list("related_activity_id", flat=True)
    )
    activities = (
        Activity.objects.activated()  # 本学期的
            .filter(organization_id=org)  # 本部门组织的
            .filter(status=Activity.Status.END)  # 已结束的
            .exclude(id__in=reimbursed_act_ids))  # 还没有报销的
    activities.len=len(activities)
    return activities
def accept_modifyorg_submit(application): #同意申请，假设都是合法操作
    # 新建一系列东西
    username = find_max_oname()
    user = User.objects.create(username=username)
    password=random_code_init(user.id)
    user.set_password(password)
    user.save()
    org = Organization.objects.create(organization_id=user, oname=application.oname, \
        otype=application.otype, YQPoint=0.0, introduction=application.introduction, avatar=application.avatar)
    charger = get_person_or_org(application.pos)
    pos = Position.objects.create(person=charger,org=org,pos=0,status=Position.Status.INSERVICE)
    # 修改申请状态
    ModifyOrganization.objects.filter(id=application.id).update(status=ModifyOrganization.Status.CONFIRMED)

# 在错误的情况下返回的字典,message为错误信息
def wrong(message="检测到恶意的申请操作. 如有疑惑，请联系管理员!"):
    context = dict()
    context["warn_code"] = 1
    context["warn_message"] = message
    return context


def succeed(message="检测到恶意的申请操作. 如有疑惑，请联系管理员!"):
    context = dict()
    context["warn_code"] = 2
    context["warn_message"] = message
    return context


# 修改人事申请状态的操作函数, application为修改的对象，可以为None
# me为操作者
# info为前端POST字典
# 返回值为context, warn_code = 1表示失败, 2表示成功; 错误信息在context["warn_message"]
# 如果成功context会返回update之后的application,

def update_org_application(application, me, request):
    # 关于这个app和我的关系已经完成检查
    # 确定info中有post_type且不为None

    # 首先上锁
    with transaction.atomic():
        info = request.POST
        if application is not None:
            application = ModifyOrganization.objects.select_for_update().get(id=application.id)
            user_type = 'pos' if me.person_id==application.pos else 'incharge'
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
                ModifyOrganization.objects.filter(id=application.id).update(status=ModifyOrganization.Status.CANCELED)
                context = succeed("成功取消组织" + application.oname + "的申请!")
                context["application_id"] = application.id
                return context
            else:
                # 无论是新建还是修改, 都需要检查所有参数的合法性
                context = check_neworg_request(request, application)
                if context['warn_code'] == 1:
                    return context
                
                # 写入数据库
                if post_type == 'new_submit':
                    application = ModifyOrganization.objects.create(
                        oname=info.get('oname'),
                        otype=OrganizationType.objects.get(otype_name=info.get('otype')),
                        pos=me.person_id,
                        introduction=info.get('introduction'),
                        application=info.get('application')
                    )
                    if context["avatar"] is not None:
                        application.avatar = context['avatar'];
                        application.save()
                    context = succeed("成功地发起"+info.get("oname")+"的申请！")
                    context['application_id'] = application.id
                    return context
                else: # modify_submit
                    if not application.is_pending():
                        return wrong("不能修改状态不为“申请中”的申请！")
                    if application.oname == info.get("oname") and \
                        application.otype.otype_name == info.get("otype") and \
                            application.introduction == info.get('introduction') and \
                                application.avatar == info.get('avatar', None) and \
                                    application.application == info.get('application'):
                                    return wrong("没有检测到修改！")
                    # 至此可以发起修改
                    ModifyOrganization.objects.filter(id=application.id).update(
                        oname=info.get('oname'),
                        otype=OrganizationType.objects.get(otype_name=info.get('otype')),
                        introduction=info.get('introduction'),
                        application=info.get('application'))
                    if context["avatar"] is not None:
                        application.avatar = context['avatar'];
                        application.save()
                    context = succeed("成功修改新建组织" + info.get('oname') + "的申请!")
                    context["application_id"] = application.id
                    return context
        else: # 是老师审核的操作, 通过\拒绝
            # 已经确定 me == application.otype.inchage 了
            # 只需要确定状态是否匹配
            if not application.is_pending():
                return wrong("无法操作, 该申请已经完成或被取消!")
            # 否则，应该直接完成状态修改
            if post_type == "refuse_submit":
                ModifyOrganization.objects.filter(id=application.id).update(status=ModifyOrganization.Status.REFUSED)
                context = succeed("成功拒绝来自" + NaturalPerson.objects.get(person_id=application.pos).name + "的申请!")
                context["application_id"] = application.id
                return context
            else:   # 通过申请
                '''
                    注意，在这个申请发起、修改的时候，都应该保证这条申请的合法地位
                    例如不存在冲突申请、职位的申请是合理的等等
                    否则就不应该通过这条创建
                '''
                try:
                    accept_modifyorg_submit(application)
                    context = succeed("成功通过来自" +  NaturalPerson.objects.get(person_id=application.pos).name + "的申请!")
                    context["application_id"] = application.id
                    return context
                except:
                    return wrong("出现系统意料之外的行为，请联系管理员处理!")


import threading
import os
# 线程锁，用于对文件写入的排他性
lock = threading.RLock()
# 文件操作体系
log_root = "logstore"
if not os.path.exists(log_root):
    os.mkdir(log_root)
log_root_path = os.path.join(os.getcwd(), log_root)
log_user = "user_detail"
if not os.path.exists(os.path.join(log_root_path, log_user)):
    os.mkdir(os.path.join(log_root_path, log_user))
log_user_path = os.path.join(log_root_path, log_user)


# 通用日志写入程序 写入时间(datetime.now()),操作主体(Sid),操作说明(Str),写入函数(Str)
# 参数说明：第一为Sid也是文件名，第二位消息，第三位来源的函数名（类别）
# 如果是系统相关的 请写local_dict["system_log"]
def operation_writer(user, message, source, status_code="OK"):
    lock.acquire()
    try:
        timestamp = str(datetime.now())
        source = str(source).ljust(30)
        status = status_code.ljust(10)
        message = f"{timestamp} {source}{status}: {message}\n"

        with open(os.path.join(log_user_path, f"{str(user)}.log"), mode="a") as journal:
            journal.write(message)

        if status_code == "Error":
            pass
            # TODO 发送微信消息提醒运维成员
            '''
            send_wechat_message(
                stu_list=['', '', ''],
                starttime=datetime.now(),
                room=Room.objects.get(Rid="B107A"),
                message_type="violated",
                major_student="地下室系统",
                usage="发生Error错误",
                announcement="",
                num=1,
                reason=message,
                # credit=appoint.major_student.Scredit,
            )
            '''
    except Exception as e:
        # 最好是发送邮件通知存在问题
        # 待补充
        print(e)

    lock.release()


# 导出Excel文件
def export_activity_signin(activity):

  # 设置HTTPResponse的类型
  response = HttpResponse(content_type='application/vnd.ms-excel')
  response['Content-Disposition'] = f'attachment;filename={activity.title}({activity.start.month}月{activity.start.day}日).xls'
  participants=Participant.objects.filter(activity_id=activity.id ).filter(status=Participant.AttendStatus.ATTENDED)
  """导出excel表"""
  if len(participants)>0:
    # 创建工作簿
    ws = xlwt.Workbook(encoding='utf-8')
    # 添加第一页数据表
    w = ws.add_sheet('sheet1') # 新建sheet（sheet的名称为"sheet1"）
    # 写入表头
    w.write(0, 0, u'姓名')
    w.write(0, 1, u'学号')
    # 写入数据
    excel_row = 1
    for participant in participants:
      name = participant.person_id.name
      Sno = participant.person_id.person_id.username
      # 写入每一行对应的数据
      w.write(excel_row, 0, name)
      w.write(excel_row, 1, Sno)
      excel_row += 1
    # 写出到IO
    output = BytesIO()
    ws.save(output)
    # 重新定位到开始
    output.seek(0)
    response.write(output.getvalue())
  return response
# 导出组织成员信息Excel文件
def export_orgpos_info(org):
    # 设置HTTPResponse的类型
    response = HttpResponse(content_type='application/vnd.ms-excel')
    response['Content-Disposition'] = f'attachment;filename=组织{org.oname}成员信息.xls'
    participants = Position.objects.filter(org=org).filter(status=Position.Status.INSERVICE)
    """导出excel表"""
    if len(participants) > 0:
        # 创建工作簿
        ws = xlwt.Workbook(encoding='utf-8')
        # 添加第一页数据表
        w = ws.add_sheet('sheet1')  # 新建sheet（sheet的名称为"sheet1"）
        # 写入表头
        w.write(0, 0, u'姓名')
        w.write(0, 1, u'学号')
        w.write(0, 2, u'职位')
        # 写入数据
        excel_row = 1
        for participant in participants:
            name = participant.person.name
            Sno = participant.person.person_id.username
            pos=org.otype.job_name_list[participant.pos]
            # 写入每一行对应的数据
            w.write(excel_row, 0, name)
            w.write(excel_row, 1, Sno)
            w.write(excel_row, 2, pos)
            excel_row += 1
        # 写出到IO
        output = BytesIO()
        ws.save(output)
        # 重新定位到开始
        output.seek(0)
        response.write(output.getvalue())
    return response

operation_writer(local_dict["system_log"], "系统启动", "util_底部")
