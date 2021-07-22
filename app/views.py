from app.models import (
    NaturalPerson,
    Position,
    Organization,
    OrganizationType,
    Position,
    Activity,
    TransferRecord,
    Paticipant,
)
import app.utils as utils
from app.forms import UserForm
from app.data_import import load, load_orgtype, load_org
from app.utils import MyMD5PasswordHasher, MySHA256Hasher

from django.shortcuts import render, redirect
from django.http import HttpResponseRedirect, JsonResponse
from django.contrib import auth, messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password, check_password
from django.db import transaction
from django.db.models import Q
from django.conf import settings
from django.urls import reverse
from django.views.decorators.http import require_POST, require_GET

import json
from time import mktime
from datetime import datetime
from boottest import local_dict
import re
import random, requests  # 发送验证码

email_url = local_dict["url"]["email_url"]
hash_coder = MySHA256Hasher(local_dict["hash"]["base_hasher"])
email_coder = MySHA256Hasher(local_dict["hash"]["email"])


def load_org_data(request):
    if request.user.is_superuser:
        load_type = request.GET.get("loadtype", None)
        message = "加载失败！"
        if load_type is None:
            message = "没有得到loadtype参数:[org或type]"
        elif load_type == "otype":
            load_orgtype()
            message = "load type成功！"
        elif load_type == "org":
            load_org()
            message = "load org成功！"
    else:
        message = "请先以超级账户登录后台后再操作！"
    return render(request, "debugging.html", locals())


def get_person_or_org(user, user_type):
    return (
        NaturalPerson.objects.get(person_id=user)
        if user_type == "Person"
        else Organization.objects.get(organization_id=user)
    )  #


def index(request):
    arg_origin = request.GET.get("origin")
    modpw_status = request.GET.get("success")
    # request.GET['success'] = "no"
    arg_islogout = request.GET.get("is_logout")
    if arg_islogout is not None:
        if request.user.is_authenticated:
            auth.logout(request)
            return render(request, "index.html", locals())
    if arg_origin is None:  # 非外部接入
        if request.user.is_authenticated:
            return redirect("/welcome/")
            """
            valid, user_type , html_display = utils.check_user_type(request)
            if not valid:
                return render(request, 'index.html', locals())
            return redirect('/stuinfo') if user_type == "Person" else redirect('/orginfo')
            """
    if request.method == "POST" and request.POST:
        username = request.POST["username"]
        password = request.POST["password"]

        try:
            user = User.objects.get(username=username)
        except:
            # if arg_origin is not None:
            #    redirect(f'/login/?origin={arg_origin}')
            message = local_dict["msg"]["404"]
            invalid = True
            return render(request, "index.html", locals())
        userinfo = auth.authenticate(username=username, password=password)
        if userinfo:
            auth.login(request, userinfo)
            request.session["username"] = username
            if arg_origin is not None:
                # 加时间戳
                # 以及可以判断一下 arg_origin 在哪
                # 看看是不是 '/' 开头就行
                d = datetime.utcnow()
                t = mktime(datetime.timetuple(d))
                timeStamp = str(int(t))
                print("utc time: ", d)
                print(timeStamp)
                en_pw = hash_coder.encode(username + timeStamp)
                try:
                    userinfo = NaturalPerson.objects.get(person_id=username)
                    name = userinfo.name
                    return redirect(
                        arg_origin
                        + f"?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}&name={name}"
                    )
                except:
                    return redirect(
                        arg_origin
                        + f"?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}"
                    )
            else:
                # 先处理初次登录
                valid, user_type, html_display = utils.check_user_type(request)
                if not valid:
                    return redirect("/logout/")
                me = get_person_or_org(userinfo, user_type)
                if me.first_time_login:
                    return redirect("/modpw/")

                return redirect("/welcome/")
                """
                valid, user_type , html_display = utils.check_user_type(request)
                if not valid:
                    return render(request, 'index.html', locals())
                return redirect('/stuinfo') if user_type == "Person" else redirect('/orginfo')
                """
        else:
            invalid = True
            message = local_dict["msg"]["406"]

    # 非 post 过来的
    if arg_origin is not None:
        if request.user.is_authenticated:
            d = datetime.utcnow()
            t = mktime(datetime.timetuple(d))
            timeStamp = str(int(t))
            print("utc time: ", d)
            print(timeStamp)
            username = request.session["username"]
            en_pw = hash_coder.encode(username + timeStamp)
            return redirect(
                arg_origin + f"?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}"
            )

    return render(request, "index.html", locals())


# Return content
# Sname 姓名 Succeed 成功与否
wechat_login_coder = MyMD5PasswordHasher("wechat_login")


def miniLogin(request):
    try:
        assert request.method == "POST"
        username = request.POST["username"]
        password = request.POST["password"]
        secret_token = request.POST["secret_token"]
        assert wechat_login_coder.verify(username, secret_token) == True
        user = User.objects.get(username=username)

        userinfo = auth.authenticate(username=username, password=password)

        if userinfo:

            auth.login(request, userinfo)

            request.session["username"] = username
            en_pw = hash_coder.encode(request.session["username"])
            user_account = NaturalPerson.objects.get(person_id=username)
            return JsonResponse({"Sname": user_account.name, "Succeed": 1}, status=200)
        else:
            return JsonResponse({"Sname": username, "Succeed": 0}, status=400)
    except:
        return JsonResponse({"Sname": "", "Succeed": 0}, status=400)


@login_required(redirect_field_name="origin")
def stuinfo(request, name=None):
    """
        进入到这里的逻辑:
        首先必须登录，并且不是超级账户
        如果name是空
            如果是个人账户，那么就自动跳转个人主页"/stuinfo/myname"
            如果是组织账户，那么自动跳转welcome
        如果name非空但是找不到对应的对象
            自动跳转到welcome
        如果name有明确的对象
            如果不重名
                如果是自己，那么呈现并且有左边栏
                如果不是自己或者自己是组织，那么呈现并且没有侧边栏
            如果重名
                那么期望有一个"+"在name中，如果搜不到就跳转到Search/？Query=name让他跳转去
    """

    user = request.user
    valid, user_type, html_display = utils.check_user_type(request)
    if not valid:
        return redirect("/logout/")

    if name is None:
        if user_type == "Organization":
            return redirect("/welcome/")
        else:
            assert user_type == "Person"
            try:
                oneself = NaturalPerson.objects.activated().get(pid=user)
            except:
                return redirect("/welcome/")
            return redirect("/stuinfo/" + oneself.name)
    else:
        # 先对可能的加号做处理
        name_list = name.split("+")
        name = name_list[0]
        person = NaturalPerson.objects.activated().filter(name=name)
        if len(person) == 0:  # 查无此人
            return redirect("/welcome/")
        if len(person) == 1:  # 无重名
            person = person[0]
        else:  # 有很多人，这时候假设加号后面的是user的id
            if len(name_list) == 1:  # 没有任何后缀信息，那么如果是自己则跳转主页，否则跳转搜索
                if (
                    user_type == "Person"
                    and NaturalPerson.objects.activated().get(pid=user).name == name
                ):
                    person = NaturalPerson.objects.activated().get(pid=user)
                else:  # 不是自己，信息不全跳转搜索
                    return redirect("/search?Query=" + name)
            else:
                obtain_id = int(name_list[1])  # 获取增补信息
                get_user = User.objects.get(id=obtain_id)
                potential_person = NaturalPerson.objects.activated().get(pid=get_user)
                assert potential_person in person
                person = potential_person

        is_myself = user_type == "Person" and person.pid == user  # 用一个字段储存是否是自己
        html_display["is_myself"] = is_myself  # 存入显示

        # 处理被搜索人的信息，这里应该和“用户自己”区分开
        join_pos_id_list = Position.objects.activated().filter(person=person)

        # html_display['join_org_list'] = Organization.objects.filter(org__in = join_pos_id_list.values('org'))               # 我属于的组织

        # 呈现信息
        # 首先是左边栏
        html_display = utils.get_user_left_narbar(person, is_myself, html_display)

        modpw_status = request.GET.get("modinfo", None)
        html_display["modpw_code"] = (
            modpw_status is not None and modpw_status == "success"
        )
        html_display["warn_code"] = request.GET.get("warn_code", 0)  # 是否有来自外部的消息
        html_display["warn_message"] = request.GET.get("warn_message", "")  # 提醒的具体内容

        html_display["userinfo"] = person

        html_display["title_name"] = "User Profile"
        html_display["narbar_name"] = "个人主页"

        return render(request, "stuinfo.html", locals())


@login_required(redirect_field_name="origin")
def request_login_org(request, name=None):  # 特指个人希望通过个人账户登入组织账户的逻辑
    """
        这个函数的逻辑是，个人账户点击左侧的管理组织直接跳转登录到组织账户
        首先检查登录的user是个人账户，否则直接跳转orginfo
        如果个人账户对应的是name对应的组织的最高权限人，那么允许登录，否则跳转回stuinfo并warning
    """
    user = request.user
    valid, user_type, html_display = utils.check_user_type(request)
    if not valid:
        return redirect("/logout/")
    if user_type == "Organization":
        return redirect("/orginfo/")
    try:
        me = NaturalPerson.objects.activated().get(person_id=user)
    except:  # 找不到合法的用户
        return redirect("/welcome/")
    if name is None:  # 个人登录未指定登入组织,属于不合法行为,弹回欢迎
        return redirect("/welcome/")
    else:  # 确认有无这个组织
        try:
            org = Organization.objects.get(oname=name)
        except:  # 找不到对应组织
            urls = "/stuinfo/" + me.name + "?warn_code=1&warn_message=找不到对应组织,请联系管理员!"
            return redirect(urls)
        try:
            position = Position.objects.activated().filter(org=org, person=me)
            assert len(position) == 1
            position = position[0]
            assert position.pos == 0
        except:
            urls = "/stuinfo/" + me.name + "?warn_code=1&warn_message=没有登录到该组织账户的权限!"
            return redirect(urls)
        # 到这里,是本人组织并且有权限登录
        auth.logout(request)
        auth.login(request, org.organization_id)  # 切换到组织账号
        if org.first_time_login:
            return redirect("/modpw/")
        return redirect("/orginfo/")


@login_required(redirect_field_name="origin")
def orginfo(request, name=None):
    """
        orginfo负责呈现组织主页，逻辑和stuinfo是一样的，可以参考
        只区分自然人和法人，不区分自然人里的负责人和非负责人。任何自然人看这个组织界面都是【不可管理/编辑组织信息】
    """
    user = request.user
    valid, user_type, html_display = utils.check_user_type(request)
    me = get_person_or_org(user, user_type)

    if not valid:
        return redirect("/logout/")

    if name is None:  # 此时登陆的必需是法人账号，如果是自然人，则跳转welcome
        if user_type == "Person":
            return redirect("/welcome/")
        try:
            org = Organization.objects.activated().get(organization_id=user)
        except:
            return redirect("/welcome/")
        return redirect("/orginfo/" + org.oname)

    try:  # 指定名字访问组织账号的，可以是自然人也可以是法人。在html里要注意区分！

        # 下面是组织信息

        org = Organization.objects.activated().get(oname=name)
        organization_name = name
        organization_type_name = org.otype.otype_name
        # org的属性 YQPoint 和 information 不在此赘述，直接在前端调用

    except:
        return redirect("/welcome/")

        # 这一部分是负责人boss的信息
        boss = Position.objects.activated().get(org=org, pos=0).person
        # boss = NaturalPerson.objects.activated().get(person_id = bossid)
        boss_display = {}

        boss_display["bossname"] = boss.name
        boss_display["year"] = boss.stu_grade
        boss_display["major"] = boss.stu_major
        boss_display["email"] = boss.email
        boss_display["tel"] = boss.telephone

        # jobpos = Position.objects.activated().get(person=boss, org = org).pos
        boss_display["job"] = org.otype.job_name_list[0]

        # 补充左边栏信息
        # 判断是否是负责人，如果是，在html的sidebar里要加上一个【切换账号】的按钮
        html_display["isboss"] = (
            True if (user_type == "Person" and boss.person_id == user) else False
        )
        # 判断是否为组织账户本身在登录
        html_display["is_myself"] = me == org

        # 再处理修改信息的回弹
        modpw_status = request.GET.get("modinfo", None)
        html_display["modpw_code"] = (
            modpw_status is not None and modpw_status == "success"
        )

        # 补充其余信息
        html_display = utils.get_org_left_narbar(
            org, html_display["is_myself"], html_display
        )

        # 组织活动的信息

    # 补充一些呈现信息
    html_display["title_name"] = "Org. Profile"
    html_display["narbar_name"] = "组织主页"
    return render(request, "orginfo.html", locals())


@login_required(redirect_field_name="origin")
def homepage(request):
    valid, user_type, html_display = utils.check_user_type(request)
    is_person = True if user_type == "Person" else False
    if not valid:
        return redirect("/logout/")
    me = get_person_or_org(request.user, user_type)
    myname = me.name if is_person else me.oname

    # 直接储存在html_display中
    # profile_name = "个人主页" if is_person else "组织主页"
    # profile_url = "/stuinfo/" + myname if is_person else "/orginfo/" + myname

    # 补充一些呈现信息
    html_display["title_name"] = "Welcome Page"
    html_display["narbar_name"] = "近期要闻"  #
    return render(request, "welcome_page.html", locals())


@login_required(redirect_field_name="origin")
def account_setting(request):
    valid, user_type, html_display = utils.check_user_type(request)
    if not valid:
        return redirect("/logout/")

    # 在这个页面 默认回归为自己的左边栏
    html_display["is_myself"] = True
    user = request.user
    info = NaturalPerson.objects.filter(person_id=user)
    userinfo = info.values()[0]

    useroj = NaturalPerson.objects.get(person_id=user)

    former_img = html_display["avatar_path"]

    if request.method == "POST" and request.POST:
        aboutbio = request.POST["aboutBio"]
        tel = request.POST["tel"]
        email = request.POST["email"]
        Major = request.POST["major"]
        ava = request.FILES.get("avatar")
        expr = bool(tel or Major or email or aboutbio or ava)
        if aboutbio != "":
            useroj.biography = aboutbio
        if Major != "":
            useroj.stu_major = Major
        if email != "":
            useroj.email = email
        if tel != "":
            useroj.telephone = tel
        if ava is None:
            pass
        else:
            useroj.avatar = ava
        useroj.save()
        avatar_path = settings.MEDIA_URL + str(ava)
        if expr == False:
            return render(request, "user_account_setting.html", locals())

        else:
            upload_state = True
            return redirect("/stuinfo/?modinfo=success")

    # 补充网页呈现所需信息
    html_display["title_name"] = "Account Setting"
    html_display["narbar_name"] = "账户设置"

    # 然后是左边栏
    html_display = utils.get_user_left_narbar(
        useroj, html_display["is_myself"], html_display
    )

    return render(request, "user_account_setting.html", locals())


def register(request):
    if request.user.is_superuser:
        if request.method == "POST" and request.POST:
            name = request.POST["name"]
            password = request.POST["password"]
            sno = request.POST["snum"]
            email = request.POST["email"]
            password2 = request.POST["password2"]
            stu_grade = request.POST["syear"]
            # gender = request.POST['sgender']
            if password != password2:
                render(request, "index.html")
            else:
                # user with same sno
                same_user = NaturalPerson.objects.filter(person_id=sno)
                if same_user:
                    render(request, "auth_register_boxed.html")
                same_email = NaturalPerson.objects.filter(email=email)
                if same_email:
                    render(request, "auth_register_boxed.html")

                # OK!
                user = User.objects.create(username=sno)
                user.set_password(password)
                user.save()

                new_user = NaturalPerson.objects.create(person_id=user)
                new_user.name = name
                new_user.email = email
                new_user.stu_grade = stu_grade
                new_user.save()
                return HttpResponseRedirect("/index/")
        return render(request, "auth_register_boxed.html")
    else:
        return HttpResponseRedirect("/index/")


# @login_required(redirect_field_name=None)
def logout(request):
    auth.logout(request)
    return HttpResponseRedirect("/index/")


"""
def org_spec(request, *args, **kwargs):
    arg = args[0]
    org_dict = local_dict['org']
    topic = org_dict[arg]
    org = Organization.objects.filter(oname=topic)
    pos = Position.objects.filter(Q(org=org) | Q(pos='部长') | Q(pos='老板'))
    try:
        pos = Position.objects.filter(Q(org=org) | Q(pos='部长') | Q(pos='老板'))
        boss_no = pos.values()[0]['person_id']#存疑，可能还有bug here
        boss = NaturalPerson.objects.get(person_id=boss_no).name
        job = pos.values()[0]['pos']
    except:
        person_incharge = '负责人'
    return render(request, 'org_spec.html', locals())
"""


def get_stu_img(request):
    print("in get stu img")
    stuId = request.GET.get("stuId")
    if stuId is not None:
        try:
            print(stuId)
            img_path = NaturalPerson.objects.get(person_id=stuId).avatar
            if str(img_path) == "":
                img_path = settings.MEDIA_URL + "avatar/codecat.jpg"
            else:
                img_path = settings.MEDIA_URL + str(img_path)
            print(img_path)
            return JsonResponse({"path": img_path}, status=200)
        except:
            return JsonResponse({"message": "Image not found!"}, status=404)
    return JsonResponse({"message": "User not found!"}, status=404)


def search(request):
    """
        搜索界面的呈现逻辑
        分成搜索个人和搜索组织两个模块，每个模块的呈现独立开，有内容才呈现，否则不显示
        搜索个人：
            支持使用姓名搜索，支持对未设为不可见的昵称和专业搜索
            搜索结果的呈现采用内容/未公开表示，所有列表为people_filed
        搜索组织
            支持使用组织名、组织类型搜索、一级负责人姓名
            组织的呈现内容由拓展表体现，不在这个界面呈现具体成员
    """
    try:
        valid, user_type, html_display = utils.check_user_type(request)
        if not valid:
            return redirect("/logout/")

        '''
        is_person = True if user_type == "Person" else False
        me = get_person_or_org(request.user, user_type)
        html_display["is_myself"] = True
        if is_person:
            html_display = utils.get_user_left_narbar(
                me, html_display["is_myself"], html_display
            )
        else:
            html_display = utils.get_org_left_narbar(
                me, html_display["is_myself"], html_display
            )
        '''
        # syb: 以上一段目前不注释掉运行还会报错，我去查查为什么;好像是position类里面缺一些相关的设置
        # 或许我一会儿补一下下面报错的描述

        query = request.GET.get("Query", "")
        if query == "":
            return redirect("/welcome/")

        # 首先搜索个人
        people_list = NaturalPerson.objects.filter(
            Q(pname__icontains=query)
            | (Q(pnickname__icontains=query) & Q(show_nickname=True))
            | (Q(pmajor__icontains=query) & Q(show_major=True))
        )

        # 接下来准备呈现的内容
        # 首先是准备搜索个人信息的部分
        people_field = [
            "姓名",
            "年级",
            "班级",
            "昵称",
            "性别",
            "专业",
            "邮箱",
            "电话",
            "宿舍",
            "状态",
        ]  # 感觉将年级和班级分开呈现会简洁很多

        return render(request, "search.html", locals())
    except Exception as e:
        print(
            f"Error was found in app/views.py, function search.\nError description: {str(e)}\n"
        )
        auth.logout(request)
        return redirect("/index/")


def test(request):
    request.session["cookies"] = "hello, i m still here."
    return render(request, "all_org.html")


def forget_password(request):
    """
        忘记密码页（Pylance可以提供文档字符串支持）

        页面效果
        -------
        - 根据（邮箱）验证码完成登录，提交后跳转到修改密码界面
        - 本质是登录而不是修改密码
        - 如果改成支持验证码登录只需修改页面和跳转（记得修改函数和页面名）

        页面逻辑
        -------
        1. 发送验证码
            1.5 验证码冷却避免多次发送
        2. 输入验证码
            2.5 保留表单信息
        3. 错误提醒和邮件发送提醒

        实现逻辑
        -------
        - 通过脚本使按钮提供不同的`send_captcha`值，区分按钮
        - 通过脚本实现验证码冷却，页面刷新后重置冷却（避免过长等待影响体验）
        - 通过`session`保证安全传输验证码和待验证用户
        - 成功发送/登录后才在`session`中记录信息
        - 页面模板中实现消息提醒
            - `err_code`非零值代表错误，在页面中显示
            - `err_code`=`0`或`4`是预设的提醒值，额外弹出提示框
            - forget_password.html中可以进一步修改
        - 尝试发送验证码后总是弹出提示框，通知用户验证码的发送情况

        注意事项
        -------
        - 尝试忘记密码的不一定是本人，一定要做好隐私和逻辑处理
            - 用户邮箱应当部分打码，避免向非本人提供隐私数据！
        - 不发送消息时`err_code`应为`None`或不声明，不同于modpw
        - `err_code`=`4`时弹出
        - 连接设置的timeout为6s
        - 如果引入企业微信验证，建议将send_captcha分为'qywx'和'email'
    """
    if request.method == "POST":
        username = request.POST["username"]
        send_captcha = request.POST["send_captcha"] == "yes"
        vertify_code = request.POST["vertify_code"]  # 用户输入的验证码

        user = User.objects.filter(username=username)
        if not user:
            err_code = 1
            err_message = "账号不存在"
        else:
            user = User.objects.get(username=username)
            useroj = NaturalPerson.objects.get(person_id=user)  # 目前似乎保证是自然人
            isFirst = useroj.first_time_login
            if isFirst:
                err_code = 2
                err_message = "初次登录密码与账号相同！"
            elif send_captcha:
                email = useroj.email
                if not email or email.lower() == "none" or "@" not in email:
                    err_code = 3
                    err_message = "您没有设置邮箱，请发送姓名、学号和常用邮箱至gypjwb@pku.edu.cn进行修改"  # 记得填
                else:
                    captcha = random.randrange(1000000)  # randint包含端点，randrange不包含
                    captcha = f"{captcha:06}"
                    msg = (
                        f"<h3><b>亲爱的{useroj.name}同学：</b></h3><br/>"
                        "您好！您的账号正在进行邮箱验证，本次请求的验证码为：<br/>"
                        f'<p style="color:orange">{captcha}'
                        '<span style="color:gray">(仅当前页面有效)</span></p>'
                        '点击进入<a href="https://yppf.yuanpei.life">元培成长档案</a><br/>'
                        "<br/><br/><br/>"
                        "元培学院开发组<br/>" + datetime.now().strftime("%Y年%m月%d日")
                    )
                    post_data = {
                        "toaddrs": [email],  # 收件人列表
                        "subject": "YPPF登录验证",  # 邮件主题/标题
                        "content": msg,  # 邮件内容
                        # 若subject为空, 第一个\n视为标题和内容的分隔符
                        "html": True,  # 可选 如果为真则content被解读为html
                        "private_level": 0,  # 可选 应在0-2之间
                        # 影响显示的收件人信息
                        # 0级全部显示, 1级只显示第一个收件人, 2级只显示发件人
                        "secret": email_coder.encode(msg),  # content加密后的密文
                    }
                    post_data = json.dumps(post_data)
                    pre, suf = email.rsplit("@", 1)
                    if len(pre) > 5:
                        pre = pre[:2] + "*" * len(pre[2:-3]) + pre[-3:]
                    try:
                        response = requests.post(email_url, post_data, timeout=6)
                        response = response.json()
                        if response["status"] != 200:
                            err_code = 4
                            err_message = f"未能向{pre}@{suf}发送邮件"
                        else:
                            # 记录验证码发给谁 不使用username防止被修改
                            request.session["received_user"] = username
                            request.session["captcha"] = captcha
                            err_code = 0
                            err_message = f"验证码已发送至{pre}@{suf}"
                    except:
                        err_code = 4
                        err_message = "邮件发送失败：超时"
            else:
                captcha = request.session.get("captcha", "")
                received_user = request.session.get("received_user", "")
                if len(captcha) != 6 or username != received_user:
                    err_code = 5
                    err_message = "请先发送验证码"
                elif vertify_code.upper() == captcha.upper():
                    auth.login(request, user)
                    request.session.pop("captcha")
                    request.session["username"] = username
                    request.session["forgetpw"] = "yes"
                    return redirect(reverse("modpw"))
                else:
                    err_code = 6
                    err_message = "验证码不正确"
    return render(request, "forget_password.html", locals())


@login_required(redirect_field_name="origin")
def modpw(request):
    err_code = 0
    err_message = None
    forgetpw = request.session.get("forgetpw", "") == "yes"  # added by pht
    user = request.user
    username = user.username
    valid, user_type, html_display = utils.check_user_type(request)
    useroj = get_person_or_org(user, user_type)
    isFirst = useroj.first_time_login
    if str(useroj.avatar) == "":
        avatar_path = settings.MEDIA_URL + "avatar/codecat.jpg"
    else:
        avatar_path = settings.MEDIA_URL + str(useroj.avatar)
    if request.method == "POST" and request.POST:
        oldpassword = request.POST["pw"]
        newpw = request.POST["new"]
        strict_check = False

        if oldpassword == newpw and strict_check and not forgetpw:  # modified by pht
            err_code = 1
            err_message = "新密码不能与原密码相同"
        elif newpw == username and strict_check:
            err_code = 2
            err_message = "新密码不能与学号相同"
        elif newpw != oldpassword and forgetpw:  # added by pht
            err_code = 5
            err_message = "两次输入的密码不匹配"
        else:
            userauth = auth.authenticate(username=username, password=oldpassword)
            if forgetpw:  # added by pht: 这是不好的写法，可改进
                userauth = True
            if userauth:
                try:  # modified by pht: if检查是错误的，不存在时get会报错
                    user.set_password(newpw)
                    user.save()
                    useroj.first_time_login = False
                    useroj.save()

                    if forgetpw:
                        request.session.pop("forgetpw")  # 删除session记录

                    urls = reverse("index") + "?success=yes"
                    return redirect(urls)
                except:  # modified by pht: 之前使用的if检查是错误的
                    err_code = 3
                    err_message = "学号不存在"
            else:
                err_code = 4
                err_message = "原始密码不正确"
    return render(request, "modpw.html", locals())


def load_data(request):
    if request.user.is_superuser:
        df_1819 = load()
        for i in range(len(df_1819)):  # import 2018 stu info.
            username = str(df_1819["学号"].iloc[i])
            sno = username
            password = sno
            email = df_1819["邮箱"].iloc[i]
            if email == "None":
                if sno[0] == "2":
                    email = sno + "@stu.pku.edu.cn"
                else:
                    email = sno + "@pku.edu.cn"
            tel = str(df_1819["手机号"].iloc[i])
            year = "20" + sno[0:2]
            gender = df_1819["性别"].iloc[i]
            major = df_1819["专业"].iloc[i]
            name = df_1819["姓名"].iloc[i]
            stu_class = df_1819["班级"].iloc[i]
            user = User.objects.create(username=username)
            user.set_password(password)
            user.save()
            stu = NaturalPerson.objects.create(person_id=sno)
            stu.email = email
            stu.telephone = tel
            stu.stu_grade = year
            if gender == "男":
                stu.gender = NaturalPerson.Gender.MALE
            elif gender == "女":
                stu.gender = NaturalPerson.Gender.FEMALE
            else:
                stu.gender = NaturalPerson.Gender.OTHER
            stu.stu_major = major
            stu.name = name
            stu.stu_class = stu_class
            stu.save()
        message = "导入学生信息成功！"
    else:
        message = "请先以超级账户登录后台后再操作！"
    return render(request, "debugging.html", locals())


# 参与活动，get 传两个简单参数即可，活动 aid，价格等级
# 再加一个 origin from，点一下即可返回 ( 可以看到已经报名 )
# 活动的多字段怎么弄
@require_GET
@login_required(redirect_field_name="origin")
def engage_activity(request):
    origin = request.GET.get("origin")
    if origin is None:
        origin = "/"
    context = dict()
    context["origin"] = origin
    choice = request.GET.get("choice")
    # 默认是 0，没有分级的情况下可以只传 activity_id
    if choice is None:
        choice = 0
    else:
        choice = int(choice)
    activity_id = request.GET.get("activity_id")
    person_id = request.session["username"]

    try:
        activity = Activity.objects.select_for_update().filter(id=activity_id)
        payer = NaturalPerson.objects.select_for_update().filter(
            pid__username=person_id
        )
        with transaction.atomic():
            assert len(activity) == 1
            assert len(payer) == 1
            activity = activity[0]
            payer = payer[0]

            try:
                panticipant = Paticipant.objects.get(
                    activity_id=activity, person_id=payer
                )
                context[
                    "msg"
                ] = "You have already participated in the activity. If you are not deliberately do it, please contact the administrator to report this bug."
                return render(request, "msg.html", context)
            except:
                pass

            organization_id = activity.oid_id
            orgnization = Organization.objects.select_for_update().filter(
                organization_id=organization_id
            )
            assert len(orgnization) == 1
            orgnization = orgnization[0]

            amount = float(activity.YQPoint[choice])
            cnt = activity.places[choice]
            if cnt <= 0:
                context["msg"] = "Failed to fetch the ticket."
                return render(request, "msg.html", context)
            if payer.YQPoint < amount:
                context["msg"] = "No enough YQPoint"
                return render(request, "msg.html", context)
            payer.YQPoint -= float(amount)
            activity.places[choice] = cnt - 1
            orgnization.YQPoint += float(amount)

            record = TransferRecord.objects.create(
                proposer=request.user, recipient=orgnization.organization_id
            )
            record.amount = amount
            record.message = f"Participate Activity {activity.topic}"
            record.status = 0  # Wating
            record.time = str(datetime.now())

            panticipant = Paticipant.objects.create(
                activity_id=activity, person_id=payer
            )

            panticipant.save()
            record.save()
            payer.save()
            activity.save()
            orgnization.save()

    except:
        context[
            "msg"
        ] = "Unexpected failure. If you are not deliberately do it, please contact the administrator to report this bug."
        return render(request, "msg.html", context)

    context["msg"] = "Successfully participate the activity."
    return render(request, "msg.html", context)


# 用已有的搜索，加一个转账的想他转账的 field
# 调用的时候传一下 url 到 origin
# 搜索不希望出现学号，rid 为 User 的 index
@require_GET
@login_required(redirect_field_name="origin")
def transaction_page(request, rid=None):
    # recipient_id = request.GET.get("rid")
    recipient_id = rid
    origin = request.GET.get("origin")
    if origin is None:
        origin = "/"
    # 可以有一个默认金额，但好像用不到
    # amount = request.GET.get('amount')
    context = dict()

    # r_user = User.objects.get(id=recipient_id)

    try:
        if re.match("zz\d+", str(recipient_id)) is not None:
            recipient = Organization.objects.get(oid=recipient_id)
            recipient_type = "org"
        else:
            recipient = NaturalPerson.objects.get(person_id=recipient_id)
            recipient_type = "np"
    except:
        context[
            "msg"
        ] = "Unexpected recipient. If you are not deliberately doing this, please contact the administrator to report this bug."
        context["origin"] = origin
        return render(request, "msg.html", context)


    if recipient_type == "np":
        name = recipient.nickname
        if name == "":
            name = recipient.name
        context["avatar"] = recipient.avatar
    else:
        name = recipient.oname
    context["name"] = name
    context["rid"] = recipient_id
    context["rtype"] = recipient_type
    context["origin"] = origin
    return render(request, "transaction_page.html", context)


# 涉及表单，一般就用 post 吧
# 这边先扣，那边先不加，等确认加
# 预期这边成功之后，用企业微信通知接收方，调转到查看未接收记录的窗口
@require_POST
@login_required(redirect_field_name="origin")
def start_transaction(request):
    recipient_id = request.POST.get("rid")  # index
    recipient_type = request.POST.get("rtype")
    origin = request.POST.get("origin")
    amount = request.POST.get("amount")
    transaction_msg = request.POST.get("msg")
    name = request.POST.get("name")
    context = dict()
    context["origin"] = origin

    # r_user = User.objects.get(username=recipient_id)

    try:
        # 允许一位小数，* 10 存成整数
        amount = int(float(amount) * 10)
    except:
        context[
            "msg"
        ] = "Unexpected amount. If you are not deliberately doing this, please contact the administrator to report this bug."
        return render(request, "msg.html", context)

    try:
        if recipient_type == "np":
            recipient = NaturalPerson.objects.get(person_id=recipient_id).person_id
        else:
            recipient = Organization.objects.get(
                organization_id=recipient_id
            ).organization_id
    except:
        context[
            "msg"
        ] = "Unexpected recipient. If you are not deliberately doing this, please contact the administrator to report this bug."
        return render(request, "msg.html", context)

    payer_id = request.session["username"]
    if re.match("zz\d+", payer_id) is not None:
        payer = Organization.objects.get(organization_id=request.user)
    else:
        payer = NaturalPerson.objects.get(person_id=request.user)

    try:
        if re.match("zz\d+", payer_id) is not None:
            payer = Organization.objects.select_for_update().filter(
                organization_id=request.user
            )
        else:
            payer = NaturalPerson.objects.select_for_update().filter(
                person_id=request.user
            )
        with transaction.atomic():
            assert len(payer) == 1
            payer = payer[0]
            payer.YQPoint -= float(amount)
            # TODO 目前用的是 nickname，可能需要改成 name
            # 需要确认 create 是否会在数据库产生记录，如果不会是否会有主键冲突？
            record = TransferRecord.objects.create(
                proposer=request.user, recipient=recipient
            )
            record.amount = amount
            record.message = transaction_msg
            record.status = 1  # Wating
            record.time = str(datetime.now())
            record.save()

            # TODO 确认 save 之后会释放锁？
            payer.save()

    except:
        context[
            "msg"
        ] = "Check if you have enough YQPoint. If so, please contact the administrator to report this bug."
        return render(request, "msg.html", context)

    context["msg"] = "Waiting the recipient to confirm the transaction."
    return render(request, "msg.html", context)


@require_GET
@login_required(redirect_field_name="origin")
def confirm_transaction(request, tid=None, reject=None):
    # tid = request.GET.get("tid")
    # reject = request.GET.get("reject")
    origin = request.GET.get("origin")
    if origin is None:
        origin = "/"
    context = dict()
    try:
        record = TransferRecord.objects.select_for_update().filter(id=tid)
        with transaction.atomic():
            assert len(record) == 1
            record = record[0]
            if record.recipient != request.user:
                context[
                    "msg"
                ] = "The transaction is not yours. If you are not deliberately doing this, please contact the administrator to report this bug."
                return render(request, "msg.html", context)
            if record.status != 1:
                context[
                    "msg"
                ] = "The transaction has already been dealt. If you are not deliberately doing this, please contact the administrator to report this bug."
                return render(request, "msg.html", context)
            payer = record.proposer
            if re.match("zz\d+", payer.username) is not None:
                payer = Organization.objects.select_for_update().filter(
                    organization_id=payer
                )
            else:
                payer = NaturalPerson.objects.select_for_update().filter(
                    person_id=payer
                )
            assert len(payer) == 1
            payer = payer[0]
            recipient = record.recipient
            if re.match("zz\d+", recipient.username) is not None:
                recipient = Organization.objects.select_for_update().filter(
                    organization_id=recipient
                )
            else:
                recipient = NaturalPerson.objects.select_for_update().filter(
                    person_id=recipient
                )
            assert len(recipient) == 1
            recipient = recipient[0]
            if reject == 2:
                record.tstatus = 2
                payer.YQPoint += record.amount
            elif reject == 0:
                record.tstatus = 0
                recipient.YQPoint += record.amount
            record.save()
            payer.save()
            recipient.save()
        context["msg"] = "Confirmed transaction."
        context["origin"] = origin
        return render(request, "msg.html", context)
    except:
        context[
            "msg"
        ] = "Can not find the transaction record. If you are not deliberately doing this, please contact the administrator to report this bug."
        return render(request, "msg.html", context)

#modified by Kinnuch
@login_required(redirect_field_name='origin')
def mywallet(request):
    query = request.session['username']
    flag = -1
    if re.match('zz\d+', query) is not None:
        queryman = Organization.objects.get(oid=request.user)
        flag = 0
    else:
        queryman = NaturalPerson.objects.get(pid=request.user)
        flag = 1
    balance = queryman.YQPoint
    query_id = queryman.pid_id
    Record_list = TransferRecord.objects.filter(
        Q(proposer=query_id) | (Q(recipient=query_id)))
    return render(request, 'mywallet.html', locals())

def showActivities(request):
    notes = [
        {"title": "活动名称1", "Date": "11/01/2019", "Address": ["B107A", "B107B"]},
        {"title": "活动名称2", "Date": "11/02/2019", "Address": ["B108A"]},
        {"title": "活动名称3", "Date": "11/02/2019", "Address": ["B108A"]},
        {"title": "活动名称4", "Date": "11/02/2019", "Address": ["B108A"]},
        {"title": "活动名称5", "Date": "11/02/2019", "Address": ["B108A"]},
    ]

    person = True  # 人/法人

    return render(request, "notes.html", locals())


def viewActivities(request):
    """
    aname = str(request.POST["aname"])  # 活动名称
    oid = request.POST["oid"]  # 组织id
    astart = request.POST["astart"]  # 默认传入的格式为 2021-07-21 21:00:00
    afinish = request.POST["afinish"]
    content = str(request.POST["content"])
    URL = str(request.POST["URL"])  # 活动推送链接
    QRcode = request.POST["QRcode"]  # 收取元气值的二维码
    aprice = request.POST["aprice"]  # 活动价格
    places = request.POST["places"]  # 活动举办的地点，默认是list
    """

    person = True

    return render(request, "activity_info.html", locals())


def addActivities(request):
    """
    aname = str(request.POST["aname"])  # 活动名称
    oid = request.POST["oid"]  # 组织id
    astart = request.POST["astart"]  # 默认传入的格式为 2021-07-21 21:00:00
    afinish = request.POST["afinish"]
    content = str(request.POST["content"])
    URL = str(request.POST["URL"])  # 活动推送链接
    QRcode = request.POST["QRcode"]  # 收取元气值的二维码
    aprice = request.POST["aprice"]  # 活动价格
    places = request.POST["places"]  # 活动举办的地点，默认是list
    """

    person = True

    return render(request, "activity_add.html", locals())
