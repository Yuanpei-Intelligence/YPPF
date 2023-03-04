from enum import Enum

__all__ = ['MessageType']

class MessageType(Enum):
    NEW = 'new'
    NEW_INCOMING = 'new_incoming'
    REMIND = 'remind'
    VIOLATED = 'violated'
    CANCELED = 'canceled'
    LONGTERM_CREATED = 'longterm_created'
    LONGTERM_REVIEWING = 'longterm_reviewing'
    LONGTERM_APPROVED = 'longterm_approved'
    LONGTERM_REJECTED = 'longterm_rejected'
    PRE_CONFIRMED = 'pre_confirmed'
    APPEAL_APPROVED = 'appeal_approved'
    REVIEWD_VIOLATE = 'review_violate'
    TEMPORARY = 'temp_new'
