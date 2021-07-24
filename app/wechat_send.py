from datetime import datetime, timedelta
import random, requests  # 发送验证码
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
from boottest import local_dict
from app.utils import MyMD5PasswordHasher, MySHA256Hasher
import json
login_url = local_dict["url"]["login_url"]
wechat_url = local_dict["url"]["wechat_url"]
email_url = local_dict["url"]["email_url"]
hash_coder = MySHA256Hasher(local_dict["hash"]["base_hasher"])
wechat_coder = MySHA256Hasher(local_dict["hash"]["wechat"])
email_coder = MySHA256Hasher(local_dict["hash"]["email"])
'''
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore

scheduler = BackgroundScheduler()
scheduler.add_jobstore(DjangoJobStore(), "default")
'''
def base_send_wechat(users, message, card=True, url=None, btntxt=None, default=True):
    '''底层实现发送到微信，是为了方便设置定时任务'''
    post_data = {
        "tousers" : users,
        "content" : message,
        "toall" : True,
        "secret" : wechat_coder.encode(message)
    }
    if card:
        post_data["card"] = True
        if default:
            post_data["url"] = url if url is not None else login_url
            post_data["btntxt"] = btntxt if btntxt is not None else "详情"
        else:
            if url is not None:
                post_data["url"] = url
            if btntxt is not None:
                post_data["btntxt"] = btntxt
    post_data = json.dumps(post_data)
    try:
        failed = users
        errmsg = "连接api失败"
        response = requests.post(wechat_url, post_data, timeout=15)
        response = response.json()
        if response["status"] == 200:
            return
        elif response["data"].get("detail"):
            errinfos = response["data"]["detail"]
            failed = [x[0] for x in errinfos]
            errmsg = errinfos[0][1]
        raise OSError
    except:
        print(f"向企业微信发送失败：失败用户：{failed[:3]}等{len(failed)}人，主要失败原因：{errmsg}")

def publish_activity(aid):
    try:
        activity = Activity.objects.get(pk=aid)
    except:
        print(f"未找到id为{aid}的活动")
        return False
    org = activity.organization_id
    subcribers = org.subscribers                # flat=True时必须只有一个键
    subcribers = list(subcribers.values_list("person_id__username", flat=True))
    num = len(subcribers)
    start, finish = activity.start, activity.finish
    if start.year == datetime.now().year and finish.year == datetime.now().year:
        timeformat = "%m月%d日 %H:%M"       # 一般不显示年和秒
    else:
        timeformat = "%Y年%m月%d日 %H:%M"   # 显示具体年份
    start = start.strftime(timeformat)
    finish = finish.strftime(timeformat)
    message = "\n".join((
        activity.topic,
        f"组织者：{activity.organization_id.oname}",
        f"活动时间：{start}-{finish}",
        "活动内容：",
        activity.content,
        "点击查看详情"
    ))
    kws = {"card" : True}
    if activity.URL:
        kws["url"] = activity.URL
        kws["btntxt"] = "阅读原文"
    for i in range(0, num, 500):
        userids = subcribers[i:i+500]
        '''
        scheduler.add_job(base_send_wechat, 'date', 
            args=(userids, message),
            kwargs=kws,
            next_run_time=datetime.now() + timedelta(seconds=5+i/100)
            )
        '''
        base_send_wechat(userids, message, **kws) #不使用定时任务请改为这句
