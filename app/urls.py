from django.urls import path,re_path
from django.conf.urls.static import static
from . import views
from django.conf import settings
urlpatterns = [
     path('', views.index, name='index'),
     path('index/',views.index, name='index'),
     path('stuinfo/',views.stuinfo, name='stuinfo'),
     path('stuinfo/<str:queryname>/',views.stuinfo, name='stuinfo'),
     path('register/',views.register, name='register'),
     path('login/',views.index,name='index'),
     path('logout/',views.logout, name='logout'),
     #path('org/',views.org, name='org'),
     path('modpw/',views.modpw, name='modpw'),
     path('test/',views.test,name='test'),
     #path('loaddata/',views.load_data, name='load_data'),
     path('user_account_setting/',views.account_setting, name='user_account_setting'),
     path('search/',views.search,name='search'),
     path('minilogin',views.miniLogin,name='minilogin'),
     re_path('^org([0-9]{2})',views.org_spec,name='org_spec'),
     path('getStuImg',views.get_stu_img,name='get_stu_img'),
            ]
if settings.DEBUG:
     urlpatterns += static(settings.MEDIA_URL,document_root=settings.MEDIA_ROOT)