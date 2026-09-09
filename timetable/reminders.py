"""
Class reminders (``timetable/README.md`` §6.1): the due-window selection
used by the periodic job, delivery through a WeChat mini-program subscribe
message with the 站内通知 (+ WeChat push) fallback, subscribe-quota
bookkeeping and the ``ReminderLog`` audit trail.

Channel order for one reminder:

1. subscribe message — only when ``wx_miniapp.subscribe_templates.
   class_reminder.id`` is configured, the user has a ``UserWechatProfile``
   and an unused grant (``SubscribeQuota.count > 0``); the grant is
   consumed atomically before sending, given back when WeChat did not
   deliver for a reason other than 43101, and zeroed on 43101;
2. otherwise ``app.notification_utils.notification_create(...,
   to_wechat=True)``;
3. ``skipped`` when even the notification could not be created.

Every outcome is a ``ReminderLog`` row, claimed before sending so the same
occurrence is never reminded twice. The notification channel imports
``app`` lazily inside the function so the module stays importable when the
notification system is not part of the product.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Iterator

from django.db import IntegrityError, transaction
from django.db.models import F

from api.config import (
    CONFIG as WX_CONFIG,
    DEFAULT_SUBSCRIBE_FIELDS,
    get_subscribe_template,
)
from extern.wx_miniapp import ERR_USER_REFUSED, send_subscribe_message
from timetable.config import CONFIG
from timetable.models import (
    AcademicTerm,
    ReminderLog,
    SubscribeQuota,
    TimetableSettings,
)
from timetable.sources.base import (
    EventSource,
    Occurrence,
    load_sources,
    occurrence_sort_key,
)

__all__ = [
    'TEMPLATE_KEY',
    'REMINDER_TITLE',
    'JOB_INTERVAL_MINUTES',
    'DUE_WINDOW',
    'TIME_FORMAT',
    'subscribe_template_keys',
    'grant_subscribe_quota',
    'build_reminder_data',
    'reminder_content',
    'occurrences_on',
    'due_reminders',
    'send_class_reminder',
]

logger = logging.getLogger(__name__)

TEMPLATE_KEY = 'class_reminder'
REMINDER_TITLE = '上课提醒'
# Interval of the periodic job; the due window has the same width so that
# consecutive runs cover the timeline without gaps or overlaps.
JOB_INTERVAL_MINUTES = 5
# Look back three job intervals so a short scheduler outage does not drop a
# window; ReminderLog keeps re-scans idempotent and a reminder is never sent
# once the class has started (see due_reminders).
DUE_WINDOW = timedelta(minutes=3 * JOB_INTERVAL_MINUTES)
TIME_FORMAT = '%Y年%m月%d日 %H:%M'
DATE_FORMAT = '%Y年%m月%d日'
LOCATION_FALLBACK = '待定'
# Character limits of WeChat subscribe-message value types, by key prefix.
_TYPE_LIMITS = {'thing': 20, 'character_string': 32, 'phrase': 5, 'number': 32}
_TEXT_TYPES = ('thing', 'character_string', 'phrase')
_KEY_PREFIX_RE = re.compile(r'^[a-z_]+?(?=\d|$)')
_SPACES_RE = re.compile(r'\s+')
_WEEKDAY_NAMES = '一二三四五六日'
_KIND_LABELS = {
    'course': '学校课程',
    'college': '书院课',
    'activity': '活动',
    'appoint': '预约',
    'custom': '自定义',
}


# ---------------------------------------------------------------------------
# quota
# ---------------------------------------------------------------------------

def subscribe_template_keys() -> list[str]:
    """Template keys a client may grant: the configured ones plus ``class_reminder``."""
    templates = WX_CONFIG.subscribe_templates
    keys = {str(key) for key in templates} if isinstance(templates, dict) else set()
    keys.add(TEMPLATE_KEY)
    return sorted(keys)


def grant_subscribe_quota(user, template_key: str, count: int = 1) -> SubscribeQuota:
    """
    Record ``count`` accepted grants of ``template_key`` for ``user``; the
    stored count is capped at ``timetable.subscribe_quota_cap``. Atomic:
    the row is locked while it is updated.
    """
    cap = max(int(CONFIG.subscribe_quota_cap), 0)
    count = max(int(count), 0)
    with transaction.atomic():
        quota, _ = SubscribeQuota.objects.select_for_update().get_or_create(
            user=user, template_key=template_key)
        quota.count = min(quota.count + count, cap)
        quota.save(update_fields=['count', 'updated_at'])
    return quota


# ---------------------------------------------------------------------------
# message content
# ---------------------------------------------------------------------------

def _sections_label(occurrence: Occurrence) -> str:
    start, end = occurrence.start_section, occurrence.end_section
    if not start or not end:
        return ''
    return f'第{start}节' if start == end else f'第{start}-{end}节'


def _semantic_values(occurrence: Occurrence) -> dict[str, Any]:
    # Values a template field may refer to (see DEFAULT_SUBSCRIBE_FIELDS);
    # text values are never empty because WeChat rejects empty ``thing``s.
    weekday = ''
    if 1 <= occurrence.weekday <= 7:
        weekday = f'周{_WEEKDAY_NAMES[occurrence.weekday - 1]}'
    sections = _sections_label(occurrence)
    kind = _KIND_LABELS.get(occurrence.kind, occurrence.kind)
    note = ' '.join(part for part in (f'第{occurrence.week}周', weekday, sections) if part)
    return {
        'course': occurrence.title or kind,
        'time': occurrence.start,
        'end_time': occurrence.end,
        'date': occurrence.date,
        'location': occurrence.location or LOCATION_FALLBACK,
        'note': note or kind,
        'teacher': occurrence.subtitle or LOCATION_FALLBACK,
        'subtitle': occurrence.subtitle or kind,
        'kind': kind,
        'week': occurrence.week,
        'weekday': weekday or kind,
        'sections': sections or kind,
    }


def _format_value(key: str, value: Any) -> str:
    match = _KEY_PREFIX_RE.match(key)
    prefix = match.group(0) if match else ''
    if isinstance(value, datetime):
        text = value.strftime(DATE_FORMAT if prefix == 'date' else TIME_FORMAT)
    elif isinstance(value, date):
        text = value.strftime(DATE_FORMAT)
    else:
        text = _SPACES_RE.sub(' ', str(value)).strip()
    limit = _TYPE_LIMITS.get(prefix)
    if limit is not None and len(text) > limit:
        text = text[:limit]
    if prefix in _TEXT_TYPES and not text:
        text = '-'
    return text


def build_reminder_data(occurrence: Occurrence,
                        template_cfg: dict[str, Any]) -> dict[str, dict[str, str]]:
    """
    The ``data`` of a subscribe message: ``template_cfg['fields']`` maps
    semantic names (``course``, ``time``, ``location``, ``note``, also
    ``end_time``, ``date``, ``teacher``, ``subtitle``, ``kind``, ``week``,
    ``weekday``, ``sections``) to WeChat keys. Values are formatted and
    truncated by key type: ``thing*`` 20 chars, ``character_string*`` 32,
    ``phrase*`` 5, ``time*`` as ``YYYY年MM月DD日 HH:MM``, ``date*`` as
    ``YYYY年MM月DD日``. Unknown semantic names are skipped.
    """
    fields = template_cfg.get('fields') if isinstance(template_cfg, dict) else None
    if not isinstance(fields, dict) or not fields:
        fields = DEFAULT_SUBSCRIBE_FIELDS
    values = _semantic_values(occurrence)
    data: dict[str, dict[str, str]] = {}
    for semantic, key in fields.items():
        if semantic not in values or not key:
            continue
        data[str(key)] = {'value': _format_value(str(key), values[semantic])}
    return data


def reminder_content(occurrence: Occurrence) -> str:
    """Text of the fallback notification: ``'<title> HH:MM–HH:MM @<location>'``."""
    text = f'{occurrence.title} {occurrence.start:%H:%M}–{occurrence.end:%H:%M}'
    if occurrence.location:
        text += f' @{occurrence.location}'
    return text


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

def occurrences_on(person, term: AcademicTerm, on: date, settings: TimetableSettings,
                   sources: Iterable[EventSource] | None = None) -> list[Occurrence]:
    """
    Visible (not hidden, not canceled) occurrences of ``person`` on ``on``
    from every enabled source, sorted by time. ``on`` must lie in a
    teaching week of ``term``; otherwise the list is empty.
    """
    week = term.week_of(on)
    if not term.contains_week(week):
        return []
    if sources is None:
        sources = load_sources()
    occurrences: list[Occurrence] = []
    for source in sources:
        occurrences.extend(source.occurrences(person, term, week, week, settings))
    occurrences = [
        item for item in occurrences
        if item.date == on and not item.hidden and item.status != 'canceled'
    ]
    occurrences.sort(key=occurrence_sort_key)
    return occurrences


def _log_key(occurrence: Occurrence) -> str:
    return occurrence.id[:128]


def due_reminders(now: datetime | None = None) -> Iterator[tuple[Any, Occurrence]]:
    """
    ``(person, occurrence)`` pairs whose reminder is due at ``now``: for
    every ``TimetableSettings`` with ``reminder_enabled``, today's visible
    occurrences whose ``start - reminder_minutes`` lies in
    ``(now - DUE_WINDOW, now]`` and that have no ``ReminderLog`` yet. A
    failing source for one person is logged and that person skipped.
    """
    if now is None:
        now = datetime.now()
    today = now.date()
    term = AcademicTerm.current(today)
    if term is None or not term.contains_week(term.week_of(today)):
        return
    sources = load_sources()
    settings_rows = (
        TimetableSettings.objects.filter(reminder_enabled=True)
        .select_related('person', 'person__person_id').order_by('id')
    )
    for settings in settings_rows.iterator():
        person = settings.person
        lead = timedelta(minutes=int(settings.reminder_minutes))
        try:
            occurrences = occurrences_on(person, term, today, settings, sources)
        except Exception:
            logger.exception('class reminders: sources failed for person %s', person.pk)
            continue
        due = [item for item in occurrences
               if now - DUE_WINDOW < item.start - lead <= now <= item.start]
        if not due:
            continue
        logged = set(ReminderLog.objects.filter(
            person=person, occurrence_id__in=[_log_key(item) for item in due],
        ).values_list('occurrence_id', flat=True))
        for item in due:
            if _log_key(item) not in logged:
                yield person, item


# ---------------------------------------------------------------------------
# sending
# ---------------------------------------------------------------------------

def _claim_log(person, occurrence: Occurrence,
               scheduled_for: datetime) -> tuple[ReminderLog, bool]:
    # Insert the audit row first so a concurrent run cannot send twice.
    key = _log_key(occurrence)
    try:
        with transaction.atomic():
            log = ReminderLog.objects.create(
                person=person, occurrence_id=key,
                channel=ReminderLog.Channel.SKIPPED,
                scheduled_for=scheduled_for, detail='pending')
    except IntegrityError:
        return ReminderLog.objects.get(person=person, occurrence_id=key), False
    return log, True


def _openid_of(user) -> str:
    from generic.models import UserWechatProfile
    openid = UserWechatProfile.objects.filter(user=user).values_list(
        'openid', flat=True).first()
    return openid or ''


def _send_subscribe(user, occurrence: Occurrence) -> tuple[str | None, str]:
    # (channel, detail): channel is None when the fallback must be used.
    template = get_subscribe_template(TEMPLATE_KEY)
    if template is None:
        return None, 'no template'
    openid = _openid_of(user)
    if not openid:
        return None, 'no wx_profile'
    claimed = SubscribeQuota.objects.filter(
        user=user, template_key=TEMPLATE_KEY, count__gt=0,
    ).update(count=F('count') - 1)
    if not claimed:
        return None, 'no quota'
    ok, errcode, errmsg = send_subscribe_message(
        openid, template['id'], template['page'],
        build_reminder_data(occurrence, template))
    if ok:
        return ReminderLog.Channel.SUBSCRIBE, 'ok'
    quota = SubscribeQuota.objects.filter(user=user, template_key=TEMPLATE_KEY)
    if errcode == ERR_USER_REFUSED:
        # The user withdrew the permission or WeChat holds no grant for us:
        # nothing we count is usable any more.
        quota.update(count=0)
    else:
        # Not delivered for another reason; WeChat did not consume the
        # grant, so give it back.
        quota.update(count=F('count') + 1)
    return None, f'{errcode} {errmsg}'.strip()


def _send_notification(user, person, occurrence: Occurrence,
                       reason: str) -> tuple[str, str]:
    from app.models import Notification
    from app.notification_utils import notification_create
    try:
        notification_create(
            user, None, Notification.Type.NEEDREAD, REMINDER_TITLE,
            reminder_content(occurrence), URL=None, to_wechat=True)
    except Exception:
        # The job must go on with the next person; the log row records it.
        logger.exception('class reminder notification failed for person %s', person.pk)
        return ReminderLog.Channel.SKIPPED, f'notification failed; {reason}'
    return ReminderLog.Channel.NOTIFICATION, reason


def send_class_reminder(person, occurrence: Occurrence, *,
                        now: datetime | None = None) -> ReminderLog:
    """
    Remind ``person`` of ``occurrence`` once, through the first usable
    channel (see the module docstring), and return the ``ReminderLog``
    row. A second call for the same occurrence sends nothing and returns
    the existing row.
    """
    if now is None:
        now = datetime.now()
    settings = TimetableSettings.objects.filter(person=person).first()
    minutes = (settings.reminder_minutes if settings is not None
               else CONFIG.reminder_default_minutes)
    scheduled_for = occurrence.start - timedelta(minutes=int(minutes))
    log, created = _claim_log(person, occurrence, scheduled_for)
    if not created:
        return log
    user = person.get_user()
    channel, detail = _send_subscribe(user, occurrence)
    if channel is None:
        channel, detail = _send_notification(user, person, occurrence, detail)
    log.channel = channel
    log.detail = detail[:128]
    log.sent_at = now
    log.save(update_fields=['channel', 'detail', 'sent_at'])
    return log
