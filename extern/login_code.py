"""Deliver login codes through the same bounded, non-persistent mail queue."""
from extern.password_reset import _deliver_code_email, _queue_prepared_delivery
from extern.wechat import send_verify_code


def deliver_login_email(name, email, code):
    _deliver_code_email(name, email, code, title='登录')


def queue_login_delivery(channel, prepare):
    delivery = deliver_login_email if channel == 'email' else send_verify_code
    return _queue_prepared_delivery(delivery, prepare)
