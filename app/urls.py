from django.urls import path, re_path
from django.conf.urls.static import static
from . import views, data_import
from django.conf import settings

urlpatterns = [
    path("", views.index, name="index"),
    path("index/", views.index, name="index"),
    path("stuinfo/", views.stuinfo, name="stuinfo"),
    path("orginfo/", views.orginfo, name="orginfo"),
    path("stuinfo/<str:name>", views.stuinfo, name="stuinfo"),
    path("orginfo/<str:name>", views.orginfo, name="orginfo"),
    path(
        "request_login_org/<str:name>",
        views.request_login_org,
        name="request_login_org",
    ),
    path("welcome/", views.homepage, name="welcome"),
    path("register/", views.register, name="register"),
    path("login/", views.index, name="index"),
    path("logout/", views.logout, name="logout"),
    # path("org/",views.org, name="org"),
    path("forgetpw/", views.forget_password, name="forgetpw"),
    path("modpw/", views.modpw, name="modpw"),
    path("test/", views.test, name="test"),
    path("loaddata/", data_import.load_stu_info, name="load_data"),
    path("loadorgdata/", data_import.load_org_info, name="load_org_data"),
    path("user_account_setting/", views.account_setting, name="user_account_setting"),
    path("search/", views.search, name="search"),
    path("minilogin", views.miniLogin, name="minilogin"),
    # re_path("^org([0-9]{2})",views.org_spec,name="org_spec"),
    path("getStuImg", views.get_stu_img, name="get_stu_img"),
    path("transPage/<str:rid>", views.transaction_page, name="transPage"),
    path("startTrans/", views.start_transaction, name="startTrans"),
    #path("confirmTrans/", views.confirm_transaction, name="confirmTrans"),
    #path(
    #    "confirmTrans/<int:tid>/<int:reject>",
    #    views.confirm_transaction,
    #    name="confirmTrans",
    #),
    path("applyActivity/<str:aid>", views.applyActivity, name="applyActivity"),
    path("myYQPoint/", views.myYQPoint, name="myYQPoint"),
    path("showActivities/", views.showActivities, name="showActivities"),
    path("viewActivity/<str:aid>", views.viewActivity, name="viewActivity"),
    path("getActivityInfo/", views.getActivityInfo, name="getActivityInfo"),
    path("checkinActivity/", views.checkinActivity, name="checkinActivity"),
    path("addActivities/", views.addActivities, name="addActivities"),
    path("subscribeActivities/", views.subscribeActivities, name="subscribeActivities"),
    path("save_subscribe_status", views.save_subscribe_status, name="save_subscribe_status"),
    path("notifications/", views.notifications, name="notifications"),
    path("addOrgnization/",views.addOrgnization,name="addOrgnization"),
    path("auditOrgnization/",views.auditOrgnization,name="auditOrgnization"),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

