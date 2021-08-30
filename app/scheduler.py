from apscheduler.schedulers.background import BackgroundScheduler
from django.dispatch.dispatcher import receiver
from django_apscheduler.jobstores import DjangoJobStore, register_events, register_job

# 定时任务生成器
scheduler = BackgroundScheduler()
scheduler.add_jobstore(DjangoJobStore(), "default")