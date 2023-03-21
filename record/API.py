from datetime import datetime

from record.models import (
    PageLog,
    ModuleLog,
)
from utils.http.dependency import *


def eventTrackingFunc(request: HttpRequest):
    """
    用于处理埋点的视图函数。监测用户的访问情况并更新相关数据库表。

    :param request: HTTP请求
    :type request: HttpRequest
    :return: 如未登录，返回一个重定向(到登录页面); 否则返回Json响应
    :rtype: HttpResponseRedirect | JsonResponse
    """
    
    # 首先检查有无登录，如未登录则重定向到登录页面
    if not request.user.is_authenticated:
        return redirect("/index/")
    
    # unpack request:
    logType = int(request.POST['Type'])
    logUrl = request.POST['Url']
    try:
        logTime = int(request.POST['Time'])
        logTime = datetime.fromtimestamp(logTime / 1000)
    except:
        logTime = datetime.now()
    # 由于对PV/PD埋点的JavaScript脚本在base.html中实现，所以所有页面的PV/PD都会被track
    logPlatform = request.POST.get('Platform', None)
    try:
        logExploreName, logExploreVer = request.POST['Explore'].rsplit(maxsplit=1)
    except:
        logExploreName, logExploreVer = None, None

    kwargs = {}
    kwargs.update(
        user=request.user,
        type=logType,
        page=logUrl,
        time=logTime,
        platform=logPlatform,
        explore_name=logExploreName,
        explore_version=logExploreVer,
    )
    if logType in ModuleLog.CountType.values:
        # Module类埋点
        kwargs.update(
            module_name=request.POST['Name'],
        )
        ModuleLog.objects.create(**kwargs)
    elif logType in PageLog.CountType.values:
        # Page类的埋点
        PageLog.objects.create(**kwargs)

    return JsonResponse({'status': 'ok'})
