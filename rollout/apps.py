from django.apps import AppConfig


class RolloutAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rollout"
    verbose_name = "灰度发布"
