import os

from utils.config import Config, LazySetting
from boot import config


# 只有全大写的变量才会被django读取，其它名称放心使用即可
class SettingConfig(Config):
    """Configurables in django framework w.r.t the project.

    For example, login url is not configurable and should be hard-coded.
    """
    db_host = os.getenv('DB_HOST') or LazySetting(
        'db/HOST', default='localhost')
    db_user = os.getenv('DB_USER') or LazySetting('db/USER', default='root')
    db_password = os.getenv('DB_PASSWORD') or LazySetting(
        'db/PASSWORD', default='secret')
    db_name = os.getenv('DB_DATABASE') or LazySetting(
        'db/NAME', default='yppf')
    db_port = os.getenv('DB_PORT') or LazySetting('db/PORT', default='3306')

    secret_key = ('k+8az5x&aq_!*@%v17(ptpeo@gp2$u-uc30^fze3u_+rqhb#@9'
                  if config.DEBUG else os.environ['SESSION_KEY'])
    static_dir = os.getenv('STATIC_DIR') or config.BASE_DIR


_configurables = SettingConfig(config.ROOT_CONFIG, 'django')


# SECURITY
# WARNING: don't run with debug turned on in production!
DEBUG = config.DEBUG
SECRET_KEY = _configurables.secret_key
ALLOWED_HOSTS = ["*"]
AUTH_USER_MODEL = 'generic.User'
AUTHENTICATION_BACKENDS = [
    "generic.backend.BlacklistBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator", },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator", },
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator", },
]


# URL Config
LOGIN_URL = '/'
ROOT_URLCONF = "boot.urls"
WSGI_APPLICATION = "boot.wsgi.application"


# Application definition & Middlewares
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_apscheduler",
    "rest_framework",
    "generic",
    "semester",
    "record",
    "app",
    "Appointment",
    'dm',
    "scheduler",
    "yp_library",
    "questionnaire",
    "dormitory",
    "feedback",
    "achievement",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # 'django.middleware.csrf.CsrfViewMiddleware',
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# TODO: Fix this
CSRF_TRUSTED_ORIGINS = [config.GLOBAL_CONFIG.base_url]

# Templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(config.BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.media",
            ],
        },
    },
]


# Database
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATABASES = {
    # 使用自己的数据库的时候请修改这里的配置
    # 注意需要先创建数据库
    # mysql -u root -p
    # create database db_dev charset='utf8mb4';
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": _configurables.db_name,
        "HOST": _configurables.db_host,
        "PORT": _configurables.db_port,
        "USER": _configurables.db_user,
        "PASSWORD": _configurables.db_password,
        'OPTIONS': {
            'charset': 'utf8mb4',
            #     "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
        'TEST': {
            'CHARSET': 'utf8',
            'COLLATION': 'utf8_general_ci',
        },
    },
}


# 两类文件URL配置在生产环境失效，在urls.py查看开发环境如何配置

# Static files (CSS, JavaScript, Images)
# staticfiles应用默认只搜寻STATICFILES_DIRS和%APP%/static目录，不符合项目需求
# 由于使用统一static，无需支持collectstatic，废弃STATIC_ROOT
STATIC_URL = "/static/"
STATICFILES_DIRS = (os.path.join(_configurables.static_dir, "static/"),)

# Media files (user uploaded imgs)
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(_configurables.static_dir, "media/")


# Disordered settings
LANGUAGE_CODE = "zh-Hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
# 是否启用数据的本地化格式，如果开启将会导致django以他认为的本地格式显示后台数据
# 主要表现为时间的呈现形式变为年/月/日 小时:分钟 关闭时则为yyyy-mm-dd HH:MM:SS
# 关闭后，后台才能正常显示秒并进行修改
# 本地化有其他副作用，比如其他前端呈现的兼容
# 不想关闭可以调整django/conf/locale/zh_Hans/format.py中的TIME_INPUT_FORMATS顺序
# 而该文件中的其它变量被证明对后台呈现无效
# https://docs.djangoproject.com/zh-hans/3.1/ref/settings/#use-i18n
USE_L10N = True
# USE_TZ限制了Datetime等时间Field被存入数据库时是否必须包含时区信息
# 这导致定时任务和常用的datetime.now()等无时区时间在存入时被强制-8h转化为UTC时间
# 从而使数据库可读性差，存储前需要强制增加时区信息，且发送消息容易出错
# 从数据库取出的数据将是有时区信息的，几乎与datetime.now()不可比
USE_TZ = False

REST_FRAMEWORK = {
    # Use Django's standard `django.contrib.auth` permissions,
    # or allow read-only access for unauthenticated users.
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.DjangoModelPermissionsOrAnonReadOnly'
    ]
}
