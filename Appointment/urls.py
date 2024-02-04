'''YPUnderground URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
'''
from django.urls import path
from Appointment import views, summary, hardware_api

# 参考：https://stackoverflow.com/questions/61254816/what-is-the-purpose-of-app-name-in-urls-py-in-django
# 一般情况下不需要使用 app_name
# 当 view 的名称存在重复时，使用 app_name 设置 namespace，避免 reverse url 时因 url 同名造成混淆
# 由于 Appointment 代码过于古老，命名不规范，故使用 app_name
# 在 reverse 时，使用 `reverse('Appointment:view_name)`
app_name = 'Appointment'

urlpatterns = [
    # 认证
    path('', views.index, name='root'),
    path('index', views.index, name='index'),
    path('logout', views.logout, name='logout'),
] + [
    # 账户
    path('admin-index.html', views.account, name='account'),
    path('admin-credit.html', views.credit, name='credit'),
    path('agreement', views.agreement, name='agreement'),
] + [
    # 预约
    path('arrange_time', views.arrange_time, name='arrange_time'),
    path('arrange_talk', views.arrange_talk_room, name='arrange_talk'),
    path('check_out', views.checkout_appoint, name='checkout_appoint'),
    path('cancelAppoint', views.cancelAppoint, name='cancelAppoint'),
    path('renewLongtermAppoint', views.renewLongtermAppoint,
         name='renewLongtermAppoint'),
    path('review', views.review, name='review'),
] + [
    # 硬件对接
    path('door_check', hardware_api.door_check, name='door_check'),
    path('camera-check', hardware_api.cameracheck, name='cameracheck'),
    path('display_getappoint', hardware_api.display_getappoint,
         name='display_getappoint'),
    path('summary', summary.summary, name='summary'),
    path('summary/2021', summary.summary2021, name='summary2021'),
    path('summary/2023', summary.summary2023, name='summary2023'),
]
