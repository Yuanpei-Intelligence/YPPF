"""
Provides a uniform way to read settings from *config.json*. 

假设要在名为 app_name 的 app 下加入新的设置，可按以下步骤：
1. 在 *config.json* 中添加相应设置
2. 在 *app_name/config.py* 中，将新设置添加到 `class AppnameConfig(Config)` 中
3. 在要用到的文件中引用 from app_name.config import CONFIG

Env variables are not taken into consideration since they are relatively rare,
and do not share the hierarchy structure.

As for now, only part of django configuration and "service" can be set with env
vars.
"""

import os
import json
from typing import Optional, Any, Callable, Generic, TypeVar, Dict, overload


DEBUG = True  # WARNING! TODO: Set to False in main branch
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    """
    为各个 app 提供的 Config 基类

    使用方法可参考 scheduler/config.py
    """

    with open('./config.json') as f:
        __root_conf = json.load(f)

    def __init__(self, dict_prefix: str = ''):
        if dict_prefix:
            self.__root_conf = self.__root_conf[dict_prefix]

    def __getattribute__(self, __name: str) -> Any:
        attr = object.__getattribute__(self, __name)
        if isinstance(attr, LazySetting):
            object.__setattr__(self, __name, attr.resolve(self.__root_conf))
        return object.__getattribute__(self, __name)

    def _lazy_setting_get_conf(self):
        '''仅供LazySetting使用'''
        return self.__root_conf


T = TypeVar('T')


class LazySetting(Generic[T]):
    '''
    延迟加载的配置项

    在Config类中作为属性定义，如：
    ```
    class AppConfig(Config):
        # 由语言服务器自动推断类型
        value = LazySetting('value', default=0)
        op1 = LazySetting('op1', int)
        op2 = LazySetting('op2', int, default=0)
    ```
    上述代码在访问时会自动计算并缓存结果：
    ```
    config = AppConfig()
    # 自动推断的类型
    config.value: int
    config.op1: int | None
    config.op2: int
    ```
    '''

    def __init__(self, path: str, trans_fn: Optional[Callable[[Any], T]] = None,
                 default: T = None) -> None:
        '''
        :param path: 配置路径，以'/'分隔
        :type path: str
        :param trans_fn: 转换函数，将配置值转换为最终值，defaults to None
        :type trans_fn: Callable[[Any], T], optional
        :param default: 默认值, defaults to None
        :type default: T, optional
        '''
        self.path = path
        self.trans_fn = trans_fn
        self.default = default

    # 为了支持更准确的泛型类型提示，重载 __new__ 方法
    # 无参数时，标注为Any
    @overload
    def __new__( # type: ignore
        self,
        path: str,
    ) -> 'LazySetting[Any | None]': ...
    @overload
    def __new__( # type: ignore
        self,
        path: str,
        trans_fn: Optional[Callable[[Any], T]] = ...,
        default: T = ...,
    ) -> 'LazySetting[T]': ...
    # 必须要有这个重载，否则会报错
    def __new__(cls, *args, **kwargs): # type: ignore
        return super().__new__(cls)

    @overload
    def __get__(self, instance: None, owner: Any) -> 'LazySetting[T]': ...
    @overload
    def __get__(self, instance: Config, owner: Any) -> T: ...
    @overload
    def __get__(self, instance: Any, owner: Any) -> 'LazySetting[T]': ...
    def __get__(self, instance: Any, owner: Any):
        '''作为类属性时，访问时会调用此方法，提供更好的类型提示'''
        if instance is None or not isinstance(instance, Config):
            return self
        # 此处假设一个类只会有一个实例，否则需要建立dict来存储不同实例的值
        if hasattr(self, '_data'):
            return self._data
        self._data = self.resolve(instance._lazy_setting_get_conf())
        return self._data

    def resolve(self, d: dict[str, Any]) -> T:
        value = self.__walk_dict(self.path, d)
        if value is None:
            return self.default
        if self.trans_fn is not None:
            value = self.trans_fn(value)
        return value

    @staticmethod
    def __walk_dict(path: str, d: Dict[str, Any]) -> Optional[T]:
        paths = path.strip("/").split("/")
        current_dir = d
        for query in paths:
            if query in current_dir:
                current_dir = current_dir[query]
            else:
                return None
        return current_dir  # type: ignore


class GlobalConfig(Config):
    base_url = LazySetting('base_url', default='http://localhost:8000')
    hash_salt = LazySetting('hash_salt', default='salt')
    acadamic_year = LazySetting('acadamic_year', int)
    semester = LazySetting('semester')

    def __init__(self, dict_prefix: str = 'global'):
        super().__init__(dict_prefix)
        def _to_list_str(raw: str | list) -> list[str]:
            if isinstance(raw, str):
                raw = raw.replace(' ', '').split(',')
            return list(map(str, raw))
        self.debug_stuids: list[str] = LazySetting(
            'debug_stuids', _to_list_str, [])           # type: ignore

        assert self.semester is not None

GLOBAL_CONF = GlobalConfig()
