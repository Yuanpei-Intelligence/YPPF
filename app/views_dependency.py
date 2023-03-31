'''
views_dependency.py

内容
----
- 常量和设置
- 视图间的通信参数
- 权限和加密
- 请求和回应
- 可以放心全部导入，只有最基础的包体内容放到了命名空间中

views
-----
- 任何视图文件应尽量首先导入本依赖，并按下列顺序导入其他所需模块
- 导入Python自带或没有子目录的简单外部依赖模块
- 导入Django等复杂的依赖模块
- 从app.models导入所有视图依赖的模型类，User除外
- 随后导入所有类相关的工具函数文件，如activity_utils
- 再导入必要的通用工具函数，如utils内部函数，使用不频繁时请直接使用本文件的utils模块
- 导入其它内部的模块，除了views
- 在以上导入完成后，声明文件内所需的全局变量

- 推荐随后定义__all__列表，包含所有待呈现的视图名(str)

依赖关系
-------
- 依赖于 utils
- 依赖于 app.constants

@Date 2022-01-17
'''
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_POST, require_GET

from utils.hasher import MySHA256Hasher
import utils.global_messages as my_messages
from utils.global_messages import (
    wrong,
    succeed,
    message_url,
    append_query,
)
from utils.http.dependency import *
from utils.views import *
from generic.models import User
from app.config import *
from app import utils
from app.log import logger


# 不应导出，接口内部使用
from django.core.exceptions import ImproperlyConfigured as _ImproperlyConfigured
from app.log import ProfileLogger as _ProfileLogger
class ProfileTemplateView(SecureTemplateView):
    request: UserRequest
    PrepareType = SecureView.NoReturnPrepareType | None

    need_prepare: bool = True
    logger_name: str = 'ProfileError'
    page_name: str

    def dispatch_prepare(self, method: str):
        return self.default_prepare(method, return_needed=False,
                                    prepare_needed=self.need_prepare)

    def render(self, **kwargs):
        if not hasattr(self, 'page_name'):
            raise _ImproperlyConfigured('page_name is not defined!')
        self.extra_context['bar_display'] = utils.get_sidebar_and_navbar(
            self.request.user, self.page_name)
        return super().render(**kwargs)

    def get_logger(self):
        return _ProfileLogger.getLogger(self.logger_name)


class ProfileJsonView(SecureJsonView):
    request: UserRequest
    PrepareType = SecureView.NoReturnPrepareType | None

    need_prepare: bool = True
    logger_name: str = 'ProfileAPIerror'

    def dispatch_prepare(self, method: str):
        return self.default_prepare(method, return_needed=False,
                                    prepare_needed=self.need_prepare)

    def json_response(self, extra_data = None, **kwargs):
        _ProfileLogger.getLogger('recording').info('json_response')
        return super().json_response(extra_data, **kwargs)

    def get_logger(self):
        return _ProfileLogger.getLogger(self.logger_name)
