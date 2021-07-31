from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore, register_events, register_job


from django.http import JsonResponse, HttpResponse  # Json响应
from django.shortcuts import render, redirect  # 网页render & redirect
from django.urls import reverse
from datetime import datetime, timedelta, timezone, time, date
from django.db import transaction  # 原子化更改数据库

# 定时任务生成器
scheduler = BackgroundScheduler()
scheduler.add_jobstore(DjangoJobStore(), "default")


@register_job(scheduler, 'cron', id='test', day=1, hour=15, minute=23)
def test():
    # 具体要执行的代码
    print("\n\n\nthis is a test register job!\n\n\n")