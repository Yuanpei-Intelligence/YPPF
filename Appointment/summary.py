import os
import json

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
