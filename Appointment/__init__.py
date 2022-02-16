from boottest import base_get_setting
from boottest.hasher import MyMD5PasswordHasher, MySHA256Hasher

from django.conf import settings

__PREFIX = 'underground/'

DEBUG = settings.DEBUG


def get_setting(path: str='', default=None, trans_func=None,
               fuzzy_lookup=False, raise_exception=True):
    '''
    默认值更宽松的`get_setting`, 适合可选本地设置

    提供/或\\分割的setting路径，尝试寻找对应路径的设置，失败时返回default
    - 如果某级目录未找到且设置了fuzzy_lookup，会依次尝试其小写、大写版本，并忽略空目录
    - 可选的trans_func标识了结果转换函数，可以是int str等
    - 也可以判断结果类型，在范围外抛出异常，从而得到设定的default值
    '''
    return base_get_setting(
        __PREFIX + path, default, trans_func, fuzzy_lookup, raise_exception)

def get_config(path: str='', default=None, trans_func=None,
               fuzzy_lookup=False, raise_exception=False):
    '''
    默认值更宽松的`get_setting`, 适合可选本地设置

    提供/或\\分割的setting路径，尝试寻找对应路径的设置，失败时返回default
    - 如果某级目录未找到且设置了fuzzy_lookup，会依次尝试其小写、大写版本，并忽略空目录
    - 可选的trans_func标识了结果转换函数，可以是int str等
    - 也可以判断结果类型，在范围外抛出异常，从而得到设定的default值
    '''
    return base_get_setting(
        __PREFIX + path, default, trans_func, fuzzy_lookup, raise_exception)


class LocalSetting():
    def __init__(self):
        # 读取json文件, 包括url地址、输入输出位置等
        try:
            # TODO: task 0 pht 2022-01-24 等待base_get_setting可以正确获取文件夹
            load_json = get_setting(fuzzy_lookup=True)
        except:
            raise IOError("Can not found json settings.")
        
        self.json = load_json

        if DEBUG: print('Loading necessary field...')
        self.login_url = settings.LOGIN_URL                 # 由陈子维学长提供的统一登录入口
        self.img_url = get_setting('url/img_url')           # 跳过DNS解析的秘密访问入口,帮助加速头像
        self.wechat_url = base_get_setting('url/wechat_url')# 访问企业微信封装层的接口
        self.system_log = get_setting('system_log')

        if DEBUG: print('Loading token field...')
        self.YPPF_salt = base_get_setting('hash/base_hasher')
        self.wechat_salt = base_get_setting('hash/wechat')
        self.display_token = get_setting('token/display')

        # 设置全局参数
        # added by wxy 人数检查
        # 修改这两个变量以决定检查的宽严
        self.check_rate = 0.6  # 摄像头发来的每个数据，都有check_rate的几率当成采样点
        self.camera_qualified_check_rate = 0.4  # 人数够的次数达到(总采样次数*rate)即可。
        # 由于最短预约时间为30分钟，允许晚到15分钟，所以达标线设在50%以下比较合适(?)
        
        # 是否清除一周前的预约
        self.delete_appoint_weekly = False

        # 表示当天预约时放宽的人数下限
        self.today_min = 2
        # 表示临时预约放宽的人数下限
        self.temporary_min = 1
        # 是否允许不存在学生自动注册
        self.allow_newstu_appoint = True

        # 是否开启登录系统，默认为开启
        try:
            self.debug_stuids = base_get_setting('debug_stuids')
            if isinstance(self.debug_stuids, str):
                self.debug_stuids = self.debug_stuids.replace(' ', '').split(',')
            self.debug_stuids = list(map(str, self.debug_stuids))
        except:
            self.debug_stuids = []
        self.account_auth = True

        # end

global_info = LocalSetting()
hash_wechat_coder = MySHA256Hasher(secret=global_info.wechat_salt)
