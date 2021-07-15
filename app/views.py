from django.shortcuts import render, redirect
from app.models import NaturalPerson, Position, Organization
from django.contrib import auth, messages
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from app.forms import UserForm
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from app.data_import import load
from django.contrib.auth.hashers import make_password, check_password
from django.db.models import Q
from app.utils import MyMD5PasswordHasher, MySHA256Hasher, load_local_json
from django.conf import settings
from django.urls import reverse
import json
from datetime import datetime
import time

local_dict = load_local_json()
underground_url = local_dict['url']['base_url']
# underground_url = 'http://127.0.0.1:8080/appointment/index'
hash_coder = MySHA256Hasher(local_dict['hash']['base_hasher'])


def index(request):
    arg_origin = request.GET.get('origin')
    modpw_status = request.GET.get('success')
    # request.GET['success'] = "no"
    arg_islogout = request.GET.get('is_logout')
    if arg_islogout is not None:
        if request.user.is_authenticated:
            auth.logout(request)
            return render(request, 'index.html', locals())
    if arg_origin is None:  # 非外部接入
        if request.user.is_authenticated:
            return redirect('/stuinfo')
    if request.method == 'POST' and request.POST:
        username = request.POST['username']
        password = request.POST['password']

        try:
            user = User.objects.get(username=username)
        except:
            # if arg_origin is not None:
            #    redirect(f'/login/?origin={arg_origin}')
            message = local_dict['msg']['404']
            invalid = True
            return render(request, 'index.html', locals())
        userinfo = auth.authenticate(username=username, password=password)
        if userinfo:
            auth.login(request, userinfo)
            request.session['username'] = username
            if arg_origin is not None:
                ##   加时间戳
                ##   以及可以判断一下 arg_origin 在哪
                ##   看看是不是 '/' 开头就行
                d = datetime.utcnow()
                t = time.mktime(datetime.timetuple(d))
                timeStamp = str(int(t))
                print("utc time: ", d)
                print(timeStamp)
                en_pw = hash_coder.encode(username + timeStamp)
                try:
                    userinfo = NaturalPerson.objects.get(pid=username)
                    name = userinfo.pname
                    return redirect(arg_origin + f'?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}&name={name}')
                except:
                    return redirect(arg_origin + f'?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}')
            else:
                return redirect('/stuinfo')
        else:
            invalid = True
            message = local_dict['msg']['406']

    # 非 post 过来的
    if arg_origin is not None:
        if request.user.is_authenticated:
            d = datetime.utcnow()
            t = time.mktime(datetime.timetuple(d))
            timeStamp = str(int(t))
            print("utc time: ", d)
            print(timeStamp)
            username = request.session['username']
            en_pw = hash_coder.encode(username + timeStamp)
            return redirect(arg_origin + f'?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}')

    return render(request, 'index.html', locals())


# Return content
# Sname 姓名 Succeed 成功与否
wechat_login_coder = MyMD5PasswordHasher("wechat_login")


def miniLogin(request):
    try:
        assert (request.method == 'POST')
        username = request.POST['username']
        password = request.POST['password']
        secret_token = request.POST['secret_token']
        assert (wechat_login_coder.verify(username, secret_token) == True)
        user = User.objects.get(username=username)

        userinfo = auth.authenticate(username=username, password=password)

        if userinfo:

            auth.login(request, userinfo)

            request.session['username'] = username
            en_pw = hash_coder.encode(request.session['username'])
            user_account = NaturalPerson.objects.get(pid=username)
            return JsonResponse(
                {'Sname': user_account.pname, 'Succeed': 1},
                status=200
            )
        else:
            return JsonResponse(
                {'Sname': username, 'Succeed': 0},
                status=400
            )
    except:
        return JsonResponse(
            {'Sname': '', 'Succeed': 0},
            status=400
        )


@login_required(redirect_field_name='origin')
def stuinfo(request):
    print(request.user.is_authenticated)
    print("stuinfo getin!!!")
    undergroundurl = underground_url
    mod_status = request.GET.get('modinfo')
    if mod_status is not None:
        if mod_status == 'success':
            mod_code = True
    try:
        username = request.session['username']
        user = User.objects.get(username= username)
        useroj = NaturalPerson.objects.get(pid=user)
        #user_pos = Position.objects.get(person=person)
        #user_org = user_pos.org

    except:
        redirect('/index/')
    ##user_pos.pos = 部员
    ##user_pos.org = <organization对象>
    ##<organization对象>.oname = 共青团北京大学元培学院委员会
    ##解释性语言##

    try:
        #userinfo = NaturalPerson.objects.filter(pid=user).values()[0]
        userinfo = useroj
        isFirst = useroj.firstTimeLogin
        # 未修改密码
        if isFirst:
            return redirect('/modpw/')
        ava = useroj.avatar
        ava_path = ''
        if str(ava) == '':
            ava_path = settings.MEDIA_URL + 'avatar/codecat.jpg'
        else:
            ava_path = settings.MEDIA_URL + str(ava)
        return render(request, 'indexinfo.html', locals())
    except:
        auth.logout(request)
        return redirect('/index')


@login_required(redirect_field_name='origin')
def account_setting(request):
    undergroundurl = underground_url
    username = request.session['username']
    info = NaturalPerson.objects.filter(pid=username)
    userinfo = info.values()[0]
    useroj = NaturalPerson.objects.get(pid=username)
    if str(useroj.avatar) == '':
        former_img = settings.MEDIA_URL + 'avatar/codecat.jpg'
    else:
        former_img = settings.MEDIA_URL + str(useroj.avatar)

    if request.method == 'POST' and request.POST:
        aboutbio = request.POST['aboutBio']
        tel = request.POST['tel']
        email = request.POST['email']
        Major = request.POST['major']
        ava = request.FILES.get('avatar')
        expr = bool(tel or Major or email or aboutbio or ava)
        if aboutbio != '':
            useroj.pBio = aboutbio
        if Major != '':
            useroj.pmajor = Major
        if email != '':
            useroj.pemail = email
        if tel != '':
            useroj.ptel = tel
        if ava is None:
            pass
        else:
            useroj.avatar = ava
        useroj.save()
        ava_path = settings.MEDIA_URL + str(ava)
        if expr == False:
            return render(request, 'user_account_setting.html', locals())

        else:
            upload_state = True
            return redirect("/stuinfo/?modinfo=success")
    return render(request, 'user_account_setting.html', locals())


def register(request):
    if request.user.is_superuser:
        if request.method == 'POST' and request.POST:
            name = request.POST['name']
            password = request.POST['password']
            sno = request.POST['snum']
            email = request.POST['email']
            password2 = request.POST['password2']
            pyear = request.POST['syear']
            #pgender = request.POST['sgender']
            if password != password2:
                render(request, 'index.html')
            else:
                # user with same sno
                same_user = NaturalPerson.objects.filter(pid=sno)
                if same_user:
                    render(request, 'auth_register_boxed.html')
                same_email = NaturalPerson.objects.filter(pemail=email)
                if same_email:
                    render(request, 'auth_register_boxed.html')

                # OK!
                user = User.objects.create(username=sno)
                user.set_password(password)
                user.save()

                new_user = NaturalPerson.objects.create(pid=user)
                new_user.pname = name
                new_user.pemail = email
                new_user.pyear= pyear
                new_user.save()
                return HttpResponseRedirect('/index/')
        return render(request, 'auth_register_boxed.html')
    else:
        return HttpResponseRedirect('/index/')


@login_required(redirect_field_name=None)
def logout(request):
    auth.logout(request)
    return HttpResponseRedirect('/index/')


def org_spec(request, *args, **kwargs):
    arg = args[0]
    org_dict = local_dict['org']
    title = org_dict[arg]
    org = Organization.objects.filter(oname=title)
    pos = Position.objects.filter(Q(org=org) | Q(pos='部长') | Q(pos='老板'))
    try:
        pos = Position.objects.filter(Q(org=org) | Q(pos='部长') | Q(pos='老板'))
        boss_no = pos.values()[0]['person_id']#存疑，可能还有bug here
        boss = NaturalPerson.objects.get(pid=boss_no).pname
        job = pos.values()[0]['pos']
    except:
        person_incharge = '负责人'
    return render(request, 'org_spec.html', locals())


def get_stu_img(request):
    print("in get stu img")
    stuId = request.GET.get('stuId')
    if stuId is not None:
        try:
            print(stuId)
            img_path = NaturalPerson.objects.get(pid=stuId).avatar
            if str(img_path) == '':
                img_path = settings.MEDIA_URL + 'avatar/codecat.jpg'
            else:
                img_path = settings.MEDIA_URL + str(img_path)
            print(img_path)
            return JsonResponse({'path': img_path}, status=200)
        except:
            return JsonResponse({'message': "Image not found!"}, status=404)
    return JsonResponse({'message': 'User not found!'}, status=404)


def search(request):
    undergroundurl = underground_url
    query = request.GET.get('Query')
    stu_list = NaturalPerson.objects.filter(Q(pid__icontains=query) | Q(pname__icontains=query))
    return render(request, 'search.html', locals())


def test(request):
    request.session['cookies'] = 'hello, i m still here.'
    return render(request, 'all_org.html')


@login_required(redirect_field_name='origin')
def modpw(request):
    err_code = 0
    err_message = None
    isFirst = NaturalPerson.objects.get(pid=request.session['username']).firstTimeLogin
    username = request.session['username']  # added by wxy
    useroj = NaturalPerson.objects.get(pid=username)
    if str(useroj.avatar) == '':
        ava_path = settings.MEDIA_URL + 'avatar/codecat.jpg'
    else:
        ava_path = settings.MEDIA_URL + str(useroj.avatar)
    if request.method == 'POST' and request.POST:
        oldpassword = request.POST['pw']
        newpw = request.POST['new']
        username = request.session['username']
        if oldpassword == newpw:
            err_code = 1
            err_message = "新密码不能与原密码相同"
        elif newpw == username:
            err_code = 2
            err_message = "新密码不能与学号相同"
        else:
            userauth = auth.authenticate(username=username, password=oldpassword)
            if userauth:
                user = User.objects.get(username=username)
                if user:
                    user.set_password(newpw)
                    user.save()
                    stu = NaturalPerson.objects.filter(pid=username)
                    stu.update(firstTimeLogin=False)

                    urls = reverse("index") + "?success=yes"
                    return redirect(urls)
                else:
                    err_code = 3
                    err_message = "学号不存在"
            else:
                err_code = 4
                err_message = "原始密码不正确"
    return render(request, 'modpw.html', locals())


def load_data(request):
    if request.user.is_superuser:
        df_1819 = load()
        for i in range(len(df_1819)):  # import 2018 stu info.
            username = str(df_1819['学号'].iloc[i])
            sno = username
            password = sno
            email = df_1819['邮箱'].iloc[i]
            if email == 'None':
                if sno[0] == '2':
                    email = sno + '@stu.pku.edu.cn'
                else:
                    email = sno + '@pku.edu.cn'
            tel = str(df_1819['手机号'].iloc[i])
            year = '20' + sno[0:2]
            gender = df_1819['性别'].iloc[i]
            major = df_1819['专业'].iloc[i]
            name = df_1819['姓名'].iloc[i]
            pclass = df_1819['班级'].iloc[i]
            user = User.objects.create(username=username)
            user.set_password(password)
            user.save()
            stu = NaturalPerson.objects.create(pid=sno)
            stu.pemail = email
            stu.ptel = tel
            stu.pyear= year
            stu.pgender = gender
            stu.pmajor = major
            stu.pname = name
            stu.pclass = pclass
            stu.save()
        return render(request, 'debugging.html')