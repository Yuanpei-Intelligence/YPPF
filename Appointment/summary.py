import os
import json
from datetime import datetime

from django.http import HttpRequest
from django.shortcuts import render, redirect
from django.urls import reverse

from Appointment.models import Room
from Appointment.utils.identity import identity_check


@identity_check(redirect_field_name='origin')
def summary(request):  # 主页
    Pid = ""

    try:
        if not Pid:
            Pid = request.user.username
        with open(f'Appointment/summary_info/{Pid}.txt', 'r', encoding='utf-8') as fp:
            myinfo = json.load(fp)
    except:
        return redirect(reverse("Appointment:logout"))

    Rid_list = {room.Rid: room.Rtitle.split(
        '(')[0] for room in Room.objects.all()}

    # page 0
    Sname = myinfo['Sname']

    # page 1
    all_appoint_num = 12649
    all_appoint_len = 19268.17
    all_appoint_len_day = round(all_appoint_len/24)

    # page 2
    appoint_make_num = int(myinfo['appoint_make_num'])
    appoint_make_num_pct = myinfo['rank_num']
    appoint_make_hour = round(myinfo['appoint_make_hour'], 2)
    appoint_make_hour_pct = myinfo['rank_hour']
    appoint_attend_num = int(myinfo['appoint_attend_num'])
    appoint_attend_hour = round(myinfo['appoint_attend_hour'], 2)

    # page 3
    hottest_room_1 = ['B214', Rid_list['B214'], 1952]
    hottest_room_2 = ['B220', Rid_list['B220'], 1715]
    hottest_room_3 = ['B221', Rid_list['B221'], 1661]

    # page 4
    Sfav_room_id = myinfo['favourite_room_id']
    if Sfav_room_id:
        Sfav_room_name = Rid_list[Sfav_room_id]
        Sfav_room_freq = int(myinfo['favourite_room_freq'])

    # page 5
    Smake_time_most = myinfo['make_time_most']
    if Smake_time_most:
        Smake_time_most = int(Smake_time_most)

    try:
        Suse_time_list = myinfo['use_time_list'].split(';')
    except:
        Suse_time_list = [0]*24
    Suse_time_list = list(map(lambda x: int(x), Suse_time_list))
    try:
        Suse_time_most = Suse_time_list.index(max(Suse_time_list))
    except:
        Suse_time_most = -1
    Suse_time_list_js = json.dumps(Suse_time_list[6:])
    Suse_time_list_label = [str(i) for i in range(6, 24)]
    Suse_time_list_label_js = json.dumps(Suse_time_list_label)

    # page 6
    Sfirst_appoint = myinfo['first_appoint']
    if Sfirst_appoint:
        Sfirst_appoint = Sfirst_appoint.split('|')
        Sfirst_appoint.append(Rid_list[Sfirst_appoint[4]])

    # page 7
    Skeywords = myinfo['usage']
    if Skeywords:
        Skeywords = Skeywords.split('|')
        Skeywords_for_len = Skeywords.copy()
        if '' in Skeywords_for_len:
            Skeywords_for_len.remove('')
        Skeywords_len = len(Skeywords_for_len)
    else:
        Skeywords_len = 0

    # page 8
    Sfriend = myinfo['friend']
    if Sfriend == '':
        Sfriend = None
    if Sfriend:
        Sfriend = Sfriend.split(';')

    # page 9 熬夜冠军
    aygj = myinfo['aygj']
    if aygj:
        aygj = aygj.split('|')
        aygj_num = 80

    # page 10 早起冠军
    zqgj = myinfo['zqgj']
    if zqgj:
        zqgj = zqgj.split('|')
        # print(zqgj)
        zqgj.insert(6, Rid_list[zqgj[5]])
        zqgj_num = 109

    # page 11 未雨绸缪
    wycm = myinfo['wycm']
    wycm_num = 44

    # page 12 极限操作
    jxcz = myinfo['jxcz']
    if jxcz:
        jxcz = jxcz.split('|')
        jxcz.insert(6, Rid_list[jxcz[5]])
        jxcz_num = 102

    # page 13 元培鸽王
    ypgw = myinfo['ypgw']
    ypgw_num = 22

    # page 14 新功能预告
    return render(request, 'Appointment/summary.html', locals())


def summary2021(request: HttpRequest):
    # 年度总结
    from dm.summary import generic_info, person_info

    base_dir = 'test_data'

    logged_in = request.user.is_authenticated
    if logged_in:
        username = request.session.get("NP", "")
        if username:
            from app.utils import update_related_account_in_session
            update_related_account_in_session(request, username, shift=True)

    is_freshman = request.user.username.startswith('22')
    user_accept = request.GET.get('accept') == 'true'
    infos = generic_info()
    infos.update(
        logged_in=logged_in,
        is_freshman=is_freshman,
        user_accept=user_accept,
    )

    if user_accept and logged_in and not is_freshman:
        try:
            infos.update(person_info(request.user))
            with open(os.path.join(base_dir, 'rank_info.json')) as f:
                rank_info = json.load(f)
                sid = request.user.username
                for k in ['co_pct', 'func_appoint_pct', 'discuss_appoint_pct']:
                    infos[k] = rank_info[k].index(
                        sid) * 100 // len(rank_info[k])
        except:
            pass
    else:
        try:
            example_file = os.path.join(base_dir, 'example.json')
            with open(example_file) as f:
                infos.update(json.load(f))
        except:
            pass

    return render(request, 'Appointment/summary2021.html', infos)


def summary2023(request: HttpRequest):
    # 2023年度总结
    base_dir = 'static/Appointment/assets/summary_data/summary2023'

    logged_in = request.user.is_authenticated
    if logged_in:
        username = request.session.get("NP", "")
        if username:
            from app.utils import update_related_account_in_session
            update_related_account_in_session(request, username, shift=True)

    user_accept = request.GET.get('accept') == 'true'
    user_cancel = request.GET.get('cancel') == 'true'
    infos = {}

    infos.update(logged_in=logged_in, user_accept=user_accept, user_cancel=user_cancel)

    if not user_accept or not logged_in or user_cancel:
        # 新生/不接受协议/未登录 展示样例
        example_file = os.path.join(base_dir, 'template.json')
        with open(example_file) as f:
            infos.update(json.load(f))
        if logged_in:
            with open(os.path.join(base_dir, 'summary2023.json'), 'r') as f:
                infos.update(home_Sname=json.load(f)[request.user.username].get('Sname', ''))
    else:
        # 读取年度总结中该用户的个人数据
        with open(os.path.join(base_dir, 'summary2023.json'), 'r') as f:
            infos.update(json.load(f)[request.user.username])

        infos.update(home_Sname = infos['Sname'])

        # 读取年度总结中该用户的排名数据
        with open(os.path.join(base_dir, 'rank2023.json'), 'r') as f:
            infos.update(json.load(f)[request.user.username])

    # 读取年度总结中所有用户的总体数据
    with open(os.path.join(base_dir, 'summary_overall_2023.json'), 'r') as f:
        infos.update(json.load(f))

    # 将数据中缺少的项利用white-template中的默认值补齐
    with open(os.path.join(base_dir, 'white-template.json'), 'r') as f:
        white_template = json.load(f)
        for key, value in white_template.items():
            if key not in infos.keys():
                infos[key] = value

    # 计算用户自注册起至今过去的天数
    _date_joint = datetime.fromisoformat(infos['date_joined'])
    _date_now = datetime.now()
    days_passed = (_date_now - _date_joint).days
    infos.update(days_passed=days_passed)

    # 处理导出的最常预约研讨室/功能室的数据格式是单元素list的情况
    Function_appoint_most_room = infos.get('Function_appoint_most_room')
    if Function_appoint_most_room is not None:
        if isinstance(Function_appoint_most_room, list):
            if Function_appoint_most_room:
                infos['Function_appoint_most_room'] = Function_appoint_most_room[0]
            else:
                infos['Function_appoint_most_room'] = ''

    Discuss_appoint_most_room = infos.get('Discuss_appoint_most_room')
    if Discuss_appoint_most_room is not None:
        if isinstance(Discuss_appoint_most_room, list):
            if Discuss_appoint_most_room:
                infos['Discuss_appoint_most_room'] = Discuss_appoint_most_room[0]
            else:
                infos['Discuss_appoint_most_room'] = ''

    # 将导出数据中iosformat的日期转化为只包含年、月、日的文字
    if infos.get('Discuss_appoint_longest_day'): # None or ''
        Discuss_appoint_longest_day = datetime.fromisoformat(infos['Discuss_appoint_longest_day'])
        infos['Discuss_appoint_longest_day'] = Discuss_appoint_longest_day.strftime("%Y年%m月%d日")
    if infos.get('Function_appoint_longest_day'):
        Function_appoint_longest_day = datetime.fromisoformat(infos['Function_appoint_longest_day'])
        infos['Function_appoint_longest_day'] = Function_appoint_longest_day.strftime("%Y年%m月%d日")

    # 对最长研讨室/功能室预约的小时数向下取整
    if infos.get('Discuss_appoint_longest_duration'):
        Discuss_appoint_longest_day_hours = infos['Discuss_appoint_longest_duration'].split('小时')[0]
        infos.update(Discuss_appoint_longest_day_hours = Discuss_appoint_longest_day_hours)
    else:
        infos.update(Discuss_appoint_longest_day_hours = 0)

    if infos.get('Function_appoint_longest_duration'):
        Function_appoint_longest_day_hours = infos['Function_appoint_longest_duration'].split('小时')[0]
        infos.update(Function_appoint_longest_day_hours = Function_appoint_longest_day_hours)
    else:
        infos.update(Function_appoint_longest_day_hours = 0)

    # 处理导出共同预约关键词数据格式为[co_keyword, appear_num]的情况
    if infos.get('co_keyword'):
        if isinstance(infos.get('co_keyword'), list):
            if infos['co_keyword']:
                co_keyword, num = infos['co_keyword']
                infos['co_keyword'] = co_keyword
            else:
                infos['co_keyword'] = ''

    # 将list格式的top3最热门课程转化为一个字符串
    hottest_courses_23_fall_dict = infos['hottest_courses_23_Fall']
    hottest_course_names_23_fall = '\n'.join([list(dic.keys())[0] for dic in hottest_courses_23_fall_dict])
    infos.update(hottest_course_names_23_fall=hottest_course_names_23_fall)
    hottest_courses_23_spring_dict = infos['hottest_courses_23_Spring']
    hottest_course_names_23_spring = '\n'.join([list(dic.keys())[0] for dic in hottest_courses_23_spring_dict])
    infos.update(hottest_course_names_23_spring=hottest_course_names_23_spring)

    # 根据最长连续签到天数授予用户称号
    max_consecutive_days = infos.get('max_consecutive_days')
    if max_consecutive_days is not None:
        if max_consecutive_days <= 3:
            infos.update(consecutive_days_name='初探新世界')
        elif max_consecutive_days <= 7:
            infos.update(consecutive_days_name='到此一游')
        elif max_consecutive_days <= 15:
            infos.update(consecutive_days_name='常住居民')
        else:
            infos.update(consecutive_days_name='永恒真爱粉')
    else:
        infos.update(consecutive_days_name='')

    # 处理用户创建学生小组过多的情况
    if infos.get('myclub_name'):
        myclub_name_list = infos['myclub_name'].split('，')
        if len(myclub_name_list) > 3:
            myclub_name_list = myclub_name_list[:3]
            infos.update(myclub_name='，'.join(myclub_name_list) + '等')

    # 处理用户担任admin职务的小组数过多的情况
    if infos.get('admin_org_names'):
        admin_org_names = infos['admin_org_names']
        if len(admin_org_names) > 3:
            admin_org_names = admin_org_names[:3]
            infos.update(admin_org_names_str='，'.join(admin_org_names) + '等')
        else:
            infos.update(admin_org_names_str='，'.join(admin_org_names))
    else:
         infos.update(admin_org_names_str='')

    # 将小组活动预约top3关键词由list转为一个string
    if infos.get('act_top_three_keywords'):
        act_top_three_keywords = infos['act_top_three_keywords']
        infos.update(act_top_three_keywords_str='，'.join(act_top_three_keywords))
    else:
        infos.update(act_top_three_keywords_str='')

    # 根据参加小组活动最频繁时间段授予用户称号
    most_act_common_hour = infos.get('most_act_common_hour')
    if most_act_common_hour is not None:
        if most_act_common_hour <= 10:
            infos.update(most_act_common_hour_name='用相聚开启元气满满的一天')
        elif most_act_common_hour <= 13:
            infos.update(most_act_common_hour_name='不如再用一顿美食为这次相聚做个注脚')
        elif most_act_common_hour <= 16:
            infos.update(most_act_common_hour_name='突击检查，瞌睡虫有没有出现？')
        elif most_act_common_hour <= 18:
            infos.update(most_act_common_hour_name='此刻的欢畅还有落霞余晖作伴')
        elif most_act_common_hour <= 23:
            infos.update(most_act_common_hour_name='夜色深沉时，每一个细胞都在期待着相约相聚')
        else:
            infos.update(most_act_common_hour_name='让星月陪我们狂歌竞夜')
    else:
        infos.update(most_act_common_hour_name='')

    # 计算参与的学生小组+书院课程小组数
    infos.update(club_course_num=infos.get('club_num', 0)+infos.get('course_org_num', 0))

    # 根据已选修书院课程种类数授予成就
    type_count = infos.get('type_count', 0)
    if type_count == 5:
        infos.update(type_count_name='五边形战士')
    elif type_count >= 2:
        infos.update(type_count_name='广泛涉猎')
    elif type_count == 1:
        infos.update(type_count_name='垂直深耕')
    else:
        infos.update(type_count_name='你先别急')

    # 计算2023年两学期平均书院课程预选数和选中数
    avg_preelect_num = (infos['preelect_course_23fall_num'] + infos['preelect_course_23spring_num']) / 2
    avg_elected_num = (infos['elected_course_23fall_num'] + infos['elected_course_23spring_num']) / 2
    infos.update(avg_preelect_num=avg_preelect_num, avg_elected_num=avg_elected_num)

    # 根据盲盒中奖率授予成就
    mystery_boxes_num = infos['mystery_boxes_num']
    # 处理导出数据中的typo
    if 'lukcy_mystery_boxes_num' in infos.keys():
        lucky_mystery_boxes_num = infos.pop('lukcy_mystery_boxes_num')
        infos.update(lucky_mystery_boxes_num=lucky_mystery_boxes_num)
    lucky_mystery_boxes_num = infos['lucky_mystery_boxes_num']
    # 防止除零错误
    if (lucky_mystery_boxes_num != 0):
        lucky_rate = mystery_boxes_num / lucky_mystery_boxes_num
        if lucky_rate >= 0.5:
            infos.update(mystery_boxes_name='恭迎欧皇加冕')
        else:
            infos.update(mystery_boxes_name='发出尖锐爆鸣的非酋')
    else:
        infos.update(mystery_boxes_name='')

    return render(request, 'Appointment/summary2023.html', infos)


def summary2024(request: HttpRequest):
    # 2024年度总结
    base_dir = 'static/Appointment/assets/summary_data/summary2024'

    logged_in = request.user.is_authenticated
    if logged_in:
        username = request.session.get("NP", "")
        if username:
            from app.utils import update_related_account_in_session
            update_related_account_in_session(request, username, shift=True)

    user_accept = request.GET.get('accept') == 'true'
    user_cancel = request.GET.get('cancel') == 'true'
    infos = {}

    infos.update(logged_in=logged_in, user_accept=user_accept, user_cancel=user_cancel)

    if not user_accept or not logged_in or user_cancel:
        # 新生/不接受协议/未登录 展示样例
        example_file = os.path.join(base_dir, 'template.json')
        with open(example_file ,encoding='utf-8') as f:
            infos.update(json.load(f))
        if logged_in:
            with open(os.path.join(base_dir, 'summary2024.json'), 'r', encoding='utf-8') as f:
                infos.update(home_Sname=json.load(f)[request.user.username].get('Sname', ''))
    else:
        # 读取年度总结中该用户的个人数据
        with open(os.path.join(base_dir, 'summary2024.json'), 'r', encoding='utf-8') as f:
            infos.update(json.load(f)[request.user.username])

        infos.update(home_Sname = infos['Sname'])

        # 读取年度总结中该用户的排名数据
        with open(os.path.join(base_dir, 'rank2024.json'), 'r', encoding='utf-8') as f:
            infos.update(json.load(f)[request.user.username])

    # 读取年度总结中所有用户的总体数据
    with open(os.path.join(base_dir, 'summary_overall_2024.json'), 'r', encoding='utf-8') as f:
        infos.update(json.load(f))

    # 将数据中缺少的项利用white-template中的默认值补齐
    with open(os.path.join(base_dir, 'white-template.json'), 'r', encoding='utf-8') as f:
        white_template = json.load(f)
        for key, value in white_template.items():
            if key not in infos.keys():
                infos[key] = value

    # 计算用户自注册起至今过去的天数
    _date_joint = datetime.fromisoformat(infos['date_joined'])
    _date_now = datetime.now()
    days_passed = (_date_now - _date_joint).days
    infos.update(days_passed=days_passed)

    # 处理导出的最常预约研讨室/功能室的数据格式是单元素list的情况
    Function_appoint_most_room = infos.get('Function_appoint_most_room')
    if Function_appoint_most_room is not None:
        if isinstance(Function_appoint_most_room, list):
            if Function_appoint_most_room:
                infos['Function_appoint_most_room'] = Function_appoint_most_room[0]
            else:
                infos['Function_appoint_most_room'] = ''

    Discuss_appoint_most_room = infos.get('Discuss_appoint_most_room')
    if Discuss_appoint_most_room is not None:
        if isinstance(Discuss_appoint_most_room, list):
            if Discuss_appoint_most_room:
                infos['Discuss_appoint_most_room'] = Discuss_appoint_most_room[0]
            else:
                infos['Discuss_appoint_most_room'] = ''

    # 将导出数据中iosformat的日期转化为只包含年、月、日的文字
    if infos.get('Discuss_appoint_longest_day'): # None or ''
        Discuss_appoint_longest_day = datetime.fromisoformat(infos['Discuss_appoint_longest_day'])
        infos['Discuss_appoint_longest_day'] = Discuss_appoint_longest_day.strftime("%Y年%m月%d日")
    if infos.get('Function_appoint_longest_day'):
        Function_appoint_longest_day = datetime.fromisoformat(infos['Function_appoint_longest_day'])
        infos['Function_appoint_longest_day'] = Function_appoint_longest_day.strftime("%Y年%m月%d日")

    # 对最长研讨室/功能室预约的小时数向下取整
    if infos.get('Discuss_appoint_longest_duration'):
        Discuss_appoint_longest_day_hours = infos['Discuss_appoint_longest_duration'].split('小时')[0]
        infos.update(Discuss_appoint_longest_day_hours = Discuss_appoint_longest_day_hours)
    else:
        infos.update(Discuss_appoint_longest_day_hours = 0)

    if infos.get('Function_appoint_longest_duration'):
        Function_appoint_longest_day_hours = infos['Function_appoint_longest_duration'].split('小时')[0]
        infos.update(Function_appoint_longest_day_hours = Function_appoint_longest_day_hours)
    else:
        infos.update(Function_appoint_longest_day_hours = 0)

    # 处理导出共同预约关键词数据格式为[co_keyword, appear_num]的情况
    if infos.get('co_keyword'):
        if isinstance(infos.get('co_keyword'), list):
            if infos['co_keyword']:
                co_keyword, num = infos['co_keyword']
                infos['co_keyword'] = co_keyword
            else:
                infos['co_keyword'] = ''

    # 将list格式的top3最热门课程转化为一个字符串
    hottest_courses_23_fall_dict = infos['hottest_courses_24_Fall']
    hottest_course_names_23_fall = '\n'.join([list(dic.keys())[0] for dic in hottest_courses_23_fall_dict])
    infos.update(hottest_course_names_23_fall=hottest_course_names_23_fall)
    hottest_courses_23_spring_dict = infos['hottest_courses_24_Spring']
    hottest_course_names_23_spring = '\n'.join([list(dic.keys())[0] for dic in hottest_courses_23_spring_dict])
    infos.update(hottest_course_names_23_spring=hottest_course_names_23_spring)

    # 处理用户创建学生小组过多的情况
    if infos.get('myclub_name'):
        myclub_name_list = infos['myclub_name'].split('，')
        if len(myclub_name_list) > 3:
            myclub_name_list = myclub_name_list[:3]
            infos.update(myclub_name='，'.join(myclub_name_list) + '等')

    # 处理用户担任admin职务的小组数过多的情况
    if infos.get('admin_org_names'):
        admin_org_names = infos['admin_org_names']
        if len(admin_org_names) > 3:
            admin_org_names = admin_org_names[:3]
            infos.update(admin_org_names_str='，'.join(admin_org_names) + '等')
        else:
            infos.update(admin_org_names_str='，'.join(admin_org_names))
    else:
         infos.update(admin_org_names_str='')

    # 将小组活动预约top3关键词由list转为一个string
    if infos.get('act_top_three_keywords'):
        act_top_three_keywords = infos['act_top_three_keywords']
        infos.update(act_top_three_keywords_str='，'.join(act_top_three_keywords))
    else:
        infos.update(act_top_three_keywords_str='')

    # 计算参与的学生小组+书院课程小组数
    infos.update(club_course_num=infos.get('club_num', 0)+infos.get('course_org_num', 0))

    # 计算2023年两学期平均书院课程预选数和选中数
    avg_preelect_num = (infos['preelect_course_23fall_num'] + infos['preelect_course_23spring_num']) / 2
    avg_elected_num = (infos['elected_course_23fall_num'] + infos['elected_course_23spring_num']) / 2
    infos.update(avg_preelect_num=avg_preelect_num, avg_elected_num=avg_elected_num)

    # 2024 年新特性（MBTI计算等）
    # 未使用的 2023 特性没有删除
    # 根据最长连续签到百分比对用户进行评语，评语选择于前端实现
    max_consecutive_days_rank = infos.get('max_consecutive_days_rank', 0.0)

    # 根据用户预约习惯对用户进行评语
    sharp_appoint_num = infos.get('sharp_appoint_num')
    disobey_num = infos.get('disobey_num')
    appoint_habit: int = 1
    if sharp_appoint_num == 0:
        if disobey_num == 0:
            appoint_habit = 1
        else:
            appoint_habit = 2
    else:
        if disobey_num == 0:
            appoint_habit = 3
        else:
            appoint_habit = 4
    infos['appoint_habit'] = appoint_habit

    # 根据参加小组活动最频繁时间段授予用户评语（已修改为2024文案版本）
    most_act_common_hour = infos.get('most_act_common_hour')
    if most_act_common_hour is not None:
        if most_act_common_hour <= 10:
            infos.update(most_act_common_hour_name='元气满满的一天当然要在欢聚中开始！')
        elif most_act_common_hour <= 13:
            infos.update(most_act_common_hour_name='睡个饱觉之后，正好和朋友们碰碰面！')
        elif most_act_common_hour <= 16:
            infos.update(most_act_common_hour_name='什么午后休息，不存在的！')
        elif most_act_common_hour <= 18:
            infos.update(most_act_common_hour_name='时间正好，和小伙伴们去看看夕阳')
        elif most_act_common_hour <= 23:
            infos.update(most_act_common_hour_name='辛苦学习一天，当然要和伙伴们痛快一场！')
        else:
            infos.update(most_act_common_hour_name='主打一个“月亮不睡我不睡”！')
    else:
        infos.update(most_act_common_hour_name='')
    
    # 根据已选修书院课程种类数授予成就（已根据 2024 文案修改）
    type_count = infos.get('type_count', 0)
    if type_count >= 3:
        infos.update(type_count_name='通识楷模')
    elif type_count == 2:
        infos.update(type_count_name='涉猎多元')
    elif type_count == 1:
        infos.update(type_count_name='初步探索')
    else:
        infos.update(type_count_name='我自有安排')

    #根据用户兑换的奖池奖品数量给出相应的评语
    # number_of_unique_prizes_comment = ''
    # number_of_unique_prizes = infos.get('number_of_unique_prizes', 0)
    # if number_of_unique_prizes > 0:
    #     number_of_unique_prizes_comment = '手速与元气值兼备，你就是古希腊掌管兑换奖池的神！'
    # else:
    #     number_of_unique_prizes_comment = '元气值商城永远欢迎你！'
    # infos['number_of_unique_prizes_comment'] = number_of_unique_prizes_comment

    # 根据盲盒中奖率授予成就（已经修改为 2024 版本）
    mystery_boxes_num = infos['mystery_boxes_num']
    # 处理导出数据中的typo
    if 'lukcy_mystery_boxes_num' in infos.keys():
        lucky_mystery_boxes_num = infos.pop('lukcy_mystery_boxes_num', 0)
        infos.update(lucky_mystery_boxes_num=lucky_mystery_boxes_num)
    lucky_mystery_boxes_num = infos['lucky_mystery_boxes_num']
    # 防止除零错误
    if (mystery_boxes_num != 0):
        lucky_rate = lucky_mystery_boxes_num / mystery_boxes_num 
        infos['lucky_rate'] = lucky_rate
        if lucky_rate >= 0.5:
            infos.update(mystery_boxes_name='不说了，让我默默羡慕一会儿……')
        else:
            infos.update(mystery_boxes_name='根据运气守恒定律，下一次我看好你！')
    else:
        infos.update(mystery_boxes_name='')

    # MBTI 计算部分
    MBTI_EI = ''
    MBTI_SN = ''
    MBTI_TF = ''
    MBTI_JP = ''
    act_num_rank: float = infos.get('act_num_rank', 0)
    # 小组活动排名
    if act_num_rank >= 50.0:
        MBTI_EI = 'E'
    else:
        MBTI_EI = 'I'
    # 书院课程数量
    if type_count >= 3:
        MBTI_SN = 'S'
    else:
        MBTI_SN = 'N'
    # 平均研讨时间排名
    average_duration_rank: float = infos.get('average_duration_rank', 0)
    if average_duration_rank < 50.0:
        MBTI_TF = 'T'
    else:
        MBTI_TF = 'F'
    # 极限预约次数
    if sharp_appoint_num == 0:
        MBTI_JP = 'J'
    else:
        MBTI_JP = 'P'
    infos['MBTI_EI'] = MBTI_EI
    infos['MBTI_SN'] = MBTI_SN
    infos['MBTI_TF'] = MBTI_TF
    infos['MBTI_JP'] = MBTI_JP

    average_duration_rank_inverse: float = 100 - average_duration_rank
    infos['average_duration_rank_inverse'] = average_duration_rank_inverse

    # Django模板无法进行减法运算
    sharp_appoint_num_rank: float = infos.get('sharp_appoint_num_rank', 0)
    sharp_appoint_num_rank_inverse: float = 100 - sharp_appoint_num_rank
    infos['sharp_appoint_num_rank_inverse'] = sharp_appoint_num_rank_inverse

    return render(request, 'Appointment/summary2024.html', infos)
