from app.models import (
    NaturalPerson,
    Organization,
    OrganizationType,
    Position,
    Notification,
    NewOrganization,
    Activity,
    Reimbursement
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
    ava = obj.avatar
    if not ava:
        if user_type == "Person":
            return settings.MEDIA_URL + "avatar/person_default.jpg"
        else:
            return settings.MEDIA_URL + "avatar/org_default.png"
    else:
        return settings.MEDIA_URL + str(ava)


def get_user_wallpaper(person):
    return settings.MEDIA_URL + (str(person.wallpaper) or "wallpaper/default.jpg")


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
            bar_display["help_paragraphs"] = local_dict["use_help"].get(
                navbar_name, list()
            )
        except:
            bar_display["help_paragraphs"] = list()

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

    bar_display["navbar_name"] = navbar_name
    bar_display["title_name"] = (
        title_name if not title_name else navbar_name
    )  # title_name默认与navbar_name相同

    if navbar_name != "":
        try:
            bar_display["help_message"] = local_dict["help_message"].get(
                navbar_name, ""
            )
        except:  # 找不到提醒, 直接跳过
            pass
        try:
            bar_display["help_paragraphs"] = local_dict["use_help"].get(
                navbar_name, list()
            )
        except:  # 找不到提醒, 直接跳过
            pass

    return bar_display


def url_check(arg_url):
    # DEBUG 默认通过
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

# 检查neworg request参数的合法性 ,用在addOrganization和auditOrganization函数中
def check_neworg_request(request, org=None):
    context = dict()
    context["warn_code"] = 0
    oname = str(request.POST["oname"])
    if len(oname) >= 32:
        context["warn_code"] = 1
        context["warn_msg"] = "组织的名字不能超过32字节"
        return context
    if oname == "":
        context["warn_code"] = 1
        context["warn_msg"] = "组织的名字不能为空"
        return context
    if org is not None and oname == org.oname:
        if (
            len(
                NewOrganization.objects.exclude(
                    status=NewOrganization.NewOrgStatus.CANCELED
                )
                .exclude(status=NewOrganization.NewOrgStatus.REFUSED)
                .filter(oname=oname)
            )
            > 1
            or len(Organization.objects.filter(oname=oname)) != 0
        ):
            context["warn_code"] = 1
            context["warn_msg"] = "组织的名字不能与正在申请的或者已存在的组织的名字重复"
            return context
    else:
        if (
            len(
                NewOrganization.objects.exclude(
                    status=NewOrganization.NewOrgStatus.CANCELED
                )
                .exclude(status=NewOrganization.NewOrgStatus.REFUSED)
                .filter(oname=oname)
            )
            != 0
            or len(Organization.objects.filter(oname=oname)) != 0
        ):
            context["warn_code"] = 1
            context["warn_msg"] = "组织的名字不能与正在申请的或者已存在的组织的名字重复"
            return context

    try:
        otype = int(request.POST.get("otype"))
        context["otype"] = OrganizationType.objects.get(otype_id=otype)
    except:
        context["warn_code"] = 1
        # user can't see it . we use it for debugging
        context["warn_msg"] = "数据库没有小组的所在类型，请联系管理员！"
        return context

    context["avatar"] = request.FILES.get("avatar")
    if context["avatar"] is not None:
        if if_image(context["avatar"]) == 1:
            context["warn_code"] = 1
            context["warn_msg"] = "组织的头像应当为图片格式！"
            return context

    context["oname"] = oname  # 组织名字
    # 组织类型，必须有
    context["pos"] = request.user  # 负责人，必须有滴
    context["introduction"] = str(request.POST.get("introduction", ""))  # 组织介绍，可能为空

    context["application"] = str(request.POST.get("application", ""))  # 申请理由

    if context["application"] == "":
        context["warn_code"] = 1
        context["warn_msg"] = "申请理由不能为空"
    return context
# 检查neworg request参数的合法性 ,用在addOrganization和auditOrganization函数中

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

    context['application'] = str(request.POST.get('application', ""))  # 申请理由

    if context['application']=="" :
        context['warn_code'] = 1
        context['warn_msg'] = "申请理由不能为空"
    return context


# 查询组织代号的最大值+1 用于addOrganization()函数，新建组织
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
def random_code_init():
    b = string.digits + string.ascii_letters  # 构建密码池
    password = ""
    for i in range(0, 6):
        password = password + random.choice(b)
    return password


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


def set_YQPoint_credit_to(YQP):
    """
        后台设定所有自然人的元气值为一特定值，这个值就是每月的限额
        给所有用户发送通知
    """
    activated_npeople = NaturalPerson.objects.activated()
    activated_npeople.update(YQPoint_credit_card=YQP)
    notification_content = f"学院已经将大家的元气信用值充值为{YQP},祝您使用愉快！"
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

        attr_dict['nickname'] = request.POST['nickname']
        attr_dict['biography'] = request.POST["aboutBio"]
        attr_dict['telephone'] = request.POST["tel"]
        attr_dict['email'] = request.POST["email"]
        attr_dict['stu_major'] = request.POST["major"]
        #attr_dict['stu_grade'] = request.POST['grade'] 用户无法填写
        #attr_dict['stu_class'] = request.POST['class'] 用户无法填写
        attr_dict['stu_dorm'] = request.POST['dorm']
        attr_dict['ava'] = request.FILES.get("avatar")
        attr_dict['gender'] = request.POST['gender']
        attr_dict['wallpaper'] = request.FILES.get("wallpaper")

        show_dict = dict()

        show_dict['show_nickname'] = request.POST.get(
            'show_nickname') == 'on'
        show_dict['show_gender'] = request.POST.get('show_gender') == 'on'
        show_dict['show_tel'] = request.POST.get('show_tel') == 'on'
        show_dict['show_email'] = request.POST.get('show_email') == 'on'
        show_dict['show_major'] = request.POST.get('show_major') == 'on'
        show_dict['show_dorm'] = request.POST.get('show_dorm') == 'on'

        # 合法性检查
        if len(attr_dict['nickname']) > 20:
            html_display['warn_code'] = 1
            html_display['warn_message'] += "输入的昵称过长，不能超过20个字符哦！"

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
            .values_list("activity_id", flat=True)
    )
    activities = (
        Activity.objects.activated()  # 本学期的
            .filter(organization_id=org)  # 本部门组织的
            .filter(status=Activity.Status.END)  # 已结束的
            .exclude(id__in=reimbursed_act_ids))  # 还没有报销的
    return activities