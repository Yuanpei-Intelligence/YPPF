import pymysql
import json

pymysql.install_as_MySQLdb()
pymysql.version_info = (1, 4, 6, "final", 0)


def load_local_json(path="./local_json.json"):
    with open(path, encoding="utf_8") as f:
        local_dict = json.load(f)
    return local_dict


local_dict = load_local_json()

help_message = {
    "个人主页": "在这里你可以看到自己向别的用户展示的信息，以及别的用户公开展示的信息~",
    "组织主页": "",
    # "近期要闻": "",
    "通知信箱": "信箱会自动收集和您相关的信息，包括各类通知和回执~常来看看吧",
    "我的元气值": "元气值可以用于报名参加活动、进行学院周边产品的购买和组织申请报销。元气值的来源是学院定期的发放和账户之间的转账",
    "我的订阅": "这里展示了你订阅的组织。在你订阅的组织发布活动信息时，你会在企业微信收到活动推送",
    "账户设置": "直接在框中修改，点击下方的submit按钮就可以修改个人信息啦",
    "修改密码": ""
}
