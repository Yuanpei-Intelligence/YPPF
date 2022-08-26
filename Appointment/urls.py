"""YPUnderground URL Configuration

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
"""
from django.urls import path
from Appointment import views
app_name = 'Appointment'

urlpatterns = [
    # 学生操作
    #path('get-student', views.getStudent, name='getStudent'),
    # 房间操作
    #path('get-room', views.getRoom, name='getRoom'),
    # 预约操作
    #path('add-appoint', views.addAppoint, name='addAppoint'),
    path('cancel-appoint', views.cancelAppoint, name='cancelAppoint'),
    # path('get-appoint', views.getAppoint, name='getAppoint'),
    #path('get-violated', views.getViolated, name='getViolated'),
    #path('check-time', views.checkTime, name='checkTime'),

    # 部署后需要删除的操作
    #path('add-student', views.addStudent, name='addStudent'),
    #path('add-room', views.addRoom, name='addRoom'),

    # csrf验证操作（待完善）
    #path('get-csrf', views.getToken, name='getToken'),
    path('',views.index,name="root"),
    path('index',views.index,name="index"),
    path('agreement',views.agreement,name="agreement"),
    path('arrange_time',views.arrange_time,name='arrange_time'),
    path('check_out',views.check_out,name='check_out'),
    path('admin-index.html', views.admin_index, name='admin_index'), #added by wxy
    path('admin-credit.html',views.admin_credit, name='admin_credit'),#added by wxy
    path('cancelAppoint',views.cancelAppoint,name="cancelAppoint"),
    path('logout',views.logout,name="logout"),
    path('arrange_talk',views.arrange_talk_room,name='arrange_talk'),
    # added by wxy
    # 硬件对接部分的网页
    path('door_check', views.door_check, name='door_check'),
    path('camera-check',views.cameracheck,name='cameracheck'),
    path('display_getappoint',views.display_getappoint,name='display_getappoint'),
    #path('img_get_func',views.img_get_func,name='img_get_func'),    # 获取头像位置的函数
    path('summary', views.summary, name='summary'),
]
