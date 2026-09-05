from datetime import timedelta, datetime
import os
import uuid

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

__all__ = [
    'birthboard_waiting_remind_and_autoreject',
    'birthboard_nightly_update_2345',
    'birthboard_nightly_retry_0005',
    'birthboard_auto_terminate_stale_waiting',
    'birthboard_retry_pending_takedowns',
    'attempt_pending_takedown',
]

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


def _acquire_update_lock(timeout: int = 60 * 60) -> str | None:
    """Acquire the cross-process display lock without replacing its owner."""
    token = uuid.uuid4().hex
    try:
        if cache.add(_BB_UPDATE_LOCK_KEY, token, timeout=timeout):
            return token
    except Exception:
        logger.exception(
            '[birthboard.jobs] failed to acquire display update lock'
        )
    return None


def _release_update_lock(token: str) -> None:
    """Release the display lock only when this process still owns it."""
    try:
        if cache.get(_BB_UPDATE_LOCK_KEY) == token:
            cache.delete(_BB_UPDATE_LOCK_KEY)
    except Exception:
        logger.exception(
            '[birthboard.jobs] failed to release display update lock'
        )


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
            cost_map = {35: 1, 60: 3, 10000: 365}
            if mode in cost_map:
                return cost_map[mode]
        if isinstance(mode, str) and mode.isdigit():
            m = int(mode)
            cost_map = {35: 1, 60: 3, 10000: 365}
            return cost_map.get(m, 1)
    except Exception:
        logger.exception("[birthboard.jobs] _get_mode_duration_days: failed to deduce duration, default to 1")
    return 1


def attempt_pending_takedown(record_id: int) -> bool:
    """Serialize a display takedown against nightly updates and other retries."""
    lock_token = _acquire_update_lock()
    if lock_token is None:
        return False
    try:
        return _attempt_pending_takedown(record_id)
    finally:
        _release_update_lock(lock_token)


def _attempt_pending_takedown(record_id: int) -> bool:
    """Try to remove a rejected/revoked active image from every display list.

    The pending flag is cleared only after the external controller reports a
    complete success. Failures remain durable for the periodic retry job.
    """
    record = BirthboardRecord.objects.filter(
        pk=record_id,
        display_takedown_pending=True,
    ).first()
    if record is None:
        return True
    image_path = _get_abs_image_path(record.image)
    if not image_path:
        logger.error(
            '[birthboard.jobs] pending takedown has no image record_id=%s',
            record_id,
        )
        return False

    from playwright.sync_api import sync_playwright
    from birthboard.config import shihannet
    from birthboard.web_controller import open_and_login, _run_update_cycle

    browser = None
    outcome = None
    try:
        with sync_playwright() as playwright:
            browser, page = open_and_login(
                playwright=playwright,
                url=shihannet.url,
                username=shihannet.username,
                password=shihannet.password,
            )
            browser, page, outcome = _run_update_cycle(
                playwright=playwright,
                browser=browser,
                page=page,
                url=shihannet.url,
                username=shihannet.username,
                password=shihannet.password,
                up_image_name=[],
                del_image_name=[image_path],
            )
    except Exception:
        logger.exception(
            '[birthboard.jobs] display takedown failed record_id=%s',
            record_id,
        )
        return False
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                logger.warning(
                    '[birthboard.jobs] display browser close failed record_id=%s',
                    record_id,
                )

    if not getattr(outcome, 'ok', False):
        logger.error(
            '[birthboard.jobs] display takedown incomplete record_id=%s',
            record_id,
        )
        return False

    with transaction.atomic():
        locked_record = BirthboardRecord.objects.select_for_update().get(
            pk=record_id,
        )
        if locked_record.display_takedown_pending:
            locked_record.display_takedown_pending = False
            locked_record.save(update_fields=['display_takedown_pending'])
    return True


@periodical(
    'interval',
    'birthboard_retry_pending_takedowns',
    minutes=15,
)
def birthboard_retry_pending_takedowns():
    """Retry durable display takedowns that did not complete immediately."""
    record_ids = list(
        BirthboardRecord.objects.filter(display_takedown_pending=True)
        .order_by('id')
        .values_list('id', flat=True)
    )
    for record_id in record_ids:
        attempt_pending_takedown(record_id)


def _today_local_date():
    # logger.debug("[birthboard.jobs] _today_local_date: start")
    now = datetime.now()
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
            role=BirthboardParticipant.Role.SENDER,
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
            refund_amount = paid_part.cost
            paid_user.YQpoint += refund_amount
            paid_user.save(update_fields=["YQpoint"])
            YQPointRecord.objects.create(
                user=paid_user,
                delta=refund_amount,
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
    transaction.on_commit(lambda: notify_auto_reject_refund(record, paid_users))


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
def birthboard_nightly_update_2345(
    target_date=None,
    *,
    send_starting_reminder=True,
):
    """Nightly task at 23:45: switch READY->ONGOING and ONGOING->FINISHED for target_date=tomorrow,
    collect absolute image paths and call update_list for each path.
    """
    today = _today_local_date()
    if target_date is None:
        target_date = today + timedelta(days=1)
    logger.info("[birthboard.jobs] nightly_update_2345: start target_date=%s", target_date)

    # lazy imports for playright-dependent modules
    from playwright.sync_api import sync_playwright
    from birthboard.web_controller import open_and_login, _run_update_cycle
    from birthboard.config import shihannet

    to_start = []
    to_stop = []
    start_records = []
    stop_records = []

    lock_token = _acquire_update_lock()
    if lock_token is None:
        logger.warning(
            '[birthboard.jobs] nightly update skipped because display lock '
            'is unavailable'
        )
        return
    try:
        if send_starting_reminder:
            tomorrow_records = BirthboardRecord.objects.filter(
                status=BirthboardRecord.Status.READY,
                date=target_date,
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
                img_path = _get_abs_image_path(rec.image)
                if img_path:
                    to_start.append(img_path)
                start_records.append(rec)

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
                    img_path = _get_abs_image_path(rec.image)
                    if img_path:
                        to_stop.append(img_path)
                    stop_records.append(rec)
                elif dur > 1 and end_date - timedelta(days=1) == target_date:
                    transaction.on_commit(lambda rec=rec, end_date=end_date: notify_broadcast_ending_soon(rec, end_date))

        # After the database commit, synchronize removals before additions.
        # The two phases have separate outcomes so a failed upload cannot
        # roll back a removal that has already succeeded on the display.
        stop_update_ok = not to_stop
        start_update_ok = not to_start
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
            if to_start or to_stop:
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

                        if to_stop:
                            browser, page, stop_outcome = _run_update_cycle(
                                playwright=p,
                                browser=browser,
                                page=page,
                                url=url,
                                username=username,
                                password=password,
                                up_image_name=[],
                                del_image_name=to_stop,
                            )
                            stop_update_ok = bool(
                                getattr(stop_outcome, 'ok', False)
                            )
                        if stop_update_ok and to_start:
                            browser, page, start_outcome = _run_update_cycle(
                                playwright=p,
                                browser=browser,
                                page=page,
                                url=url,
                                username=username,
                                password=password,
                                up_image_name=to_start,
                                del_image_name=[],
                            )
                            start_update_ok = bool(
                                getattr(start_outcome, 'ok', False)
                            )
                    finally:
                        if browser is not None:
                            try:
                                browser.close()
                            except Exception:
                                pass
        except Exception:
            logger.exception("[birthboard.jobs] nightly_update_2345: update_list loop failed")
            if to_stop and not stop_update_ok:
                start_update_ok = False
            elif to_start:
                start_update_ok = False

        if not stop_update_ok:
            # A required removal failed. Roll back both phases and do not add
            # new content while stale content may still be present.
            logger.error(
                "[birthboard.jobs] nightly_update_2345: display removal failed, reverting transitions "
                "to_start=%s to_stop=%s",
                len(to_start),
                len(to_stop),
            )
            _revert_nightly_transitions(start_records, stop_records, target_date)
        elif not start_update_ok:
            logger.error(
                '[birthboard.jobs] nightly_update_2345: display upload failed, '
                'reverting start transitions to_start=%s',
                len(to_start),
            )
            _revert_nightly_transitions(start_records, [], target_date)

        if start_update_ok:
            for record in start_records:
                notify_broadcast_started(record)
        if stop_update_ok:
            for record in stop_records:
                end_date = record.date + timedelta(
                    days=_get_mode_duration_days(record)
                )
                notify_broadcast_ended(record, end_date)

        logger.info(
            "[birthboard.jobs] nightly_update_2345: finished to_start=%s to_stop=%s",
            len(to_start),
            len(to_stop),
        )
    finally:
        _release_update_lock(lock_token)


@periodical(
    'cron',
    'birthboard_nightly_retry_0005',
    hour=0,
    minute=5,
)
def birthboard_nightly_retry_0005():
    """Retry the previous 23:45 display sync for the now-current date."""
    birthboard_nightly_update_2345(
        target_date=_today_local_date(),
        send_starting_reminder=False,
    )


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

def _revert_nightly_transitions(
    start_records: list, stop_records: list, target_date
):
    """屏幕更新失败后回退夜间已推进的状态，保证下个任务周期可重试。

    - READY->ONGOING 的记录回退为 READY
    - ONGOING->FINISHED 的记录回退为 ONGOING
    仅回退当前仍处于推进后状态的记录，避免覆盖并发产生的其它状态变化。
    """
    for rec in start_records:
        with transaction.atomic():
            refreshed = (
                BirthboardRecord.objects.select_for_update()
                .filter(pk=rec.pk, status=BirthboardRecord.Status.ONGOING)
                .first()
            )
            if refreshed is None:
                continue
            refreshed.status = BirthboardRecord.Status.READY
            refreshed.save(update_fields=["status"])
            ChangeRecord.log(
                record=refreshed,
                actor=None,
                action=ChangeRecord.Action.UPDATE,
                before_status=BirthboardRecord.Status.ONGOING,
                after_status=BirthboardRecord.Status.READY,
                detail={"scope": "nightly_revert_start", "date": str(target_date)},
            )
    for rec in stop_records:
        with transaction.atomic():
            refreshed = (
                BirthboardRecord.objects.select_for_update()
                .filter(pk=rec.pk, status=BirthboardRecord.Status.FINISHED)
                .first()
            )
            if refreshed is None:
                continue
            refreshed.status = BirthboardRecord.Status.ONGOING
            refreshed.save(update_fields=["status"])
            ChangeRecord.log(
                record=refreshed,
                actor=None,
                action=ChangeRecord.Action.UPDATE,
                before_status=BirthboardRecord.Status.FINISHED,
                after_status=BirthboardRecord.Status.ONGOING,
                detail={"scope": "nightly_revert_stop", "date": str(target_date)},
            )

@periodical(
    "cron",
    "birthboard_auto_terminate_stale_waiting",
    hour=0,
    minute=10,
)
def birthboard_auto_terminate_stale_waiting():
    """Daily at 00:10: terminate records whose planned date has passed but which
    never reached READY (still waiting_confirm / waiting_receiver / waiting_approve).

    Refund paid participants and mark TERMINATED (same as abort), then log a
    REJECT change record with scope auto_terminate_stale.
    """
    today = _today_local_date()
    stale_statuses = [
        BirthboardRecord.Status.WAITING_CONFIRM,
        BirthboardRecord.Status.WAITING_RECEIVER,
        BirthboardRecord.Status.WAITING_APPROVE,
    ]
    stale_ids = list(
        BirthboardRecord.objects.filter(
            date__lte=today,
            status__in=stale_statuses,
        ).values_list("id", flat=True)
    )
    logger.info(
        "[birthboard.jobs] birthboard_auto_terminate_stale_waiting: start today=%s candidates=%s",
        today,
        len(stale_ids),
    )
    for record_id in stale_ids:
        with transaction.atomic():
            locked_record = BirthboardRecord.objects.select_for_update().get(id=record_id)
            # 加锁后复查，避免与并发审批/付款交错
            if locked_record.status not in stale_statuses or locked_record.date > today:
                continue
            before_status = locked_record.status
            _refund_paid_participants_and_terminate(locked_record)
            ChangeRecord.log(
                record=locked_record,
                actor=None,
                action=ChangeRecord.Action.REJECT,
                before_status=before_status,
                after_status=locked_record.status,
                detail={"scope": "auto_terminate_stale", "date": str(locked_record.date)},
            )
            logger.info(
                "[birthboard.jobs] birthboard_auto_terminate_stale_waiting: terminated record_id=%s before=%s after=%s",
                locked_record.id,
                before_status,
                locked_record.status,
            )
    logger.info(
        "[birthboard.jobs] birthboard_auto_terminate_stale_waiting: finished candidates=%s",
        len(stale_ids),
    )
