'''
日志实用程序的模块。

提供了默认的日志级别和格式，并且始终写入**logger_name.log**文件。
项目应该使用这个代替标准的``logging``模块。

与``logging.getLogger``的区别:

1. ``Logger``默认初始化。
2. ``Logger``默认使用模块设置，模块设置由启动模块负责初始化，
   ``utils``模块可从forward.py向前引用，以避免启动项依赖（仅可用于类型声明，不可实例化）。
3. 栈追踪长度调整。

根据
https://stackoverflow.com/questions/47968861/does-python-logging-support-multiprocessing,
在管道长度范围（通常为4096 B）内的日志记录是原子的。
对于大多数情况来说，它足够大，除了回溯时。
'''
