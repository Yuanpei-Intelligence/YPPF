"""
Shared judgements for the ``<app>/deploy_checks.py`` plugins of
``python manage.py deploy_check``.

A plugin exposes ``checks(*, online: bool = False)`` and yields plain
``(level, name, detail)`` tuples. These helpers only keep the levels
consistent across plugins; nothing here performs I/O.

Level policy:

- ``FAIL``: the deployment is broken or insecure; an operator must act.
- ``WARN``: a feature is degraded or a value looks unintended.
- A problem that only matters in production (a template placeholder, a local
  URL, missing production data) uses :func:`production_level`: ``FAIL``
  outside debug mode and ``WARN`` when ``YPPF_DEBUG=true``.

Details must never contain secrets: print whether a credential is set, a
URL's scheme and host, or an exception class, never the value itself.
"""
from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from boot.config import DEBUG


__all__ = [
    'OK', 'WARN', 'FAIL', 'LEVELS',
    'debug_mode', 'production_level',
    'resolve_setting', 'is_blank', 'is_placeholder',
    'url_host', 'is_local_host', 'preview',
]


OK = 'OK'
WARN = 'WARN'
FAIL = 'FAIL'
LEVELS = (OK, WARN, FAIL)

_LOCAL_HOSTS = frozenset({'localhost', '0.0.0.0', '::1'})


def debug_mode() -> bool:
    """Whether this process runs with ``YPPF_DEBUG=true``."""
    return DEBUG


def production_level() -> str:
    """Level of a problem that only matters in production."""
    return WARN if debug_mode() else FAIL


def resolve_setting(config: Any, attr: str) -> tuple[Any, str | None]:
    """
    Resolve ``config.<attr>`` and return ``(value, error)``.

    ``error`` is the exception class name when the setting is missing or
    malformed, otherwise ``None``. The message is dropped on purpose: casts
    may echo the configured value, which can be a credential.

    ``LazySetting`` caches the first resolved value on the class attribute,
    so tests should replace a plugin's config object rather than build a
    second instance of the same ``Config`` class.
    """
    try:
        return getattr(config, attr), None
    except (ImproperlyConfigured, ValueError, TypeError) as exc:
        return None, type(exc).__name__


def is_blank(value: Any) -> bool:
    """Whether ``value`` is not a string or only whitespace."""
    return not isinstance(value, str) or not value.strip()


def is_placeholder(value: Any) -> bool:
    """Whether ``value`` is a ``$NAME$`` placeholder from the config template."""
    return (isinstance(value, str) and len(value) > 2
            and value.startswith('$') and value.endswith('$'))


def url_host(url: Any) -> tuple[str, str]:
    """
    Return the lower-cased ``(scheme, hostname)`` of ``url``.

    Both are empty strings when ``url`` is not an absolute URL. Only these two
    parts are safe to print: a path or query may carry a token and the
    network location may carry credentials.
    """
    if not isinstance(url, str):
        return '', ''
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname or ''
    except ValueError:
        return '', ''
    return parts.scheme.lower(), host


def is_local_host(host: str) -> bool:
    """Whether ``host`` names this machine (loopback or unspecified address)."""
    host = host.lower()
    return (host in _LOCAL_HOSTS or host.startswith('127.')
            or host.endswith('.localhost'))


def preview(items: list[str], limit: int = 5) -> str:
    """Join the first ``limit`` items and count the rest."""
    shown = ', '.join(items[:limit])
    if len(items) > limit:
        shown += f' (+{len(items) - limit} more)'
    return shown
