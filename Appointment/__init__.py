import json

from boottest import base_get_setting
from boottest.hasher import MyMD5PasswordHasher, MySHA256Hasher

__PREFIX = 'underground/'


class LocalSetting():
    def __init__(self):
        # 读取json文件, 包括url地址、输入输出位置等
        try:
            load_json = base_get_setting(__PREFIX[:-1])
        except:
            raise IOError("Can not found json settings.")
        
        self.json = load_json
        
        try:
            self.login_url = load_json['url']['login_url']     # 由陈子维学长提供的统一登录入口
            self.img_url = load_json['url']['img_url']         # 跳过DNS解析的秘密访问入口,帮助加速头像
            self.wechat_url = load_json['url']['wechat_url']   # 访问企业微信封装层的接口
            self.system_log = load_json['url']['system_log']
        except:
            raise IndexError("Can not find necessary field, please check your json file.")

        # 读取敏感密码参数
        #try:
        #    load_file = open("token.json",'r')
        #except:
        #    raise IOError("Can not found token.json. Please use local debug mode instead.")

        try:
            self.YPPF_salt = load_json['token']['YPPF_salt']
            self.wechat_salt = load_json['token']['wechat_salt']
            self.display_token = load_json['token']['display']
        except:
            raise IndexError("Can not find token field, please check your json file.")

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
            self.debug_stuids = load_json['debug']['wechat_receivers']
            if isinstance(self.debug_stuids, str):
                self.debug_stuids = self.debug_stuids.replace(' ', '').split(',')
            self.debug_stuids = list(map(str, self.debug_stuids))
        except:
            self.debug_stuids = []
        self.account_auth = True

        # end

global_info = LocalSetting()
hash_wechat_coder = MySHA256Hasher(secret=global_info.wechat_salt)
