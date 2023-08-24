"""元培书房 URL

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
from yp_library import views

urlpatterns = [
    path('', views.WelcomeView.as_view(), name="libWelcome"),
    path('search/', views.SearchView.as_view(), name="libSearch"),
]
