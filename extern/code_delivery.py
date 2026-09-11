"""Bounded, non-persistent delivery of one code to all available channels."""
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from threading import BoundedSemaphore
from time import monotonic
from typing import Callable, Literal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from app.config import CONFIG
from extern.code_email import send_code_email
from extern.config import wechat_config
from extern.log import ExternLogger
from extern.wechat import send_password_reset_token, send_verify_code


Purpose = Literal['login', 'password_reset']
DeliveryArgs = tuple[int, str, str, str | None, str]
logger = ExternLogger.getLogger('code_delivery')
_delivery_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='code-delivery')
_delivery_slots = BoundedSemaphore(16)


def _send_email(purpose: Purpose, name: str, email: str | None, code: str) -> str | None:
    if not email:
        return 'no_valid_email'
    try:
        validate_email(email)
    except ValidationError:
        return 'no_valid_email'
    if not CONFIG.email.url:
        return 'not_configured'
    send_code_email(name, email, code, title='登录' if purpose == 'login' else '密码重置')
    return None


def _send_wechat(purpose: Purpose, username: str, code: str) -> str | None:
    if not wechat_config.api_url:
        return 'not_configured'
    sender = send_verify_code if purpose == 'login' else send_password_reset_token
    sender(username, code)
    return None


def deliver_code(purpose: Purpose, delivery_id: str, account_id: int,
                 username: str, name: str, email: str | None, code: str) -> None:
    """Try each channel independently; acceptance is not proof of inbox receipt."""
    channels = (
        ('email', partial(_send_email, purpose, name, email, code)),
        ('wechat', partial(_send_wechat, purpose, username, code)),
    )
    for channel, send in channels:
        started = monotonic()
        try:
            reason = send()
            status = 'skipped' if reason else 'accepted'
            reason = reason or 'provider_accepted'
        except Exception as error:
            # Provider response bodies and exception messages may contain credentials.
            status, reason = 'failed', type(error).__name__
        log = logger.warning if status == 'failed' else logger.info
        log('delivery_id=%s account_id=%s purpose=%s channel=%s status=%s reason=%s elapsed_ms=%d',
            delivery_id, account_id, purpose, channel, status, reason,
            int((monotonic() - started) * 1000))


def _run_delivery(purpose: Purpose, delivery_id: str,
                  prepared: Future[DeliveryArgs | None]) -> None:
    try:
        args = prepared.result()
        if args is not None:
            deliver_code(purpose, delivery_id, *args)
    except Exception as error:
        logger.error('delivery_id=%s purpose=%s status=failed reason=%s',
                     delivery_id, purpose, type(error).__name__)
    finally:
        _delivery_slots.release()


def queue_code_delivery(purpose: Purpose, prepare: Callable[[], DeliveryArgs | None]) -> bool:
    """Reserve capacity before signing; publish to the worker after preparation commits."""
    if purpose not in ('login', 'password_reset'):
        raise ValueError('Unsupported code purpose')
    delivery_id = uuid4().hex
    if not _delivery_slots.acquire(blocking=False):
        logger.warning('delivery_id=%s purpose=%s status=queue_rejected reason=full', delivery_id, purpose)
        return False

    prepared: Future[DeliveryArgs | None] = Future()
    try:
        _delivery_executor.submit(_run_delivery, purpose, delivery_id, prepared)
    except RuntimeError:
        _delivery_slots.release()
        logger.warning('delivery_id=%s purpose=%s status=queue_rejected reason=unavailable', delivery_id, purpose)
        return False

    try:
        args = prepare()
    except BaseException as error:
        # Unblock the worker even if preparation is interrupted; it releases the slot.
        prepared.set_result(None)
        logger.error('delivery_id=%s purpose=%s status=preparation_failed reason=%s',
                     delivery_id, purpose, type(error).__name__)
        raise
    logger.info('delivery_id=%s purpose=%s status=%s', delivery_id, purpose,
                'prepared' if args is not None else 'skipped')
    prepared.set_result(args)
    return True
