from enum import Enum

__all__ = ['MessageType']

class MessageType(Enum):
    ADMIN = 'admin'
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
    NEED_AGREE = 'need_agree'
    TEMPORARY = 'temp_appointment'
    TEMPORARY_FAILED = 'temp_appointment_fail'
