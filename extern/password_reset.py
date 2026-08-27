"""Non-persistent, bounded delivery for password-reset credentials."""

import json
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from threading import BoundedSemaphore
from typing import Callable

import requests

from app.config import CONFIG
from extern.log import ExternLogger
from extern.wechat import send_password_reset_token


_DELIVERY_WORKERS = 4
_DELIVERY_CAPACITY = 16
_delivery_executor = ThreadPoolExecutor(
    max_workers=_DELIVERY_WORKERS,
    thread_name_prefix="password-reset-delivery",
)
_delivery_slots = BoundedSemaphore(_DELIVERY_CAPACITY)
logger = ExternLogger.getLogger("password_reset_delivery")


def _run_delivery(delivery: Callable, args: tuple) -> None:
    try:
        delivery(*args)
    except Exception:
        # Delivery errors must not copy the credential into logs.
        logger.error("Password-reset credential delivery failed")
    finally:
        _delivery_slots.release()


def _submit_delivery(runner: Callable, *args) -> bool:
    if not _delivery_slots.acquire(blocking=False):
        logger.warning("Password-reset delivery queue is full")
        return False
    try:
        _delivery_executor.submit(runner, *args)
    except RuntimeError:
        _delivery_slots.release()
        logger.warning("Password-reset delivery queue is unavailable")
        return False
    return True


def _queue_delivery(delivery: Callable, *args) -> bool:
    return _submit_delivery(_run_delivery, delivery, args)


def _run_prepared_delivery(
    delivery: Callable,
    prepared_args: Future[tuple | None],
) -> None:
    try:
        args = prepared_args.result()
        if args is not None:
            delivery(*args)
    except Exception:
        # Preparation and delivery errors must not copy credentials into logs.
        logger.error("Password-reset credential delivery failed")
    finally:
        _delivery_slots.release()


def _queue_prepared_delivery(
    delivery: Callable,
    prepare_args: Callable[[], tuple | None],
) -> bool:
    prepared_args: Future[tuple | None] = Future()
    if not _submit_delivery(
        _run_prepared_delivery,
        delivery,
        prepared_args,
    ):
        return False
    try:
        args = prepare_args()
    except BaseException:
        prepared_args.set_result(None)
        raise
    prepared_args.set_result(args)
    return True


def _deliver_password_reset_email(
    person_name: str,
    email: str,
    token: str,
) -> None:
    message = (
        f"<h3><b>亲爱的{person_name}同学：</b></h3><br/>"
        "您好！本次密码重置凭证为：<br/>"
        f'<p style="color:orange">{token}</p>'
        "凭证有效期较短，请尽快使用，且只能使用一次。<br/>"
        "<br/>元培学院开发组<br/>"
        + datetime.now().strftime("%Y年%m月%d日")
    )
    post_data = json.dumps({
        "sender": "元培学院开发组",
        "toaddrs": [email],
        "subject": "YPPF密码重置",
        "content": message,
        "html": True,
        "private_level": 0,
        "secret": CONFIG.email.hasher.encode(message),
    })
    response = requests.post(
        CONFIG.email.url,
        post_data,
        timeout=6,
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict) or result.get("status") != 200:
        raise RuntimeError("Password-reset email service rejected delivery")


def queue_password_reset_email(
    person_name: str,
    email: str,
    token: str,
) -> bool:
    return _queue_delivery(
        _deliver_password_reset_email,
        person_name,
        email,
        token,
    )


def queue_password_reset_wechat(username: str, token: str) -> bool:
    return _queue_delivery(send_password_reset_token, username, token)


def queue_prepared_password_reset_email(
    prepare_args: Callable[[], tuple[str, str, str] | None],
) -> bool:
    return _queue_prepared_delivery(
        _deliver_password_reset_email,
        prepare_args,
    )


def queue_prepared_password_reset_wechat(
    prepare_args: Callable[[], tuple[str, str] | None],
) -> bool:
    return _queue_prepared_delivery(
        send_password_reset_token,
        prepare_args,
    )
