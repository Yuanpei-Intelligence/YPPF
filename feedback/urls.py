from django.urls import path

from feedback import views

# reverse 函数中是否使用了该 app_name 设置的 namespace 仍需检查，如不必要可将该变量删去
app_name = 'feedback'

urlpatterns = [
    # 反馈中心
    path("feedback/", views.feedbackWelcome, name="feadbackWelcome"),
    path("modifyFeedback/", views.modifyFeedback, name="modifyFeedback"),
    path("viewFeedback/<str:fid>", views.viewFeedback, name="viewFeedback"),
]
