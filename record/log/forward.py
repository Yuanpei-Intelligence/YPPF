'''
提供Logger的向前引用声明。

向前引用记录器，以避免启动项依赖，在工具模块中引用。

Logger是实际存在的伪类型，可用于类型声明，不可实例化，例如::

    from record.log.forward import Logger

    def foo(logger: Logger) -> None: pass  # OK
    def bar() -> 'Logger':  # OK
    logger = Logger()  # Error
    logger = Logger.getLogger()  # Error

'''

from typing_extensions import Never

__all__ = ['Logger']

class Logger:
    def __init__(self: Never) -> None:
        raise TypeError('Logger是一个向前引用声明，不应该被实例化')
