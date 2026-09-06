from urllib import parse
from typing import cast

from django.utils.http import url_has_allowed_host_and_scheme

from utils.http import HttpRequest

from boot.config import GLOBAL_CONFIG


__all__ = ["get_ip", "build_full_url", "safe_local_redirect_target"]


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
    Convert '/path/from/root' to 'protocol://domain/path/from/root'
    if path is already a full url, just return it.
    """
    if root is None:
        root = GLOBAL_CONFIG.base_url
    if not path:
        return root
    return parse.urljoin(root.rstrip('/') + '/', path)


def safe_local_redirect_target(
    request: HttpRequest,
    target: str | None,
    fallback: str,
    *,
    allow_site_absolute: bool = False,
) -> str:
    """Accept local paths and optionally absolute URLs on global.base_url host."""
    if not isinstance(target, str):
        return fallback
    target = target.strip()
    if (
        # 拒绝空目标（包括去掉首尾空白后为空的字符串）。
        not target
        # //host/path 会沿用当前协议访问指定主机，并非站内路径。
        or target.startswith("//")
        # 浏览器可能将反斜杠当成斜杠，导致校验结果与实际跳转不一致。
        or "\\" in target
    ):
        return fallback
    allowed_hosts = set()
    if allow_site_absolute:
        site = parse.urlsplit(GLOBAL_CONFIG.base_url)
        if site.scheme in ("http", "https") and site.netloc:
            allowed_hosts.add(site.netloc)
    try:
        destination = parse.urlsplit(target)
    except ValueError:
        return fallback
    if not target.startswith("/") and not (
        destination.scheme in ("http", "https") and destination.netloc
    ):
        return fallback
    if not url_has_allowed_host_and_scheme(
        target,
        allowed_hosts=allowed_hosts,
        require_https=request.is_secure(),
    ):
        return fallback
    return target
