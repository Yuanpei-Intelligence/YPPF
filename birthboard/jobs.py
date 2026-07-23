from datetime import timedelta, datetime
import os

from django.db import transaction
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings

from record.log.utils import get_logger as bb_get_logger

from birthboard.models import BirthboardRecord, BirthboardParticipant, ChangeRecord
from generic.models import YQPointRecord, User
from scheduler.periodic import periodical

from birthboard.notify import (
    notify_waiting_reminder,
    notify_auto_reject_refund,
    notify_broadcast_starting_tomorrow,
    notify_broadcast_started,
    notify_broadcast_ended,
    notify_broadcast_ending_soon,
)

logger = bb_get_logger(__name__)

_BB_UPDATE_LOCK_KEY = "birthboard:update_in_progress"


def _get_abs_image_path(image_field) -> str | None:
    """Return absolute file path for ImageField/FileField.

    Prefer storage-provided `.path`; fallback to MEDIA_ROOT + `.name`.
    """
    if not image_field:
        return None

    try:
        p = image_field.path
        if p:
            return os.path.abspath(p)
    except Exception:
        pass

    name = getattr(image_field, "name", None)
    if not name:
        return None

    media_root = getattr(settings, "MEDIA_ROOT", "")
    if media_root:
        return os.path.abspath(os.path.join(media_root, name))
    return os.path.abspath(name)


def _set_update_lock(val: bool, timeout: int = 60 * 60):
    try:
        if val:
            # set with timeout to avoid stale lock
            cache.set(_BB_UPDATE_LOCK_KEY, True, timeout=timeout)
        else:
            cache.delete(_BB_UPDATE_LOCK_KEY)
    except Exception:
        logger.exception("[birthboard.jobs] _set_update_lock: cache operation failed")


def _get_mode_duration_days(record: BirthboardRecord) -> int:
    """Return duration in days for a record's mode.

    Heuristic mapping (defaults): mode index 0->1,1->3,2->365; also allow numeric cost mapping 35/60/1000.
    """
    try:
        mode = getattr(record, 'mode', None)
        if isinstance(mode, int):
            mapping = {0: 1, 1: 3, 2: 365}
            if mode in mapping:
                return mapping[mode]
            # sometimes mode stores actual cost
            cost_map = {35: 1, 60: 3, 1000: 365}
            if mode in cost_map:
                return cost_map[mode]
        if isinstance(mode, str) and mode.isdigit():
            m = int(mode)
            cost_map = {35: 1, 60: 3, 1000: 365}
            return cost_map.get(m, 1)
    except Exception:
        logger.exception("[birthboard.jobs] _get_mode_duration_days: failed to deduce duration, default to 1")
    return 1


def _today_local_date():
    # logger.debug("[birthboard.jobs] _today_local_date: start")
    now = timezone.now()
    # now = timezone.make_aware(datetime(2026, 4, 24, 12, 0))
    is_aware = timezone.is_aware(now)
    today = timezone.localtime(now).date() if is_aware else now.date()
    # logger.debug(
    #     "[birthboard.jobs] _today_local_date: now=%s aware=%s today=%s",
    #     now,
    #     is_aware,
    #     today,
    # )
    return today


def _send_waiting_reminder(participant: BirthboardParticipant):
    """Send reminder via the existing enterprise-WeChat channel."""
    notify_waiting_reminder(participant)


@transaction.atomic
def _refund_paid_participants_and_terminate(record: BirthboardRecord):
    # logger.debug(
    #     "[birthboard.jobs] _refund_paid_participants_and_terminate: start record_id=%s status=%s per_cost=%s",
    #     record.id,
    #     record.status,
    #     record.per_cost,
    # )
    paid_parts = list(
        BirthboardParticipant.objects.select_for_update().filter(
            record=record,
            status=BirthboardParticipant.Status.PAID,
        )
    )
    # logger.debug(
    #     "[birthboard.jobs] _refund_paid_participants_and_terminate: paid_parts_count=%s record_id=%s",
    #     len(paid_parts),
    #     record.id,
    # )
    paid_users = {}
    if paid_parts:
        paid_user_ids = [p.user_id for p in paid_parts]
        paid_users = {
            u.id: u
            for u in User.objects.select_for_update().filter(id__in=paid_user_ids)
        }
        now = datetime.now()
        for paid_part in paid_parts:
            paid_user = paid_users.get(paid_part.user_id)
            if paid_user is None:
                logger.warning(
                    "[birthboard.jobs] _refund_paid_participants_and_terminate: missing user for paid_part_id=%s user_id=%s",
                    paid_part.id,
                    paid_part.user_id,
                )
                continue
            # logger.debug(
            #     "[birthboard.jobs] _refund_paid_participants_and_terminate: refunding user=%s paid_part_id=%s delta=%s",
            #     paid_user.username,
            #     paid_part.id,
            #     record.per_cost,
            # )
            paid_user.YQpoint += record.per_cost
            paid_user.save(update_fields=["YQpoint"])
            YQPointRecord.objects.create(
                user=paid_user,
                delta=record.per_cost,
                source="birthboard_refund",
                source_type=getattr(YQPointRecord.SourceType, "BIRTHBOARD", 0),
            )
            paid_part.status = BirthboardParticipant.Status.REFUNDED
            paid_part.action_time = now
            paid_part.save(update_fields=["status", "action_time"])
            # logger.debug(
            #     "[birthboard.jobs] _refund_paid_participants_and_terminate: paid_part refunded paid_part_id=%s",
            #     paid_part.id,
            # )

    record.status = BirthboardRecord.Status.TERMINATED
    record.save(update_fields=["status"])
    logger.info(
        "[birthboard.jobs] _refund_paid_participants_and_terminate: record terminated record_id=%s new_status=%s",
        record.id,
        record.status,
    )
    notify_auto_reject_refund(record, paid_users)


@periodical(
    "cron",
    "birthboard_waiting_remind_and_autoreject",
    hour=12,
    minute=0,
)
def birthboard_waiting_remind_and_autoreject():
    """At 12:00 daily:
    - D-3: remind waiting sender/receiver
    - D-1: auto reject waiting sender/receiver
    """
    today = _today_local_date()
    # print(today)
    remind_date = today + timedelta(days=3)
    auto_reject_date = today + timedelta(days=1)
    logger.info(
        "[birthboard.jobs] birthboard_waiting_remind_and_autoreject: start today=%s remind_date=%s auto_reject_date=%s",
        today,
        remind_date,
        auto_reject_date,
    )

    waiting_record_statuses = [
        BirthboardRecord.Status.WAITING_CONFIRM,
        BirthboardRecord.Status.WAITING_RECEIVER,
    ]

    remind_parts = (
        BirthboardParticipant.objects.select_related("record", "user")
        .filter(
            status=BirthboardParticipant.Status.WAIT,
            role__in=[
                BirthboardParticipant.Role.SENDER,
                BirthboardParticipant.Role.RECEIVER,
            ],
            record__status__in=waiting_record_statuses,
            record__date=remind_date,
        )
        .order_by("record_id", "id")
    )
    remind_count = remind_parts.count()
    logger.info(
        "[birthboard.jobs] birthboard_waiting_remind_and_autoreject: remind_parts_count=%s",
        remind_count,
    )
    for part in remind_parts:
        # logger.debug(
        #     "[birthboard.jobs] birthboard_waiting_remind_and_autoreject: remind part_id=%s record_id=%s user=%s role=%s",
        #     part.id,
        #     part.record_id,
        #     part.user.username,
        #     part.role,
        # )
        _send_waiting_reminder(part)

    auto_parts = (
        BirthboardParticipant.objects.select_related("record", "user")
        .filter(
            status=BirthboardParticipant.Status.WAIT,
            role__in=[
                BirthboardParticipant.Role.SENDER,
                BirthboardParticipant.Role.RECEIVER,
            ],
            record__status__in=waiting_record_statuses,
            record__date=auto_reject_date,
        )
        .order_by("record_id", "id")
    )
    auto_count = auto_parts.count()
    logger.info(
        "[birthboard.jobs] birthboard_waiting_remind_and_autoreject: auto_parts_count=%s",
        auto_count,
    )

    processed_record_ids: set[int] = set()
    for part in auto_parts:
        # logger.debug(
        #     "[birthboard.jobs] birthboard_waiting_remind_and_autoreject: auto part_id=%s record_id=%s user=%s role=%s",
        #     part.id,
        #     part.record_id,
        #     part.user.username,
        #     part.role,
        # )
        if part.record_id in processed_record_ids:
            # logger.debug(
            #     "[birthboard.jobs] birthboard_waiting_remind_and_autoreject: skip processed record_id=%s",
            #     part.record_id,
            # )
            continue

        with transaction.atomic():
            locked_record = BirthboardRecord.objects.select_for_update().get(id=part.record_id)
            locked_part = BirthboardParticipant.objects.select_for_update().get(id=part.id)
            # logger.debug(
            #     "[birthboard.jobs] birthboard_waiting_remind_and_autoreject: locked record_id=%s record_status=%s record_date=%s part_id=%s part_status=%s",
            #     locked_record.id,
            #     locked_record.status,
            #     locked_record.date,
            #     locked_part.id,
            #     locked_part.status,
            # )

            if (
                locked_record.status not in waiting_record_statuses
                or locked_record.date != auto_reject_date
                or locked_part.status != BirthboardParticipant.Status.WAIT
            ):
                # logger.debug(
                #     "[birthboard.jobs] birthboard_waiting_remind_and_autoreject: skip after recheck record_id=%s",
                #     locked_record.id,
                # )
                continue

            before_status = locked_record.status
            locked_part.status = BirthboardParticipant.Status.REJECTED
            locked_part.action_time = datetime.now()
            locked_part.save(update_fields=["status", "action_time"])
            logger.info(
                "[birthboard.jobs] birthboard_waiting_remind_and_autoreject: auto reject participant part_id=%s user=%s role=%s record_id=%s",
                locked_part.id,
                locked_part.user.username,
                locked_part.role,
                locked_record.id,
            )

            _refund_paid_participants_and_terminate(locked_record)
            ChangeRecord.log(
                record=locked_record,
                actor=locked_part.user,
                action=ChangeRecord.Action.REJECT,
                before_status=before_status,
                after_status=locked_record.status,
                detail={
                    "scope": "auto_timeout",
                    "role": locked_part.role,
                    "participant": locked_part.user.username,
                    "days_before": 1,
                },
            )
            logger.info(
                "[birthboard.jobs] birthboard_waiting_remind_and_autoreject: change log created record_id=%s before=%s after=%s",
                locked_record.id,
                before_status,
                locked_record.status,
            )

            processed_record_ids.add(locked_record.id)

    logger.info(
        "[birthboard.jobs] birthboard_waiting_remind_and_autoreject: finished processed_record_ids=%s",
        sorted(processed_record_ids),
    )


@periodical(
    "cron",
    "birthboard_nightly_update_2345",
    hour=23,
    minute=45,
)
def birthboard_nightly_update_2345():
    """Nightly task at 23:45: switch READY->ONGOING and ONGOING->FINISHED for target_date=tomorrow,
    collect absolute image paths and call update_list for each path.
    """
    today = _today_local_date()
    target_date = today + timedelta(days=1)
    logger.info("[birthboard.jobs] nightly_update_2345: start target_date=%s", target_date)

    # lazy imports for playright-dependent modules
    from playwright.sync_api import sync_playwright
    from birthboard.web_controller import open_and_login, _run_update_cycle
    from boot.config import shihannet

    to_start = []
    to_stop = []

    # Acquire lock (cache key) to notify views
    _set_update_lock(True)
    try:
        tomorrow_records = BirthboardRecord.objects.filter(
            status=BirthboardRecord.Status.READY, date=target_date
        )
        for rec in tomorrow_records:
            notify_broadcast_starting_tomorrow(rec, target_date)

        # START: READY -> ONGOING
        with transaction.atomic():
            starts = list(
                BirthboardRecord.objects.select_for_update().filter(
                    status=BirthboardRecord.Status.READY,
                    date=target_date,
                )
            )
            for rec in starts:
                before = rec.status
                rec.status = BirthboardRecord.Status.ONGOING
                rec.save(update_fields=["status"])
                ChangeRecord.log(
                    record=rec,
                    actor=None,
                    action=ChangeRecord.Action.UPDATE,
                    before_status=before,
                    after_status=rec.status,
                    detail={"scope": "nightly_start", "date": str(target_date)},
                )
                notify_broadcast_started(rec)
                img_path = _get_abs_image_path(rec.image)
                if img_path:
                    to_start.append(img_path)

            # STOP: ONGOING -> FINISHED when end_date == target_date
            ongoing_qs = list(
                BirthboardRecord.objects.select_for_update().filter(
                    status=BirthboardRecord.Status.ONGOING,
                    date__lte=target_date,
                )
            )
            for rec in ongoing_qs:
                dur = _get_mode_duration_days(rec)
                end_date = rec.date + timedelta(days=dur)
                if end_date == target_date:
                    before = rec.status
                    rec.status = BirthboardRecord.Status.FINISHED
                    rec.save(update_fields=["status"])
                    ChangeRecord.log(
                        record=rec,
                        actor=None,
                        action=ChangeRecord.Action.UPDATE,
                        before_status=before,
                        after_status=rec.status,
                        detail={"scope": "nightly_finish", "date": str(target_date), "duration_days": dur},
                    )
                    notify_broadcast_ended(rec, end_date)
                    img_path = _get_abs_image_path(rec.image)
                    if img_path:
                        to_stop.append(img_path)
                elif dur > 1 and end_date - timedelta(days=1) == target_date:
                    notify_broadcast_ending_soon(rec, end_date)

        # After commits, call update_list for each path (do not roll back on update_list failure)
        try:
            url = shihannet.url
            username = shihannet.username
            password = shihannet.password
            # for p in to_start:
            #     try:
            #         update_list(p)
            #     except Exception:
            #         logger.exception("[birthboard.jobs] nightly_update_2345: update_list(start) failed for %s", p)
            # for p in to_stop:
            #     try:
            #         update_list(p)
            #     except Exception:
            #         logger.exception("[birthboard.jobs] nightly_update_2345: update_list(stop) failed for %s", p)
            with sync_playwright() as p:
                browser = None
                page = None
                try:
                    browser, page = open_and_login(
                        playwright=p,
                        url=url,
                        username=username,
                        password=password,
                    )

                    browser, page, outcome = _run_update_cycle(
                        playwright=p,
                        browser=browser,
                        page=page,
                        url=url,
                        username=username,
                        password=password,
                        up_image_name=to_start,
                        del_image_name=to_stop,
                    )
                finally:
                    if browser is not None:
                        try:
                            browser.close()
                        except Exception:
                            pass
        except Exception:
            logger.exception("[birthboard.jobs] nightly_update_2345: update_list loop failed")

        logger.info(
            "[birthboard.jobs] nightly_update_2345: finished to_start=%s to_stop=%s",
            len(to_start),
            len(to_stop),
        )
    finally:
        _set_update_lock(False)


# @periodical(
#     "cron",
#     "birthboard_nightly_update_0005",
#     hour=0,
#     minute=5,
# )
# def birthboard_nightly_update_0005():
#     """Repeat the same transition at 00:05; calls update_list similarly (with different parameter you will implement).
#     """
#     today = _today_local_date()
#     target_date = today + timedelta(days=1)
#     logger.info("[birthboard.jobs] nightly_update_0005: start target_date=%s", target_date)

#     to_start = []
#     to_stop = []

#     _set_update_lock(True)
#     try:
#         with transaction.atomic():
#             starts = list(
#                 BirthboardRecord.objects.select_for_update().filter(
#                     status=BirthboardRecord.Status.READY,
#                     date=target_date,
#                 )
#             )
#             for rec in starts:
#                 before = rec.status
#                 rec.status = BirthboardRecord.Status.ONGOING
#                 rec.save(update_fields=["status"])
#                 ChangeRecord.log(
#                     record=rec,
#                     actor=None,
#                     action=ChangeRecord.Action.UPDATE,
#                     before_status=before,
#                     after_status=rec.status,
#                     detail={"scope": "nightly_start_0005", "date": str(target_date)},
#                 )
#                 img_path = getattr(rec.image, 'path', None)
#                 if img_path:
#                     to_start.append(img_path)

#             ongoing_qs = list(
#                 BirthboardRecord.objects.select_for_update().filter(
#                     status=BirthboardRecord.Status.ONGOING,
#                     date__lte=target_date,
#                 )
#             )
#             for rec in ongoing_qs:
#                 dur = _get_mode_duration_days(rec)
#                 end_date = rec.date + timedelta(days=dur)
#                 if end_date == target_date:
#                     before = rec.status
#                     rec.status = BirthboardRecord.Status.FINISHED
#                     rec.save(update_fields=["status"])
#                     ChangeRecord.log(
#                         record=rec,
#                         actor=None,
#                         action=ChangeRecord.Action.UPDATE,
#                         before_status=before,
#                         after_status=rec.status,
#                         detail={"scope": "nightly_finish_0005", "date": str(target_date), "duration_days": dur},
#                     )
#                     img_path = getattr(rec.image, 'path', None)
#                     if img_path:
#                         to_stop.append(img_path)

#         # call update_list; you mentioned second run uses a different parameter — implement in your update_list
#         try:
#             for p in to_start:
#                 try:
#                     update_list(p)
#                 except Exception:
#                     logger.exception("[birthboard.jobs] nightly_update_0005: update_list(start) failed for %s", p)
#             for p in to_stop:
#                 try:
#                     update_list(p)
#                 except Exception:
#                     logger.exception("[birthboard.jobs] nightly_update_0005: update_list(stop) failed for %s", p)
#         except Exception:
#             logger.exception("[birthboard.jobs] nightly_update_0005: update_list loop failed")

#         logger.info(
#             "[birthboard.jobs] nightly_update_0005: finished to_start=%s to_stop=%s",
#             len(to_start),
#             len(to_stop),
#         )
#     finally:
#         _set_update_lock(False)
