from app.models import NaturalPerson, Organization, Position, Notification, Activity
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

    context = dict()

    edit = False
    if request.POST.get('edit') == "True":
        edit = True

    # edit 时，不能修改预算和元气值支付模式，只在创建时考虑
    if not edit:
        context['budget'] = float(request.POST["budget"])
        context['signschema'] = int(request.POST["signschema"])
        if context['budget'] > float(local_dict['thresholds']['activity_budget']):
            context['need_check'] = True


    # title, introduction, location 创建时不能为空
    context['aname'] = request.POST.get("aname")
    context['content'] = request.POST.get("content")
    context['location'] = request.POST.get("location")
    if not edit:
        assert len(context['aname']) > 0
        assert len(context['content']) > 0
        assert len(context['location']) > 0

    # url
    context['URL'] = request.POST.get("URL")


    # 时间
    # datetime 这里有 bug，PM 不会把时间加上去，到时候考虑 patch ......
    act_start = datetime.strptime(request.POST["actstart"], '%m/%d/%Y %H:%M %p')  # 活动报名时间
    act_end = datetime.strptime(request.POST["actend"], '%m/%d/%Y %H:%M %p')  # 活动报名结束时间
    now_time = datetime.now()
    prepare_scheme = int(request.POST["prepare_scheme"])
    prepare_times = Activity.EndBeforeHours.prepare_times
    prepare_time = prepare_times[prepare_scheme]
    signup_start = now_time
    signup_end = act_start - timedelta(hours=prepare_time)

    context['prepare_scheme'] = int(prepare_scheme)
    context['signup_start'] = signup_start
    context['signup_end'] = signup_end
    context['act_start'] = act_start
    context['act_end'] = act_end

    assert check_ac_time(act_start, act_end)
    assert signup_start <= signup_end

    # 人数限制
    capacity = request.POST.get("maxpeople")
    no_limit = request.POST.get("unlimited_capacity")
    if no_limit is not None:
        capacity = 10000
    if capacity is not None:
        context['capacity'] = int(capacity)
        assert context['capacity'] >= 0

    # 价格
    aprice = request.POST.get("aprice")
    if aprice is not None:
        aprice = float(aprice)
        assert int(aprice * 10) / 10 == aprice
        assert aprice >= 0
        context['aprice'] = aprice

    return context


# 时间合法性的检查，检查时间是否在当前时间的一个月以内，并且检查开始的时间是否早于结束的时间，
def check_ac_time(start_time, end_time):
    try:
        now_time = datetime.now()
        month_late = now_time + timedelta(days=30)
        if now_time < start_time < month_late:
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
