from app.models import NaturalPerson, Organization, OrganizationType, Position, Notification
from django.dispatch.dispatcher import receiver
from django.contrib import auth
from django.contrib.auth.models import User
from django.conf import settings
from boottest import local_dict
from datetime import datetime, timedelta
import re

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
def check_user_type(user):  # return Valid(Bool), otype
    html_display = {}
    if user.is_superuser:
        return False, "", html_display
    if user.username[:2] == "zz":
        user_type = "Organization"
        html_display["user_type"] = user_type
    else:
        user_type = "Person"
        html_display['user_type'] = user_type

    return True, user_type, html_display


def get_user_ava(obj, user_type):
    try:
        ava = obj.avatar
        assert ava != ""
        return settings.MEDIA_URL + str(ava)
    except:
        if user_type == "Person":
            return settings.MEDIA_URL + "avatar/person_default.jpg"
        else:
            return settings.MEDIA_URL + "avatar/org_default.png"


def get_user_wallpaper(person):
    return settings.MEDIA_URL + (str(person.wallpaper) or "wallpaper/default.jpg")


def get_user_left_narbar(person, is_myself, html_display):  # 获取左边栏的内容，is_myself表示是否是自己, person表示看的人
    # assert (
    #        "is_myself" in html_display.keys()
    # ), "Forget to tell the website whether this is the user itself!"
    raise NotImplementedError("old left_narbar function has been abandoned, please use `get_sidebar_and_navbar` instead!")
    html_display["underground_url"] = local_dict["url"]["base_url"]

    my_org_id_list = Position.objects.activated().filter(person=person).filter(pos=0)
    html_display["my_org_list"] = [w.org for w in my_org_id_list]  # 我管理的组织
    html_display["my_org_len"] = len(html_display["my_org_list"])
    return html_display


def get_org_left_narbar(org, is_myself, html_display):
    # assert (
    #        "is_myself" in html_display.keys()
    # ), "Forget to tell the website whether this is the user itself!"
    raise NotImplementedError("old left_narbar function has been abandoned, please use `get_sidebar_and_navbar` instead!")
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
def get_sidebar_and_navbar(user, bar_display = None):
    if bar_display is None:
        bar_display = {}            # 默认参数只会初始化一次，所以不应该设置为{}
    me = get_person_or_org(user)    # 获得对应的对象
    _, user_type, _ = check_user_type(user)
    bar_display["user_type"] = user_type

    # 接下来填补各种前端呈现信息

    # 头像
    bar_display["avatar_path"] = get_user_ava(me, user_type)

    # 信箱数量
    bar_display['mail_num'] = Notification.objects.filter(receiver=user, status=Notification.Status.UNDONE).count()

    if user_type == "Person":   
        bar_display["profile_name"] = "个人主页"
        bar_display["profile_url"] = "/stuinfo/"

        # 个人需要地下室跳转
        bar_display["underground_url"] = local_dict["url"]["base_url"]

        # 个人所管理的组织列表
        my_org_id_list = Position.objects.activated().filter(person=me).filter(pos=0)
        bar_display["my_org_list"] = [w.org for w in my_org_id_list]  # 我管理的组织
        bar_display["my_org_len"] = len(bar_display["my_org_list"])

    else:
        bar_display["profile_name"] = "组织主页"
        bar_display["profile_url"] = "/orginfo/"
    
    return bar_display

# 检查发起活动的request的合法性
def check_ac_request(request):
    # oid的获取
    context = dict()
    context['warn_code'] = 0

    try:
        assert request.POST['edit'] == "True"
        edit = True
    except:
        edit = False

    # signup_start = request.POST["actstar"]
    act_start = request.POST.get("actstart")  # 活动报名时间
    act_end = request.POST.get("actend")  # 活动报名结束时间
    prepare_scheme = request.POST.get("prepare_scheme")
    context['need_check'] = False

    # edit 不能改预算和报名方式
    if not edit:
        try:
            budget = float(request.POST["budget"])
            context['budget'] = budget
            if context['budget'] > local_dict['thresholds']['activity_budget']:
                context['need_check'] = True
        except:
            budget = local_dict['thresholds']['activity_budget']
        try:
            schema = int(request.POST["signschema"])
        except:
            schema = 0
        context['signschema'] = schema

    # 准备时间
    try:
        prepare_scheme = int(prepare_scheme)
        prepare_times = [1, 24, 72, 168]
        prepare_time = prepare_times[prepare_scheme]
        context['prepare_scheme'] = prepare_scheme
    except:
        if not edit:
            context['warn_code'] = 1
            context['warn_msg'] = "非预期错误，请联系管理员"
            return context

    # 人数限制
    try:
        t = int(request.POST["unlimited_capacity"])
        capacity = 10000
    except:
        capacity = 0
    try:
        if capacity == 0:
            capacity = int(request.POST["maxpeople"])
        if capacity <= 0:
            context['warn_code'] = 1
            context['warn_msg'] = "人数限制应当大于 0。"
            return context
        context['capacity'] = capacity
    except:
        if not edit:
            context['warn_code'] = 1
            context['warn_msg'] = "人数限制必须是一个整数。"
            return context

    # 价格
    try:
        aprice = float(request.POST["aprice"])
        assert int(aprice * 10) / 10 == aprice
        if aprice < 0:
            context['warn_code'] = 1
            context['warn_msg'] = "价格应该大于 0。"
            return context
        context['aprice'] = aprice
    except:
        if not edit:
            context['warn_code'] = 1
            context['warn_msg'] = "价格必须是一个单精度浮点数。"
            return context

    # 时间
    try:
        act_start = datetime.strptime(act_start, '%m/%d/%Y %H:%M %p')
        act_end = datetime.strptime(act_end, '%m/%d/%Y %H:%M %p')
        now_time = datetime.now()

        # 创建活动即开始报名
        signup_start = now_time
        signup_end = act_start - timedelta(hours=prepare_time)

        # print('now', now_time)
        # print('end', signup_end)

        if signup_start >= signup_end:
            context['warn_code'] = 1
            context['warn_msg'] = "没有足够的时间准备活动。"
            return context

        if now_time + timedelta(days=30) < act_start:
            context['warn_code'] = 1
            context['warn_msg'] = "活动应该在一个月之内。"
            return context

        context['signup_start'] = signup_start
        context['signup_end'] = signup_end
        context['act_start'] = act_start
        context['act_end'] = act_end

    except:
        if not edit:
            context['warn_code'] = 1
            context['warn_msg'] = "错误的时间格式。"
            return context

    try:
        context['URL'] = request.POST["URL"]
    except:
        pass
    if context['warn_code'] != 0:
        return context

    try:
        context['aname'] = str(request.POST["aname"])  # 活动名称
        context['content'] = str(request.POST["content"])  # 活动内容
        context['location'] = str(request.POST["location"])  # 活动地点
        if context.get('aname'):
            assert len(context['aname']) > 0
        if context.get('content'):
            assert len(context['content']) > 0
        if context.get('location'):
            assert len(context['location']) > 0
    except:
        if not edit:
            context['warn_code'] = 1
            context['warn_msg'] = "请确认已输入活动名称/地点/简介。"
    return context


# 时间合法性的检查，检查时间是否在当前时间的一个月以内，并且检查开始的时间是否早于结束的时间，
def check_ac_time(start_time, end_time):
    try:
        now_time = datetime.now().strptime("%Y-%m-%d %H:%M:%S")
        month_late = now_time + datetime.timedelta(days=30)
        if now_time < start_time < end_time < month_late:
            return True  # 时间所处范围正确
    except:
        return False

    return False


def url_check(arg_url):
    if arg_url is None:
        return True
    if re.match('^/[^/?]*/', arg_url):  # 相对地址
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
def check_neworg_request(request):
    """

    """
    context = dict()
    context['warn_code'] = 0
    oname = str(request.POST['oname'])
    if len(oname) >= 32:
        context['warn_code'] = 1
        context['warn_msg'] = "组织的名字不能超过32字节"
        return context
    try:
        otype = int(request.POST.get('otype'))
        if otype not in [7, 8, 10]:  # 7 for 书院俱乐部，8 for 学生小组 ，10 for 书院课程
            context['warn_code'] = 1
            context['warn_msg'] = "你应该从书院俱乐部、学生小组和书院课程中选择!"
            return context
    except:
        context['warn_code'] = 1
        context['warn_msg'] = "小组的数据类型应该为整数"  # user can't see it . we use it for debugging
        return context
    try:
        context['otype'] = OrganizationType.objects.get(otype_id=otype)
    except:
        context['warn_code'] = 1
        context['warn_msg'] = "数据库没有小组的所在类型，请联系管理员！"  # user can't see it . we use it for debugging
        return context
    context['oname'] = oname  # 组织名字
     # 组织类型，必须有
    context['pos'] = request.user  # 负责人，必须有滴
    context['introduction'] = str(request.POST.get('introduction', ""))  # 组织介绍，可能为空
    context['avatar'] = request.FILES.get('avatar')
    context['application'] = str(request.POST.get('application', ""))  # 申请理由
    return context

# 查询组织代号的最大值+1 用于addOrganization()函数，新建组织
def find_max_oname():
    organizations=Organization.objects.filter(organization_id__username__startswith='zz').order_by("-organization_id__username")
    max_org=organizations[0]
    max_oname=str(max_org.organization_id.username)
    max_oname=int(max_oname[2:])+1
    prefix="zz"
    max_oname=prefix+str(max_oname).zfill(5)
    return max_oname