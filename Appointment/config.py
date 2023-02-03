import os

from django.apps import apps

from . import str_to_time
from .apps import AppConfig
from boot.config import Config, LazySetting, GLOBAL_CONF
from app.config import CONFIG as PROFILE_CONFIG
from utils.log import get_logger
from utils.hasher import MySHA256Hasher
import utils.global_messages as my_messages


APP_NAME = apps.get_app_config('Appointment').name


class AppointmentConfig(Config):

    def __init__(self, dict_prefix: str = 'underground'):
        super().__init__(dict_prefix)

        self.this_url = LazySetting('underground/base_url')         # 地下室的访问入口
        self.display_token = LazySetting('token/display')

        # 读取学期开始，用于过滤既往预约
        self.semester_start = LazySetting(
            'semester_data/semester_start', str_to_time)

        # 设置全局参数
        # added by wxy 人数检查
        # 修改这两个变量以决定检查的宽严
        self.check_rate = 0.6  # 摄像头发来的每个数据，都有check_rate的几率当成采样点
        self.camera_qualify_rate = 0.4  # 人数够的次数达到(总采样次数*rate)即可。
        # 由于最短预约时间为30分钟，允许晚到15分钟，所以达标线设在50%以下比较合适(?)

        # 是否清除一周前的预约
        self.delete_appoint_weekly = False

        # 表示当天预约时放宽的人数下限
        self.today_min = 2
        # 表示临时预约放宽的人数下限
        self.temporary_min = 1
        # 长期预约总数上限
        self.longterm_max_num = 4
        # 单个长期预约总次数上限
        self.longterm_max_time_once = 8
        self.longterm_max_time = 16
        # 单个长期预约总周数上限
        self.longterm_max_interval = 2
        self.longterm_max_week = 16
        # 面试预约总数上限
        self.interview_max_num = 1
        # 是否允许不存在学生自动注册
        self.allow_newstu_appoint = True
        # 是否限制开始前的预约取消时间
        self.restrict_cancel_time = False


CONFIG = AppointmentConfig()
hash_wechat_coder = MySHA256Hasher(secret=PROFILE_CONFIG.hash_wechat)
logger = get_logger(APP_NAME)
