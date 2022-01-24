import pymysql
import json

pymysql.install_as_MySQLdb()
pymysql.version_info = (1, 4, 6, "final", 0)


def load_local_json(path="./local_json.json"):
    with open(path, encoding="utf_8") as f:
        local_dict = json.load(f)
    return local_dict

class LongTermInfo():
    def __init__(self):
        # 读取json文件, 包括url地址、输入输出位置等
        try:
            load_file = open("load_setting.json",'r')
            load_json = json.load(load_file)
            load_file.close()
        except:
            raise IOError("Can not found load_setting.json.")
        
        self.json = load_json
        
        try:
            self.login_url = load_json['url']['login_url']     # 由陈子维学长提供的统一登录入口
            self.img_url = load_json['url']['img_url']         # 跳过DNS解析的秘密访问入口,帮助加速头像
            self.this_url = load_json['url']['this_url']       # 跳过DNS解析的秘密访问入口,帮助加速头像
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
            #load_json = json.load(load_file)
            #load_file.close()
            self.YPPF_salt = load_json['token']['YPPF_salt']
            self.wechat_salt = load_json['token']['wechat_salt']
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


local_dict = load_local_json()
global_info = LongTermInfo()


# settings是懒惰的，所以可以提前导入并读取正确的值，导入boottest.settings则会错误
from django.conf import settings
# 寻找本地设置
def base_get_setting(path: str='', default=None, trans_func=None,
                fuzzy_lookup=False, raise_exception=True):
    '''
    提供/或\\分割的setting路径，尝试寻找对应路径的设置，失败时返回default
    - 如果某级目录未找到且设置了fuzzy_lookup，会依次尝试其小写、大写版本，并忽略空目录
    - 可选的trans_func标识了结果转换函数，可以是int str等
    - 也可以判断结果类型，在范围外抛出异常，从而得到设定的default值
    - 除非未设置raise_exception，否则不抛出异常
    '''
    try:
        paths = path.replace('\\', '/').split('/')
        current_dir = local_dict
        for query in paths:
            if fuzzy_lookup and not query:
                continue
            if current_dir.get(query, OSError) != OSError:
                current_dir = current_dir[query]
            elif fuzzy_lookup and current_dir.get(query.lower(), OSError) != OSError:
                current_dir = current_dir[query.lower()]
            elif fuzzy_lookup and current_dir.get(query.upper(), OSError) != OSError:
                current_dir = current_dir[query.upper()]
            else:
                raise OSError(f'setting not found: {query} in {path}')
        return current_dir if trans_func is None else trans_func(current_dir)
    except Exception as e:
        if raise_exception:
            raise
        if settings.DEBUG:
            if default is None:
                print(f'{e}, but given no default')
            else:
                print(f'{e}, returning {default} instead')
        return default


from .hasher import MySHA256Hasher
hash_wechat_coder = MySHA256Hasher(secret=global_info.wechat_salt)