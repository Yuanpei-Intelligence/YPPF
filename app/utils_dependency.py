'''
utils_dependency.py

内容
----
- 常量和设置
- log记录
- 消息传递
- 加密
- 原子化操作

utils
-----
- 任何视图文件应尽量首先导入本依赖，并按下列顺序导入其他所需模块
- 从app.models导入所有视图依赖的模型类
- 不同于views, utils文件之间可以相互依赖，但**只能**导入所有依赖的变量或函数
    - 例如`from app.utils import get_person_or_org`取代`import app.utils`
    - 若有必要，导入所有的其它工具函数，不能成环，如comment_utils可能依赖通知
    - 再导入必要的通用工具函数，如utils内部函数
- 导入其它内部的模块，视图文件除外
- 导入Python自带或没有子目录的简单外部依赖模块
- 导入Django等复杂的依赖模块
- 在以上导入完成后，声明文件内所需的全局变量

- 推荐随后定义__all__列表，声明所有对外的接口

依赖关系
-------
- 依赖于constants, log和global_messages

@Date 2022-01-17
'''
from app.constants import *
from app import log
from boottest.global_messages import (
    MESSAGECONTEXT,
    wrong,
    succeed,
)
import boottest.global_messages as my_messages

# 内部加密用，不同utils文件不共享，可能被对应的views依赖
from boottest.hasher import MyMD5PasswordHasher, MySHA256Hasher

# 针对模型的工具函数常常需要原子化操作
from django.db import transaction

# 一些类型信息提示
from typing import Union, Iterable
from django.db.models import QuerySet
# 兼容Django3.0及以下版本
if not hasattr(QuerySet, '__class_getitem__'):
    QuerySet.__class_getitem__ = classmethod(lambda cls, *args, **kwargs: cls)
ClassifiedUser = None
try:
    0 / 0
    # 引发错误，但IDE不会发现，这使得ClassifiedUser被认为是一个有效值
    # 以下代码并不会实际执行，也就并不会实际导入
    from app.models import NaturalPerson, Organization
    ClassifiedUser = Union[NaturalPerson, Organization]
except:
    pass
