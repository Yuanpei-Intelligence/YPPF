'''
context_managers.py

- 上下文管理器
- 错误管理器

@Author pht
@Date 2022-07-04
'''

from typing import Type, Tuple, Union

__all__ = [
    'Checker',
]

DEFAULT_EXC_TYPE = AssertionError
ExceptionType = Type[BaseException]
TrappableException = Union[ExceptionType, Tuple[ExceptionType]]


class Checker:
    '''
    错误管理器

    记录当前状态发生错误应当给出的提示信息，发生错误时抛出AssertionError

    示例代码
    -------
    ```
    try:
        with Checker(AssertionError) as checker:
            checker.assert_(1 == 1, '相等比较异常')
            value, div = 10, 0
            checker.assert_(value > 0, '被除数应为正数', '除数为0')
            value /= div
            checker.set_output(f'不存在活跃度为{value}的同学')
            student = Person.objects.get(point=value)
    except AssertionError as e:
        content = wrong(str(e))
    ```
    '''
    def __init__(self,
                 untrapped: TrappableException = (),
                 output: str = '发生了意料之外的错误，请检查输入') -> None:
        '''
        :param untrapped: 不捕获的异常，直接抛出，需要精准匹配, defaults to ()
        :type untrapped: Union[Type[Exception], Tuple[Type[Exception]]], optional
        :param output: 错误提示, defaults to '发生了意料之外的错误，请检查输入'
        :type output: str, optional
        '''
        self.exc_type = DEFAULT_EXC_TYPE
        self.set_output(output)
        self.set_untrapped(untrapped)

    def set_output(self, output: str):
        '''
        设置错误提示，当发生错误时，抛出对应提示的AssertionError

        :param output: 错误提示
        :type output: str
        '''
        self.output = output

    def set_untrapped(self, exceptions: TrappableException = ()):
        '''
        设置不捕获的异常类型

        :param exceptions: 直接抛出的异常类别，暂不支持子类, defaults to ()
        :type exceptions: Union[Type[Exception], Tuple[Type[Exception]]], optional
        '''
        try:
            assert issubclass(exceptions, Exception)
            exceptions = (exceptions, )
        except:
            pass
        self.untrapped = tuple(exceptions)

    def assert_(self, expr, output: str = None, next: str = None):
        '''
        断言，可设置本步和下一步的错误提示，用于无异常的简单表达式

        :param expr: 支持__bool__的表达式值
        :param output: 本步的错误提示, defaults to None
        :type output: str, optional
        :param next: 本步成功后接下来的错误提示, defaults to None
        :type next: str, optional
        '''
        if output is not None:
            self.set_output(output)
        assert expr, self.output
        if next is not None:
            self.set_output(next)

    def __enter__(self):
        '''上下文管理器的返回值，即自身'''
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        '''
        若发生了异常且希望屏蔽异常，返回True
        若未发生异常，参数为三个None，无需提供返回值
        '''
        if exc_type is None:
            return True
        if exc_type in self.untrapped:
            return False
        raise self.exc_type(self.output)
