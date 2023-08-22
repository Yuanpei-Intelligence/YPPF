from django.urls import path

from feedback import views


urlpatterns = [
    # 反馈中心
    path("feedback/", views.feedbackWelcome, name="feadbackWelcome"),
    path("modifyFeedback/", views.modifyFeedback, name="modifyFeedback"),
    path("viewFeedback/<str:fid>", views.viewFeedback, name="viewFeedback"),
]
