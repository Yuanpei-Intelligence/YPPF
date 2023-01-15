'''
为各个app提供设定

e.g. 
假设要在名为 app_name 的app下加入新的设置，可按以下步骤：
1. 在 local_json_template.json 中添加设置
2. 在 app_name/config.py 中，将新设置添加到 class AppnameConfig() 中，详见 Config()
3. 在要用到的文件中引用 from app_name.config import CONFIG
'''
from typing import Dict, Any, Callable, Optional
import json
import os

__all__ = ["LazySetting", "Setting", "Config"]


def _load_local_json(path="./local_json.json"):
    with open(path, encoding="utf_8") as f:
        local_dict = json.load(f)
    return local_dict


local_dict: Dict[str, Any] = _load_local_json()


def _query_setting(path: str, dic: Dict[str, Any] = local_dict,
                   fuzzy_lookup: bool = False) -> Optional[Any]:
    """TODO: Add doc
    """
    current_dir = dic
    paths = path.replace("\\", "/").replace("__", "/").strip("/").split("/")
    if len(paths) and paths[0] == "":
        paths = paths[1:]
    for query in paths:
        if fuzzy_lookup and not query:
            continue
        if query in current_dir.keys():
            current_dir = current_dir[query]
        elif fuzzy_lookup and query.lower() in current_dir.keys():
            current_dir = current_dir[query.lower()]
        elif fuzzy_lookup and query.upper() in current_dir.keys():
            current_dir = current_dir[query.upper()]
        else:
            return None
    return current_dir


def optional(type):
    """产生用于可选设置的转换函数，None被直接返回"""
    def _trans_func(value):
        if value is None:
            return None
        return type(value)
    return _trans_func


class LazySetting:
    '''
    Lazy从环境变量/配置文件读入设置，用法和 `get_setting` 相似
    e.g.
    1. 在各个 app/config.py 中作为 AppnameConfig class 的 attr。见 Config
    2. 在文件中手动读入（不建议），如 xxx = LazySetting("path/to/LazySetting").get()
    找不到配置不会有异常，transfer function 可能会出现异常
    '''

    def __init__(self, path: str,
                 trans_func: Optional[Callable[[Optional[Any]], Any]] = None,
                 default=Optional[Any]) -> None:
        self.path = path
        self.trans_func = trans_func
        self.default = default

    def get(self) -> Optional[Any]:
        """读取实际值，如果找不到返回 None，转换过程中可能抛出异常"""
        value = os.getenv(self.path) or _query_setting(self.path)
        if value is None:
            return self.default
        if self.trans_func is not None:
            value = self.trans_func(value)
        return value


class Setting(LazySetting):
    '''
    和LazySetting的实现完全相同，只是会在 Config init 时读入。详见 Config
    '''
    pass


class Config:
    '''
    为各个 app 提供的 Config 基类
    e.g.
    ``` appname/config.py
        from utils.config *
        class AppnameConfig(Config):
            def __init__(self):
                self.aaa = Setting("path/to/setting")
                self.xxx = LazySetting("path/to/lazysetting")
                self.init_setting()
        CONFIG = AppnameConfig()
    ```
    '''

    def init_setting(self):
        for __name in self.__dir__():
            if isinstance(object.__getattribute__(self, __name), Setting):
                setattr(self, __name, getattr(self, __name))

    def get_setting(self, path: str, trans_func=None, default=None) -> Any:
        return LazySetting(path, trans_func, default).get()

    def __getattribute__(self, __name: str) -> Any:
        attr = object.__getattribute__(self, __name)
        if isinstance(attr, LazySetting):
            object.__setattr__(self, __name, attr.get())
        return object.__getattribute__(self, __name)
