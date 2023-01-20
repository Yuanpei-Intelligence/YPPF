from django.http import HttpRequest

from boot.config import GLOBAL_CONF


def get_ip(request: HttpRequest) -> 'str | None':
    x_forwarded_for: str = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[-1].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def build_full_url(root_path: str) -> str:
    """
    Add protocol and domain for url.
    Convert '/path/from/root' to 'protocol://domain/path/from/too'
    """
    root_path.lstrip('/')
    return GLOBAL_CONF.base_url + '/' + root_path
