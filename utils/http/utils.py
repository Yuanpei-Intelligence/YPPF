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


def _is_same_site_absolute(
    target: str,
    *,
    require_https: bool = False,
) -> bool:
    """Whether ``target`` is an absolute URL on the configured site origin."""
    parsed = parse.urlsplit(target)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    if require_https and parsed.scheme != 'https':
        return False
    base = parse.urlsplit(GLOBAL_CONFIG.base_url)
    return (
        parsed.scheme == base.scheme
        and parsed.netloc.lower() == base.netloc.lower()
    )


def safe_local_redirect_target(
    request: HttpRequest,
    target: str | None,
    fallback: str,
) -> str:
    """Validate caller-supplied target; return trusted fallback unchanged.

    Accepts a single-slash relative path or an absolute URL on the configured
    site origin (``GLOBAL_CONFIG.base_url``). Absolute same-origin URLs are
    accepted because the mini-program WebView bridge passes a fully qualified
    backend URL as its ``to`` parameter. Every other value falls back.
    """
    if not isinstance(target, str):
        return fallback
    target = target.strip()
    if not target or target.startswith("//") or "\\" in target:
        return fallback
    if target.startswith("/"):
        if not url_has_allowed_host_and_scheme(
            target,
            allowed_hosts=set(),
            require_https=request.is_secure(),
        ):
            return fallback
        return target
    if _is_same_site_absolute(
        target,
        require_https=request.is_secure(),
    ):
        return target
    return fallback
