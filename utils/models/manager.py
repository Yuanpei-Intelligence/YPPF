'''
相关对象的访问器。与django.models.manager使用相同的类型提示信息。
它们只可用于提示，应以字符串形式标注::

    class Pool(models.Model):
        poolitem_set: 'models.manager.RelatedManager[PoolItem]'

        @property
        def users(self) -> 'models.manager.ManyRelatedManager[User]':
            return self.users

当一个字段定义两个模型之间的关系时，每个模型类提供
访问其他模型类的相关实例的属性（除非已使用 related_name='+' 禁用反向访问器）。

访问器作为描述符实现，以便自定义访问和分配。该模块定义了描述符类。

前向访问器遵循外键。 反向访问器追溯它们。 例如，使用以下模型::

    class Parent(Model):
        pass

    class Child(Model):
        parent = ForeignKey(Parent, related_name='children')

 ``child.parent``是向前的多对一关系. ``parent.children`` 是反向多对一关系。

'''

from django.db.models import Manager
from django.db.models.fields.related_descriptors import (
    create_reverse_many_to_one_manager,
    create_forward_many_to_many_manager,
)

__all__ = [
    'RelatedManager',
    'ManyRelatedManager',
]


class RelatedManager(Manager):
    '''查看``create_reverse_many_to_one_manager``以获取更多实现细节'''
    pass

class ManyRelatedManager(RelatedManager):
    '''查看``create_forward_many_to_many_manager``以获取更多实现细节'''
    pass
