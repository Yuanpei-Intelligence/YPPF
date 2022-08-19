## 如何在项目中期切换到自定义用户模型

### 测试流程
1. 创建有User依赖的模型

2. 迁移

3. 添加数据

### 迁移流程
本项目已写好了主要迁移内容，操作请参考**完整迁移流程**
1. 首先将2,3步恢复到指定状态

2. 执行7,8,9步

3. 根据需要执行第11步或直接迁移

### 完整迁移流程
1. 创建新应用（下文中默认新应用名为generic）
   `python manage.py startapp generic`
2. 向新应用的models文件添加以下内容
```python
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    class Meta:
        db_table = 'auth_user'
```

3. 检查apps中默认自增字段设置（否则可能生成错误的迁移文件）
    `default_auto_field = 'django.db.models.AutoField'`

4. 添加到INSTALLED_APP（settings.py中）
```python
INSTALLED_APPS = [
    ...,
    'generic',
]
```
5. 设置认证User模型（settings.py中，建议放在INSTALLED_APPS后）
   `AUTH_USER_MODEL = 'generic.User'`
   否则创建初始迁移可能报错
   
6. 将所有原先的User模型关系改为新的User或`settings.AUTH_USER_MODEL`
   否则创建初始迁移可能报错
   
7. 创建初始迁移（此时User必须只包含了Meta信息而没有其它字段，且apps设置正确）
   `python manage.py makemigrations generic`
   创建迁移名应为0001_initial.py，与第10步保持一致
   如果不是初始迁移，请检查是否出现异常，删除迁移文件后重试
   
8. 标记迁移已应用
   - 数据库
      在django_migrations表添加一行(generic, 0001_initial, CURRENT_TIMESTAMP)
   - django（不可用，会提示InconsistentMigrationHistory，admin迁移已应用）
      `python manage.py migrate generic --fake-initial`
   
9. 纠正contenttype表
   - 在数据库中，将django_content_type表中app_label列为auth且model列为user的行app_label改为generic
   
   - 或者运行
   
       ```python
       from django.contrib.contenttypes.models import ContentType
       my_app_label = # 'generic'
       ContentType.objects.filter(app_label='auth', model='user').update(app_label=my_app_label)
       ```
   
10. 补充其它自定义功能

    - 添加后台（替换模型后User后台自动失效）

        ```python
        from django.contrib.auth.admin import UserAdmin
        
        admin.site.register(User, UserAdmin)
        ```

    - 自定义管理器
    
        ```python
        from django.contrib.auth.models import UserManager as _UserManager
        class UserManager(_UserManager):
            pass
        ```
    
11. 重命名用户表或修改自增字段

    ```python
    class User(AbstractUser):
        class Meta:
            # db_table = 'auth_user'
            pass
    ```

    修改后，运行

    ```shell
    python manage.py makemigrations generic --name rename_user_table
    python manage.py migrate generic
    ```

    若有必要可以将default_auto_field改为BigAutoField，然后类似操作


### 参考
- [How to Switch to a Custom Django User Model Mid-Project](https://www.caktusgroup.com/blog/2019/04/26/how-switch-custom-django-user-model-mid-project/)
- [Django: Document how to migrate from a built-in User model to a custom User model](https://code.djangoproject.com/ticket/25313)