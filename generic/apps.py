from django.apps import AppConfig


class GenericConfig(AppConfig):
    # 初次生成时使用AutoField与auth模块保持一致
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'generic'
    verbose_name = '0.通用模块'
