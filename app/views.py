from django.shortcuts import render, redirect
from app.models import NaturalPerson,Position,Organization
from django.contrib import auth,messages
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from app.forms import UserForm
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from app.data_import import load
from django.contrib.auth.hashers import make_password, check_password
from django.db.models import Q
from app.utils import MyMD5PasswordHasher,load_local_json
from django.conf import settings
from django.urls import reverse
import json

local_dict = load_local_json()
underground_url = local_dict['url']['base_url']
hash_coder = MyMD5PasswordHasher(local_dict['hash']['base_hasher'])
# Create your views here.
def index(request):
    arg_origin = request.GET.get('origin')
    modpw_status = request.GET.get('success')
    #request.GET['success'] = "no"
    arg_islogout = request.GET.get('is_logout')
    if arg_islogout is not None:
        if request.user.is_authenticated:
            auth.logout(request)
    if arg_origin is None: #非外部接入
        if request.user.is_authenticated:
            return redirect('/stuinfo')
    if request.method == 'POST' and request.POST:
        username = request.POST['username']
        password = request.POST['password']
        
        try:
            user = User.objects.get(username=username)
        except:
            #if arg_origin is not None:
            #    redirect(f'/login/?origin={arg_origin}')
            message = local_dict['msg']['404']
            invalid = True
            return render(request,'index.html',locals())
        userinfo = auth.authenticate(username=username,password=password)
        if userinfo:
            auth.login(request,userinfo)
            request.session['username'] = username
            if arg_origin is not None:
                
                en_pw = hash_coder.encode(username)
                try:
                    userinfo = NaturalPerson.objects.get(pid=username)
                    name = userinfo.pname
                    return redirect(arg_origin+f'?Sid={username}&Secret={en_pw}&name={name}')
                    
                except:
                    return redirect(arg_origin+f'?Sid={username}&Secret={en_pw}')
            else:
                return redirect('/stuinfo')
        else:
            invalid = True
            message = local_dict['msg']['406']
    
    if arg_origin is not None:
        if request.user.is_authenticated:
            
            en_pw = hash_coder.encode(request.session['username'])
            return redirect(arg_origin+f'?Sid=' + str(request.session['username']) + '&Secret=' + str(en_pw))

    return render(request,'index.html',locals())

#Return content
# Sname 姓名 Succeed 成功与否
wechat_login_coder = MyMD5PasswordHasher("wechat_login")
def miniLogin(request):
    try:
        assert (request.method == 'POST')
        username = request.POST['username']
        password = request.POST['password']
        secret_token = request.POST['secret_token']
        assert (wechat_login_coder.verify(username,secret_token) == True)
        user = User.objects.get(username=username)
        
        userinfo = auth.authenticate(username=username,password=password)
        
        if userinfo:
            
            auth.login(request,userinfo)
            
            request.session['username'] = username
            en_pw = hash_coder.encode(request.session['username'])
            user_account = NaturalPerson.objects.get(pid=username)
            return JsonResponse(
            {'pname': user_account.pname, 'Succeed': 1},
            status = 200
        )
        else:
            return JsonResponse(
            {'pname': username, 'Succeed': 0},
            status = 400
        )
    except:
        return JsonResponse(
                {'pname': '', 'Succeed': 0},
                status = 400
            )


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
        userinfo = NaturalPerson.objects.filter(pid=username)
        user_pos = Position.objects.get(position_stu=NaturalPerson.objects.get(pid=username))
        user_org = user_pos.from_organization
    except:
        redirect('/index/')
    ##user_pos.job = 部员
    ##user_pos.from_organization = <organization对象>
    ##<organization对象>.oname = 共青团北京大学元培学院委员会
    ##<organization对象>.department = 团委宣传部
    ##解释性语言##

    
    if request.user.is_authenticated:
        try:
            username = request.session['username']
            userinfo = NaturalPerson.objects.filter(pid=username).values()[0]
            useroj = NaturalPerson.objects.get(pid=username)
            isFirst = useroj.firstTimeLogin
            #未修改密码
            if isFirst:
                return redirect('/modpw/')
            ava = useroj.avatar
            ava_path = ''
            if str(ava) == '':
                ava_path = settings.MEDIA_URL + 'avatar/codecat.jpg' 
            else:
                ava_path = settings.MEDIA_URL + str(ava)
            return render(request,'indexinfo.html',locals())
        except:
            auth.logout(request)
            return redirect('/index')
    else:
        return redirect('/index')

def account_setting(request):
    undergroundurl = underground_url
    if request.user.is_authenticated:
        username = request.session['username']
        info = NaturalPerson.objects.filter(username=username)
        userinfo = info.values()[0]
        useroj = NaturalPerson.objects.get(pno=username)
        if str(useroj.avatar) == '' :
            former_img = settings.MEDIA_URL + 'avatar/codecat.jpg' 
        else:
            former_img = settings.MEDIA_URL + str(useroj.avatar)
        
        if request.method == 'POST' and request.POST:
            aboutbio = request.POST['aboutBio']
            tel = request.POST['tel']
            email = request.POST['email']
            Major = request.POST['major']
            ava =  request.FILES.get('avatar')
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
                return render(request,'user_account_setting.html',locals())
            
            else:
                upload_state = True
                return redirect("/stuinfo/?modinfo=success")
        return render(request,'user_account_setting.html',locals())

def register(request):
    if request.user.is_superuser:
        if request.method == 'POST' and request.POST:
            name = request.POST['name']
            password = request.POST['password']
            pno = request.POST['snum']
            email = request.POST['email']
            password2 = request.POST['password2']
            pyear = request.POST['pyear']
            pgender = request.POST['pgender']
            if password != password2:
                render(request,'index.html')
            else:
                #user with same pno
                same_user = NaturalPerson.objects.filter(pno=pno)
                if same_user:
                    render(request,'auth_register_boxed.html')
                same_email = NaturalPerson.objects.filter(pemail=email)
                if same_email:
                    render(request,'auth_register_boxed.html')
                
                #OK!
                user = User.objects.create(username=pno)
                user.set_password(password)
                user.save()
                new_user = NaturalPerson.objects.create(pno=pno,username=user)
                new_user.pemail = email
                new_user.pyear = pyear
                new_user.pgender = pgender
                new_user.pname = name
                new_user.save()
                return HttpResponseRedirect('/index/')
        return render(request,'auth_register_boxed.html')
    else:
        return HttpResponseRedirect('/index/')

def logout(request):
    auth.logout(request)
    return HttpResponseRedirect('/index/')

def org_spec(request,*args, **kwargs):
    arg = args[0]
    org_dict = local_dict['org']
    title = org_dict[arg]
    org = Organization.objects.filter(oname=title)
    #department = org.department
    pos = Position.objects.filter(Q(from_organization=org) | Q(job='部长') | Q(job='老板'))
    try:
        pos = Position.objects.filter(Q(from_organization=org) | Q(job='部长') | Q(job='老板'))
        boss_no = pos.values()[0]['position_stu_id']
        boss = NaturalPerson.objects.get(pno=boss_no).pname
        job = pos.values()[0]['job']
    except:
        person_incharge = '负责人'
    return render(request,'org_spec.html',locals())

def get_stu_img(request):
    print("in get stu img")
    stuId = request.GET.get('stuId')
    if stuId is not None:
        try:
            print(stuId)
            img_path = NaturalPerson.objects.get(pno=stuId).avatar
            if str(img_path) == '':
                img_path = settings.MEDIA_URL + 'avatar/codecat.jpg'
            else:
                img_path = settings.MEDIA_URL  +str(img_path)
            print(img_path)
            return JsonResponse({'path':img_path}, status=200)
        except:
            return JsonResponse({'message':"Image not found!"},status=404)
    return JsonResponse({'message':'User not found!'},status=404)



def search(request):
    undergroundurl = underground_url
    query = request.GET.get('Query')
    stu_list = NaturalPerson.objects.filter(Q(pno__icontains=query) | Q(pname__icontains=query))
    return render(request,'search.html',locals())
    

def test(request):
    request.session['cookies'] = 'hello, i m still here.'
    return render(request,'all_org.html')
def modpw(request):
    err_code = 0
    err_message = None
    if request.user.is_authenticated:
        isFirst = NaturalPerson.objects.get(pno=request.session['username']).firstTimeLogin
        username = request.session['username']  # added by wxy
        useroj = NaturalPerson.objects.get(pno=username)
        if str(useroj.avatar) == '' :
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
                userauth = auth.authenticate(username=username,password=oldpassword)
                if userauth:
                    user = User.objects.get(username=username)
                    if user:
                        user.set_password(newpw)
                        user.save()
                        stu = NaturalPerson.objects.filter(username=username)
                        stu.update(firstTimeLogin=False)

                        urls = reverse("index") + "?success=yes"
                        return redirect(urls)
                    else:
                        err_code = 3
                        err_message = "学号不存在"
                else:
                    err_code = 4
                    err_message = "原始密码不正确"
        return render(request,'modpw.html',locals())
    else:
        return redirect('/index/')

def load_data(request):
    if request.user.is_superuser:
        df_1819 = load()
        for i in range(len(df_1819)): #import 2018 stu info.
            username = str(df_1819['学号'].iloc[i])
            pno = username
            password = pno
            email = df_1819['邮箱'].iloc[i]
            if email == 'None':
                if pno[0] == '2':
                    email = pno + '@stu.pku.edu.cn'
                else:
                    email = pno + '@pku.edu.cn'
            tel = str(df_1819['手机号'].iloc[i])
            year = '20' + pno[0:2]
            gender = df_1819['性别'].iloc[i]
            major = df_1819['专业'].iloc[i]
            name = df_1819['姓名'].iloc[i]
            pclass = df_1819['班级'].iloc[i]
            user = User.objects.create(username=username)
            user.set_password(password)
            user.save()
            stu = NaturalPerson.objects.create(pid=pno)
            #stu = NaturalPerson.objects.create(pid=pno,username=user)
            stu.pemail = email
            stu.ptel = tel
            stu.pyear = year
            stu.pgender = gender
            stu.pmajor = major
            stu.pname = name
            stu.pclass = pclass
            stu.save()
        return render(request,'debugging.html')
