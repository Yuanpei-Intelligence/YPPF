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
    """
    """

    def __init__(self, path: str, trans_fn: Optional[Callable[[Any], T]] = None,
                 default: T = None) -> None:
        self.path = path
        self.trans_fn = trans_fn
        self.default = default

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

    def __init__(self, dict_prefix: str = 'global'):
        super().__init__(dict_prefix)
        self.base_url: str = LazySetting(
            'base_url', default='http://localhost:8000')  # type: ignore
        self.hash_salt: str = LazySetting(
            'hash_salt', default='salt')              # type: ignore
        self.acadamic_year: int = LazySetting(
            'acadamic_year', int)                     # type: ignore
        self.semester: str = LazySetting('semester')  # type: ignore

        assert self.semester is not None


GLOBAL_CONF = GlobalConfig()
