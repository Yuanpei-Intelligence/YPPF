from urllib import parse
from typing import cast

from utils.http import HttpRequest

from boot.config import GLOBAL_CONFIG


def get_ip(request: HttpRequest) -> str | None:
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = cast(str, x_forwarded_for).split(',')[-1].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def build_full_url(path: str, root: str | None = None) -> str:
    """
    Add protocol and domain for url.
    Convert '/path/from/root' to 'protocol://domain/path/from/too'
    if path is already a full url, just return it.
    """
    if root is None:
        root = GLOBAL_CONFIG.base_url
    if not path:
        return root
    return parse.urljoin(root.rstrip('/') + '/', path)
