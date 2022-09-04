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
from Appointment import views
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
    path('renewLongtermAppoint', views.renewLongtermAppoint, name='renewLongtermAppoint'),
    path('review', views.review, name='review'),
] + [
    # 硬件对接
    path('door_check', views.door_check, name='door_check'),
    path('camera-check', views.cameracheck, name='cameracheck'),
    path('display_getappoint', views.display_getappoint, name='display_getappoint'),
    path('summary', views.summary, name='summary'),
    path('summary2', views.summary2, name='summary2'),
]
