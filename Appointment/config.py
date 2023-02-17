from . import str_to_time
from .apps import AppointmentConfig as APP
from boot.config import Config, LazySetting
from extern.config import wechat_config as WECHAT_CONFIG
from utils.log import get_logger
from utils.hasher import MySHA256Hasher


# 暂不允许*导入
__all__ = []


class AppointmentConfig(Config):

    def __init__(self, dict_prefix: str = 'underground'):
        super().__init__(dict_prefix)

    # 地下室的访问入口和硬件对接密钥
    this_url = LazySetting('base_url')
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
    longterm_max_num = 4
    # 单个长期预约总次数上限
    longterm_max_time_once = 8
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


CONFIG = AppointmentConfig()
hash_wechat_coder = MySHA256Hasher(secret=WECHAT_CONFIG.salt)
logger = get_logger(APP.name)
