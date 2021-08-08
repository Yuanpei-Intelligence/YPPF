from app.models import NaturalPerson, Organization, Position, Notification
from django.dispatch.dispatcher import receiver
from django.contrib import auth
from django.conf import settings

from boottest import local_dict

from datetime import datetime, timedelta
import re


def check_user_type(user):  # return Valid(Bool), otype
    html_display = {}
    if user.is_superuser:
        return False, "", html_display
    if user.username[:2] == "zz":
        user_type = "Organization"
        html_display["profile_name"] = "组织主页"
        html_display["profile_url"] = "/orginfo/"
        org = Organization.objects.get(organization_id=user)
        html_display["avatar_path"] = get_user_ava(org, user_type)
        html_display["user_type"] = user_type
    else:
        user_type = "Person"
        person = NaturalPerson.objects.activated().get(person_id=user)
        html_display["profile_name"] = "个人主页"
        html_display["profile_url"] = "/stuinfo/"
        html_display["avatar_path"] = get_user_ava(person, user_type)
        html_display["user_type"] = user_type

    html_display["mail_num"] = Notification.objects.filter(
        receiver=user, status=Notification.NotificationStatus.UNDONE
    ).count()

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
    #assert (
    #        "is_myself" in html_display.keys()
    #), "Forget to tell the website whether this is the user itself!"
    html_display["underground_url"] = local_dict["url"]["base_url"]

    my_org_id_list = Position.objects.activated().filter(person=person).filter(pos=0)
    html_display["my_org_list"] = [w.org for w in my_org_id_list]  # 我管理的组织
    html_display["my_org_len"] = len(html_display["my_org_list"])
    return html_display


def get_org_left_narbar(org, is_myself, html_display):
    #assert (
    #        "is_myself" in html_display.keys()
    #), "Forget to tell the website whether this is the user itself!"
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

    # edit 不能改预算和报名方式
    if not edit:
        try:
            budget = float(request.POST["budget"])
            context['budget'] = budget
            context['need_check'] = False
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
            context['warn_msg'] = "Unexpected exception. If you are not doing it deliberately, please contact the administrator to report this bug."
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
            context['warn_msg'] = "The number of participants must exceed 0."
            return context
        context['capacity'] = capacity
    except:
        if not edit:
            context['warn_code'] = 1
            context['warn_msg'] = "The number of participants must be an integer."
            return context

    # 价格
    try:
        aprice = float(request.POST["aprice"])
        if aprice < 0:
            context['warn_code'] = 1
            context['warn_msg'] = "The price should be no less than 0!"
            return context
        context['aprice'] = aprice
    except:
        if not edit:
            context['warn_code'] = 1
            context['warn_msg'] = "The price must be a floating point number one decimal place"
            return context

    # 时间
    try:
        act_start = datetime.strptime(act_start, '%m/%d/%Y %H:%M %p')
        act_end = datetime.strptime(act_end, '%m/%d/%Y %H:%M %p')

        now_time = datetime.now()

        # 创建活动即开始报名
        signup_start = now_time
        signup_end = act_start - timedelta(hours=prepare_time)

        print('now', now_time)
        print('end', signup_end)

        if signup_start >= signup_end:
            context['warn_code'] = 1
            context['warn_msg'] = "No enough time to prepare."
            return context

        if now_time + timedelta(days=30) < act_start == False:
            context['warn_code'] = 1
            context['warn_msg'] = "The activity has to be in a month! "
            return context
            
        context['signup_start'] = signup_start
        context['signup_end'] = signup_end
        context['act_start'] = act_start
        context['act_end'] = act_end

    except:
        if not edit:
            context['warn_code'] = 1
            context['warn_msg'] = "you have sent a wrong time form!"
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
    except:
        if not edit:
            context['warn_code'] = 1
            context['warn_msg'] = "请检查您的输入是否正确。"
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
