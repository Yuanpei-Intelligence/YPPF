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
from django.urls import path, re_path
from django.conf.urls.static import static
from . import data_import
from . import (
    views,
    org_views,
    activity_views,
    reimbursement_views,
    YQPoint_views,
    course_views,
    feedback_views,
)
from django.conf import settings

# 尽量不使用<type:arg>, 不支持
urlpatterns = [
    # 登录和验证
    path("", views.index, name="index"),
    path("index/", views.index, name="index"),
    # path("requestLoginOrg/", views.requestLoginOrg, name="requestLoginOrg"), # 已废弃
    # path("requestLoginOrg/<str:name>", views.requestLoginOrg, name="requestLoginOrg"),
    path("welcome/", views.homepage, name="welcome"),
    path("freshman/", views.freshman, name="freshman"),
    path("register/", views.authRegister, name="register"),
    path("login/", views.index, name="index"),
    path("agreement/", views.userAgreement, name="userAgreement"),
    path("logout/", views.logout, name="logout"),
    path("shiftAccount/", views.shiftAccount, name="shiftAccount"),
    # path("org/", views.org, name="org"),
    path("forgetpw/", views.forgetPassword, name="forgetpw"),
    path("modpw/", views.modpw, name="modpw"),
    path("minilogin", views.miniLogin, name="minilogin"),
    path("getStuImg", views.get_stu_img, name="get_stu_img"),
] + [
    # 用户画像和互动
    path("stuinfo/", views.stuinfo, name="stuinfo"),
    path("orginfo/", views.orginfo, name="orginfo"),
    # path("stuinfo/<str:name>", views.stuinfo, name="stuinfo"),
    # path("orginfo/<str:name>", views.orginfo, name="orginfo"),
    path("userAccountSetting/", views.accountSetting, name="userAccountSetting"),
    path("notifications/", views.notifications, name="notifications"),
    path("search/", views.search, name="search"),
    path("subscribeOrganization/", views.subscribeOrganization, name="subscribeOrganization"),
    path("saveSubscribeStatus", views.saveSubscribeStatus, name="saveSubscribeStatus"),
    path("QAcenter/", views.QAcenter, name="QAcenter"),
] + [
    # 元气值和后台操作
    path("myYQPoint/", YQPoint_views.myYQPoint, name="myYQPoint"),
    path("YQP_distributions/", YQPoint_views.YQPoint_distributions, name="YQP_distributions"),
    # path("YQP_distribution/<int:dis_id>", YQPoint_views.YQPoint_distribution, name="YQP_distribution"),
    # path("new_YQP_distribution", YQPoint_views.new_YQPoint_distribute, name="new_YQP_distribution"),
    path("transPage/<str:rid>", YQPoint_views.transaction_page, name="transPage"),
] + [
    # 活动与报销
    path("applyActivity/<str:aid>", activity_views.applyActivity, name="applyActivity"),
    path("viewActivity/<str:aid>", activity_views.viewActivity, name="viewActivity"),
    path("getActivityInfo/", activity_views.getActivityInfo, name="getActivityInfo"),
    path("checkinActivity/<str:aid>", activity_views.checkinActivity, name="checkinActivity"),
    path("addActivity/", activity_views.addActivity, name="addActivity"),
    path("showActivity/", activity_views.showActivity, name="showActivity"),
    path("editActivity/<str:aid>", activity_views.addActivity, name="editActivity"),
    path("examineActivity/<str:aid>", activity_views.examineActivity, name="examineActivity"),
    path("endActivity/", reimbursement_views.endActivity, name="endActivity"),
    path("modifyEndActivity/", reimbursement_views.modifyEndActivity, name="modifyEndActivity"),
    path("offlineCheckinActivity/<str:aid>", activity_views.offlineCheckinActivity, name="offlineCheckinActivity"),
] + [
    # 组织相关操作
    path("saveShowPositionStatus", org_views.saveShowPositionStatus, name="saveShowPositionStatus"),
    path("showNewOrganization/", org_views.showNewOrganization, name="showNewOrganization"),
    path('showPosition/', org_views.showPosition, name="showPosition"),
    path("modifyPosition/", org_views.modifyPosition, name="modifyPosition"),
    path("modifyOrganization/", org_views.modifyOrganization, name="modifyOrganization"),
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
    path("addSingleCourseActivity/", course_views.addSingleCourseActivity, name="addSingleCourseActivity"),
    path("editCourseActivity/<str:aid>", course_views.editCourseActivity, name="editCourseActivity"),
    path("showCourseActivity/", course_views.showCourseActivity, name="showCourseActivity"),
    path("showCourseRecord/", course_views.showCourseRecord, name="showCourseRecord"),
    # 数据导出
    path("outputRecord/", course_views.outputRecord, name="outputRecord"),
    path("outputSelectInfo/", course_views.outputSelectInfo, name="outputSelectInfo"),
] + [
    # 反馈中心
    path("feedback/", feedback_views.feedbackWelcome, name="feadbackWelcome"),
    path("modifyFeedback/", feedback_views.modifyFeedback, name="modifyFeedback"),
    path("viewFeedback/<str:fid>", feedback_views.viewFeedback, name="viewFeedback"),
] + [
    # 数据导入
    path("loadstudata/", data_import.load_stu_data, name="load_stu_data"),
    path("loadfreshman/", data_import.load_freshman_info, name="load_freshman"),
    path("loadorgdata/", data_import.load_org_data, name="load_org_data"),
    path("loadorgtag/", data_import.load_org_tag, name="loag_org_tag"),
    path("loadoldorgtags/", data_import.load_tags_for_old_org, name="load_tags_for_old_org"),
    path("loadfeedbackdata/", data_import.load_feedback_data, name="load_feedback_data"),
    # path("loadtransferinfo/",
    #      data_import.load_transfer_info,
    #      name="load_transfer_info"),        #服务器弃用
    # path("loadactivity/",
    #      data_import.load_activity_info,
    #      name="load_activity_info"),        #服务器弃用
    # path("loadnotification/",
    #      data_import.load_notification_info,
    #      name="load_notification_info"),    #服务器弃用
    path("loadhelp/", data_import.load_help, name="load_help"),
    path("loadcourserecord/", data_import.load_course_record, name="load_course_record"),
] + [
    # 埋点
    path('eventTrackingFunc/', views.eventTrackingFunc, name='eventTracking'),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
