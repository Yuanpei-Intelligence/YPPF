import types
from typing import (
    Optional, Any, Callable, Generic,
    TypeVar, Type, Literal, overload
)

from django.core.exceptions import ImproperlyConfigured


class Config:
    """
    为各个 app 提供的 Config 基类
    """
    def __init__(self, source: 'Config | dict[str, Any]', dict_prefix: str = ''):
        if isinstance(source, Config):
            self._root_conf = source._root_conf
        elif isinstance(source, dict):
            self._root_conf = source
        if dict_prefix:
            self._root_conf: dict[str, Any] = self._root_conf[dict_prefix]


T = TypeVar('T')


class LazySetting(Generic[T]):
    '''
    延迟加载的配置项

    在Config类中作为属性定义，如::

        class AppConfig(Config):
            # 由语言服务器自动推断类型
            value = LazySetting('value', default=0)
            op1 = LazySetting('op1', int)
            op2 = LazySetting('op2', int, default=0)
            # 也可以使用type指定类型，写法建议参考`LazySetting.checkable_type`的文档
            assert_d = LazySetting('value/dict', type=dict)
            i_or_s = LazySetting('value/i_or_s', type=(int, str))
            assert_ls = LazySetting('value/ls', type=list[str])
            tuple = LazySetting('value/tuple', type=tuple[int, str])

    上述代码在访问时会自动计算并缓存结果::

        config = AppConfig()
        # 自动推断的类型
        config.value: int
        config.op1: int | None
        config.op2: int
        # 用type指定的类型
        config.assert_d: dict
        config.i_or_s: int | str    # 检查是否为int或str
        list[str], tuple[int, str]  # 检查是否为列表，元组等，不检查元素类型

    :raises ImproperlyConfigured: 配置最终值不匹配期望类型
    '''
    class TypeCheck: '默认类型检查，忽略默认值'

    _real_type = type
    def __init__(self, source: 'str | LazySetting[Any]', /,
                 trans_fn: Optional[Callable[[Any], T]] = None,
                 default: T = None, *,
                 type: Optional[Type[T|TypeCheck] | tuple[Type[T], ...]] = None) -> None:
        '''
        :param source: 配置路径或来源，路径以'/'分隔，加载项应在同一类内使用，否则行为未定义
        :type source: str | LazySetting
        :param trans_fn: 转换函数，将配置值转换为最终值，defaults to None
        :type trans_fn: Callable[[Any], T], optional
        :param default: 默认值, defaults to None
        :type default: T, optional
        :param type: 最终值类型，参考`checkable_type`的文档，
                     None时按其他参数推断，TypeCheck时忽略default，defaults to None
        :type type: Type[T] | tuple[Type[T], ...], optional
        '''
        self.source = source
        self.trans_fn = trans_fn
        self.default = default
        if type is None or type is LazySetting.TypeCheck:
            if default is not None and not isinstance(default, self._real_type):
                self.type = self.checkable_type(self._real_type(default))
            elif isinstance(trans_fn, self._real_type):
                or_none = type is None and default is None
                self.type = self.checkable_type(trans_fn, or_none=or_none)
            else:
                self.type = None
        else:
            self.type = self.checkable_type(type)

    # 为了支持更准确的泛型类型提示，重载 __new__ 方法
    # 无参数时，标注为Any
    @overload
    def __new__( # type: ignore
        self,    # type: ignore
        source: str,
    ) -> 'LazySetting[Any | None]': ...
    @overload
    def __new__( # type: ignore
        self,    # type: ignore
        source: 'LazySetting[T]',
    ) -> 'LazySetting[T]': ...
    @overload
    def __new__( # type: ignore
        self,    # type: ignore
        source: 'str | LazySetting',
        trans_fn: Optional[Callable[[Any], T]] = None,
        default: T = None,
    ) -> 'LazySetting[T]': ...
    # TypeCheck时，忽略default=None类型
    @overload
    def __new__( # type: ignore
        self,    # type: ignore
        source: 'str | LazySetting',
        trans_fn: Callable[[Any], T] = ...,
        default: Literal[None] = ...,
        *,
        type: Type[TypeCheck] = ...,
    ) -> 'LazySetting[T]': ...
    # 否则正常检查（但这个时候为什么要传入type=TypeCheck呢？）
    @overload
    def __new__( # type: ignore
        self,    # type: ignore
        source: 'str | LazySetting',
        trans_fn: Optional[Callable[[Any], T]] = ...,
        default: T = ...,
        *,
        type: Type[TypeCheck] = ...,
    ) -> 'LazySetting[T]': ...
    # 提供type参数时，忽略default类型，无论如何都标注为该类型
    @overload
    def __new__( # type: ignore
        self,    # type: ignore
        source: 'str | LazySetting',
        trans_fn: Optional[Callable[[Any], Any]] = ...,
        default: Any = ...,
        *,
        type: Type[T] | tuple[Type[T], ...] = ...,
    ) -> 'LazySetting[T]': ...
    # 必须要有这个重载，否则会报错
    def __new__(cls, *args, **kwargs): # type: ignore
        return super().__new__(cls)

    _CheckableType = type | types.UnionType | tuple['_CheckableType', ...]
    _AvailableType = _CheckableType | None
    def checkable_type(self, type: Any | None, or_none: bool = False) -> _AvailableType:
        '''
        提供可用于检查类型的类，只能进行初级检查(isinstance)

        type应小心以下写法：

        - `list[int] | ...` 极不推荐，无法检查，无法提示，应尽量避免
        - `list[int]` 只能进行简单检查，无法检查列表内的元素类型
        - `int | str`或`Union[int, str]` IDE无法正确提示类型，应使用`(int, str)`
        - `tuple[...]` 默认的JSON解析器会将元组解析为列表，务必提供tuple转化函数

        合法的最终检查类型由以下规则定义（语法略有扩展）::

            FAT := AT | TF                              # final available type
            TF: tuple[CT, ...] := ...                   # tuple of checkable types
            AT := CT | None                             # available type
            CT := RT | UT                               # checkable type
            RT := RNT | RGT                             # raw type
            RNT := RBT | _RNT                           # raw normal type
            RBT := int | str | float | bool             # buildin types
                |  list | dict | set | tuple | ...
            _RNT := types.NoneType | any class          # normal class & NoneType
            RGT := List | Dict | Set | Tuple | ...      # generic types
            UT := UNT | UGA                             # union type
            _N := _NT | None
            _NT := RNT | UNT | Optional[None]
            UNT := _N '|' RNT | _NT '|' None            # union normal types
            _GT := RGT | UGA
            UGA := Optional[CT] | Union[CT, AT{, AT}]   # union generic alias
                |  _GT '|' AT | _N '|' _GT

        :param type: 上文所定义的FAT形式
        :type type: Any | None，如果希望检查，则应该是_CheckableType
        :return: 可用于检查的类型
        :rtype: _CheckableType | None
        '''
        if type is None:
            return None
        if or_none:
            return self._or_none(self.checkable_type(type, or_none=False))

        # 符合FAT定义的_CheckableType都能通过isinstance检查
        try:
            isinstance(None, type)
            return type
        except:
            pass

        # 可能进行了泛型参数化，尝试回退到原始类型
        # __origin__只支持实例化CT, ParamSpecArgs, ParamSpecKwargs
        # 后两种可通过isinstance排除
        try:
            origin = type.__origin__
            isinstance(None, origin)
            return origin
        except:
            pass
        return None

    @staticmethod
    def _or_none(checkable_type: _AvailableType)-> _AvailableType:
        if checkable_type is None:
            return None
        if isinstance(checkable_type, tuple):
            return (type(None),) + checkable_type
        return type(None) | checkable_type

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
        self._data = self.resolve(instance._root_conf)
        return self._data

    def resolve(self, d: dict[str, Any]) -> T:
        if isinstance(self.source, LazySetting):
            value = self.source.resolve(d)
        else:
            value = self.__walk_dict(self.source, d)
        if value is None:
            value = self.default
        elif self.trans_fn is not None:
            value = self.trans_fn(value)
        self.check_type(value)
        return value

    def check_type(self, value: Any) -> bool:
        '''检查value是否符合待检查的类型，如果不符合则抛出异常'''
        if self.type is None:
            return True
        if not isinstance(value, self.type):  # type: ignore  Why?
            raise ImproperlyConfigured(
                f'Config value {self.source} should be {self.type}, '
                f'but got {type(value)}'
            )
        return True

    def _get_path(self) -> str:
        if isinstance(self.source, LazySetting):
            return self.source._get_path()
        return self.source

    def __str__(self) -> str:
        if self.type is None:
            return f'LazySetting({self._get_path()})'
        return f'LazySetting({self._get_path()}: {self.type})'

    @staticmethod
    def __walk_dict(path: str, d: dict[str, Any]) -> Optional[T]:
        paths = path.strip("/").split("/")
        current_dir = d
        for query in paths:
            if query in current_dir:
                current_dir = current_dir[query]
            else:
                return None
        return current_dir  # type: ignore
