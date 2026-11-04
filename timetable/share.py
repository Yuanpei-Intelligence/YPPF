"""
Share assets of the timetable poster (``timetable/README.md`` §8.5): the
mini-program code produced by ``wxacode.getUnlimited`` — cached as a file
under ``MEDIA_ROOT/timetable/share/`` for ``CACHE_DAYS`` and served from
``MEDIA_URL`` — the configured official-account QR code and the slogan.

Failures never surface as errors: an asset that cannot be produced is
``None`` and the poster is drawn without it.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from django.conf import settings

from utils.http.utils import build_full_url
from api.config import get_share_config
from extern.wx_miniapp import fetch_miniapp_code

__all__ = [
    'SCENE',
    'CACHE_DAYS',
    'SHARE_DIR',
    'CODE_WIDTH',
    'share_assets',
    'miniapp_code_url',
    'official_qrcode_url',
]

logger = logging.getLogger(__name__)

SCENE = 'timetable'
CACHE_DAYS = 30
# Relative to MEDIA_ROOT / MEDIA_URL.
SHARE_DIR = 'timetable/share'
CODE_WIDTH = 430


def _cache_path(scene: str) -> Path:
    return Path(settings.MEDIA_ROOT) / SHARE_DIR / f'miniapp_{scene}.png'


def _media_url(relative: str) -> str:
    base = str(settings.MEDIA_URL or '/media/')
    if not base.endswith('/'):
        base += '/'
    return build_full_url(base + relative.lstrip('/'))


def _is_fresh(path: Path, now: float) -> bool:
    try:
        return now - path.stat().st_mtime < CACHE_DAYS * 86400
    except OSError:
        return False


def _write_atomic(path: Path, content: bytes) -> bool:
    # Write next to the target and rename, so a concurrent reader never
    # sees a partial image.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
        temp.write_bytes(content)
        os.replace(temp, path)
    except OSError as exc:
        logger.warning('share asset %s not cached: %s', path.name, type(exc).__name__)
        return False
    return True


def miniapp_code_url(scene: str = SCENE, *, now: float | None = None) -> str | None:
    """
    Absolute URL of the cached mini-program code for ``scene``, fetching a
    new image when the cache file is missing or older than ``CACHE_DAYS``.
    When WeChat cannot produce one, a stale cached image is still served;
    with no image at all the result is ``None``.
    """
    if now is None:
        now = time.time()
    config = get_share_config()
    path = _cache_path(scene)
    if not _is_fresh(path, now):
        content = fetch_miniapp_code(
            scene, config['miniapp_page'], env_version=config['env_version'],
            width=CODE_WIDTH)
        if content:
            _write_atomic(path, content)
        elif not path.exists():
            return None
        else:
            logger.warning('mini-program code for %s not refreshed; '
                           'serving the cached file', scene)
    return _media_url(f'{SHARE_DIR}/{path.name}')


def official_qrcode_url() -> str | None:
    """
    The configured official-account QR code as an absolute URL: an
    absolute ``http(s)`` value is returned as is, a site path starting with
    ``/`` (the repository ships ``/static/assets/img/yppf_official_qrcode.png``)
    is joined with ``global.base_url``, and any other relative value is a
    path under ``MEDIA_URL``; empty configuration gives ``None``.
    """
    value = get_share_config()['official_qrcode_url']
    if not value:
        return None
    if value.startswith(('http://', 'https://')):
        return value
    if value.startswith('/'):
        return build_full_url(value)
    return _media_url(value)


def share_assets(scene: str = SCENE) -> dict:
    """``GET share/assets/`` payload: ``{miniapp_qrcode, official_qrcode, slogan}``."""
    return {
        'miniapp_qrcode': miniapp_code_url(scene),
        'official_qrcode': official_qrcode_url(),
        'slogan': get_share_config()['slogan'],
    }
