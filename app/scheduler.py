import os   # apscheduler 0.3以上版本要求先导入os 请勿删除
from apscheduler.schedulers.background import BackgroundScheduler
from django.dispatch.dispatcher import receiver
from django_apscheduler.jobstores import DjangoJobStore
# from django_apscheduler.jobstores import register_events, register_job
# 仅在django-apscheduler的0.4以下（不含）版本中才可以使用这些函数，高版本不兼容，不要用
# register_job(scheduler, ...)的替代写法为scheduler.scheduled_job(...)

# 定时任务生成器
scheduler = BackgroundScheduler()
scheduler.add_jobstore(DjangoJobStore(), "default")
# scheduler.start() # 把启动函数放到scheduler_func，只在views调用避免多次触发