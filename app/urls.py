"""YPPF URL

新增URL应当遵守以下要求
- URL遵守小驼峰命名法，并尽量简洁
- 函数名和URL基本相同
- 可呈现页面的URL以/结束
- 可呈现页面的函数名遵守小驼峰命名法，方便辨认
- URL的名称(name)必须与URL和函数名之一相同
- 仅供后台访问的页面，URL可以适当简化
- 同一类页面风格相同
"""
from django.urls import path

from app import (
    views,
    org_views,
)

# 尽量不使用<type:arg>, 不支持
urlpatterns = [
    # path("requestLoginOrg/", views.requestLoginOrg, name="requestLoginOrg"), # 已废弃
    path("welcome/", views.homepage, name="welcome"),
    path("freshman/", views.freshman, name="freshman"),
    path("agreement/", views.userAgreement, name="userAgreement"),
    path("shiftAccount/", views.shiftAccount, name="shiftAccount"),
    # path("org/", views.org, name="org"),
    path("forgetpw/", views.forgetPassword, name="forgetpw"),
    path("modpw/", views.modpw, name="modpw"),
    path("minilogin", views.miniLogin, name="minilogin"),
] + [
    # 用户画像和互动
    path("stuinfo/", views.stuinfo, name="stuinfo"),
    path("orginfo/", views.orginfo, name="orginfo"),
    path("userAccountSetting/", views.accountSetting, name="userAccountSetting"),
    path("notifications/", views.notifications, name="notifications"),
    path("search/", views.search, name="search"),
    path("subscribeOrganization/", views.subscribeOrganization,
         name="subscribeOrganization"),
    path("saveSubscribeStatus", views.saveSubscribeStatus,
         name="saveSubscribeStatus"),
] + [
    # 组织相关操作
    path("saveShowPositionStatus", org_views.saveShowPositionStatus,
         name="saveShowPositionStatus"),
    path("showNewOrganization/", org_views.showNewOrganization,
         name="showNewOrganization"),
    path('showPosition/', org_views.showPosition, name="showPosition"),
    path("modifyPosition/", org_views.modifyPosition, name="modifyPosition"),
    path("modifyOrganization/", org_views.modifyOrganization,
         name="modifyOrganization"),
    path("sendMessage/", org_views.sendMessage, name="sendMessage"),
]
