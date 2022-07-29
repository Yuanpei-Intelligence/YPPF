from yp_library.models import (
    Reader,
    Book,
    LendRecord,
)
from datetime import datetime, timedelta
from app.notification_utils import notification_create, bulk_notification_create
from app.models import Notification
from app.wechat_send import publish_notifications, WechatMessageLevel, WechatApp

__all__ = ['bookreturn_notifcation']


def bookreturn_notification():
    """
    对每一条未归还的借阅记录进行检查
    在应还书时间前1天、应还书时间、应还书时间逾期5天发送还书提醒，提醒链接到“我的借阅”界面
    在应还书时间逾期7天，将借阅信息改为“超时扣分”，扣除1信用分并发送提醒
    """
    cr_time = datetime.now
    one_day_before = LendRecord.objects.filter(returned=False,
                                               due_time=cr_time - timedelta(days=1))
    now_return = LendRecord.objects.filter(returned=False, due_time=cr_time)
    five_days_after = LendRecord.objects.filter(returned=False,
                                                due_time=cr_time + timedelta(days=5))
    one_week_after = LendRecord.objects.filter(returned=False,
                                               due_time=cr_time + timedelta(weeks=1))
    
