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
- 从app.models导入所有视图依赖的模型类，User除外
- 随后导入所有类相关的工具函数文件，如activity_utils
- 再导入必要的通用工具函数，如utils内部函数，使用不频繁时请直接使用本文件的utils模块
- 导入其它内部的模块，除了views
- 导入Python自带或没有子目录的简单外部依赖模块
- 导入Django等复杂的依赖模块
- 在以上导入完成后，声明文件内所需的全局变量

- 推荐随后定义__all__列表，包含所有待呈现的视图名(str)

依赖关系
-------
- 依赖于constants, log和global_messages
- 依赖于boottest.hasher的哈希类定义
- 灵活依赖于utils

@Date 2022-01-17
'''
from app.constants import *
from boottest.global_messages import (
    wrong,
    succeed,
    message_url,
    append_query,
)
import boottest.global_messages as my_messages
from app import log
from app import utils

# 内部加密用，不同views文件不共享，如果依赖的utils使用了，尽量从utils导入
from boottest.hasher import MyMD5PasswordHasher, MySHA256Hasher

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib.auth.models import User
from django.views.decorators.http import require_POST, require_GET

# 用于重定向的视图专用常量
EXCEPT_REDIRECT = HttpResponseRedirect(message_url(wrong('出现意料之外的错误, 请联系管理员!')))
