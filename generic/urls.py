from django.urls import path

from generic import views

urlpatterns = [
    # 登录和验证
    path('', views.Index.as_view(), name=''),
    path('index/', views.Index.as_view(), name='index'),
    path('login/', views.Index.as_view(), name='login'),
    path('logout/', views.Logout.as_view(), name='logout'),
    path('healthcheck/', views.healthcheck, name='healthcheck'),
]
