from typing import overload, Literal

from apscheduler.jobstores.base import JobLookupError

from scheduler.scheduler import scheduler
from scheduler.config import scheduler_config as CONFIG


@overload
def remove_job(job_id: str, no_except: Literal[False] = ...) -> Literal[True]: ...
@overload
def remove_job(job_id: str, no_except: Literal[True] = ...) -> bool: ...

def remove_job(job_id: str, no_except: bool = True):
    '''删除定时任务

    尝试删除定时任务，不启用定时任务时，不进行任何操作

    Args:
        job_id(str): 任务ID
        no_except(bool, optional): 忽略异常，默认为True

    Returns:
        bool: 捕获异常且任务不存在时返回False，否则返回True

    Raises:
        JobLookupError: 任务不存在，且未忽略异常时抛出
    '''
    if no_except:
        try:
            return remove_job(job_id, no_except=False)
        except JobLookupError:
            return False
    if CONFIG.use_scheduler:
        scheduler.remove_job(job_id)
    return True
