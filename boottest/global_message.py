# utils for build dict used for rendering

from boottest.const import WRONG, SUCCEED


__all__ = [
    'WRONG', 'SUCCEED',
    'get_global_message',
    'set_global_alert',
    'set_global_message',
    'set_global_info',
]

# 在错误的情况下返回的字典, message为错误信息
def wrong(message, _context):
    '''
    在错误的情况下返回的字典, message为错误信息
    如果提供了context，则向其中添加信息
    '''
    _context.update(
        warn_code=WRONG,
        warn_message=message,
    )

    return _context

def succeed(message, _context):
    '''
    在成功的情况下返回的字典, message为提示信息
    如果提供了context，则向其中添加信息
    '''
    _context.update(
        warn_code=SUCCEED,
        warn_message=message,
    )

    return _context

def set_global_info(request, **kwargs):
    request.session.update(**kwargs)

def set_global_message(request, warn_code, warn_message):
    request.session['warn_code'] = warn_code
    request.session['warn_message'] = warn_message

def set_global_alert(request, alert_message):
    request.session['alert_message'] = alert_message

def get_global_message(request, _context=None):

    warn_code = request.session.pop('warn_code', '')
    warn_message = request.session.pop('warn_message', '')
    alert_message = request.session.pop('alert_message', '')

    # if not _context:
    #     _context = {}
    # _context['alert_message'] = request.session.pop('alert_message', '')
    # if warn_code == WRONG:
    #     return wrong(warn_message, _context)
    # elif warn_code == SUCCEED:
    #     return succeed(warn_message, _context)
    # return _context

    return warn_code, warn_message, alert_message

