from app.utils_dependency import *
from app.models import (
    NaturalPerson,
    Organization,
    OrganizationType,
    Position,
    Notification,
    Activity,
    Help,
    Reimbursement,
    Participant,
    ModifyRecord,
)
from boottest import local_dict

import re
import imghdr
import string
import random
import xlwt
from io import BytesIO
import urllib.parse

from datetime import datetime, timedelta
from functools import wraps
from django.contrib.auth.models import User
from django.contrib import auth
from django.shortcuts import redirect
from django.http import HttpResponse
from django.db.models import F


def check_user_access(redirect_url="/logout/", is_modpw=False):
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
            # 如果是首次登陆，会跳转到用户须知的页面
            if isFirst:
                if request.session.get('confirmed') != 'yes':
                    return redirect("/agreement/")
                if not is_modpw:
                    return redirect('/modpw/')

            return view_function(request, *args, **kwargs)

        return _wrapped_view

    return actual_decorator


def get_classified_user(user: User, user_type=None, *,
                        update=False, activate=False) -> ClassifiedUser:
    '''
    通过User对象获取对应的实例

    check_user_type返回valid=True时，应能得到一个与user_type相符的实例

    Parameters
    ----------
    user_type : UTYPE, optional
        用来加速访问，不提供时按顺序尝试，非法值抛出`AssertionError`
    update : bool, optional
        获取用来更新的对象，需要在事务中调用，否则会报错
    activate : bool, optional
        只获取活跃的用户，由对应的模型管理器检查，用户不活跃可能报错
    '''
    if user_type is None:
        if hasattr(user, "naturalperson"):
            return NaturalPerson.objects.get_by_user(user, update=update, activate=activate)
        else:
            return Organization.objects.get_by_user(user, update=update, activate=activate)
    elif user_type == UTYPE_PER:
        return NaturalPerson.objects.get_by_user(user, update=update, activate=activate)
    elif user_type == UTYPE_ORG:
        return Organization.objects.get_by_user(user, update=update, activate=activate)
    else:
        raise AssertionError(f"非法的用户类型：“{user_type}”")

# 保持之前的函数名接口
get_person_or_org = get_classified_user


def get_user_by_name(name):
    """通过 name/oname 获取 user 对象，用于导入评论者
    Comment只接受User对象
    Args:
        name/oname
    Returns:
        user<object>: 用户对象
        user_type: 用户类型
    """
    try: return NaturalPerson.objects.get(name=name).person_id, UTYPE_PER
    except: pass
    try: return Organization.objects.get(oname=name).organization_id, UTYPE_ORG
    except: pass
    print(f"{name} is neither natural person nor organization!")


# YWolfeee, Aug 16
# check_user_type只是获得user的类型，其他用于呈现html_display的内容全部转移到get_siderbar_and_navbar中
# 同步开启一个html_display，方便拓展前端逻辑的呈现
def check_user_type(user):
    html_display = {}
    if user.is_superuser or user.is_staff:
        if user.is_staff:
            for user_type, model_name in [
                (UTYPE_ORG, "organization"),
                (UTYPE_PER, "naturalperson"),
                ]:
                if hasattr(user, model_name):
                    html_display["user_type"] = user_type
                    return True, user_type, html_display
        return False, "", html_display
    if user.username[:2] == "zz":
        user_type = UTYPE_ORG
        html_display["user_type"] = user_type
    else:
        user_type = UTYPE_PER
        html_display["user_type"] = user_type

    return True, user_type, html_display


def get_user_ava(obj: ClassifiedUser, user_type):
    try:
        ava = obj.avatar
    except:
        ava = ""
    if not ava:
        if user_type == UTYPE_PER:
            return NaturalPerson.get_user_ava()
        else:
            return Organization.get_user_ava()
    else:
        return MEDIA_URL + str(ava)


def get_user_wallpaper(person: ClassifiedUser, user_type):
    if user_type == UTYPE_PER:
        return MEDIA_URL + (str(person.wallpaper) or "wallpaper/person_wall_default.jpg")
    else:
        return MEDIA_URL + (str(person.wallpaper) or "wallpaper/org_wall_default.jpg")


def get_user_left_navbar(person, is_myself, html_display):
    '''已废弃；获取左边栏的内容，is_myself表示是否是自己, person表示看的人'''
    # assert (
    #        "is_myself" in html_display.keys()
    # ), "Forget to tell the website whether this is the user itself!"
    raise NotImplementedError(
        "old left_navbar function has been abandoned, please use `get_sidebar_and_navbar` instead!"
    )
    html_display["underground_url"] = UNDERGROUND_URL

    my_org_id_list = Position.objects.activated().filter(person=person).filter(is_admin=True)
    html_display["my_org_list"] = [w.org for w in my_org_id_list]  # 我管理的小组
    html_display["my_org_len"] = len(html_display["my_org_list"])
    return html_display


def get_org_left_navbar(org, is_myself, html_display):
    '''已废弃'''
    # assert (
    #        "is_myself" in html_display.keys()
    # ), "Forget to tell the website whether this is the user itself!"
    raise NotImplementedError(
        "old left_navbar function has been abandoned, please use `get_sidebar_and_navbar` instead!"
    )
    html_display["switch_org_name"] = org.oname
    html_display["underground_url"] = UNDERGROUND_URL
    html_display["org"] = org
    return html_display


# 检验是否要展示如何分享信息的帮助，预期只在stuinfo, orginfo, viewActivity使用
def get_inform_share(me: ClassifiedUser, is_myself=True):
    alert_message = ""
    if is_myself and me.inform_share:
        alert_message = ("【关于分享】:如果你在使用手机浏览器，"+
                        "可以使用浏览器自带的分享来分享你的主页或者活动主页，"+
                        "或者可以选择将其在微信/朋友圈中打开并分享。")
        # me.inform_share = False
        # me.save()
        return True, alert_message
    return False, alert_message


def get_sidebar_and_navbar(user, navbar_name="", title_name="", bar_display=None):
    '''
    YWolfeee Aug 16
    修改left siderbar的逻辑，统一所有个人和所有小组的左边栏，不随界面而改变
    这个函数负责统一get sidebar和navbar的内容，解决了信箱条数显示的问题
    user对象是request.user对象直接转移
    内容存储在bar_display中
    Attention: 本函数请在render前的最后时刻调用

    added by syb, 8.23:
    在函数中添加了title_name和navbar_name参数，根据这两个参数添加帮助信息
    现在最推荐的调用方式是：在views的函数中，写
    bar_display = utils.get_sidebar_and_navbar(user, title_name, navbar_name)
    '''
    if bar_display is None:
        bar_display = {}  # 默认参数只会初始化一次，所以不应该设置为{}
    me = get_person_or_org(user)  # 获得对应的对象
    _, user_type, _ = check_user_type(user)
    bar_display["user_type"] = user_type
    if user.is_staff:
        bar_display["is_staff"] = True

    # 接下来填补各种前端呈现信息

    # 头像
    bar_display["avatar_path"] = get_user_ava(me, user_type)

    # 信箱数量
    bar_display["mail_num"] = Notification.objects.filter(
        receiver=user, status=Notification.Status.UNDONE
    ).count()

    if user_type == UTYPE_PER:
        bar_display["profile_name"] = "个人主页"
        bar_display["profile_url"] = "/stuinfo/"
        bar_display["name"] = me.name
        bar_display["person_type"] = me.identity

        # 个人需要地下室跳转
        bar_display["underground_url"] = UNDERGROUND_URL

        # 个人所管理的小组列表
        # my_org_id_list = Position.objects.activated().filter(person=me, is_admin=True).select_related("org")
        # bar_display["my_org_list"] = [w.org for w in my_org_id_list]  # 我管理的小组
        # bar_display["my_org_len"] = len(bar_display["my_org_list"])


        bar_display['is_auditor'] = me.is_teacher()

    else:
        bar_display["profile_name"] = "小组主页"
        bar_display["profile_url"] = "/orginfo/"
        bar_display["is_course"] = me.otype.otype_name == COURSE_TYPENAME

    bar_display["navbar_name"] = navbar_name
    # title_name默认与navbar_name相同

    bar_display["title_name"] = title_name if title_name else navbar_name

    if navbar_name == "我的元气值":
        bar_display["help_message"] = local_dict["help_message"].get(
            (navbar_name + user_type.lower()),  ""
        )
        try:
            bar_display["help_paragraphs"] = Help.objects.get(title=navbar_name).content
        except:
            bar_display["help_paragraphs"] = ""
    elif navbar_name != "":
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


def url_check(arg_url):
    if DEBUG:  # DEBUG默认通过
        return True
    if arg_url is None:
        return True
    if re.match("^/[^/?]*/", arg_url):  # 相对地址
        return True
    for url in local_dict["url"].values():
        base = re.findall("^https?://([^/]*)/?", url)[0]
        base = f'^https?://{base}/?'
        # print('base:', base)
        if re.match(base, arg_url):
            return True
    log.operation_writer(SYSTEM_LOG, f'URL检查不合格: {arg_url}', 'utils[url_check]', log.STATE_WARNING)
    return False

def url2site(url):
    return urllib.parse.urlparse(url).netloc

def site_match(site, url, path_check_level=0, scheme_check=False):
    '''检查是否是同一个域名，也可以检查路径是否相同
    - path_check_level: 0-2, 不检查/忽视末尾斜杠/完全相同
    - scheme_check: bool, 协议是否相同
    '''
    site = urllib.parse.urlparse(site)
    url = urllib.parse.urlparse(url)
    if site.netloc != url.netloc:
        return False
    if scheme_check and site.scheme != url.scheme:
        return False
    if path_check_level:
        spath, upath = site.path, url.path
        if path_check_level > 1:
            spath, upath = spath.rstrip('/'), upath.rstrip('/')
        if spath != upath:
            return False
    return True


def get_std_url(arg_url: str, site_url: str, path_dir=None, match_func=None):
    '''
    检查是否匹配，返回(is_match, standard_url)，匹配时规范化url，否则返回原url

    Args
    ----
    - arg_url: 需要判断的url或者None，后者返回(False, site_url)
    - site_url: 规范的网址，其scheme, netloc和path部分被用于参考
    - path_dir: 需要保持一致的路径部分，默认为空
    - match_func: 检查匹配的函数，默认为site_match(site_url, arg_url)
    '''
    if match_func is None:
        match_func = lambda x: site_match(site_url, x)

    if arg_url is None:
        return False, site_url

    if match_func(arg_url):
        site_parse = urllib.parse.urlparse(site_url)
        arg_parse = urllib.parse.urlparse(arg_url)

        def in_dir(path, path_dir):
            return path.startswith(path_dir) or path == path_dir.rstrip('/')

        std_path = arg_parse.path
        if path_dir:
            if (in_dir(site_parse.path, path_dir) and not in_dir(std_path, path_dir)):
                std_path = path_dir.rstrip('/') + std_path
            elif (not in_dir(site_parse.path, path_dir) and in_dir(std_path, path_dir)):
                std_path = std_path.split(path_dir.rstrip('/'), 1)[1]

        std_parse = [
            site_parse.scheme,
            site_parse.netloc,
            std_path,
            arg_parse.params,
            arg_parse.query,
            arg_parse.fragment,
        ]
        arg_url = urllib.parse.urlunparse(std_parse)
        return True, arg_url
    return False, arg_url


def get_std_underground_url(underground_url):
    '''检查是否是地下室网址，返回(is_underground, standard_url)
    - 如果是，规范化网址，否则返回原URL
    - 如果参数为None，返回URL为地下室网址'''
    site_url = UNDERGROUND_URL
    return get_std_url(underground_url, site_url)
    if underground_url is None:
        underground_url = site_url
    if site_match(site_url, underground_url):
        underground_url = urllib.parse.urlunparse(
            urllib.parse.urlparse(site_url)[:2]
            + urllib.parse.urlparse(underground_url)[2:])
        return True, underground_url
    return False, underground_url

def get_std_inner_url(inner_url):
    '''检查是否是内部网址，返回(is_inner, standard_url)
    - 如果是，规范化网址，否则返回原URL
    - 如果参数为None，返回URL为主页相对地址'''
    site_url = LOGIN_URL
    return get_std_url(
        inner_url, '/welcome/',
        match_func=lambda x: (site_match(site_url, x)
                           or site_match('', x, scheme_check=True)),
    )
    if inner_url is None:
        inner_url = '/welcome/'
    if site_match(site_url, inner_url):
        inner_url = urllib.parse.urlunparse(
            ('', '') + urllib.parse.urlparse(inner_url)[2:])
    url_parse = urllib.parse.urlparse(inner_url)
    if url_parse.scheme or url_parse.netloc:
        return False, inner_url
    return True, inner_url


# 允许进行 cross site 授权时，return True
def check_cross_site(request, arg_url):
    netloc = url2site(arg_url)
    if netloc not in [
        '',  # 内部相对地址
        url2site(UNDERGROUND_URL),  # 地下室
        url2site(LOGIN_URL),  # yppf
    ]:
        return False
    return True


def get_url_params(request, html_display):
    raise NotImplementedError
    full_path = request.get_full_path()
    if "?" in full_path:
        params = full_path.split["?"][1]
        params = params.split["&"]
        for param in params:
            key, value = param.split["="][0], param.split["="][1]
            if key not in html_display.keys():  # 禁止覆盖
                html_display[key] = value


def if_image(image):
    '''判断是否为图片'''
    if image is None:
        return 0
    imgType_list = {"jpg", "bmp", "png", "jpeg", "rgb", "tif"}

    if imghdr.what(image) in imgType_list:
        return 2  # 为图片
    return 1  # 不是图片


def random_code_init(seed):
    '''用于新建小组时，生成6位随机密码'''
    b = string.digits + string.ascii_letters  # 构建密码池
    password = ""
    random.seed(seed)
    for i in range(0, 6):
        password = password + random.choice(b)
    return password


def get_captcha(request, username, valid_seconds=None, more_info=False):
    '''
    noexcept
    - username: 学号/小组号, 不一定对应request.user(此时应尚未登录)
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


def set_nperson_quota_to(quota):
    """
        后台设定所有自然人的元气值为一特定值，这个值就是每月的限额
        给所有用户发送通知
    """
    activated_npeople = NaturalPerson.objects.activated()


    activated_npeople.update(quota=quota)
    notification_content = f"学院已经将大家的元气值配额重新设定为{quota},祝您使用愉快！"
    title = Notification.Title.VERIFY_INFORM
    YPcollege = Organization.objects.get(oname=YQP_ONAME)

    # 函数内导入是为了防止破坏utils的最高优先级，如果以后确定不会循环引用也可提到外面
    # 目前不发送到微信哦
    from notification_utils import bulk_notification_create
    receivers = activated_npeople.select_related('person_id')
    receivers = [receiver.person_id for receiver in receivers]
    success, _ = bulk_notification_create(
        receivers,
        YPcollege,
        Notification.Type.NEEDREAD,
        title,
        notification_content,
    )
    return success


def check_account_setting(request, user_type):
    if user_type == UTYPE_PER:
        html_display = dict()
        attr_dict = dict()

        html_display['warn_code'] = 0
        html_display['warn_message'] = ""

        attr_dict['nickname'] = request.POST["nickname"]
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
        attr_dict['accept_promote'] = request.POST['accept_promote']
        attr_dict['wechat_receive_level'] = request.POST['wechat_receive_level']
        attr_dict['wallpaper'] = request.FILES.get("wallpaper")

        show_dict = dict()

        show_dict['show_nickname'] = request.POST.get('show_nickname') == 'on'
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
        attr_dict['tags_modify'] = request.POST['tags_modify']
    return attr_dict, show_dict, html_display

#获取未报销的活动
def get_unreimb_activity(org):
    """
    用于views.py&reimbursement_utils.py
    注意：默认传入参数org类型为Organization
    """
    reimbursed_act_ids = (
        Reimbursement.objects.all()
            .exclude(status=Reimbursement.ReimburseStatus.CANCELED)  # 未取消的
            .exclude(status=Reimbursement.ReimburseStatus.REFUSED)   # 未被拒绝的
            .values_list("related_activity_id", flat=True)
    )
    activities = (
        Activity.objects.activated()  # 本学期的
            .filter(organization_id=org)  # 本部门小组的
            .filter(status=Activity.Status.END)  # 已结束的
            .exclude(id__in=reimbursed_act_ids))  # 还没有报销的
    activities.len = len(activities)
    return activities


# 导出Excel文件
def export_activity(activity, inf_type):

    # 设置HTTPResponse的类型
    response = HttpResponse(content_type='application/vnd.ms-excel')
    if activity is None:
        return response
    response['Content-Disposition'] = f'attachment;filename={activity.title}.xls'
    if inf_type == "sign":#签到信息
        participants = Participant.objects.filter(activity_id=activity.id).filter(
            status=Participant.AttendStatus.ATTENDED)
    elif inf_type == "enroll":#报名信息
        participants = Participant.objects.filter(activity_id=activity.id).exclude(
            status=Participant.AttendStatus.CANCELED)
    else:
        return response
        """导出excel表"""
    if len(participants) > 0:
        # 创建工作簿
        ws = xlwt.Workbook(encoding='utf-8')
        # 添加第一页数据表
        w = ws.add_sheet('sheet1')  # 新建sheet（sheet的名称为"sheet1"）
        # 写入表头
        w.write(0, 0, u'姓名')
        w.write(0, 1, u'学号')
        w.write(0, 2, u'年级/班级')
        if inf_type == "enroll":
            w.write(0, 3, u'报名状态')
            w.write(0, 4, u'注：报名状态为“已参与”时表示报名成功并成功签到，“未签到”表示报名成功但未签到，'
                          u'"已报名"表示报名成功，“活动申请失败”表示在抽签模式中落选，“申请中”则表示抽签尚未开始。')
        # 写入数据
        excel_row = 1
        for participant in participants:
            name = participant.person_id.name
            Sno = participant.person_id.person_id.username
            grade = str(participant.person_id.stu_grade) + '级' + str(participant.person_id.stu_class) + '班'
            if inf_type == "enroll":
                status = participant.status
                w.write(excel_row, 3, status)
            # 写入每一行对应的数据
            w.write(excel_row, 0, name)
            w.write(excel_row, 1, Sno)
            w.write(excel_row, 2, grade)
            excel_row += 1
        # 写出到IO
        output = BytesIO()
        ws.save(output)
        # 重新定位到开始
        output.seek(0)
        response.write(output.getvalue())
    return response


# 导出小组成员信息Excel文件
def export_orgpos_info(org):
    # 设置HTTPResponse的类型
    response = HttpResponse(content_type='application/vnd.ms-excel')
    if org is None:
        return response
    response['Content-Disposition'] = f'attachment;filename=小组{org.oname}成员信息.xls'
    participants = Position.objects.activated().filter(org=org).filter(status=Position.Status.INSERVICE)
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
            pos = org.otype.get_name(participant.pos)
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


def escape_for_templates(text:str):
    return text.strip().replace("\r", "").replace("\\", "\\\\").replace("\n", "\\n").replace("\"", "\\\"")


def record_modification(user, info=""):
    try:
        _, usertype, _ = check_user_type(user)
        obj = get_person_or_org(user, usertype)
        name = obj.get_display_name()
        firsttime = not user.modify_records.exists()
        ModifyRecord.objects.create(user=user, usertype=usertype, name=name, info=info)
        return firsttime
    except:
        return None


def get_modify_rank(user):
    try:
        _, usertype, _ = check_user_type(user)
        records = user.modify_records.all()
        if not records:
            return -1
        first = records.order_by('time')[0]
        rank = ModifyRecord.objects.filter(
            usertype=usertype,
            time__lte=first.time,
            ).values('user').distinct().count()
        return rank
    except:
        return -1


def record_modify_with_session(request, info=""):
    try:
        _, usertype, _ = check_user_type(request.user)
        recorded = record_modification(request.user, info)
        if recorded == True:
            rank = get_modify_rank(request.user)
            is_person = usertype == UTYPE_PER
            info_rank = local_dict.get("max_inform_rank", {}).get(usertype, -1)
            if rank > -1 and rank <= info_rank:
                msg = (
                    f'您是第{rank}名修改账号信息的'+
                    ('个人' if is_person else '小组')+
                    '用户！保留此截图可在游园会兑换奖励！'
                )
                request.session['alert_message'] = msg
    except:
        pass


def update_related_account_in_session(request, username, shift=False, oname=""):
    """
    外层保证 username 是一个自然人的 username 并且合法

    登录时 shift 为 false，切换时为 True
    切换到某个组织时 oname 不为空，否则都是空
    """

    try:
        np = NaturalPerson.objects.activated().get(person_id__username=username)
    except:
        return False
    orgs = list(Position.objects.activated().filter(
        is_admin=True, person=np).values_list("org__oname", flat=True))

    if oname:
        if oname not in orgs:
            return False
        orgs.remove(oname)
        user = Organization.objects.get(oname=oname).organization_id
    else:
        user = np.person_id

    if shift:
        auth.logout(request)
        auth.login(request, user)

    request.session["Incharge"] = orgs
    request.session["NP"] = username

    return True


@log.except_captured(source='utils[user_login_org]', record_user=True)
def user_login_org(request, org) -> MESSAGECONTEXT:
    '''
    令人疑惑的函数，需要整改
    尝试从用户登录到org指定的组织，如果不满足权限，则会返回wrong
    返回wrong或succeed
    '''
    user = request.user
    valid, user_type, html_display = check_user_type(request.user)

    try:
        me = NaturalPerson.objects.activated().get(person_id=user)
    except:  # 找不到合法的用户
        return wrong("您没有权限访问该网址！请用对应小组账号登陆。")
    #是小组一把手
    try:
        position = Position.objects.activated().filter(org=org, person=me)
        assert len(position) == 1
        position = position[0]
        assert position.is_admin == True
    except:
        return wrong("没有登录到该小组账户的权限!")
    # 到这里, 是本人小组并且有权限登录
    auth.logout(request)
    auth.login(request, org.organization_id)  # 切换到小组账号
    update_related_account_in_session(request, user.username, oname=org.oname)
    return succeed("成功切换到小组账号处理该事务，建议事务处理完成后退出小组账号。")


log.operation_writer(SYSTEM_LOG, "系统启动", "util_底部")
