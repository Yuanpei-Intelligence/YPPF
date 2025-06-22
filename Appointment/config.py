from boot.config import ROOT_CONFIG
from utils.config import Config, LazySetting
from utils.config.cast import str_to_time

from datetime import timedelta

__all__ = [
    'appointment_config',
]


class AppointmentConfig(Config):
    # 地下室的访问入口和硬件对接密钥
    display_token = LazySetting('token/display')

    # 读取学期开始，用于过滤既往预约
    semester_start = LazySetting('semester_data/semester_start', str_to_time)

    # 设置全局参数
    # added by wxy 人数检查
    # 修改这两个变量以决定检查的宽严
    check_rate = 0.6  # 摄像头发来的每个数据，都有check_rate的几率当成采样点
    camera_qualify_rate = 0.4  # 人数够的次数达到(总采样次数*rate)即可。
    # 由于最短预约时间为30分钟，允许晚到15分钟，所以达标线设在50%以下比较合适(?)

    # 是否清除一周前的预约
    delete_appoint_weekly = False

    # 表示当天预约时放宽的人数下限
    today_min = 2
    # 表示临时预约放宽的人数下限
    temporary_min = 1
    # 长期预约总数上限
    longterm_max_num = 8
    # 单个长期预约总次数上限
    longterm_max_time_once = 11
    longterm_max_time = 16
    # 单个长期预约总周数上限
    longterm_max_interval = 2
    longterm_max_week = 16
    # 面试预约总数上限
    interview_max_num = 1
    # 是否允许不存在学生自动注册
    allow_newstu_appoint = True
    # 是否限制开始前的预约取消时间
    restrict_cancel_time = False
    # 单人单日预约总时长上限
    max_appoint_time = timedelta(hours=6)
    # 是否允许单人同一时段预约两个房间
    allow_overlap = False

appointment_config = AppointmentConfig(ROOT_CONFIG, 'underground')
