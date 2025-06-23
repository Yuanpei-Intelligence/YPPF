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
from typing import Any

from utils.config import Config, LazySetting
from utils.config.cast import mapping
from utils.hasher import MySHA256Hasher
from utils.models.semester import Semester


__all__ = [
    'absolute_path',
    'DEBUG',
    'BASE_DIR',
    'ROOT_CONFIG',
    'GLOBAL_CONFIG',
]


DEBUG = 'DEBUG' in os.environ and os.environ['DEBUG'].lower() == 'true'
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def absolute_path(path: str) -> str:
    '''
    Sphinx生成文档时执行目录是错误的，所以要用这个函数

    :param path: 相对于项目根目录的路径
    :type path: str
    :return: 绝对路径
    :rtype: str
    '''
    if not path.startswith('./'):
        return path
    return os.path.join(BASE_DIR, path[2:])


def _init_config(path='./config.json', encoding: str = 'utf8') -> dict[str, Any]:
    with open(absolute_path(path), encoding=encoding) as f:
        return json.load(f)


ROOT_CONFIG = _init_config()


class GlobalConfig(Config):
    base_url = LazySetting('base_url', default='http://localhost:8000')
    salt = LazySetting('hash_salt', default='salt')
    hasher = LazySetting(salt, MySHA256Hasher, type=MySHA256Hasher)
    temporary_dir = LazySetting('tmp_dir', default='tmp')
    official_uid = LazySetting('official_user', default='zz00000')

    # Deprecated Settings
    acadamic_year = LazySetting('acadamic_year', type=int)
    semester = LazySetting('semester', Semester.get, type=Semester)
    debug_stuids = LazySetting('debug_stuids', mapping(list, str), [])


GLOBAL_CONFIG = GlobalConfig(ROOT_CONFIG, 'global')
