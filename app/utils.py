from app.models import NaturalPerson, Organization, Position, Notification
from django.dispatch.dispatcher import receiver
from django.contrib import auth
from django.contrib.auth.models import User
from django.conf import settings
from boottest import local_dict
from datetime import datetime, timedelta
import re
from app.models import NaturalPerson,Organization,OrganizationType,Position,Notification

def check_user_type(user):  # return Valid(Bool), otype
    html_display = {}
    if user.is_superuser:
        return False, "", html_display
    if user.username[:2] == "zz":
        user_type = "Organization"
        org = Organization.objects.get(organization_id=user)
        html_display["profile_name"] = "组织主页"
        html_display["profile_url"] = "/orginfo/"
        html_display["avatar_path"] = get_user_ava(org, user_type)
        html_display["user_type"] = user_type
    else:
        user_type = "Person"
        person = NaturalPerson.objects.activated().get(person_id=user)
        html_display["profile_name"] = "个人主页"
        html_display["profile_url"] = "/stuinfo/"
        html_display["avatar_path"] = get_user_ava(person, user_type)
        html_display['user_type'] = user_type
    
    html_display['mail_num'] = Notification.objects.filter(receiver=user, status=Notification.Status.UNDONE).count()


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
    html_display["underground_url"] = local_dict["url"]["base_url"]

    my_org_id_list = Position.objects.activated().filter(person=person).filter(pos=0)
    html_display["my_org_list"] = [w.org for w in my_org_id_list]  # 我管理的组织
    html_display["my_org_len"] = len(html_display["my_org_list"])
    return html_display


def get_org_left_narbar(org, is_myself, html_display):
    # assert (
    #        "is_myself" in html_display.keys()
    # ), "Forget to tell the website whether this is the user itself!"
    html_display["switch_org_name"] = org.oname
    html_display["underground_url"] = local_dict["url"]["base_url"]
    html_display["org"] = org
    return html_display


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


# 检查neworg request参数的合法性
def check_neworg_request(request):
    """

    """
    context = dict()
    context['warn_code'] = 0
    oname = str(request.POST['oname'])
    if len(oname) >= 32:
        context['warn_code'] = 1
        context['warn_msg'] = "The length of orgnization_name can't exceed 100 bytes!"
        return context
    try:
        otype = int(request.POST.get('otype'))
        if otype not in [7, 8, 10]:  # 7 for 书院俱乐部，8 for 学生小组 ，10 for 书院课程
            context['warn_code'] = 2
            context['warn_msg'] = "You should select choices from [academy club,student group,academy course]!"
            return context
    except:
        context['warn_code'] = 2
        context['warn_msg'] = "You should input Interger!"  # user can't see it . we use it for debugging
        return context
    context['oname'] = oname  # 组织名字
    context['otype'] = OrganizationType.objects.get(otype_id=otype)  # 组织类型，必须有
    context['pos'] = request.user  # 负责人，必须有滴
    context['introduction'] = str(request.POST.get('introduction', ""))  # 组织介绍，可能为空

    context['avatar'] = request.POST.get('avatar')  # TODO 测试有无bug

    context['application'] = str(request.POST.get('application', ""))  # 申请理由
    return context
