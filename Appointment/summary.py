import os
import json
from datetime import datetime

from django.http import HttpRequest
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import auth

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

    infos.update(logged_in=logged_in, user_accept=user_accept,
                 user_cancel=user_cancel)

    if not user_accept or not logged_in or user_cancel:
        # 新生/不接受协议/未登录 展示样例
        example_file = os.path.join(base_dir, 'template.json')
        with open(example_file) as f:
            infos.update(json.load(f))
        if logged_in:
            with open(os.path.join(base_dir, 'summary2023.json'), 'r') as f:
                infos.update(home_Sname=json.load(
                    f)[request.user.username].get('Sname', ''))
    else:
        # 读取年度总结中该用户的个人数据
        with open(os.path.join(base_dir, 'summary2023.json'), 'r') as f:
            infos.update(json.load(f)[request.user.username])

        infos.update(home_Sname=infos['Sname'])

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
    if infos.get('Discuss_appoint_longest_day'):  # None or ''
        Discuss_appoint_longest_day = datetime.fromisoformat(
            infos['Discuss_appoint_longest_day'])
        infos['Discuss_appoint_longest_day'] = Discuss_appoint_longest_day.strftime(
            "%Y年%m月%d日")
    if infos.get('Function_appoint_longest_day'):
        Function_appoint_longest_day = datetime.fromisoformat(
            infos['Function_appoint_longest_day'])
        infos['Function_appoint_longest_day'] = Function_appoint_longest_day.strftime(
            "%Y年%m月%d日")

    # 对最长研讨室/功能室预约的小时数向下取整
    if infos.get('Discuss_appoint_longest_duration'):
        Discuss_appoint_longest_day_hours = infos['Discuss_appoint_longest_duration'].split('小时')[
            0]
        infos.update(
            Discuss_appoint_longest_day_hours=Discuss_appoint_longest_day_hours)
    else:
        infos.update(Discuss_appoint_longest_day_hours=0)

    if infos.get('Function_appoint_longest_duration'):
        Function_appoint_longest_day_hours = infos['Function_appoint_longest_duration'].split('小时')[
            0]
        infos.update(
            Function_appoint_longest_day_hours=Function_appoint_longest_day_hours)
    else:
        infos.update(Function_appoint_longest_day_hours=0)

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
    hottest_course_names_23_fall = '\n'.join(
        [list(dic.keys())[0] for dic in hottest_courses_23_fall_dict])
    infos.update(hottest_course_names_23_fall=hottest_course_names_23_fall)
    hottest_courses_23_spring_dict = infos['hottest_courses_23_Spring']
    hottest_course_names_23_spring = '\n'.join(
        [list(dic.keys())[0] for dic in hottest_courses_23_spring_dict])
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
        infos.update(act_top_three_keywords_str='，'.join(
            act_top_three_keywords))
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
    infos.update(club_course_num=infos.get(
        'club_num', 0)+infos.get('course_org_num', 0))

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
    avg_preelect_num = (infos['preelect_course_23fall_num'] +
                        infos['preelect_course_23spring_num']) / 2
    avg_elected_num = (infos['elected_course_23fall_num'] +
                       infos['elected_course_23spring_num']) / 2
    infos.update(avg_preelect_num=avg_preelect_num,
                 avg_elected_num=avg_elected_num)

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

    infos.update(logged_in=logged_in, user_accept=user_accept,
                 user_cancel=user_cancel)

    if not user_accept or not logged_in or user_cancel:
        # 新生/不接受协议/未登录 展示样例
        example_file = os.path.join(base_dir, 'template.json')
        with open(example_file, encoding='utf-8') as f:
            infos.update(json.load(f))
        if logged_in:
            with open(os.path.join(base_dir, 'summary2024.json'), 'r', encoding='utf-8') as f:
                infos.update(home_Sname=json.load(
                    f)[request.user.username].get('Sname', ''))
    else:
        # 读取年度总结中该用户的个人数据
        with open(os.path.join(base_dir, 'summary2024.json'), 'r', encoding='utf-8') as f:
            infos.update(json.load(f)[request.user.username])

        infos.update(home_Sname=infos['Sname'])

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
    if infos.get('Discuss_appoint_longest_day'):  # None or ''
        Discuss_appoint_longest_day = datetime.fromisoformat(
            infos['Discuss_appoint_longest_day'])
        infos['Discuss_appoint_longest_day'] = Discuss_appoint_longest_day.strftime(
            "%Y年%m月%d日")
    if infos.get('Function_appoint_longest_day'):
        Function_appoint_longest_day = datetime.fromisoformat(
            infos['Function_appoint_longest_day'])
        infos['Function_appoint_longest_day'] = Function_appoint_longest_day.strftime(
            "%Y年%m月%d日")

    # 对最长研讨室/功能室预约的小时数向下取整
    if infos.get('Discuss_appoint_longest_duration'):
        Discuss_appoint_longest_day_hours = infos['Discuss_appoint_longest_duration'].split('小时')[
            0]
        infos.update(
            Discuss_appoint_longest_day_hours=Discuss_appoint_longest_day_hours)
    else:
        infos.update(Discuss_appoint_longest_day_hours=0)

    if infos.get('Function_appoint_longest_duration'):
        Function_appoint_longest_day_hours = infos['Function_appoint_longest_duration'].split('小时')[
            0]
        infos.update(
            Function_appoint_longest_day_hours=Function_appoint_longest_day_hours)
    else:
        infos.update(Function_appoint_longest_day_hours=0)

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
    hottest_course_names_23_fall = '\n'.join(
        [list(dic.keys())[0] for dic in hottest_courses_23_fall_dict])
    infos.update(hottest_course_names_23_fall=hottest_course_names_23_fall)
    hottest_courses_23_spring_dict = infos['hottest_courses_24_Spring']
    hottest_course_names_23_spring = '\n'.join(
        [list(dic.keys())[0] for dic in hottest_courses_23_spring_dict])
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
        infos.update(act_top_three_keywords_str='，'.join(
            act_top_three_keywords))
    else:
        infos.update(act_top_three_keywords_str='')

    # 计算参与的学生小组+书院课程小组数
    infos.update(club_course_num=infos.get(
        'club_num', 0)+infos.get('course_org_num', 0))

    # 计算2023年两学期平均书院课程预选数和选中数
    avg_preelect_num = (infos['preelect_course_23fall_num'] +
                        infos['preelect_course_23spring_num']) / 2
    avg_elected_num = (infos['elected_course_23fall_num'] +
                       infos['elected_course_23spring_num']) / 2
    infos.update(avg_preelect_num=avg_preelect_num,
                 avg_elected_num=avg_elected_num)

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

    # 根据用户兑换的奖池奖品数量给出相应的评语
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
        lucky_rate = lucky_mystery_boxes_num / mystery_boxes_num * 100.0
        infos['lucky_rate'] = lucky_rate
        if lucky_rate >= 50.0:
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


def summary2025(request: HttpRequest):
    # 2025年度总结
    base_dir = 'raw_data/summary2025'

    # 先展示入口页，让用户选择“登录查看”或“访客查看”
    view_mode = request.GET.get('view', '')
    if view_mode not in ['login', 'guest']:
        return render(request, 'Appointment/summary2025_entry.html', {
            'logged_in': request.user.is_authenticated,
            'login_failed': request.GET.get('login_failed') == '1',
        })

    logged_in = request.user.is_authenticated
    infos = {}
    # 获取用户真实姓名
    real_name = "访客"
    if logged_in:
        try:
            from app.models import NaturalPerson
            real_name = NaturalPerson.objects.get(person_id=request.user).name
        except:
            real_name = request.user.username

    if logged_in:
        username = request.session.get("NP", "")
        if username:
            from app.utils import update_related_account_in_session
            update_related_account_in_session(request, username, shift=True)

    user_accept = request.GET.get('accept') == 'true'
    user_cancel = request.GET.get('cancel') == 'true' or view_mode == 'guest'
    # 已登录且未取消时，视为展示真实数据（前端通过遮罩控制协议同意流程，避免刷新闪烁）
    show_real_data = logged_in and not user_cancel

    infos.update(logged_in=logged_in, user_accept=user_accept,
                 user_cancel=user_cancel)

    if not show_real_data:
        # 新生/不接受协议/未登录 展示样例
        example_file = os.path.join(base_dir, 'template.json')
        with open(example_file, encoding='utf-8') as f:
            template_data = json.load(f)
            # template.json 结构是 {"2300000000": {...}}，需要提取第一个用户的数据
            if template_data:
                first_key = list(template_data.keys())[0]
                infos.update(template_data[first_key])
        # 如果是访客模式，不要读取真实用户数据，即使已登录
        if logged_in and view_mode != 'guest':
            with open(os.path.join(base_dir, 'summary2025.json'), 'r', encoding='utf-8') as f:
                user_data = json.load(f).get(request.user.username, {})
                infos.update(home_Sname=user_data.get('Sname', ''))
    else:
        # 读取年度总结中该用户的个人数据
        with open(os.path.join(base_dir, 'summary2025.json'), 'r', encoding='utf-8') as f:
            user_data = json.load(f).get(request.user.username, {})
            if user_data:
                infos.update(user_data)
            else:
                # 用户不在数据中，使用模板保底
                with open(os.path.join(base_dir, 'template.json'), 'r', encoding='utf-8') as tf:
                    template_data = json.load(tf)
                    if template_data:
                        first_key = list(template_data.keys())[0]
                        infos.update(template_data[first_key])

        infos.update(home_Sname=infos.get('Sname', infos.get('name', '')))

        # 读取该用户的排名数据
        with open(os.path.join(base_dir, 'rank2025.json'), 'r', encoding='utf-8') as f:
            rank_data = json.load(f).get(request.user.username, {})
            if rank_data:
                infos.update(rank_data)
                print(f"[DEBUG] 用户 {request.user.username} 的排名数据加载成功")
                print(
                    f"[DEBUG] personal_most_frequent_co_appoint: {rank_data.get('personal_most_frequent_co_appoint')}")
            else:
                print(
                    f"[DEBUG] 用户 {request.user.username} 不在 rank2025.json 中，将使用模板默认值")

    # 处理姓名显示逻辑
    display_name = infos.get('Sname') or infos.get('name') or real_name
    if display_name == "虚拟人":
        display_name = real_name

    # 如果是访客模式，强制显示为“访客”
    if view_mode == 'guest':
        display_name = "访客"

    infos.update(home_Sname=display_name)
    if not infos.get('name') or infos.get('name') == "虚拟人" or view_mode == 'guest':
        infos['name'] = display_name
    if not infos.get('Sname') or infos.get('Sname') == "虚拟人" or view_mode == 'guest':
        infos['Sname'] = display_name

    # 读取年度总结中所有用户的总体数据
    with open(os.path.join(base_dir, 'summary_overall_2025.json'), 'r', encoding='utf-8') as f:
        infos.update(json.load(f))

    # 将数据中缺少的项利用template中的默认值补齐
    with open(os.path.join(base_dir, 'template.json'), 'r', encoding='utf-8') as f:
        template = json.load(f)
        # template.json 结构是 {"2300000000": {...}}，需要提取第一个用户的数据
        if template:
            first_key = list(template.keys())[0]
            template = template[first_key]

        # 递归填充缺失或为null的字段
        def fill_null_fields(data_dict, template_dict):
            for key, template_value in template_dict.items():
                if key not in data_dict or data_dict[key] is None:
                    data_dict[key] = template_value
                elif isinstance(template_value, dict) and isinstance(data_dict.get(key), dict):
                    fill_null_fields(data_dict[key], template_value)

        fill_null_fields(infos, template)

    # 字段名兼容：如果没有 personal_most_frequent_co_appoint 但有 organization_most_frequent_co_appoint，则复制
    # 这个逻辑必须在 fill_rank_null_fields 之前执行，否则会被 rank-template 的默认值覆盖
    if 'personal_most_frequent_co_appoint' not in infos or not infos.get('personal_most_frequent_co_appoint'):
        if infos.get('organization_most_frequent_co_appoint'):
            infos['personal_most_frequent_co_appoint'] = infos['organization_most_frequent_co_appoint']
            print(
                f"[DEBUG] 使用 organization_most_frequent_co_appoint 作为 personal_most_frequent_co_appoint: {infos['personal_most_frequent_co_appoint']}")

    # 将 rank 数据中缺少的项利用 rank-template 中的默认值补齐
    with open(os.path.join(base_dir, 'rank-template.json'), 'r', encoding='utf-8') as f:
        rank_template = json.load(f)
        # rank-template.json 结构也是 {"2300000000": {...}}
        if rank_template:
            first_key = list(rank_template.keys())[0]
            rank_template = rank_template[first_key]

        # 递归填充缺失或为null的字段（但跳过已经存在且有值的字段）
        def fill_rank_null_fields(data_dict, template_dict):
            for key, template_value in template_dict.items():
                # 跳过 personal_most_frequent_co_appoint，如果没有真实数据就让它保持为空
                if key == 'personal_most_frequent_co_appoint':
                    continue
                if key not in data_dict or data_dict[key] is None:
                    data_dict[key] = template_value
                elif isinstance(template_value, dict) and isinstance(data_dict.get(key), dict):
                    fill_rank_null_fields(data_dict[key], template_value)

        fill_rank_null_fields(infos, rank_template)

    # 处理空字符串的 usage 字段
    def fix_empty_usage(data_dict, parent_key=''):
        """递归将空字符串的 usage 字段替换为合理默认值"""
        if isinstance(data_dict, dict):
            # 如果当前字典有 usage 字段且值为空字符串，则替换
            if 'usage' in data_dict and data_dict['usage'] == '':
                # 根据父键设置合理的默认值
                if 'underground' in parent_key or 'study' in parent_key:
                    data_dict['usage'] = '自习'
                elif 'talk' in parent_key or 'func' in parent_key:
                    data_dict['usage'] = '小组讨论'
                else:
                    data_dict['usage'] = '预约活动'
                print(f"[DEBUG] 修复了 {parent_key}.usage: {data_dict['usage']}")

            # 递归处理嵌套字典
            for key, value in data_dict.items():
                if isinstance(value, dict):
                    fix_empty_usage(
                        value, parent_key=f"{parent_key}.{key}" if parent_key else key)

    fix_empty_usage(infos)

    # 判断用户是否为新用户（2025年注册）
    date_joined_str = infos.get('date_joined')
    is_new_user = False
    if date_joined_str:
        try:
            date_joined_obj = datetime.fromisoformat(date_joined_str) if isinstance(
                date_joined_str, str) else date_joined_str
            is_new_user = date_joined_obj.year >= 2025
        except:
            is_new_user = False
    infos['is_new_user'] = is_new_user

    # 计算用户自注册起至今过去的天数（2025 days己计算）

    # 将导出数据中iosformat的日期转化为只包含年、月、日的文字date_joined"# 注册日期（2025update)
    longest_usage = infos.get("longest_underground_usage", {})
    start_date = longest_usage.get("longest_continuous_start_date")
    end_date = longest_usage.get("longest_continuous_end_date")
    if infos.get('date_joined'):  # None or ''
        date_joined = datetime.fromisoformat(infos['date_joined'])
        infos['date_joined'] = date_joined.strftime("%Y年%m月%d日")
    if start_date:
        start_date = datetime.fromisoformat(start_date)
        if "longest_underground_usage" not in infos:
            infos["longest_underground_usage"] = {}
        infos["longest_underground_usage"]["longest_continuous_start_date"] = start_date.strftime(
            "%Y年%m月%d日")
    if end_date:
        end_date = datetime.fromisoformat(end_date)
        if "longest_underground_usage" not in infos:
            infos["longest_underground_usage"] = {}
        infos["longest_underground_usage"]["longest_continuous_end_date"] = end_date.strftime(
            "%Y年%m月%d日")

    # 对最长研讨室/功能室预约的小时数向下取整
    if infos.get('Discuss_appoint_longest_duration'):
        Discuss_appoint_longest_day_hours = infos['Discuss_appoint_longest_duration'].split('小时')[
            0]
        infos.update(
            Discuss_appoint_longest_day_hours=Discuss_appoint_longest_day_hours)
    else:
        infos.update(Discuss_appoint_longest_day_hours=0)

    if infos.get('Function_appoint_longest_duration'):
        Function_appoint_longest_day_hours = infos['Function_appoint_longest_duration'].split('小时')[
            0]
        infos.update(
            Function_appoint_longest_day_hours=Function_appoint_longest_day_hours)
    else:
        infos.update(Function_appoint_longest_day_hours=0)

    # 2025新特性
    # 根据刷卡/预约记录总天数超越百分比显示文字
    underground_usage_percentile = infos.get('underground_usage_percentile', 0)
    if underground_usage_percentile is None:
        underground_usage_percentile = 0
    if underground_usage_percentile <= 50:
        infos.update(underground_usage_percentile_name='新的一年，期待着和你遇见！')
    elif underground_usage_percentile <= 85:
        infos.update(underground_usage_percentile_name='新的一年，我依然在这里等你。')
    else:
        infos.update(underground_usage_percentile_name='我宣布，没有人比你更了解地下室！')
    # 如果该用户刷卡/预约记录为0，则下面三部分不保留
    record_is_zero = (infos.get('underground_usage_days', 0) == 0)
    infos.update(record_is_zero=record_is_zero)
    # 用户在统计周期内刷卡/预约记录的最早日期自习室研讨室类型？
    study_room_list = ['B108', 'B112', 'B118', 'B106', 'B119', 'B114']
    room = infos.get("first_underground_record", {}).get("room")
    first_room_study = False
    last_room_study = False
    if room in study_room_list:
        first_room_study = True
    room = infos.get("last_underground_record", {}).get("room")
    if room in study_room_list:
        last_room_study = True
    infos.update(first_room_study=first_room_study)
    infos.update(last_room_study=last_room_study)
    # 研讨室/功能室预约时长最长的日期的参与人数分类前端?
    # 房间预约-“最期待”中的数字和单位问题
    average_diff = infos.get("appoint_habit", {}).get('average_diff')
    max_diff = infos.get("appoint_habit", {}).get('max_diff')
    average_diff_time = '小时'
    max_diff_time = '小时'
    if isinstance(average_diff, (int, float)) and average_diff > 0:
        if average_diff > 24:
            average_diff_time = '天'
            average_diff = average_diff//24
    else:
        average_diff = 0  # None/非数值兜底为0

    if isinstance(max_diff, (int, float)) and max_diff > 0:
        if max_diff and max_diff > 24:
            max_diff_time = '天'
            max_diff = max_diff//24
    else:
        max_diff = 0
    infos.update(average_diff_time=average_diff_time,
                 max_diff_time=max_diff_time)
    # 确保 appoint_habit 是字典
    if not isinstance(infos.get("appoint_habit"), dict):
        infos['appoint_habit'] = {}
    infos['appoint_habit']['average_diff'] = average_diff
    infos['appoint_habit']['max_diff'] = max_diff

    # 为talk_and_func_room_longest_record添加participant_num字段
    # 如果原数据没有，则用talk_room_average_participant_num判断
    talk_and_func_record = infos.get('talk_and_func_room_usage', {}).get(
        'talk_and_func_room_longest_record')
    if talk_and_func_record and isinstance(talk_and_func_record, dict):
        if 'participant_num' not in talk_and_func_record:
            # 使用平均参与人数作为判断依据
            avg_participant = infos.get('talk_and_func_room_usage', {}).get(
                'talk_room_average_participant_num', 2)
            # 如果平均人数<=1，认为是个人使用；否则认为是多人使用
            talk_and_func_record['participant_num'] = 1 if avg_participant <= 1 else 2

    # 个人/集体预约分类

    # 如果担任职务小组数量为0，则该行不保留
    org_reserved = True
    org_usage = infos.get("org_usage", {})
    if org_usage and org_usage.get('org_num'):
        org_name_list = org_usage.get('org_name_list', [])
        if len(org_name_list) == 0:
            org_reserved = False
    infos.update(org_reserved=org_reserved)

    # 处理用户担任admin职务的小组数过多的情况(2025变量名org_name_list_str)
    org_name_list = infos.get("org_usage", {}).get('org_name_list', [])
    admin_org_num = len(org_name_list)
    if admin_org_num:
        if admin_org_num > 3:
            org_name_list = org_name_list[:3]
            infos.update(org_name_list_str='，'.join(org_name_list) + '等')
        else:
            infos.update(org_name_list_str='，'.join(org_name_list))
    else:
        infos.update(org_name_list_str='')

    # 计算已选修书院课程种类数
    course_type_str = infos.get('course_usage', {}).get('course_type_str', '')
    if course_type_str:
        course_type_list = course_type_str.split()
        infos['course_type_count'] = len(course_type_list)
        infos['course_type_str_formatted'] = '、'.join(course_type_list)
    else:
        infos['course_type_count'] = 0
        infos['course_type_str_formatted'] = ''

    return render(request, 'Appointment/summary2025.html', infos)


def summary2025_login(request: HttpRequest):
    if request.method != 'POST':
        return redirect(reverse('Appointment:summary2025'))

    username = (request.POST.get('username') or '').strip()
    password = request.POST.get('password') or ''

    if not username or not password:
        return redirect(f"{reverse('Appointment:summary2025')}?login_failed=1")

    user = auth.authenticate(username=username, password=password)
    if user is None:
        return redirect(f"{reverse('Appointment:summary2025')}?login_failed=1")

    auth.login(request, user)
    return redirect(f"{reverse('Appointment:summary2025')}?view=login")
