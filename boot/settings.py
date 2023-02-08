import os

from boot import config
from boot.config import LazySetting


class __Config(config.Config):
    """Configurables in django framework w.r.t the project.

    For example, login url is not configurable and should be hard-coded.
    """

    def __init__(self, dict_prefix: str = ''):
        super().__init__(dict_prefix)
        self.db_host = os.getenv('DB_HOST') or LazySetting(
            'db/NAME', default='localhost')
        self.db_user = os.getenv('DB_USER') or LazySetting(
            'db/USER', default='root')
        self.db_password = os.getenv('DB_PASSWORD') or LazySetting(
            'db/PASSWORD', default='secret')
        self.db_name = os.getenv('DB_DATABASE') or LazySetting(
            'db/DATABASE', default='yppf'
        )
        self.secret_key = 'k+8az5x&aq_!*@%v17(ptpeo@gp2$u-uc30^fze3u_+rqhb#@9'
        if not config.DEBUG:
            self.secret_key = os.environ['SESSION_KEY']
        self.db_port = os.getenv('DB_PORT')
        self.static_dir = os.getenv('DB_PORT') or config.BASE_DIR
        # self.installed_apps = []      # Maybe useful in the future


__configurables = __Config('django')


# SECURITY
# WARNING: don't run with debug turned on in production!
DEBUG = config.DEBUG
SECRET_KEY = "k+8az5x&aq_!*@%v17(ptpeo@gp2$u-uc30^fze3u_+rqhb#@9"
ALLOWED_HOSTS = ["*"]
AUTH_USER_MODEL = 'generic.User'
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.AllowAllUsersModelBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
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
    "generic",
    "app",
    "Appointment",
    'dm',
    "scheduler",
    "yp_library",
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
        "NAME": __configurables.db_name,
        "HOST": __configurables.db_host,
        "PORT": __configurables.db_port,
        "USER": __configurables.db_user,
        "PASSWORD": __configurables.db_password,
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


# 两类文件的URL配置并不会自动生成，在urls.py查看开发环境如何配置
# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(__configurables.static_dir, "static")
# Media files (user uploaded imgs)
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(__configurables.static_dir, "media/")


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
