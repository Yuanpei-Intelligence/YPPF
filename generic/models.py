'''
models.py

- 自定义用户模型
    - 任何应用模型如果有用户模型关系，都应该导入，并提供导出
    - 任何应用都应从其models文件导入User模型
- 用户管理器
    - 提供管理方法，并保存记录

注意事项
- 如果在使用本应用前已经迁移过，且想保留用户数据，请务必参考readme.md

@Author pht
@Date 2022-08-19
'''
from django.db import models
from django.contrib.auth.models import AbstractUser, UserManager

__all__ = [
    'User',
]

class User(AbstractUser):
    class Meta:
        db_table = 'auth_user'
        pass
