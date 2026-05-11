import json
import os
from datetime import datetime, timedelta
import logging

from django.db import transaction
from django.db.models import Q, OuterRef, Subquery, DateTimeField
from django.db.models.functions import Coalesce
from django.core.files.images import get_image_dimensions
from django.contrib import messages

from app.views_dependency import *
from birthboard.models import (
    BirthboardRecord,
    ChangeRecord,
    BirthboardApprover,
    BirthboardParticipant,
    BirthboardRejectedIssue,
    BirthboardSecondApprover,
)
from django.views.decorators.http import require_http_methods
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.http import JsonResponse

from birthboard.forms import BirthboardForm
from birthboard.utils import calculate_per_cost

User = get_user_model()

# 审核员ID白名单

from django.shortcuts import redirect
from django.urls import reverse

from django.core.cache import cache

from birthboard.web_controller import open_and_login, _run_update_cycle
from birthboard.jobs import _get_abs_image_path
from playwright.sync_api import sync_playwright

from boot.config import shihannet

_BB_UPDATE_LOCK_KEY = "birthboard:update_in_progress"
logger = logging.getLogger(__name__)

def _handle_revoke(revoke_id: str, actor=None) -> None:
    """处理撤销请求：改状态为CANCELED但不退款。"""
    # 如果正在执行批量更新（夜间任务），拒绝冲突操作
    try:
        if cache.get(_BB_UPDATE_LOCK_KEY):
            logger.info("_handle_revoke: update in progress, reject revoke %s", revoke_id)
            return
    except Exception:
        # 忽略 cache 异常，继续执行以保持兼容性
        pass
    try:
        with transaction.atomic():
            record = BirthboardRecord.objects.select_for_update().get(id=revoke_id)
            before_status = record.status
            record.status = record.Status.CANCELED
            record.save(update_fields=["status"])
            _log_record_change(record, actor=actor, action=ChangeRecord.Action.REVOKE, before_status=before_status, after_status=record.status, detail={"revoke_id": revoke_id})
            # 如果原状态为 ONGOING，调用外部的 update_list(image_path)
            try:
                if before_status == BirthboardRecord.Status.ONGOING:
                    img_path = _get_abs_image_path(record.image)
                    if img_path:
                        try:
                            url = shihannet.url
                            username = shihannet.username
                            password = shihannet.password
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
                                        up_image_name=[],
                                        del_image_name=[img_path],
                                    )
                                finally:
                                    if browser is not None:
                                        try:
                                            browser.close()
                                        except Exception:
                                            pass
                        except Exception:
                            logger.exception("[birthboard.jobs] nightly_update_2345: update_list loop failed")

            except Exception:
                # 忽略任何与补充逻辑相关的异常，确保撤销流程不被中断
                pass
    except BirthboardRecord.DoesNotExist:
        pass


def _log_record_change(record: BirthboardRecord, actor, action: str, before_status: str = '', after_status: str = '', detail=None) -> None:
    ChangeRecord.log(
        record=record,
        actor=actor,
        action=action,
        before_status=before_status,
        after_status=after_status,
        detail=detail or {},
    )


def _get_rejected_info(record: BirthboardRecord):
    if record.status != record.Status.TERMINATED_BY_ADMIN:
        return None, None
    try:
        rejected_issue = record.rejected_issue
        return rejected_issue.get_reason_list(), rejected_issue.detail
    except BirthboardRejectedIssue.DoesNotExist:
        return None, None


def _build_activity_base(record: BirthboardRecord):
    rejected_reasons, rejected_detail = _get_rejected_info(record)
    return {
        'id': record.id,
        'date': record.date,
        'image': record.image.url if record.image else '',
        'receiver_name': record.receiver_name,
        'per_cost': record.per_cost,
        'is_anonymous': record.is_anonymous,
        'mode': record.mode,
        'record_status': str(record.status),
        'rejected_reasons': rejected_reasons,
        'rejected_detail': rejected_detail,
    }


def _deduct_and_mark_paid(user, part: BirthboardParticipant, amount: int, set_action_time: bool = True) -> bool:
    from generic.models import YQPointRecord

    # Use the atomic manager method to modify user's YQpoint and record the change.
    # This ensures select_for_update and transaction.atomic are used consistently.
    try:
        User.objects.modify_YQPoint(user, -amount, source="birthboard", source_type=getattr(YQPointRecord.SourceType, 'BIRTHBOARD', 0))
    except AssertionError:
        # insufficient funds
        return False
    part.status = BirthboardParticipant.Status.PAID
    update_fields = ["status"]
    if set_action_time:
        part.action_time = datetime.now()
        update_fields.append("action_time")
    part.save(update_fields=update_fields)
    return True


def _is_user_related_to_record(record: BirthboardRecord, user) -> bool:
    is_receiver = record.receiver_username == user.username
    is_participant = BirthboardParticipant.objects.filter(
        record=record,
        user=user,
    ).exists()
    return is_receiver or is_participant


def _reject_record_by_admin(record: BirthboardRecord, reasons, detail: str, actor=None) -> None:
    before_status = record.status
    BirthboardRejectedIssue.objects.update_or_create(
        record=record,
        defaults={
            "reasons": ','.join(reasons),
            "detail": detail,
        },
    )
    record.status = BirthboardRecord.Status.TERMINATED_BY_ADMIN
    record.save(update_fields=["status"])
    _log_record_change(
        record,
        actor=actor,
        action=ChangeRecord.Action.REJECT,
        before_status=before_status,
        after_status=record.status,
        detail={"reasons": reasons, "detail": detail, "scope": "admin"},
    )


def _refund_paid_participants_and_terminate(record: BirthboardRecord, actor=None, action: str = ChangeRecord.Action.REFUND, detail=None) -> None:
    """退还活动中所有已扣款参与者，并将活动置为终止。"""
    from generic.models import YQPointRecord

    before_status = record.status
    paid_parts = list(
        BirthboardParticipant.objects.select_for_update().filter(
            record=record,
            status=BirthboardParticipant.Status.PAID,
        )
    )
    if paid_parts:
        paid_user_ids = [p.user_id for p in paid_parts]
        paid_users = {
            u.id: u for u in User.objects.select_for_update().filter(id__in=paid_user_ids)
        }
        now = datetime.now()
        for paid_part in paid_parts:
            paid_user = paid_users.get(paid_part.user_id)
            if paid_user is None:
                continue
            paid_user.YQpoint += record.per_cost
            paid_user.save(update_fields=["YQpoint"])
            YQPointRecord.objects.create(
                user=paid_user,
                delta=record.per_cost,
                source="birthboard_refund",
                source_type=getattr(YQPointRecord.SourceType, 'BIRTHBOARD', 0),
            )
            paid_part.status = BirthboardParticipant.Status.REFUNDED
            paid_part.action_time = now
            paid_part.save(update_fields=["status", "action_time"])

    record.status = record.Status.TERMINATED
    record.save(update_fields=["status"])
    _log_record_change(record, actor=actor, action=action, before_status=before_status, after_status=record.status, detail=detail or {"refunded_participants": [p.user_id for p in paid_parts]})


def _get_today_entry_reminders(user):
    now = timezone.now()
    today = timezone.localtime(now).date() if timezone.is_aware(now) else now.date()
    excluded_statuses = [
        BirthboardRecord.Status.CANCELED,
        BirthboardRecord.Status.TERMINATED,
        BirthboardRecord.Status.TERMINATED_BY_ADMIN,
    ]
    has_receiver_today = BirthboardRecord.objects.filter(
        receiver_username=user.username,
        date=today,
    ).exclude(status__in=excluded_statuses).exists()
    has_sender_today = BirthboardParticipant.objects.filter(
        user=user,
        role=BirthboardParticipant.Role.SENDER,
        record__date=today,
    ).exclude(record__status__in=excluded_statuses).exists()

    receiver_names = list(
        BirthboardRecord.objects.filter(
            receiver_username=user.username,
            date=today,
        )
        .exclude(status__in=excluded_statuses)
        .values_list("receiver_name", flat=True)
        .distinct()
    )
    sender_names = list(
        BirthboardParticipant.objects.filter(
            user=user,
            role=BirthboardParticipant.Role.SENDER,
            record__date=today,
        )
        .exclude(record__status__in=excluded_statuses)
        .values_list("record__receiver_name", flat=True)
        .distinct()
    )
    return {
        "today": today.isoformat(),
        "has_receiver_today": has_receiver_today,
        "has_sender_today": has_sender_today,
        "receiver_names": receiver_names,
        "sender_names": sender_names,
    }


def _get_birthboard_date_rule(now_dt=None):
    if now_dt is None:
        now_dt = timezone.now()
        if timezone.is_aware(now_dt):
            now_dt = timezone.localtime(now_dt)
        # now_dt = timezone.make_aware(datetime(2026, 5, 3, 12, 0))
    # print("当前时间（本地时区）:", now_dt)
    today = now_dt.date()
    week_monday = today - timedelta(days=today.weekday())
    next_monday = week_monday + timedelta(days=7)
    next_next_monday = week_monday + timedelta(days=14)
    next_next_sunday = week_monday + timedelta(days=20)
    next_next_next_sunday = week_monday + timedelta(days=27)

    sunday_noon_or_after = (today.weekday() == 6 and (now_dt.hour, now_dt.minute) >= (12, 0))
    if sunday_noon_or_after:
        return {
            "mode": "range",
            "min_date": next_next_monday,
            "max_date": next_next_next_sunday,
            "message": "当前时间已到周日中午12点后，仅可提交下下周周一到下下下周周日的投放。",
        }
    return {
        "mode": "range",
        "min_date": next_monday,
        "max_date": next_next_sunday,
        "message": "仅可提交下一周周一到下下周周日的投放。",
    }


def _serialize_birthboard_date_rule(rule):
    return {
        "mode": rule["mode"],
        "min_date": rule["min_date"].isoformat(),
        "max_date": rule["max_date"].isoformat(),
        "message": rule["message"],
    }


def _is_birthboard_date_allowed(submit_date, rule):
    return rule["min_date"] <= submit_date <= rule["max_date"]


@require_http_methods(["GET"])
def time_now(request):
    """Return current server time (uses patched timezone.now if middleware enabled)."""
    now = timezone.now()
    try:
        iso = now.isoformat()
    except Exception:
        iso = str(now)
    return JsonResponse({"now": iso})

@login_required(redirect_field_name="origin")
@require_http_methods(["GET", "POST"])
def birthboard(request):
    users = User.objects.all()
    from generic.utils import to_search_indices
    user_infos = to_search_indices(users, active=True)
    # 获取所有用户元气值
    yqpoints = {u.username: u.YQpoint for u in users}
    json_context = {'user_infos': user_infos, 'yqpoints': yqpoints}
    today_entry_reminders = _get_today_entry_reminders(request.user)
    birthboard_date_rule = _get_birthboard_date_rule()
    birthboard_date_rule_json = _serialize_birthboard_date_rule(birthboard_date_rule)

    initial = request.session.pop('birthboard_resubmit_initial', None)

    if request.method == "POST":
        # If client provided receiver_pk (hidden field), map it to 'receiver' before form binding.
        post_data = request.POST
        if 'receiver_pk' in request.POST:
            post_data = request.POST.copy()
            # set 'receiver' to the pk so BirthboardForm.ModelChoiceField can resolve it
            post_data['receiver'] = post_data.get('receiver_pk')
        form = BirthboardForm(post_data, request.FILES)
        if form.is_valid():
            receiver = form.cleaned_data['receiver']
            senders = form.cleaned_data['senders']
            image = form.cleaned_data['image']
            date = form.cleaned_data['date']
            mode = int(form.cleaned_data['mode'])
            is_anonymous = form.cleaned_data['is_anonymous']
            if not _is_birthboard_date_allowed(date, birthboard_date_rule):
                messages.error(request, birthboard_date_rule["message"])
                return render(request, "birthboard/birthboard.html", {
                    "form": form,
                    "users": users,
                    "json_context": json_context,
                    "confirm_tab_total_count": _get_confirm_tab_total_count(request, request.user),
                    "today_entry_reminders": today_entry_reminders,
                    "birthboard_date_rule": birthboard_date_rule_json,
                })
            # 校验图片尺寸
            width, height = get_image_dimensions(image)
            if width != 1920 or height != 1080:
                messages.error(request, "图片不符合要求，需1920x1080")
                current_user_id = str(request.user.username)
                return render(request, "birthboard/birthboard.html", {"form": form, "users": users, "json_context": json_context, "current_user_id": current_user_id, "confirm_tab_total_count": _get_confirm_tab_total_count(request, request.user), "today_entry_reminders": today_entry_reminders, "birthboard_date_rule": birthboard_date_rule_json})
            # 校验送出者元气值：按提交人数计算人均价，避免误按总价校验
            posted_sender_ids = set(request.POST.getlist('senders'))
            sender_count = max(len(posted_sender_ids), len(senders), 1)
            per = calculate_per_cost(mode, sender_count)
            # 实时查询数据库余额：仅校验当前登录用户本人
            current_user = request.user
            current_balance = getattr(current_user, 'YQpoint', 0)
            if current_balance < per:
                return render(request, "birthboard/birthboard.html", {
                    "form": form,
                    "users": users,
                    "json_context": json_context,
                    "insufficient_balance": current_balance,
                    "confirm_tab_total_count": _get_confirm_tab_total_count(request, request.user),
                    "today_entry_reminders": today_entry_reminders,
                    "birthboard_date_rule": birthboard_date_rule_json,
                })
            # 创建 BirthboardRecord
            try:
                from generic.models import YQPointRecord
                with transaction.atomic():
                    # 重命名图片文件：投放日期YYYYMMDD + 提交时间YYYYMMDDHHMM + 原文件名
                    original_filename = image.name
                    # 获取文件扩展名
                    file_ext = os.path.splitext(original_filename)[1]
                    original_name_without_ext = os.path.splitext(original_filename)[0]
                    # 投放日期YYYYMMDD
                    date_str = date.strftime('%Y%m%d')
                    # 提交时间YYYYMMDDHHMM
                    submit_time_str = datetime.now().strftime('%Y%m%d%H%M')
                    # 新文件名：YYYYMMDD_YYYYMMDDHHMM_原文件名
                    new_filename = f'{date_str}_{submit_time_str}_{original_name_without_ext}{file_ext}'
                    image.name = new_filename
                    
                    # 如果只有发起人自己，直接进入WAITING_RECEIVER
                    status = BirthboardRecord.Status.WAITING_RECEIVER if len(senders) == 1 and senders[0] == request.user else BirthboardRecord.Status.WAITING_CONFIRM
                    record = BirthboardRecord.objects.create(
                        receiver_username=receiver.username,
                        receiver_name=getattr(receiver, 'naturalperson', getattr(receiver, 'name', receiver.username)),
                        date=date,
                        mode=mode,
                        per_cost=per,
                        image=image,
                        is_anonymous=is_anonymous,
                        status=status,
                    )
                    # 创建送出人参与记录
                    for sender in senders:
                        is_initiator = (sender == request.user)
                        status = BirthboardParticipant.Status.PAID if is_initiator else BirthboardParticipant.Status.WAIT
                        part = BirthboardParticipant.objects.create(
                            record=record,
                            user=sender,
                            role=BirthboardParticipant.Role.SENDER,
                            is_initiator=is_initiator,
                            cost=per,
                            status=status,
                        )
                        if is_initiator:
                            try:
                                User.objects.modify_YQPoint(
                                    sender,
                                    -per,
                                    source="birthboard",
                                    source_type=getattr(YQPointRecord.SourceType, 'BIRTHBOARD', 0),
                                )
                            except AssertionError:
                                raise Exception("发起者元气值不足，无法扣款")
                    # 创建寿星参与记录
                    BirthboardParticipant.objects.create(
                        record=record,
                        user=receiver,
                        role=BirthboardParticipant.Role.RECEIVER,
                        is_initiator=False,
                        cost=0,
                        status=BirthboardParticipant.Status.WAIT,
                    )
                    _log_record_change(
                        record,
                        actor=request.user,
                        action=ChangeRecord.Action.CREATE,
                        before_status='',
                        after_status=record.status,
                        detail={
                            'receiver_username': receiver.username,
                            'sender_usernames': [sender.username for sender in senders],
                            'mode': mode,
                            'per_cost': per,
                        },
                    )
            except Exception as e:
                messages.error(request, f"记录创建失败：{e}")
                return render(request, "birthboard/birthboard.html", {"form": form, "users": users, "json_context": json_context, "confirm_tab_total_count": _get_confirm_tab_total_count(request, request.user), "today_entry_reminders": today_entry_reminders, "birthboard_date_rule": birthboard_date_rule_json})
            return redirect("birthboard_confirm")
        else:
            return render(request, "birthboard/birthboard.html", {"form": form, "users": users, "json_context": json_context, "confirm_tab_total_count": _get_confirm_tab_total_count(request, request.user), "today_entry_reminders": today_entry_reminders, "birthboard_date_rule": birthboard_date_rule_json})
    else:
        if initial:
            form = BirthboardForm(initial=initial)
        else:
            form = BirthboardForm()
        return render(request, "birthboard/birthboard.html", {
            "form": form,
            "users": users,
            "json_context": json_context,
            "birthboard_initial": json.dumps(initial) if initial else None,
            "confirm_tab_total_count": _get_confirm_tab_total_count(request, request.user),
            "today_entry_reminders": today_entry_reminders,
            "birthboard_date_rule": birthboard_date_rule_json,
        })

def _build_activity_list(records, current_user, view_type: str):
    activity_list = []
    for record in records:
        senders_part = record.participants.filter(role=BirthboardParticipant.Role.SENDER)
        base = _build_activity_base(record)

        if view_type == "received":
            receiver_part = record.participants.filter(
                role=BirthboardParticipant.Role.RECEIVER,
                user=current_user,
            ).first()
            receiver_status = receiver_part.status if receiver_part else None
            if record.status == record.Status.TERMINATED and receiver_status == BirthboardParticipant.Status.WAIT:
                continue
            activity_list.append({
                **base,
                'senders': [p.user for p in senders_part],
                'is_charged': False,
                'receiver_status': receiver_status,
            })
            continue

        senders = [
            {
                'user': p.user,
                'status': p.status,
            } for p in senders_part
        ]

        if view_type == "participation":
            confirmed_ids = [p.user.id for p in senders_part if p.status == BirthboardParticipant.Status.CONFIRMED]
            paid_ids = [p.user.id for p in senders_part if p.status == BirthboardParticipant.Status.PAID]
            all_confirmed = all(p.status == BirthboardParticipant.Status.CONFIRMED for p in senders_part)
            terminated = record.status in (record.Status.TERMINATED, record.Status.CANCELED)
            terminated_by_admin = (record.status == record.Status.TERMINATED_BY_ADMIN)
            waiting_accept = all_confirmed and record.status == record.Status.WAITING_RECEIVER
            waiting_accept_name = record.receiver_name if waiting_accept else None
            has_confirmed = any(p.user_id == current_user.id and p.status == BirthboardParticipant.Status.CONFIRMED for p in senders_part)
            has_paid = any(p.user_id == current_user.id and p.status == BirthboardParticipant.Status.PAID for p in senders_part)
            is_initiator = any(p.user_id == current_user.id and p.is_initiator for p in senders_part)
            activity_list.append({
                **base,
                'senders': senders,
                'confirmed_ids': confirmed_ids,
                'paid_ids': paid_ids,
                'has_confirmed': has_confirmed,
                'has_paid': has_paid,
                'is_charged': getattr(record, 'is_charged', False),
                'waiting_accept': waiting_accept,
                'waiting_accept_name': waiting_accept_name,
                'terminated': terminated,
                'terminated_by_admin': terminated_by_admin,
                'is_initiator': is_initiator,
            })
            continue

        activity_list.append({
            **base,
            'senders': senders,
            'is_sender': any(p.user_id == current_user.id for p in senders_part),
            'is_receiver': (record.receiver_username == current_user.username),
        })
    return activity_list


def _order_records_by_last_change(records):
    latest_change_at = (
        ChangeRecord.objects
        .filter(record_id=OuterRef("pk"))
        .order_by("-created_at")
        .values("created_at")[:1]
    )
    return (
        records
        .annotate(
            last_changed_at=Coalesce(
                Subquery(latest_change_at, output_field=DateTimeField()),
                "created_at",
            )
        )
        .order_by("-last_changed_at", "-id")
    )


def _build_participation_activity_list(current_user):
    sender_participations = BirthboardParticipant.objects.filter(user=current_user, role=BirthboardParticipant.Role.SENDER)
    excluded_statuses = [
        BirthboardRecord.Status.TERMINATED,
        BirthboardRecord.Status.CANCELED,
        BirthboardRecord.Status.FINISHED,
        BirthboardRecord.Status.TERMINATED_BY_ADMIN,
    ]
    records = BirthboardRecord.objects.filter(
        id__in=sender_participations.values_list('record_id', flat=True)
    ).exclude(status__in=excluded_statuses)
    records = _order_records_by_last_change(records)
    return _build_activity_list(records, current_user, "participation")


def _build_received_activity_list(current_user):
    valid_status = [
        BirthboardRecord.Status.WAITING_RECEIVER,
        BirthboardRecord.Status.WAITING_APPROVE,
        BirthboardRecord.Status.READY,
        BirthboardRecord.Status.ONGOING,
    ]
    records = BirthboardRecord.objects.filter(receiver_username=current_user.username, status__in=valid_status)
    records = _order_records_by_last_change(records)
    return _build_activity_list(records, current_user, "received")


def _build_finished_activity_list(current_user):
    """构建已结束的投放活动列表（作为sender或receiver）。"""
    finished_statuses = [
        BirthboardRecord.Status.TERMINATED,
        BirthboardRecord.Status.CANCELED,
        BirthboardRecord.Status.FINISHED,
        BirthboardRecord.Status.TERMINATED_BY_ADMIN,
    ]
    # 作为sender的投放
    sender_participations = BirthboardParticipant.objects.filter(
        user=current_user, role=BirthboardParticipant.Role.SENDER
    )
    sender_record_ids = list(sender_participations.values_list('record_id', flat=True))
    sender_records = BirthboardRecord.objects.filter(
        id__in=sender_record_ids,
        status__in=finished_statuses
    ) if sender_record_ids else BirthboardRecord.objects.none()
    
    # 作为receiver的投放
    receiver_records = BirthboardRecord.objects.filter(
        receiver_username=current_user.username,
        status__in=finished_statuses
    )
    
    # 合并两个querysets
    all_records = sender_records | receiver_records
    all_records = all_records.distinct()
    all_records = _order_records_by_last_change(all_records)
    
    return _build_activity_list(all_records, current_user, "finished")


def _parse_seen_time(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0)
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.fromtimestamp(0)


def _resolve_record_tab(record: BirthboardRecord, user) -> str:
    finished_statuses = {
        BirthboardRecord.Status.TERMINATED,
        BirthboardRecord.Status.CANCELED,
        BirthboardRecord.Status.FINISHED,
        BirthboardRecord.Status.TERMINATED_BY_ADMIN,
    }
    if record.status in finished_statuses:
        return "finished"
    if record.receiver_username == user.username:
        return "received"
    return "participation"


def _build_confirm_change_state(request, user, active_tab: str, clear_seen: bool = False):
    tabs = ("participation", "received", "finished")
    session_key = f"birthboard_confirm_seen_{user.id}"
    seen_raw = request.session.get(session_key, {})
    seen_dt = {tab: _parse_seen_time(seen_raw.get(tab)) for tab in tabs}

    changed_ids_by_tab = {tab: set() for tab in tabs}
    changes = (
        ChangeRecord.objects
        .filter(
            Q(record__receiver_username=user.username) |
            Q(record__participants__user=user, record__participants__role=BirthboardParticipant.Role.SENDER)
        )
        .select_related("record")
        .order_by("-created_at", "-id")
        .distinct()
    )

    for change in changes:
        tab = _resolve_record_tab(change.record, user)
        if change.created_at > seen_dt[tab]:
            changed_ids_by_tab[tab].add(change.record_id)

    # 只有显式点击某个tab时，才清零该tab的“未读变化”；默认首次打开不清零
    if clear_seen and active_tab in tabs:
        seen_raw[active_tab] = datetime.now().isoformat()
        request.session[session_key] = seen_raw
        request.session.modified = True

    return changed_ids_by_tab


def _build_pending_action_ids(participation_activity_list, received_activity_list):
    pending_ids_by_tab = {
        "participation": set(),
        "received": set(),
        "finished": set(),
    }

    for activity in participation_activity_list:
        # 仍需要当前用户执行“确认/拒绝”动作
        if (
            not activity.get("terminated")
            and not activity.get("terminated_by_admin")
            and activity.get("record_status") != BirthboardRecord.Status.CANCELED
            and (not activity.get("has_confirmed"))
            and (not activity.get("has_paid"))
        ):
            pending_ids_by_tab["participation"].add(activity["id"])

    for activity in received_activity_list:
        # 仍需要寿星执行“确认/拒绝”动作
        if activity.get("receiver_status") == BirthboardParticipant.Status.WAIT:
            pending_ids_by_tab["received"].add(activity["id"])

    return pending_ids_by_tab


def _get_confirm_tab_total_count(request, user) -> int:
    tabs = ("participation", "received", "finished")
    session_key = f"birthboard_confirm_seen_{user.id}"
    seen_raw = request.session.get(session_key, {})
    seen_dt = {tab: _parse_seen_time(seen_raw.get(tab)) for tab in tabs}

    participation_activity_list = _build_participation_activity_list(user)
    received_activity_list = _build_received_activity_list(user)
    finished_activity_list = _build_finished_activity_list(user)
    visible_ids_by_tab = {
        "participation": {activity["id"] for activity in participation_activity_list},
        "received": {activity["id"] for activity in received_activity_list},
        "finished": {activity["id"] for activity in finished_activity_list},
    }

    changed_ids_by_tab = {tab: set() for tab in tabs}
    changes = (
        ChangeRecord.objects
        .filter(
            Q(record__receiver_username=user.username) |
            Q(record__participants__user=user, record__participants__role=BirthboardParticipant.Role.SENDER)
        )
        .select_related("record")
        .order_by("-created_at", "-id")
        .distinct()
    )
    for change in changes:
        tab = _resolve_record_tab(change.record, user)
        if change.record_id in visible_ids_by_tab[tab] and change.created_at > seen_dt[tab]:
            changed_ids_by_tab[tab].add(change.record_id)

    pending_ids_by_tab = _build_pending_action_ids(participation_activity_list, received_activity_list)
    participation_count = len(changed_ids_by_tab["participation"] | pending_ids_by_tab["participation"])
    received_count = len(changed_ids_by_tab["received"] | pending_ids_by_tab["received"])
    finished_count = len(changed_ids_by_tab["finished"])
    return participation_count + received_count + finished_count


@login_required(redirect_field_name="origin")
def birthboard_confirm(request):
    requested_tab = request.GET.get("tab")
    active_tab = requested_tab if requested_tab in {"participation", "received", "finished"} else "participation"
    clear_once_key = f"birthboard_confirm_clear_once_{request.user.id}"
    if request.method == "GET" and request.GET.get("mark_seen") == "1" and active_tab in {"participation", "received", "finished"}:
        request.session[clear_once_key] = active_tab
        request.session.modified = True
        return redirect(f"{reverse('birthboard_confirm')}?tab={active_tab}")
    clear_seen = request.session.pop(clear_once_key, None) == active_tab

    message = None
    try:
        birthboard_update_in_progress = bool(cache.get(_BB_UPDATE_LOCK_KEY))
    except Exception:
        birthboard_update_in_progress = False
    if request.method == "POST":
        tab = request.POST.get("tab", active_tab)
        if tab == "received":
            record_id = request.POST.get("record_id")
            reject_id = request.POST.get("reject_id")
            revoke_id = request.POST.get("revoke_id")
            if record_id:
                try:
                    record = BirthboardRecord.objects.get(id=record_id, receiver_username=request.user.username)
                    receiver_part = record.participants.filter(role=BirthboardParticipant.Role.RECEIVER, user=request.user).first()
                    if receiver_part and receiver_part.status == BirthboardParticipant.Status.WAIT:
                        before_status = record.status
                        receiver_part.status = BirthboardParticipant.Status.CONFIRMED
                        receiver_part.action_time = datetime.now()
                        receiver_part.save(update_fields=["status", "action_time"])
                        all_senders_paid = all(
                            p.status == BirthboardParticipant.Status.PAID
                            for p in record.participants.filter(role=BirthboardParticipant.Role.SENDER)
                        )
                        if all_senders_paid:
                            receiver_part.status = BirthboardParticipant.Status.PAID
                            receiver_part.save(update_fields=["status"])
                            record.status = record.Status.WAITING_APPROVE
                            record.save(update_fields=["status"])
                        _log_record_change(
                            record,
                            actor=request.user,
                            action=ChangeRecord.Action.APPROVE,
                            before_status=before_status,
                            after_status=record.status,
                            detail={'stage': 'receiver_confirm'},
                        )
                except BirthboardRecord.DoesNotExist:
                    pass
            elif reject_id:
                try:
                    with transaction.atomic():
                        record = BirthboardRecord.objects.select_for_update().get(id=reject_id, receiver_username=request.user.username)
                        receiver_part = record.participants.select_for_update().filter(
                            role=BirthboardParticipant.Role.RECEIVER,
                            user=request.user,
                        ).first()
                        if receiver_part and receiver_part.status == BirthboardParticipant.Status.WAIT:
                            receiver_part.status = BirthboardParticipant.Status.REJECTED
                            receiver_part.action_time = datetime.now()
                            receiver_part.save(update_fields=["status", "action_time"])
                            _refund_paid_participants_and_terminate(record, actor=request.user, action=ChangeRecord.Action.REJECT, detail={"scope": "receiver"})
                except BirthboardRecord.DoesNotExist:
                    pass
            elif revoke_id:
                _handle_revoke(revoke_id, actor=request.user)
            return redirect(f"{reverse('birthboard_confirm')}?tab=received")

        record_id = request.POST.get("record_id")
        reject_id = request.POST.get("reject_id")
        resubmit_id = request.POST.get("resubmit_id")
        revoke_id = request.POST.get("revoke_id")
        abort_id = request.POST.get("abort_id")
        if resubmit_id:
            try:
                record = BirthboardRecord.objects.get(id=resubmit_id)
                initiator_part = record.participants.filter(role=BirthboardParticipant.Role.SENDER, is_initiator=True).first()
                if initiator_part and initiator_part.user == request.user:
                    request.session['birthboard_resubmit_initial'] = {
                        'receiver': record.receiver_username,
                        'senders': [p.user.username for p in record.participants.filter(role=BirthboardParticipant.Role.SENDER)],
                        'date': str(record.date),
                        'mode': record.mode,
                        'is_anonymous': record.is_anonymous,
                    }
            except Exception:
                pass
            return redirect('birthboard')
        if record_id:
            try:
                record = BirthboardRecord.objects.get(id=record_id)
                part = BirthboardParticipant.objects.get(record=record, user=request.user, role=BirthboardParticipant.Role.SENDER)
                paid_now = False
                if part.status != BirthboardParticipant.Status.PAID:
                    with transaction.atomic():
                        if not _deduct_and_mark_paid(request.user, part, record.per_cost):
                            messages.error(request, "您的元气值余额不足，无法完成扣款！")
                            return redirect(f"{reverse('birthboard_confirm')}?tab=participation")
                    paid_now = True
                senders_part = record.participants.filter(role=BirthboardParticipant.Role.SENDER)
                before_status = record.status
                all_paid = all(p.status == BirthboardParticipant.Status.PAID for p in senders_part)
                if all_paid and record.status == record.Status.WAITING_CONFIRM:
                    record.status = record.Status.WAITING_RECEIVER
                    record.save(update_fields=["status"])
                if paid_now:
                    _log_record_change(
                        record,
                        actor=request.user,
                        action=ChangeRecord.Action.PAY,
                        before_status=before_status,
                        after_status=record.status,
                        detail={'sender': request.user.username, 'amount': record.per_cost},
                    )
                    # try:
                    #     from extern.wechat import send_wechat
                    #     send_wechat(
                    #         [record.receiver_username],
                    #         "生日祝福待确认",
                    #         "你收到新的生日祝福，请前往页面确认后完成祝福投放。",
                    #         url="/birthboard/confirm?tab=received",
                    #         btntxt="去确认"
                    #     )
                    # except Exception:
                    #     pass
            except BirthboardRecord.DoesNotExist:
                pass
        elif reject_id:
            try:
                with transaction.atomic():
                    record = BirthboardRecord.objects.select_for_update().get(id=reject_id)
                    part = BirthboardParticipant.objects.select_for_update().get(
                        record=record,
                        user=request.user,
                        role=BirthboardParticipant.Role.SENDER,
                    )
                    part.status = BirthboardParticipant.Status.REJECTED
                    part.action_time = datetime.now()
                    part.save(update_fields=["status", "action_time"])
                    _refund_paid_participants_and_terminate(record, actor=request.user, action=ChangeRecord.Action.REJECT, detail={"scope": "sender"})
            except BirthboardRecord.DoesNotExist:
                pass
        elif revoke_id:
                    _handle_revoke(revoke_id, actor=request.user)
        elif abort_id:
            try:
                with transaction.atomic():
                    record = BirthboardRecord.objects.select_for_update().get(id=abort_id)
                    part = BirthboardParticipant.objects.select_for_update().get(
                        record=record,
                        user=request.user,
                        role=BirthboardParticipant.Role.SENDER,
                        is_initiator=True,
                    )
                    _refund_paid_participants_and_terminate(record, actor=request.user, action=ChangeRecord.Action.ABORT, detail={"scope": "initiator_abort"})
            except BirthboardRecord.DoesNotExist:
                pass
        return redirect(f"{reverse('birthboard_confirm')}?tab=participation")

    participation_activity_list = _build_participation_activity_list(request.user)
    received_activity_list = _build_received_activity_list(request.user)
    finished_activity_list = _build_finished_activity_list(request.user)
    visible_ids_by_tab = {
        "participation": {activity["id"] for activity in participation_activity_list},
        "received": {activity["id"] for activity in received_activity_list},
        "finished": {activity["id"] for activity in finished_activity_list},
    }

    changed_ids_by_tab = _build_confirm_change_state(request, request.user, active_tab, clear_seen=clear_seen)
    for tab in ("participation", "received", "finished"):
        changed_ids_by_tab[tab] &= visible_ids_by_tab[tab]

    pending_ids_by_tab = _build_pending_action_ids(participation_activity_list, received_activity_list)

    changed_ids_for_count = {
        "participation": set(changed_ids_by_tab["participation"]),
        "received": set(changed_ids_by_tab["received"]),
        "finished": set(changed_ids_by_tab["finished"]),
    }
    if clear_seen and active_tab in changed_ids_for_count:
        changed_ids_for_count[active_tab] = set()

    highlight_ids_by_tab = {
        "participation": changed_ids_by_tab["participation"] | pending_ids_by_tab["participation"],
        "received": changed_ids_by_tab["received"] | pending_ids_by_tab["received"],
        "finished": changed_ids_by_tab["finished"],
    }
    tab_change_counts = {
        "participation": len(changed_ids_for_count["participation"] | pending_ids_by_tab["participation"]),
        "received": len(changed_ids_for_count["received"] | pending_ids_by_tab["received"]),
        "finished": len(changed_ids_for_count["finished"]),
    }

    for activity in participation_activity_list:
        activity["is_changed"] = activity["id"] in highlight_ids_by_tab["participation"]
    for activity in received_activity_list:
        activity["is_changed"] = activity["id"] in highlight_ids_by_tab["received"]
    for activity in finished_activity_list:
        activity["is_changed"] = activity["id"] in highlight_ids_by_tab["finished"]

    return render(request, "birthboard/birthboard_confirm.html", {
        "participation_activity_list": participation_activity_list,
        "received_activity_list": received_activity_list,
        "finished_activity_list": finished_activity_list,
        "tab_change_counts": tab_change_counts,
        "current_user": request.user,
        "active_tab": active_tab,
        "message": message,
        "birthboard_update_in_progress": birthboard_update_in_progress,
    })


@login_required(redirect_field_name="origin")
def birthboard_accept(request):
    return redirect(f"{reverse('birthboard_confirm')}?tab=received")

@login_required(redirect_field_name="origin")
@require_http_methods(["GET", "POST"])
def birthboard_approve(request):

    # 判断角色
    is_first = BirthboardApprover.objects.filter(user=request.user, is_active=True).exists()
    is_second = BirthboardSecondApprover.objects.filter(user=request.user, is_active=True).exists()
    if not (is_first or is_second):
        return redirect(reverse("birthboard"))

    message = None
    if request.method == "POST":
        action = request.POST.get("action")  # 'approve' or 'reject'
        record_id = request.POST.get("record_id")
        revoke_id = request.POST.get("revoke_id")
        if revoke_id:
            _handle_revoke(revoke_id, actor=request.user)
            return redirect(request.path)
        try:
            record = BirthboardRecord.objects.get(id=record_id, status=BirthboardRecord.Status.WAITING_APPROVE)
        except BirthboardRecord.DoesNotExist:
            message = "未找到待审核的记录或状态已变更。"
        else:
            # 并发安全：再次查询最新状态
            record.refresh_from_db()
            
            # 检查管理员是否与该投放有关
            if _is_user_related_to_record(record, request.user):
                message = "此投放活动与你有关，你不能参与审核。"
            # 一审操作
            elif is_first and not record.first_approved:
                if action == "approve":
                    if record.first_approved:
                        message = "该活动已被其他管理员初审，无需重复操作。"
                    else:
                        before_status = record.status
                        record.first_approved = True
                        record.first_approver = request.user
                        record.first_approved_at = datetime.now()
                        record.save(update_fields=["first_approved", "first_approver", "first_approved_at"])
                        _log_record_change(
                            record,
                            actor=request.user,
                            action=ChangeRecord.Action.APPROVE,
                            before_status=before_status,
                            after_status=record.status,
                            detail={'stage': 'first'},
                        )
                        message = f"活动 {record.receiver_name}({record.receiver_username}) 已通过初审，等待终审。"
                elif action == "reject":
                    if record.first_approved:
                        message = "该活动已被其他管理员初审，无需操作。"
                    else:
                        reasons = request.POST.getlist("reasons")
                        detail = request.POST.get("detail", "")
                        _reject_record_by_admin(record, reasons, detail, actor=request.user)
                        message = f"活动 {record.receiver_name}({record.receiver_username}) 已被驳回。"
            # 二审操作
            elif is_second and record.first_approved:
                if action == "approve":
                    if record.status != BirthboardRecord.Status.WAITING_APPROVE or record.second_approver:
                        message = "该活动已被其他管理员终审，无需重复操作。"
                    else:
                        before_status = record.status
                        record.status = BirthboardRecord.Status.READY
                        record.second_approver = request.user
                        record.second_approved_at = datetime.now()
                        record.save(update_fields=["status", "second_approver", "second_approved_at"])
                        _log_record_change(
                            record,
                            actor=request.user,
                            action=ChangeRecord.Action.APPROVE,
                            before_status=before_status,
                            after_status=record.status,
                            detail={'stage': 'second'},
                        )
                        message = f"活动 {record.receiver_name}({record.receiver_username}) 已通过终审。"
                elif action == "reject":
                    if record.status != BirthboardRecord.Status.WAITING_APPROVE or record.second_approver:
                        message = "该活动已被其他管理员终审，无需操作。"
                    else:
                        reasons = request.POST.getlist("reasons")
                        detail = request.POST.get("detail", "")
                        _reject_record_by_admin(record, reasons, detail, actor=request.user)
                        message = f"活动 {record.receiver_name}({record.receiver_username}) 已被驳回。"
        # 防止重复提交，POST-Redirect-GET
        return redirect(request.path)

    # 展示所有需要管理员关注的活动
    visible_statuses = [
        'waiting_approve',
        'terminated_by_admin',
        'canceled',
        'ready',
        'ongoing',
        'finished',
    ]
    records = BirthboardRecord.objects.filter(status__in=visible_statuses)
    if is_second and not is_first:
        records = records.filter(first_approved=True)
    records = records.order_by("-created_at", "-id")
    
    # 为每个 record 添加 "与管理员有关" 的标记
    activity_list = []
    for record in records:
        is_related = _is_user_related_to_record(record, request.user)

        activity_list.append({
            'record': record,
            'is_related': is_related,
        })
    try:
        birthboard_update_in_progress = bool(cache.get(_BB_UPDATE_LOCK_KEY))
    except Exception:
        birthboard_update_in_progress = False

    return render(request, "birthboard/birthboard_approve.html", {
        "activity_list": activity_list,
        "message": message,
        "is_first": is_first,
        "is_second": is_second,
        "birthboard_update_in_progress": birthboard_update_in_progress,
    })