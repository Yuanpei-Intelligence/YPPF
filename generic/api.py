from datetime import datetime
from generic.models import (
    PageLog,
    ModuleLog,
)
from generic.http.dependency import *


def eventTrackingFunc(request: HttpRequest):
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
