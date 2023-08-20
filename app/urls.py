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
    activity_views,
    course_views,
    academic_views,
    chat_api,
    YQPoint_views,
)

# 尽量不使用<type:arg>, 不支持
urlpatterns = [
    # path("requestLoginOrg/", views.requestLoginOrg, name="requestLoginOrg"), # 已废弃
    path("welcome/", views.homepage, name="welcome"),
    path("freshman/", views.freshman, name="freshman"),
    path("register/", views.authRegister, name="register"),
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
    # 活动
    path("viewActivity/<str:aid>", activity_views.viewActivity, name="viewActivity"),
    path("getActivityInfo/", activity_views.getActivityInfo, name="getActivityInfo"),
    path("checkinActivity/<str:aid>",
         activity_views.checkinActivity, name="checkinActivity"),
    path("addActivity/", activity_views.addActivity, name="addActivity"),
    path("showActivity/", activity_views.showActivity, name="showActivity"),
    path("editActivity/<str:aid>", activity_views.addActivity, name="editActivity"),
    path("examineActivity/<str:aid>",
         activity_views.examineActivity, name="examineActivity"),
    path("offlineCheckinActivity/<str:aid>",
         activity_views.offlineCheckinActivity, name="offlineCheckinActivity"),
    path("endActivity/", activity_views.endActivity, name="endActivity"),
    path("modifyEndActivity/", activity_views.modifyEndActivity,
         name="modifyEndActivity"),
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
    # path("applyPosition/<str:oid>", views.apply_position, name="applyPosition"), 弃用多年
] + [
    # 发布选课相关操作
    path("addCourse/", course_views.addCourse, name="addCourse"),
    path("editCourse/<str:cid>", course_views.addCourse, name="editCourse"),
    # 选课相关操作
    path("selectCourse/", course_views.selectCourse, name="selectCourse"),
    path("viewCourse/", course_views.viewCourse, name="viewCourse"),
    # 课程相关操作
    path("addSingleCourseActivity/", course_views.addSingleCourseActivity,
         name="addSingleCourseActivity"),
    path("editCourseActivity/<str:aid>",
         course_views.editCourseActivity, name="editCourseActivity"),
    path("showCourseActivity/", course_views.showCourseActivity,
         name="showCourseActivity"),
    path("showCourseRecord/", course_views.showCourseRecord,
         name="showCourseRecord"),
    # 数据导出
    path("outputRecord/", course_views.outputRecord, name="outputRecord"),
    path("outputSelectInfo/", course_views.outputSelectInfo,
         name="outputSelectInfo"),
] + [
    # 学术地图
    path("modifyAcademic/", academic_views.modifyAcademic, name="modifyAcademic"),
    path("AcademicQA/", academic_views.ShowChats.as_view(), name="showChats"),
    path("viewQA/<int:chat_id>", academic_views.ViewChat.as_view(), name="viewChat"),
    path("auditAcademic/", academic_views.auditAcademic, name="auditAcademic"),
    path("applyAuditAcademic/", academic_views.applyAuditAcademic,
         name="applyAuditAcademic"),
] + [
    # 问答相关
    # TODO: url等合并前端后再改
    path("addChatComment/", chat_api.AddComment.as_view(), name="addComment"),
    path("closeChat/", chat_api.CloseChat.as_view(), name="closeChat"),
    path("startChat/", chat_api.StartChat.as_view(), name="startChat"),
    path("startUndirectedChat/", chat_api.StartUndirectedChat.as_view(), name="startUndirectedChat"),
    path("rateAnswer/", chat_api.RateAnswer.as_view(), name="rateAnswer")
] + [
    # 元气值
    path("myYQPoint/", YQPoint_views.myYQPoint.as_view(), name="myYQPoint"),
    path("showPools/", YQPoint_views.showPools, name="showPools"),
    path("myPrize/", YQPoint_views.myPrize.as_view(), name="myPrize"),
]