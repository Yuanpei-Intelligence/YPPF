"""
Scheduler-discovered jobs of the timetable app. ``scheduler``'s
``collect_jobs`` command imports every installed app's ``jobs`` module and
registers the ``@periodical`` functions found; the worker started by
``python manage.py runscheduler`` then executes them.
"""
from __future__ import annotations

import logging
from datetime import datetime

from scheduler.periodic import periodical

from timetable import reminders

__all__ = ['send_due_class_reminders']

logger = logging.getLogger(__name__)


@periodical('interval', 'timetable_class_reminders',
            minutes=reminders.JOB_INTERVAL_MINUTES)
def send_due_class_reminders() -> int:
    """
    Send every class reminder that became due since the previous run
    (``reminders.due_reminders``). One failing person is logged and does
    not stop the others. Returns the number of reminders handled.
    """
    now = datetime.now()
    handled = 0
    for person, occurrence in reminders.due_reminders(now):
        try:
            log = reminders.send_class_reminder(person, occurrence, now=now)
        except Exception:
            logger.exception('class reminder failed: person=%s occurrence=%s',
                             person.pk, occurrence.id)
            continue
        handled += 1
        logger.debug('class reminder %s for person %s via %s (%s)',
                     occurrence.id, person.pk, log.channel, log.detail)
    if handled:
        logger.info('class reminders: handled %d at %s', handled, now.strftime('%H:%M'))
    return handled
