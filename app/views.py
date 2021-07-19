from django.shortcuts import render, redirect
from app.models import NaturalPerson, OrganizationType, Position, Organization
from django.contrib import auth, messages
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from app.forms import UserForm
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from app.data_import import load
from django.contrib.auth.hashers import make_password, check_password
from django.db.models import Q
from app.utils import MyMD5PasswordHasher, MySHA256Hasher
from  boottest import local_dict
import app.utils as utils
from django.conf import settings
from django.urls import reverse
import json
from datetime import datetime
import time
import random, requests   # 发送验证码


email_url = local_dict['url']['email_url']
hash_coder = MySHA256Hasher(local_dict['hash']['base_hasher'])
email_coder = MySHA256Hasher(local_dict['hash']['email'])


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
            return redirect('/welcome/')
            '''
            valid, user_type , html_display = utils.check_user_type(request)
            if not valid:
                return render(request, 'index.html', locals())
            return redirect('/stuinfo') if user_type == "Person" else redirect('/orginfo')
            '''
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
                # 加时间戳
                # 以及可以判断一下 arg_origin 在哪
                # 看看是不是 '/' 开头就行
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
                return redirect('/welcome/')
                '''
                valid, user_type , html_display = utils.check_user_type(request)
                if not valid:
                    return render(request, 'index.html', locals())
                return redirect('/stuinfo') if user_type == "Person" else redirect('/orginfo')
                '''
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
def stuinfo(request, name = None):
    '''
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
    '''
    
    try:
        user = request.user
        valid, user_type, html_display = utils.check_user_type(request)
        if not valid:
            return redirect('/logout/')

        if name is None:
            if user_type == 'Organization':
                return redirect('/welcome/')
            else:
                assert(user_type == 'Person')
                try:
                    oneself = NaturalPerson.objects.activated().get(pid=user)
                except:
                    return redirect('/welcome/')
                return redirect('/stuinfo/' + oneself.pname)
        else:
            # 先对可能的加号做处理
            name_list = name.split("+")
            name = name_list[0]
            person = NaturalPerson.objects.activated().filter(pname=name)
            if len(person) == 0:            # 查无此人
                return redirect('/welcome/')
            if len(person) == 1:        # 无重名
                person = person[0]
            else:                       # 有很多人，这时候假设加号后面的是user的id
                if len(name_list) == 1: # 没有任何后缀信息，那么如果是自己则跳转主页，否则跳转搜索
                    if user_type == 'Person' and NaturalPerson.objects.activated().get(pid=user).pname == name:
                        person = NaturalPerson.objects.activated().get(pid=user)
                    else:               # 不是自己，信息不全跳转搜索
                        return redirect('/search?Query=' + name)        
                else:
                    obtain_id = int(name_list[1])                       # 获取增补信息
                    get_user = User.objects.get(id=obtain_id)
                    potential_person = NaturalPerson.objects.activated().get(pid=get_user)
                    assert potential_person in person
                    person = potential_person

            modpw_status = request.GET.get('modinfo', None)

            is_myself = user_type == 'Person' and person.pid == user    # 用一个字段储存是否是自己
            is_first = person.firstTimeLogin                            # 是否为第一次登陆
            html_display['is_myself'] = is_myself                       # 存入显示
            if is_myself and is_first:
                return redirect('/modpw/')

            # 处理被搜索人的信息，这里应该和“用户自己”区分开
            join_pos_id_list = Position.objects.activated().filter(person=person)
            #html_display['join_org_list'] = Organization.objects.filter(org__in = join_pos_id_list.values('org'))               # 我属于的组织
            
            # 呈现信息
            # 首先是左边栏
            html_display = utils.get_user_left_narbar(person, is_myself, html_display)

            html_display['modpw_code'] = modpw_status is not None and modpw_status == 'success'
            html_display['warn_code'] = request.GET.get('warn_code', 0)             # 是否有来自外部的消息
            html_display['warn_message'] = request.GET.get('warn_message', "")      # 提醒的具体内容 
            html_display['userinfo'] = person
            
            html_display['title_name'] = 'User Profile'
            html_display['narbar_name'] = '个人主页'
            
            return render(request, 'stuinfo.html', locals())
    except:
        auth.logout(request)
        return redirect('/index/')



@login_required(redirect_field_name='origin')
def request_login_org(request, name=None):  # 特指个人希望通过个人账户登入组织账户的逻辑
    '''
        这个函数的逻辑是，个人账户点击左侧的管理组织直接跳转登录到组织账户
        首先检查登录的user是个人账户，否则直接跳转orginfo
        如果个人账户对应的是name对应的组织的最高权限人，那么允许登录，否则跳转回stuinfo并warning
    '''
    user = request.user
    valid, user_type, html_display = utils.check_user_type(request)
    if not valid:
        return redirect('/logout/')
    if user_type == "Organization":
        return redirect('/orginfo/')
    try:
        me = NaturalPerson.objects.activated().get(pid=user)
    except:  # 找不到合法的用户
        return redirect('/welcome/')
    if name is None:  # 个人登录未指定登入组织,属于不合法行为,弹回欢迎
        return redirect('/welcome/')
    else:   # 确认有无这个组织
        try:
            org = Organization.objects.get(oname=name)
        except:  # 找不到对应组织
            urls = '/stuinfo/'+me.pname+"?warn_code=1&warn_message=找不到对应组织,请联系管理员!"
            return redirect(urls)
        try:
            position = Position.objects.activated().filter(org=org, person=me)
            assert len(position) == 1
            position = position[0]
            assert position.pos == 0
        except:
            urls = '/stuinfo/'+me.pname+"?warn_code=1&warn_message=没有登录到该组织账户的权限!"
            return redirect(urls)
        # 到这里,是本人组织并且有权限登录
        auth.logout(request)
        auth.login(request, org.oid)  # 切换到组织账号
        return redirect('/orginfo/')


@login_required(redirect_field_name='origin')
def orginfo(request,name = None): 
    '''
        orginfo负责呈现组织主页，逻辑和stuinfo是一样的，可以参考
        只区分自然人和法人，不区分自然人里的负责人和非负责人。任何自然人看这个组织界面都是【不可管理/编辑组织信息】
    '''
    user = request.user
    valid, user_type, html_display = utils.check_user_type(request)
    me = NaturalPerson.objects.activated().get(pid = user) if user_type == 'Person' else Organization.objects.get(oid=user)
    
    if not valid:
        return redirect('/logout/')
    if name is None: # 此时登陆的必需是法人账号，如果是自然人，则跳转welcome
        if user_type == 'Person':
            return redirect('/welcome/')
        try:
            org = Organization.objects.activated().get(oid=user)
        except:
            return redirect('/welcome/')
        return redirect('/orginfo/' + org.oname)

    try: # 指定名字访问组织账号的，可以是自然人也可以是法人。在html里要注意区分！

        # 下面是组织信息
        org = Organization.objects.activated().get(oname=name)
        organization_name = name
        organization_type_name = OrganizationType.objects.get(otype_id = org.otype_id_id).otype_name
        # org的属性 YQPoint 和 information 不在此赘述，直接在前端调用

        # 这一部分是负责人boss的信息
        boss = Position.objects.activated().get(org = org, pos = 0).person
        #boss = NaturalPerson.objects.activated().get(pid = bossid)
        boss_display = {}

        boss_display['bossname'] = boss.pname
        boss_display['year'] = boss.pyear
        boss_display['major'] = boss.pmajor
        boss_display['email'] = boss.pemail
        boss_display['tel'] = boss.ptel

        jobpos = Position.objects.activated().get(person = boss).pos
        boss_display['job'] = OrganizationType.objects.get(otype_id = org.otype_id_id).ojob_name_list[jobpos]

        # 判断是否是负责人，如果是，在html的sidebar里要加上一个【切换账号】的按钮
        ISBOSS = True if (user_type == 'Person' and boss.pid == user) else False 

        # 组织活动的信息

    except:
        return redirect('/welcome/')

    # 补充一些呈现信息
    html_display['title_name'] = 'Org. Profile'
    html_display['narbar_name'] = '组织主页'

    return render(request, 'orginfo.html', locals())


@login_required(redirect_field_name='origin')
def homepage(request):
    
    valid, user_type, html_display = utils.check_user_type(request) 
    is_person = True if user_type == 'Person' else False 
    if not valid:
        return redirect('/logout/') 
    me = NaturalPerson.objects.get(
        pid=request.user) if is_person else Organization.objects.get(oid=request.user) #
    myname = me.pname if is_person else me.oname 
    # 直接储存在html_display中
    #profile_name = "个人主页" if is_person else "组织主页"
    #profile_url = "/stuinfo/" + myname if is_person else "/orginfo/" + myname

    # 补充一些呈现信息
    html_display['title_name'] = 'Welcome Page'
    html_display['narbar_name'] = '近期要闻' 
    return render(request, 'welcome_page.html', locals())


@login_required(redirect_field_name='origin')
def account_setting(request):
    valid, user_type, html_display = utils.check_user_type(request)
    if not valid:
        return redirect('/logout/')
    
    # 在这个页面 默认回归为自己的左边栏
    html_display['is_myself'] = True
    user = request.user
    info = NaturalPerson.objects.filter(pid=user)
    userinfo = info.values()[0]

    useroj = NaturalPerson.objects.get(pid=user)

    former_img = html_display['avatar_path']

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
        avatar_path = settings.MEDIA_URL + str(ava)
        if expr == False:
            return render(request, 'user_account_setting.html', locals())

        else:
            upload_state = True
            return redirect("/stuinfo/?modinfo=success")
    
    # 补充网页呈现所需信息
    html_display['title_name'] = 'Account Setting'
    html_display['narbar_name'] = '账户设置'

    #然后是左边栏
    html_display = utils.get_user_left_narbar(useroj, html_display['is_myself'], html_display)


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
                new_user.pyear = pyear
                new_user.save()
                return HttpResponseRedirect('/index/')
        return render(request, 'auth_register_boxed.html')
    else:
        return HttpResponseRedirect('/index/')


# @login_required(redirect_field_name=None)
def logout(request):
    auth.logout(request)
    return HttpResponseRedirect('/index/')


'''
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
'''


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
    '''
        搜索界面的呈现逻辑
        分成搜索个人和搜索组织两个模块，每个模块的呈现独立开，有内容才呈现，否则不显示
        搜索个人：
            支持使用姓名搜索，支持对未设为不可见的昵称和专业搜索
            搜索结果的呈现采用内容/未公开表示，所有列表为people_filed
        搜索组织
            支持使用组织名、组织类型搜索、一级负责人姓名
            组织的呈现内容由拓展表体现，不在这个界面呈现具体成员
    '''
    try:
        valid, user_type, html_display = utils.check_user_type(request)
        if not valid:
            return redirect('/logout/')

        is_person = True if user_type == 'Person' else False
        me = NaturalPerson.objects.get(pid=request.user) if is_person else\
            Organization.objects.get(oid=request.user) # 
        html_display['is_myself'] = True
        if is_person:
            html_display = utils.get_user_left_narbar(me, html_display['is_myself'], html_display)
        else:
            html_display = utils.get_org_left_narbar(me, html_display['is_myself'], html_display)

        query = request.GET.get('Query', '')
        if query == '':
            return redirect('/welcome/')

        # 首先搜索个人
        people_list = NaturalPerson.objects.filter(
            Q(pname__icontains=query) | (Q(pnickname__icontains=query)) | (Q(pmajor__icontains = query)))

        # 接下来准备呈现的内容

        # 首先是准备搜索个人信息的部分
        people_field = ['姓名', '年级&班级', '昵称', '性别', '专业', '邮箱', '电话', '宿舍', '状态']

        return render(request, 'search.html', locals())
    except:
        auth.logout(request)
        return redirect('/index/')




def test(request):
    request.session['cookies'] = 'hello, i m still here.'
    return render(request, 'all_org.html')


def forget_password(request):
    '''
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
    '''
    if request.method == 'POST':
        username = request.POST['username']
        send_captcha = request.POST['send_captcha'] == 'yes'
        vertify_code = request.POST['vertify_code'] # 用户输入的验证码
        
        user = User.objects.filter(username=username)
        if not user:
            err_code = 1
            err_message = '账号不存在'
        else:
            user = User.objects.get(username=username)
            useroj = NaturalPerson.objects.get(pid=user) # 目前似乎保证是自然人
            isFirst = useroj.firstTimeLogin
            if isFirst:  
                err_code = 2
                err_message = '初次登录密码与账号相同！'
            elif send_captcha:
                email = useroj.pemail
                if not email or email.lower() == 'none' or '@' not in email:
                    err_code = 3
                    err_message = '您没有设置邮箱，请发送姓名、学号和常用邮箱至gypjwb@pku.edu.cn进行修改'# 记得填
                else:
                    captcha = random.randrange(1000000) # randint包含端点，randrange不包含
                    captcha = f'{captcha:06}'
                    msg = (
                    f'<h3><b>亲爱的{useroj.pname}同学：</b></h3><br/>'
                    '您好！您的账号正在进行邮箱验证，本次请求的验证码为：<br/>'
                    f'<p style="color:orange">{captcha}'
                    '<span style="color:gray">(仅当前页面有效)</span></p>'
                    '点击进入<a href="https://yppf.yuanpei.life">元培成长档案</a><br/>'
                    '<br/><br/><br/>'
                    '元培学院开发组<br/>'
                    + datetime.now().strftime('%Y年%m月%d日'))
                    post_data = {
                        'toaddrs' : [email],    # 收件人列表
                        'subject' : 'YPPF登录验证',        # 邮件主题/标题
                        'content' : msg,    # 邮件内容
                            # 若subject为空, 第一个\n视为标题和内容的分隔符
                        'html' : True,          # 可选 如果为真则content被解读为html
                        'private_level' : 0,    # 可选 应在0-2之间
                            # 影响显示的收件人信息
                            # 0级全部显示, 1级只显示第一个收件人, 2级只显示发件人
                        'secret' : email_coder.encode(msg), # content加密后的密文
                    }
                    post_data = json.dumps(post_data)
                    pre, suf = email.rsplit('@', 1)
                    if len(pre) > 5:
                        pre = pre[:2] + '*' * len(pre[2:-3]) + pre[-3:]
                    try:
                        response = requests.post(email_url, post_data, timeout=6)
                        response = response.json()
                        if response['status'] != 200:
                            err_code = 4
                            err_message = f'未能向{pre}@{suf}发送邮件'
                        else:  
                            # 记录验证码发给谁 不使用username防止被修改
                            request.session['received_user'] = username
                            request.session['captcha'] = captcha
                            err_code = 0
                            err_message = f'验证码已发送至{pre}@{suf}'
                    except:
                        err_code = 4
                        err_message = '邮件发送失败：超时'
            else:
                captcha = request.session.get('captcha', '')
                received_user = request.session.get('received_user', '')
                if len(captcha) != 6 or username != received_user:
                    err_code = 5
                    err_message = '请先发送验证码'
                elif vertify_code.upper() == captcha.upper():
                    auth.login(request, user)
                    request.session.pop('captcha')
                    request.session['username'] = username
                    request.session['forgetpw'] = 'yes'
                    return redirect(reverse('modpw'))
                else:
                    err_code = 6
                    err_message = "验证码不正确"
    return render(request, 'forget_password.html', locals())


@login_required(redirect_field_name='origin')
def modpw(request):
    err_code = 0
    err_message = None
    forgetpw = request.session.get('forgetpw', '') == 'yes'   # added by pht
    username = request.session['username']  # added by wxy
    user = User.objects.get(username=username)
    useroj = NaturalPerson.objects.get(pid=user)
    isFirst = useroj.firstTimeLogin
    if str(useroj.avatar) == '':
        avatar_path = settings.MEDIA_URL + 'avatar/codecat.jpg'
    else:
        avatar_path = settings.MEDIA_URL + str(useroj.avatar)
    if request.method == 'POST' and request.POST:
        oldpassword = request.POST['pw']
        newpw = request.POST['new']
        username = request.session['username']
        strict_check = False
        
        if oldpassword == newpw and strict_check and not forgetpw:   # modified by pht
            err_code = 1
            err_message = "新密码不能与原密码相同"
        elif newpw == username and strict_check:
            err_code = 2
            err_message = "新密码不能与学号相同"
        elif newpw != oldpassword and forgetpw:    # added by pht
            err_code = 5
            err_message = "两次输入的密码不匹配"
        else:
            userauth = auth.authenticate(
                username=username, password=oldpassword)
            if forgetpw:    # added by pht: 这是不好的写法，可改进
                userauth = True
            if userauth:
                try:    # modified by pht: if检查是错误的，不存在时get会报错
                    user = User.objects.get(username=username)
                    user.set_password(newpw)
                    user.save()
                    stu = NaturalPerson.objects.filter(pid=user)
                    stu.update(firstTimeLogin=False)

                    if forgetpw:
                        request.session.pop('forgetpw') # 删除session记录

                    urls = reverse("index") + "?success=yes"
                    return redirect(urls)
                except: # modified by pht: 之前使用的if检查是错误的
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
            stu.pyear = year
            stu.pgender = gender
            stu.pmajor = major
            stu.pname = name
            stu.pclass = pclass
            stu.save()
        return render(request, 'debugging.html')
