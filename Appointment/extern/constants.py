from enum import Enum

__all__ = ['MessageType']

class MessageType(Enum):
    ADMIN = 'admin'  # TODO: deprecated，使用notify_wechat的参数
    NEW = 'new'
    START = 'start'
    NEW_AND_START = f'{NEW}&{START}'
    VIOLATED = 'violated'
    CANCELED = 'canceled'
    LONGTERM_CREATED = 'longterm_created'
    LONGTERM_REVIEWING = 'longterm_reviewing'
    LONGTERM_APPROVED = 'longterm_approved'
    LONGTERM_REJECTED = 'longterm_rejected'
    WAITING2CONFIRM = f'confirm_{ADMIN}_w2c'
    VIOLATED2JUDGED = f'confirm_{ADMIN}_v2j'
    VIOLATE_BY_ADMIN = f'{VIOLATED}_{ADMIN}'
    TEMPORARY = 'temp_appointment'
