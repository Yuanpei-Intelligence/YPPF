from typing import Any, Callable, TypeVar, Annotated


__all__ = [
    'Annotated',  # 字段应以Annotated标注选项，从typing显式导入，或从本模块全部导入
    'choice',
    'CustomizedDisplay',
    'DefaultDisplay',
]


T = TypeVar('T')

def choice(value: T, display: Any = None) -> T:
    '''
    解决Django Choices拆分实际常量值和展示内容的问题，避免类型检查器判断错误。

    用法::

        class MyChoices(IntegerChoices):
            CHOICE1 = choice(0, '第一种选择的说明')
            CHOICE2 = choice(1)

    尽管允许使用``choice(value)``，仍应手动提供展示内容。
    '''
    if display is None:
        return value
    return value, display  # type: ignore


CustomizedDisplay = Annotated[Callable[[], str], choice('value', 'with display')]
CustomizedDisplay.__doc__ = '''
由定制好呈现内容的选择字段生成的展示函数，会被用于在admin页面展示。
'''

DefaultDisplay = Annotated[Callable[[], str], choice('value')]
DefaultDisplay.__doc__ = '''
由默认的展示内容生成的展示函数，会被用于在admin页面展示。
默认的展示内容是常量名的标题形式，如`APPOINTED`会被展示为`Appointed`。
暴露给用户可能存在常量名攻击的风险，因此不建议使用。
'''
