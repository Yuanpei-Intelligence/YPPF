import json
import mimetypes
import os
import secrets
from datetime import datetime, timedelta
import logging

from django.db import transaction
from django.db.models import (
    Q,
    F,
    OuterRef,
    Subquery,
    DateTimeField,
    Prefetch,
)
from django.db.models.functions import Coalesce
from django.core.files.images import get_image_dimensions
from django.contrib import messages

from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.decorators import login_required

from app.utils import check_user_access

from birthboard.models import (
    BirthboardRecord,
    ChangeRecord,
    BirthboardApprover,
    BirthboardParticipant,
    BirthboardRejectedIssue,
    BirthboardSecondApprover,
    BirthboardContract,
    BirthboardConfirmSeen,
    BirthboardLike,
    BirthboardReminderSeen,
)
from django.views.decorators.http import require_http_methods
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse

from birthboard.forms import BirthboardForm, BirthboardRejectForm
from birthboard.utils import calculate_per_cost, generate_thumbnail

User = get_user_model()

# 审核员ID白名单

from django.shortcuts import redirect, render
from django.urls import reverse
from functools import wraps

from django.core.cache import cache

from birthboard.jobs import attempt_pending_takedown
from birthboard.notify import (
    notify_revoke,
    notify_refund,
    notify_invite_sender,
    notify_receiver_confirmed,
    notify_payment_success,
)
from birthboard.reminder import (
    cancel_approval_reminders,
    schedule_first_approval_reminders,
    schedule_second_approval_reminders,
)
from birthboard.config import CONFIG

_BB_UPDATE_LOCK_KEY = "birthboard:update_in_progress"
logger = logging.getLogger(__name__)

__all__ = [
    'require_contract',
    'birthboard',
    'birthboard_contract',
    'birthboard_sign_contract',
    'birthboard_like_count',
    'birthboard_like_add',
    'birthboard_reminder_seen',
    'birthboard_image',
    'time_now',
    'confirm_tab_count_api',
    'birthboard_confirm',
    'birthboard_accept',
    'birthboard_approve_denied',
    'birthboard_approve',
]


def _display_update_is_locked() -> bool:
    """Fail closed when the external-display coordination lock is unknown."""
    try:
        return bool(cache.get(_BB_UPDATE_LOCK_KEY))
    except Exception:
        logger.exception('cannot verify birthboard display update lock')
        return True


def require_contract(view_func):
    """装饰器：要求用户已签署协议才能访问。"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("birthboard_contract")
        if not request.user.is_person() or not request.user.active:
            return HttpResponseForbidden('仅限状态正常的个人账号使用生日板。')
        contract = BirthboardContract.objects.filter(user=request.user).first()
        if contract is None or not contract.signed:
            return redirect("birthboard_contract")
        return view_func(request, *args, **kwargs)
    return wrapper


def _handle_revoke(revoke_id: str, actor=None) -> str:
    """处理撤销请求：改状态为CANCELED但不退款。

    Returns:
        - 'ok': 撤销请求已处理（含记录不存在）
        - 'locked': 因夜间同步窗口（23:45-24:00）被拒绝，调用方可据此提示刷新页面
        - 'forbidden': 调用者不是该投放的发起人或寿星，无权撤销
        - 'conflict': 记录已不处于可撤销的 READY/ONGOING 状态
    """
    # 如果正在执行批量更新（夜间任务），拒绝冲突操作
    if _display_update_is_locked():
        logger.info("_handle_revoke: update in progress, reject revoke %s", revoke_id)
        return 'locked'
    try:
        with transaction.atomic():
            record = BirthboardRecord.objects.select_for_update().get(id=revoke_id)
            # The nightly job can acquire the cache lock after the early
            # check but before this row lock. Recheck after serialization so
            # it cannot upload a record that this request is cancelling.
            if _display_update_is_locked():
                return 'locked'
            # 权限校验：仅发起人或寿星可撤销，避免他人按可猜测的记录 ID 取消
            # 别人的投放（含投放中，会触发从外部屏幕移除）。必须在行锁内校验。
            is_initiator = record.participants.filter(
                user=actor,
                role=BirthboardParticipant.Role.SENDER,
                is_initiator=True,
            ).exists()
            is_receiver = record.participants.filter(
                user=actor,
                role=BirthboardParticipant.Role.RECEIVER,
            ).exists()
            if actor is None or not (
                is_initiator or is_receiver
            ):
                logger.warning(
                    "[birthboard.views] _handle_revoke: forbidden revoke_id=%s actor=%s",
                    revoke_id,
                    actor.username if actor else None,
                )
                return "forbidden"
            if record.status not in {
                BirthboardRecord.Status.READY,
                BirthboardRecord.Status.ONGOING,
            }:
                return 'conflict'
            before_status = record.status
            record.status = record.Status.CANCELED
            update_fields = ['status']
            if before_status == BirthboardRecord.Status.ONGOING:
                record.display_takedown_pending = True
                update_fields.append('display_takedown_pending')
            record.save(update_fields=update_fields)
            _log_record_change(record, actor=actor, action=ChangeRecord.Action.REVOKE, before_status=before_status, after_status=record.status, detail={"revoke_id": revoke_id})
            transaction.on_commit(
                lambda record=record: cancel_approval_reminders(record)
            )
            transaction.on_commit(lambda record=record: notify_revoke(record))
            if record.display_takedown_pending:
                transaction.on_commit(
                    lambda record_id=record.id: attempt_pending_takedown(
                        record_id
                    )
                )
        return "ok"
    except (BirthboardRecord.DoesNotExist, TypeError, ValueError):
        return "ok"


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


STATUS_DISPLAY = {
    'waiting_confirm': '等待确认',
    'waiting_receiver': '等待接收',
    'waiting_approve': '等待初审',
    'ready': '待投放',
    'ongoing': '进行中',
    'finished': '已完成',
    'terminated': '中止',
    'terminated_by_admin': '需要修改',
    'canceled': '撤销',
}

STATUS_CLASS = {
    'terminated_by_admin': 'status-red',
    'terminated': 'status-red',
    'canceled': 'status-red',
    'finished': 'status-green',
    'ready': 'status-green',
    'ongoing': 'status-green',
    'waiting_confirm': 'status-yellow',
    'waiting_receiver': 'status-yellow',
    'waiting_approve': 'status-yellow',
}


def _with_activity_relations(records):
    """Prefetch the bounded relations rendered for each activity card."""
    return records.prefetch_related(
        Prefetch(
            'participants',
            queryset=BirthboardParticipant.objects.select_related('user'),
            to_attr='birthboard_participant_rows',
        ),
        Prefetch(
            'change_records',
            queryset=ChangeRecord.objects.order_by('-created_at', '-id'),
            to_attr='birthboard_change_rows',
        ),
    )


def _build_activity_base(record: BirthboardRecord):
    rejected_reasons, rejected_detail = _get_rejected_info(record)
    if record.mode == 1:
        end_date = record.date + timedelta(days=2)
    elif record.mode == 2:
        end_date = record.date + timedelta(days=364)
    else:
        end_date = None
    status_key = str(record.status)
    # 取最新一条变更记录，构建状态过渡显示
    prefetched_changes = getattr(record, 'birthboard_change_rows', None)
    if prefetched_changes is not None:
        latest_change = prefetched_changes[0] if prefetched_changes else None
    else:
        latest_change = record.change_records.order_by(
            '-created_at',
            '-id',
        ).first()
    if latest_change and latest_change.before_status:
        before_display = STATUS_DISPLAY.get(latest_change.before_status, latest_change.before_status)
        after_display = STATUS_DISPLAY.get(latest_change.after_status, latest_change.after_status)
        after_status_class = STATUS_CLASS.get(latest_change.after_status, '')
        before_status_class = STATUS_CLASS.get(latest_change.before_status, '')
        # 一审通过后 after_status 仍是 waiting_approve，但应显示"等待终审"
        if latest_change.detail and latest_change.detail.get('stage') == 'first':
            after_display = '等待终审'
        # 二审通过前 before_status 仍是 waiting_approve，应显示"等待终审"
        if latest_change.detail and latest_change.detail.get('stage') == 'second':
            before_display = '等待终审'
    elif latest_change:
        after_display = STATUS_DISPLAY.get(latest_change.after_status, latest_change.after_status)
        after_status_class = STATUS_CLASS.get(latest_change.after_status, '')
        before_display = ''
        before_status_class = ''
    else:
        after_display = ''
        after_status_class = ''
        before_display = ''
        before_status_class = ''
    return {
        'id': record.id,
        'date': record.date,
        'end_date': end_date,
        'image': (
            reverse('birthboard_image', args=[record.id, 'image'])
            if record.image else ''
        ),
        'thumbnail_url': (
            reverse(
                'birthboard_image',
                args=[
                    record.id,
                    'thumbnail' if record.thumbnail else 'image',
                ],
            )
            if record.image else ''
        ),
        'receiver_name': record.receiver_name,
        'receiver_username': record.receiver_username,
        'per_cost': record.per_cost,
        'is_anonymous': record.is_anonymous,
        'mode': record.mode,
        'record_status': status_key,
        'after_status': after_display,
        'before_status': before_display,
        'after_status_class': after_status_class,
        'before_status_class': before_status_class,
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
    prefetched_participants = getattr(
        record,
        'birthboard_participant_rows',
        None,
    )
    if prefetched_participants is not None:
        return any(
            participant.user_id == user.id
            for participant in prefetched_participants
        )
    return BirthboardParticipant.objects.filter(
        record=record,
        user=user,
    ).exists()


def _restrict_initiator_after_display_violation(
    record: BirthboardRecord,
) -> None:
    """Apply the contract's one-month restriction to the initiator."""
    initiator = (
        record.participants.filter(
            role=BirthboardParticipant.Role.SENDER,
            is_initiator=True,
        )
        .select_related('user')
        .first()
    )
    if initiator is None:
        logger.error(
            'birthboard display violation has no initiator record_id=%s',
            record.id,
        )
        return
    contract, _ = BirthboardContract.objects.select_for_update().get_or_create(
        user=initiator.user,
    )
    restricted_until = datetime.now() + timedelta(days=30)
    if (
        contract.restricted_until is None
        or contract.restricted_until < restricted_until
    ):
        contract.restricted_until = restricted_until
        contract.save(update_fields=['restricted_until'])


@transaction.atomic
def _reject_record_by_admin(record: BirthboardRecord, reasons, detail: str, actor=None, restrict=False) -> None:
    """Reject a record and enforce refund/takedown/restriction policy."""
    record = BirthboardRecord.objects.select_for_update().get(pk=record.pk)
    if record.status not in {
        BirthboardRecord.Status.WAITING_APPROVE,
        BirthboardRecord.Status.READY,
        BirthboardRecord.Status.ONGOING,
        BirthboardRecord.Status.FINISHED,
    }:
        raise ValueError('record is not in a reviewable state')
    before_status = record.status
    paid_users = {}
    if before_status == BirthboardRecord.Status.WAITING_APPROVE:
        paid_users, _ = _refund_paid_participants(record)
    BirthboardRejectedIssue.objects.update_or_create(
        record=record,
        defaults={
            "reasons": ','.join(reasons),
            "detail": detail,
        },
    )
    record.status = BirthboardRecord.Status.TERMINATED_BY_ADMIN
    update_fields = ['status']
    if before_status == BirthboardRecord.Status.ONGOING:
        record.display_takedown_pending = True
        update_fields.append('display_takedown_pending')
    record.save(update_fields=update_fields)
    if restrict:
        _restrict_initiator_after_display_violation(record)
    _log_record_change(
        record,
        actor=actor,
        action=ChangeRecord.Action.REJECT,
        before_status=before_status,
        after_status=record.status,
        detail={"reasons": reasons, "detail": detail, "scope": "admin"},
    )
    if paid_users:
        transaction.on_commit(
            lambda record=record, paid_users=paid_users: notify_refund(
                record,
                paid_users,
            )
        )
    if record.display_takedown_pending:
        transaction.on_commit(
            lambda record_id=record.id: attempt_pending_takedown(record_id)
        )


def _refund_paid_participants(record: BirthboardRecord):
    """Refund locked paid sender rows without changing the record status."""
    from generic.models import YQPointRecord

    paid_parts = list(
        BirthboardParticipant.objects.select_for_update().filter(
            record=record,
            status=BirthboardParticipant.Status.PAID,
            role=BirthboardParticipant.Role.SENDER,
        )
    )
    paid_user_ids = [participant.user_id for participant in paid_parts]
    paid_users = {
        user.id: user
        for user in User.objects.select_for_update().filter(
            id__in=paid_user_ids
        )
    }
    now = datetime.now()
    for paid_part in paid_parts:
        paid_user = paid_users.get(paid_part.user_id)
        if paid_user is None:
            continue
        refund_amount = paid_part.cost
        paid_user.YQpoint += refund_amount
        paid_user.save(update_fields=['YQpoint'])
        YQPointRecord.objects.create(
            user=paid_user,
            delta=refund_amount,
            source='birthboard_refund',
            source_type=getattr(
                YQPointRecord.SourceType,
                'BIRTHBOARD',
                0,
            ),
        )
        paid_part.status = BirthboardParticipant.Status.REFUNDED
        paid_part.action_time = now
        paid_part.save(update_fields=['status', 'action_time'])
    return paid_users, paid_parts


@transaction.atomic
def _refund_paid_participants_and_terminate(
    record: BirthboardRecord,
    actor=None,
    action: str = ChangeRecord.Action.REFUND,
    detail=None,
) -> None:
    """退还活动中所有已扣款参与者，并将活动置为中止。"""
    record = BirthboardRecord.objects.select_for_update().get(pk=record.pk)
    if record.status not in {
        BirthboardRecord.Status.WAITING_CONFIRM,
        BirthboardRecord.Status.WAITING_RECEIVER,
        BirthboardRecord.Status.WAITING_APPROVE,
    }:
        raise ValueError('record is not in a refundable waiting state')
    before_status = record.status
    paid_users, paid_parts = _refund_paid_participants(record)

    record.status = record.Status.TERMINATED
    record.save(update_fields=["status"])
    _log_record_change(record, actor=actor, action=action, before_status=before_status, after_status=record.status, detail=detail or {"refunded_participants": [p.user_id for p in paid_parts]})
    transaction.on_commit(lambda: notify_refund(record, paid_users))


def _get_today_entry_reminders(user):
    now = datetime.now()
    today = timezone.localtime(now).date() if timezone.is_aware(now) else now.date()
    # Only consider records that are actively ongoing
    ongoing_status = BirthboardRecord.Status.ONGOING
    has_receiver_today = BirthboardRecord.objects.filter(
        receiver_username=user.username,
        date=today,
        status=ongoing_status,
    ).exists()
    has_sender_today = BirthboardParticipant.objects.filter(
        user=user,
        role=BirthboardParticipant.Role.SENDER,
        record__date=today,
        record__status=ongoing_status,
    ).exists()

    receiver_names = list(
        BirthboardRecord.objects.filter(
            receiver_username=user.username,
            date=today,
            status=ongoing_status,
        ).values_list("receiver_name", flat=True).distinct()
    )
    sender_names = list(
        BirthboardParticipant.objects.filter(
            user=user,
            role=BirthboardParticipant.Role.SENDER,
            record__date=today,
            record__status=ongoing_status,
        ).values_list("record__receiver_name", flat=True).distinct()
    )
    seen_types = set(
        BirthboardReminderSeen.objects.filter(user=user, date=today)
        .values_list("reminder_type", flat=True)
    )
    return {
        "today": today.isoformat(),
        "has_receiver_today": has_receiver_today,
        "has_sender_today": has_sender_today,
        "receiver_names": receiver_names,
        "sender_names": sender_names,
        "seen": {
            "happy": "happy" in seen_types,
            "bless": "bless" in seen_types,
        },
    }


def _get_birthboard_date_rule(now_dt=None):
    if now_dt is None:
        now_dt = datetime.now()
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


@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
@require_http_methods(["GET"])
def birthboard_contract(request):
    """协议签署页面（已签署时按钮显示“回到灯牌”）"""
    if not request.user.is_person() or not request.user.active:
        return HttpResponseForbidden('仅限状态正常的个人账号签署生日板协议。')
    contract = BirthboardContract.objects.filter(user=request.user).first()
    return render(
        request,
        "birthboard/contract.html",
        {"contract_signed": bool(contract and contract.signed)},
    )


@csrf_protect
@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
@require_http_methods(["POST"])
def birthboard_sign_contract(request):
    """签署协议 API：将当前用户 contract 设为 True"""
    if not request.user.is_person() or not request.user.active:
        return JsonResponse({'ok': False}, status=403)
    contract, _ = BirthboardContract.objects.get_or_create(user=request.user)
    contract.signed = True
    contract.signed_at = datetime.now()
    contract.save(update_fields=["signed", "signed_at"])
    return JsonResponse({"ok": True})


@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
@require_http_methods(["GET"])
def birthboard_like_count(request):
    """制作名单累计点赞量查询接口：返回当前累计值。"""
    count = (
        BirthboardLike.objects.filter(pk=1)
        .values_list('count', flat=True)
        .first()
    )
    return JsonResponse({'count': count or 0})


@csrf_protect
@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
@require_http_methods(["POST"])
def birthboard_like_add(request):
    """制作名单点赞接口：累计点赞量 +1，返回新值。"""
    like, _ = BirthboardLike.objects.get_or_create(pk=1)
    BirthboardLike.objects.filter(pk=like.pk).update(count=F("count") + 1)
    like.refresh_from_db()
    return JsonResponse({"count": like.count})


@csrf_protect
@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
@require_http_methods(["POST"])
def birthboard_reminder_seen(request):
    """记录今日提醒（happy/bless）已展示：服务端去重，跨设备有效。"""
    reminder_type = request.POST.get("type")
    if reminder_type not in ("happy", "bless"):
        return JsonResponse({"ok": False, "error": "invalid type"}, status=400)
    now = datetime.now()
    today = timezone.localtime(now).date() if timezone.is_aware(now) else now.date()
    BirthboardReminderSeen.objects.get_or_create(
        user=request.user,
        date=today,
        reminder_type=reminder_type,
    )
    return JsonResponse({"ok": True})


@require_http_methods(["GET"])
def time_now(request):
    """Return current server time."""
    now = datetime.now()
    try:
        iso = now.isoformat()
    except Exception:
        iso = str(now)
    return JsonResponse({"now": iso})


@login_required(redirect_field_name='origin')
@check_user_access(redirect_url='/logout/')
@require_contract
@require_http_methods(['GET'])
def birthboard_image(request, record_id: int, kind: str):
    """Serve a poster only to its participants or active reviewers."""
    record = BirthboardRecord.objects.filter(pk=record_id).first()
    if record is None or kind not in {'image', 'thumbnail'}:
        raise Http404
    is_reviewer = (
        BirthboardApprover.objects.filter(
            user=request.user,
            is_active=True,
        ).exists()
        or BirthboardSecondApprover.objects.filter(
            user=request.user,
            is_active=True,
        ).exists()
    )
    if not is_reviewer and not _is_user_related_to_record(
        record,
        request.user,
    ):
        # Do not reveal whether a caller-supplied record ID exists.
        raise Http404
    image_field = record.thumbnail if kind == 'thumbnail' else record.image
    if not image_field:
        raise Http404
    content_type = mimetypes.guess_type(image_field.name)[0] or 'image/jpeg'
    image_field.open('rb')
    response = FileResponse(
        image_field,
        content_type=content_type,
        filename=os.path.basename(image_field.name),
    )
    response['Cache-Control'] = 'private, no-store'
    return response


def _generate_birthboard_image_filename(image, date, submit_time=None) -> str:
    """Generate an unpredictable storage name without exposing the original."""
    file_ext = os.path.splitext(image.name)[1].lower()
    date_str = date.strftime('%Y%m%d')
    return f'{date_str}_{secrets.token_hex(16)}{file_ext}'


@csrf_protect
@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
@require_contract
@require_http_methods(["GET", "POST"])
def birthboard(request):
    contract = BirthboardContract.objects.get(user=request.user)
    if (
        contract.restricted_until is not None
        and contract.restricted_until > datetime.now()
    ):
        return HttpResponseForbidden(
            f'因投放后违规，生日板发起权限限制至 '
            f'{contract.restricted_until:%Y-%m-%d %H:%M}。'
        )
    users = User.objects.filter(
        utype__in=User.Type.Persons(),
        active=True,
    )
    from generic.utils import to_search_indices
    user_infos = to_search_indices(users, active=True)
    json_context = {'user_infos': user_infos, 'max_senders': CONFIG.max_senders}
    today_entry_reminders = _get_today_entry_reminders(request.user)
    birthboard_date_rule = _get_birthboard_date_rule()
    birthboard_date_rule_json = _serialize_birthboard_date_rule(birthboard_date_rule)

    # 页脚"联系我们"邮箱（配置 birthboard.contact_email）
    contact_email = CONFIG.contact_email
    # 制作名单：组织与姓名（配置 birthboard.contributor_orgs）
    contributor_orgs = CONFIG.contributor_orgs
    # 海报"模版下载"链接（配置 birthboard.template_download_url）
    template_download_url = CONFIG.template_download_url

    if request.method == 'POST':
        initial = request.session.pop('birthboard_resubmit_initial', None)
    else:
        initial = request.session.get('birthboard_resubmit_initial')

    if request.method == "POST":
        # If client provided receiver_pk (hidden field), map it to 'receiver' before form binding.
        post_data = request.POST
        if 'receiver_pk' in request.POST:
            post_data = request.POST.copy()
            # set 'receiver' to the pk so BirthboardForm.ModelChoiceField can resolve it
            post_data['receiver'] = post_data.get('receiver_pk')
        form = BirthboardForm(post_data, request.FILES, user=request.user)
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
                    "contact_email": contact_email,
                    "contributor_orgs": contributor_orgs,
                    "template_download_url": template_download_url,
                    "confirm_tab_total_count": _get_confirm_tab_total_count(request, request.user),
                    "today_entry_reminders": today_entry_reminders,
                    "birthboard_date_rule": birthboard_date_rule_json,
                })
            # 校验图片尺寸
            width, height = get_image_dimensions(image)
            if width != 1920 or height != 1080:
                messages.error(request, "图片不符合要求，需1920x1080")
                current_user_id = str(request.user.username)
                return render(request, "birthboard/birthboard.html", {"form": form, "users": users, "json_context": json_context, "contact_email": contact_email, "contributor_orgs": contributor_orgs, "template_download_url": template_download_url, "current_user_id": current_user_id, "confirm_tab_total_count": _get_confirm_tab_total_count(request, request.user), "today_entry_reminders": today_entry_reminders, "birthboard_date_rule": birthboard_date_rule_json})
            # 校验送出者元气值：按提交人数计算人均价，避免误按总价校验
            sender_count = max(senders.count(), 1)
            per = calculate_per_cost(mode, sender_count)
            # 实时查询数据库余额：仅校验当前登录用户本人
            current_user = request.user
            current_balance = getattr(current_user, 'YQpoint', 0)
            if current_balance < per:
                return render(request, "birthboard/birthboard.html", {
                    "form": form,
                    "users": users,
                    "json_context": json_context,
                    "contact_email": contact_email,
                    "contributor_orgs": contributor_orgs,
                    "template_download_url": template_download_url,
                    "insufficient_balance": current_balance,
                    "confirm_tab_total_count": _get_confirm_tab_total_count(request, request.user),
                    "today_entry_reminders": today_entry_reminders,
                    "birthboard_date_rule": birthboard_date_rule_json,
                })
            # 创建 BirthboardRecord
            try:
                from generic.models import YQPointRecord
                with transaction.atomic():
                    # 重命名图片文件：投放日期 + 提交时间 + 计数器 + 原文件名
                    image.name = _generate_birthboard_image_filename(image, date)
                    
                    # 如果只有发起人自己，直接进入WAITING_RECEIVER
                    status = BirthboardRecord.Status.WAITING_RECEIVER if len(senders) == 1 and senders[0] == request.user else BirthboardRecord.Status.WAITING_CONFIRM
                    record = BirthboardRecord.objects.create(
                        receiver_username=receiver.username,
                        receiver_name=receiver.name or receiver.username,
                        date=date,
                        mode=mode,
                        per_cost=per,
                        image=image,
                        is_anonymous=is_anonymous,
                        status=status,
                    )
                    # 生成缩略图
                    try:
                        thumb_content = generate_thumbnail(image)
                        if thumb_content:
                            record.thumbnail.save(thumb_content.name, thumb_content, save=False)
                            record.save(update_fields=['thumbnail'])
                    except Exception:
                        pass  # 缩略图生成失败不影响主流程
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
                    initiator_name = request.user.get_full_name() or request.user.username
                    invited_senders = [
                        sender for sender in senders
                        if sender != request.user
                    ]
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
                for sender in invited_senders:
                    notify_invite_sender(record, sender, initiator_name, per)
            except Exception:
                logger.exception(
                    'birthboard record creation failed actor_id=%s',
                    request.user.pk,
                )
                messages.error(request, '记录创建失败，请稍后重试。')
                return render(request, "birthboard/birthboard.html", {"form": form, "users": users, "json_context": json_context, "contact_email": contact_email, "contributor_orgs": contributor_orgs, "template_download_url": template_download_url, "confirm_tab_total_count": _get_confirm_tab_total_count(request, request.user), "today_entry_reminders": today_entry_reminders, "birthboard_date_rule": birthboard_date_rule_json})
            return redirect("birthboard_confirm")
        else:
            return render(request, "birthboard/birthboard.html", {"form": form, "users": users, "json_context": json_context, "contact_email": contact_email, "contributor_orgs": contributor_orgs, "template_download_url": template_download_url, "confirm_tab_total_count": _get_confirm_tab_total_count(request, request.user), "today_entry_reminders": today_entry_reminders, "birthboard_date_rule": birthboard_date_rule_json})
    else:
        if initial:
            form = BirthboardForm(initial=initial, user=request.user)
        else:
            form = BirthboardForm(user=request.user)
        return render(request, "birthboard/birthboard.html", {
            "form": form,
            "users": users,
            "json_context": json_context,
            "contact_email": contact_email,
            "contributor_orgs": contributor_orgs,
            "template_download_url": template_download_url,
            "birthboard_initial": json.dumps(initial) if initial else None,
            "confirm_tab_total_count": _get_confirm_tab_total_count(request, request.user),
            "today_entry_reminders": today_entry_reminders,
            "birthboard_date_rule": birthboard_date_rule_json,
        })

def _build_activity_list(records, current_user, view_type: str):
    activity_list = []
    for record in records:
        participants = getattr(record, 'birthboard_participant_rows', None)
        if participants is None:
            participants = list(
                record.participants.select_related('user').all()
            )
        senders_part = [
            participant
            for participant in participants
            if participant.role == BirthboardParticipant.Role.SENDER
        ]
        base = _build_activity_base(record)

        if view_type == "received":
            receiver_part = next(
                (
                    participant
                    for participant in participants
                    if participant.role
                    == BirthboardParticipant.Role.RECEIVER
                    and participant.user_id == current_user.id
                ),
                None,
            )
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
            paid_ids = [p.user.id for p in senders_part if p.status == BirthboardParticipant.Status.PAID]
            has_paid = any(p.user_id == current_user.id and p.status == BirthboardParticipant.Status.PAID for p in senders_part)
            is_initiator = any(p.user_id == current_user.id and p.is_initiator for p in senders_part)
            activity_list.append({
                **base,
                'senders': senders,
                'paid_ids': paid_ids,
                'has_paid': has_paid,
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
    records = _with_activity_relations(
        _order_records_by_last_change(records)[:100]
    )
    return _build_activity_list(records, current_user, "participation")


def _build_received_activity_list(current_user):
    valid_status = [
        BirthboardRecord.Status.WAITING_RECEIVER,
        BirthboardRecord.Status.WAITING_APPROVE,
        BirthboardRecord.Status.READY,
        BirthboardRecord.Status.ONGOING,
    ]
    records = BirthboardRecord.objects.filter(
        participants__user=current_user,
        participants__role=BirthboardParticipant.Role.RECEIVER,
        status__in=valid_status,
    )
    records = _with_activity_relations(
        _order_records_by_last_change(records)[:100]
    )
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
        participants__user=current_user,
        participants__role=BirthboardParticipant.Role.RECEIVER,
        status__in=finished_statuses
    )
    
    # 合并两个querysets
    all_records = sender_records | receiver_records
    all_records = all_records.distinct()
    all_records = _with_activity_relations(
        _order_records_by_last_change(all_records)[:200]
    )
    
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
    seen_dt = {tab: BirthboardConfirmSeen.get_seen_dt(user, tab) for tab in tabs}

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
        BirthboardConfirmSeen.mark_seen(user, active_tab)

    return changed_ids_by_tab


def _build_pending_action_ids(participation_activity_list, received_activity_list):
    pending_ids_by_tab = {
        "participation": set(),
        "received": set(),
        "finished": set(),
    }

    for activity in participation_activity_list:
        # 仍需要当前用户执行“确认/拒绝”动作
        if not activity.get("has_paid"):
            pending_ids_by_tab["participation"].add(activity["id"])

    for activity in received_activity_list:
        # 仍需要寿星执行“确认/拒绝”动作
        if activity.get("receiver_status") == BirthboardParticipant.Status.WAIT:
            pending_ids_by_tab["received"].add(activity["id"])

    return pending_ids_by_tab


def _get_confirm_tab_total_count(request, user) -> int:
    tabs = ("participation", "received", "finished")
    seen_dt = {tab: BirthboardConfirmSeen.get_seen_dt(user, tab) for tab in tabs}

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
@check_user_access(redirect_url="/logout/")
@require_contract
@require_http_methods(['GET'])
def confirm_tab_count_api(request):
    """返回确认页面三个tab的未读计数之和 (JSON)。"""
    count = _get_confirm_tab_total_count(request, request.user)
    return JsonResponse({"total": count})


@csrf_protect
@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
@require_contract
@xframe_options_sameorigin
@require_http_methods(['GET', 'POST'])
def birthboard_confirm(request):
    requested_tab = request.GET.get("tab")
    active_tab = requested_tab if requested_tab in {"participation", "received", "finished"} else "participation"
    clear_seen = False

    message = None
    try:
        birthboard_update_in_progress = bool(cache.get(_BB_UPDATE_LOCK_KEY))
    except Exception:
        birthboard_update_in_progress = False
    if request.method == "POST":
        tab = request.POST.get("tab", active_tab)
        if request.POST.get('mark_seen') == '1':
            if tab not in {'participation', 'received', 'finished'}:
                return JsonResponse({'error': 'invalid tab'}, status=400)
            BirthboardConfirmSeen.mark_seen(request.user, tab)
            return redirect(f"{reverse('birthboard_confirm')}?tab={tab}")
        if tab == "received":
            record_id = request.POST.get("record_id")
            reject_id = request.POST.get("reject_id")
            revoke_id = request.POST.get("revoke_id")
            if record_id:
                receiver_conflict = False
                try:
                    with transaction.atomic():
                        # 并发安全：锁定记录行，且只有"等待寿星确认"阶段允许确认，
                        # 避免与撤销/中止/驳回并发时把已终止记录改回待审批状态。
                        record = BirthboardRecord.objects.select_for_update().get(
                            id=record_id,
                            participants__user=request.user,
                            participants__role=BirthboardParticipant.Role.RECEIVER,
                        )
                        receiver_part = record.participants.select_for_update().filter(
                            role=BirthboardParticipant.Role.RECEIVER,
                            user=request.user,
                        ).first()
                        if (
                            receiver_part
                            and receiver_part.status == BirthboardParticipant.Status.WAIT
                            and record.status == record.Status.WAITING_RECEIVER
                        ):
                            before_status = record.status
                            receiver_part.status = BirthboardParticipant.Status.CONFIRMED
                            receiver_part.action_time = datetime.now()
                            receiver_part.save(update_fields=["status", "action_time"])
                            all_senders_paid = all(
                                p.status == BirthboardParticipant.Status.PAID
                                for p in record.participants.filter(role=BirthboardParticipant.Role.SENDER)
                            )
                            if all_senders_paid:
                                record.status = record.Status.WAITING_APPROVE
                                record.save(update_fields=["status"])
                                transaction.on_commit(
                                    lambda record=record:
                                    schedule_first_approval_reminders(record)
                                )
                            _log_record_change(
                                record,
                                actor=request.user,
                                action=ChangeRecord.Action.APPROVE,
                                before_status=before_status,
                                after_status=record.status,
                                detail={'stage': 'receiver_confirm'},
                            )
                            transaction.on_commit(lambda: notify_receiver_confirmed(record))
                        else:
                            # 并发/状态冲突：灯牌已不在"等待寿星确认"阶段，提示刷新。
                            receiver_conflict = True
                except BirthboardRecord.DoesNotExist:
                    pass
                if receiver_conflict:
                    return redirect(f"{reverse('birthboard_confirm')}?tab=received&error=concurrency")
            elif reject_id:
                try:
                    with transaction.atomic():
                        record = BirthboardRecord.objects.select_for_update().get(
                            id=reject_id,
                            participants__user=request.user,
                            participants__role=BirthboardParticipant.Role.RECEIVER,
                        )
                        receiver_part = record.participants.select_for_update().filter(
                            role=BirthboardParticipant.Role.RECEIVER,
                            user=request.user,
                        ).first()
                        if (
                            receiver_part
                            and receiver_part.status
                            == BirthboardParticipant.Status.WAIT
                            and record.status
                            == BirthboardRecord.Status.WAITING_RECEIVER
                        ):
                            receiver_part.status = BirthboardParticipant.Status.REJECTED
                            receiver_part.action_time = datetime.now()
                            receiver_part.save(update_fields=["status", "action_time"])
                            _refund_paid_participants_and_terminate(record, actor=request.user, action=ChangeRecord.Action.REJECT, detail={"scope": "receiver"})
                except BirthboardRecord.DoesNotExist:
                    pass
            elif revoke_id:
                revoke_result = _handle_revoke(revoke_id, actor=request.user)
                if revoke_result == "locked":
                    return redirect(f"{reverse('birthboard_confirm')}?tab=received&error=concurrency")
                if revoke_result == "forbidden":
                    return redirect(f"{reverse('birthboard_confirm')}?tab=received&error=forbidden")
                if revoke_result == 'conflict':
                    return redirect(
                        f"{reverse('birthboard_confirm')}"
                        '?tab=received&error=concurrency'
                    )
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
                        'receiver': record.participants.filter(
                            role=BirthboardParticipant.Role.RECEIVER,
                        ).values_list('user_id', flat=True).first(),
                        'senders': list(
                            record.participants.filter(
                                role=BirthboardParticipant.Role.SENDER,
                            ).values_list('user_id', flat=True)
                        ),
                        'date': str(record.date),
                        'mode': record.mode,
                        'is_anonymous': record.is_anonymous,
                    }
            except Exception:
                pass
            return redirect('birthboard')
        if record_id:
            try:
                with transaction.atomic():
                    # 并发安全：锁定记录行并校验灯牌仍处于"等待大家确认"阶段，
                    # 防止与撤销/中止/驳回并发时扣款后无法退回。
                    record = BirthboardRecord.objects.select_for_update().get(id=record_id)
                    part = BirthboardParticipant.objects.select_for_update().get(
                        record=record,
                        user=request.user,
                        role=BirthboardParticipant.Role.SENDER,
                    )
                    if record.status != record.Status.WAITING_CONFIRM:
                        return redirect(f"{reverse('birthboard_confirm')}?tab=participation&error=concurrency")
                    if part.status not in {
                        BirthboardParticipant.Status.WAIT,
                        BirthboardParticipant.Status.PAID,
                    }:
                        return redirect(
                            f"{reverse('birthboard_confirm')}"
                            '?tab=participation&error=concurrency'
                        )
                    paid_now = False
                    if part.status != BirthboardParticipant.Status.PAID:
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
                        # ========== 企业微信通知：扣款成功时发送 ==========
                        transaction.on_commit(
                            lambda: notify_payment_success(
                                record, request.user.username, all_paid
                            )
                        )
            except (
                BirthboardRecord.DoesNotExist,
                BirthboardParticipant.DoesNotExist,
            ):
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
                    if (
                        record.status
                        != BirthboardRecord.Status.WAITING_CONFIRM
                        or part.status != BirthboardParticipant.Status.WAIT
                    ):
                        return redirect(
                            f"{reverse('birthboard_confirm')}"
                            '?tab=participation&error=concurrency'
                        )
                    part.status = BirthboardParticipant.Status.REJECTED
                    part.action_time = datetime.now()
                    part.save(update_fields=["status", "action_time"])
                    _refund_paid_participants_and_terminate(record, actor=request.user, action=ChangeRecord.Action.REJECT, detail={"scope": "sender"})
            except (
                BirthboardRecord.DoesNotExist,
                BirthboardParticipant.DoesNotExist,
            ):
                pass
        elif revoke_id:
            revoke_result = _handle_revoke(revoke_id, actor=request.user)
            if revoke_result == "locked":
                return redirect(f"{reverse('birthboard_confirm')}?tab=participation&error=concurrency")
            if revoke_result == "forbidden":
                return redirect(f"{reverse('birthboard_confirm')}?tab=participation&error=forbidden")
            if revoke_result == 'conflict':
                return redirect(
                    f"{reverse('birthboard_confirm')}"
                    '?tab=participation&error=concurrency'
                )
        elif abort_id:
            # 并发安全：夜间同步窗口（23:45-24:00）内禁止中止退款，与撤销分支保持一致。
            if _display_update_is_locked():
                return redirect(
                    f"{reverse('birthboard_confirm')}"
                    '?tab=participation&error=concurrency'
                )
            is_receiver_abort = False
            try:
                with transaction.atomic():
                    record = BirthboardRecord.objects.select_for_update().get(id=abort_id)
                    if _display_update_is_locked():
                        return redirect(
                            f"{reverse('birthboard_confirm')}"
                            '?tab=participation&error=concurrency'
                        )
                    # 发起人中止 或 被祝福者在等待初审时中止
                    is_initiator_abort = BirthboardParticipant.objects.filter(
                        record=record, user=request.user,
                        role=BirthboardParticipant.Role.SENDER, is_initiator=True,
                    ).exists()
                    is_receiver_abort = (
                        record.participants.filter(
                            user=request.user,
                            role=BirthboardParticipant.Role.RECEIVER,
                        ).exists()
                        and record.status
                        == BirthboardRecord.Status.WAITING_APPROVE
                    )
                    initiator_refundable_statuses = {
                        BirthboardRecord.Status.WAITING_CONFIRM,
                        BirthboardRecord.Status.WAITING_RECEIVER,
                        BirthboardRecord.Status.WAITING_APPROVE,
                    }
                    can_initiator_abort = (
                        is_initiator_abort
                        and record.status in initiator_refundable_statuses
                    )
                    if not (can_initiator_abort or is_receiver_abort):
                        return redirect(
                            f"{reverse('birthboard_confirm')}"
                            '?tab=participation&error=concurrency'
                        )
                    if can_initiator_abort:
                        _refund_paid_participants_and_terminate(record, actor=request.user, action=ChangeRecord.Action.ABORT, detail={"scope": "initiator_abort"})
                    elif is_receiver_abort:
                        _refund_paid_participants_and_terminate(record, actor=request.user, action=ChangeRecord.Action.ABORT, detail={"scope": "receiver_abort"})
            except BirthboardRecord.DoesNotExist:
                pass
        if tab == "received" or (abort_id and is_receiver_abort):
            return redirect(f"{reverse('birthboard_confirm')}?tab=received")
        else:
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
        "is_standalone": False,
    })


@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
@require_contract
def birthboard_accept(request):
    return redirect(f"{reverse('birthboard_confirm')}?tab=received")


@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
@require_contract
def birthboard_approve_denied(request):
    return render(request, "birthboard/birthboard_approve_denied.html", {
        "user_name": request.user.get_full_name() or request.user.username,
    })


def _build_approval_activity_list(current_user, is_first: bool, is_second: bool):
    from django.db.models import Q

    manageable_statuses = [
        BirthboardRecord.Status.WAITING_APPROVE,
        BirthboardRecord.Status.READY,
        BirthboardRecord.Status.ONGOING,
        BirthboardRecord.Status.FINISHED,
        BirthboardRecord.Status.TERMINATED,
        BirthboardRecord.Status.TERMINATED_BY_ADMIN,
        BirthboardRecord.Status.CANCELED,
    ]

    # WAITING_APPROVE 按一审/二审权限过滤，其余状态全部展示
    waiting_q = Q(status=BirthboardRecord.Status.WAITING_APPROVE)
    if is_second and not is_first:
        waiting_q &= Q(first_approved=True)
    elif is_first and not is_second:
        waiting_q &= Q(first_approved=False)

    other_statuses = [s for s in manageable_statuses if s != BirthboardRecord.Status.WAITING_APPROVE]
    records = _with_activity_relations(
        BirthboardRecord.objects.filter(waiting_q | Q(status__in=other_statuses))
        .select_related("first_approver", "second_approver")
        .order_by("-created_at", "-id")
    )[:200]  # 最多展示最近 200 条，防止数据量过大

    activity_list = []
    for record in records:
        activity = _build_activity_base(record)
        activity["is_related"] = _is_user_related_to_record(record, current_user)
        activity["first_approved"] = record.first_approved
        activity['can_post_review_reject'] = not activity['is_related']
        activity['can_first_approve'] = (
            is_first
            and not record.first_approved
            and not activity['is_related']
        )
        activity['can_second_approve'] = (
            is_second
            and record.first_approved
            and record.first_approver_id != current_user.id
            and not activity['is_related']
        )
        senders = [
            participant
            for participant in record.birthboard_participant_rows
            if participant.role == BirthboardParticipant.Role.SENDER
        ]
        activity["sender_names"] = [p.user.get_full_name() or p.user.username for p in senders]
        initiator_part = next((p for p in senders if p.is_initiator), None)
        activity["initiator_name"] = initiator_part.user.get_full_name() or initiator_part.user.username if initiator_part else ""
        # 拼音缩写用于搜索
        from generic.models import to_acronym
        search_parts = []
        search_parts.append(to_acronym(activity["receiver_name"]))
        for name in activity["sender_names"]:
            search_parts.append(to_acronym(name))
        activity["search_text"] = " ".join(search_parts)
        activity_list.append(activity)
    return activity_list


def _get_next_birthboard_approval_activity(current_user, is_first: bool, is_second: bool):
    records = _with_activity_relations(
        BirthboardRecord.objects.filter(status=BirthboardRecord.Status.WAITING_APPROVE)
        .order_by("-created_at", "-id")
    )
    if is_second and not is_first:
        records = records.filter(first_approved=True)
    elif is_first and not is_second:
        records = records.filter(first_approved=False)

    for record in records:
        if _is_user_related_to_record(record, current_user):
            continue
        senders = [
            participant
            for participant in record.birthboard_participant_rows
            if participant.role == BirthboardParticipant.Role.SENDER
        ]
        sender_names = [participant.user.get_full_name() or participant.user.username for participant in senders]
        initiator_part = next((participant for participant in senders if participant.is_initiator), None)
        initiator_name = ""
        if initiator_part:
            initiator_name = initiator_part.user.get_full_name() or initiator_part.user.username
        if is_first and not record.first_approved:
            return {
                "record": record,
                "is_related": False,
                "sender_names": sender_names,
                "initiator_name": initiator_name,
            }
        if (
            is_second
            and record.first_approved
            and record.first_approver_id != current_user.id
        ):
            return {
                "record": record,
                "is_related": False,
                "sender_names": sender_names,
                "initiator_name": initiator_name,
            }
    return None


def _is_mobile_request(request):
    """根据 User-Agent 判断是否为移动端（手机/微信内置浏览器）请求。"""
    ua = (request.META.get('HTTP_USER_AGENT') or '').lower()
    mobile_keywords = (
        'android', 'iphone', 'ipad', 'ipod', 'mobile', 'micromessenger',
    )
    return any(keyword in ua for keyword in mobile_keywords)


@csrf_protect
@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
@require_contract
@require_http_methods(["GET", "POST"])
def birthboard_approve(request):

    # 判断角色
    is_first = BirthboardApprover.objects.filter(user=request.user, is_active=True).exists()
    is_second = BirthboardSecondApprover.objects.filter(user=request.user, is_active=True).exists()
    if not (is_first or is_second):
        return redirect(reverse("birthboard_approve_denied"))

    message = None
    if request.method == "POST":
        action = request.POST.get("action")  # 'approve' or 'reject'
        record_id = request.POST.get("record_id")
        revoke_id = request.POST.get("revoke_id")
        if action not in {'approve', 'reject', None}:
            return JsonResponse({'error': 'invalid action'}, status=400)
        reject_form = None
        restrict = False
        if action == 'reject':
            reject_form = BirthboardRejectForm(request.POST)
            if not reject_form.is_valid():
                return JsonResponse(
                    {'error': 'invalid rejection reason'},
                    status=400,
                )
            restrict = reject_form.cleaned_data.get('restrict', False)
            if _display_update_is_locked():
                return redirect(f"{request.path}?error=concurrency")
        # 并发冲突标志：操作被夜间同步锁拒绝或已被其他管理员处理时置位，
        # 最终带 error=concurrency 重定向，前端弹窗提示"系统错误，请刷新"。
        error_concurrency = False
        if revoke_id:
            revoke_result = _handle_revoke(revoke_id, actor=request.user)
            if revoke_result == "locked":
                return redirect(f"{request.path}?error=concurrency")
            if revoke_result == "forbidden":
                return redirect(f"{request.path}?error=forbidden")
            return redirect(request.path)
        try:
            with transaction.atomic():
                # 并发安全：在事务内锁定记录行，并在同一事务内完成全部状态检查与
                # 审核/驳回变更，避免并发一审/二审读到旧状态后互相覆盖。
                record = BirthboardRecord.objects.select_for_update().get(id=record_id)
                if action == 'reject' and _display_update_is_locked():
                    error_concurrency = True
                elif record.status == BirthboardRecord.Status.WAITING_APPROVE:
                    # 检查管理员是否与该投放有关
                    if _is_user_related_to_record(record, request.user):
                        message = "此投放活动与你有关，你不能参与审核。"
                    # 一审操作
                    elif is_first and not record.first_approved:
                        if action == "approve":
                            if record.first_approved:
                                error_concurrency = True
                            else:
                                before_status = record.status
                                record.first_approved = True
                                record.first_approver = request.user
                                record.first_approved_at = datetime.now()
                                record.save(update_fields=["first_approved", "first_approver", "first_approved_at"])
                                transaction.on_commit(
                                    lambda record=record:
                                    cancel_approval_reminders(
                                        record,
                                        stage='first',
                                    )
                                )
                                transaction.on_commit(
                                    lambda record=record:
                                    schedule_second_approval_reminders(record)
                                )
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
                                error_concurrency = True
                            else:
                                reasons = reject_form.cleaned_data['reasons']
                                detail = reject_form.cleaned_data['detail']
                                _reject_record_by_admin(record, reasons, detail, actor=request.user, restrict=restrict)
                                transaction.on_commit(
                                    lambda record=record:
                                    cancel_approval_reminders(
                                        record,
                                        stage='first',
                                    )
                                )
                                message = f"活动 {record.receiver_name}({record.receiver_username}) 已被驳回。"
                    # 二审操作
                    elif is_second and record.first_approved:
                        if record.first_approver_id == request.user.id:
                            return JsonResponse(
                                {'error': '初审人与终审人必须不同'},
                                status=403,
                            )
                        if action == "approve":
                            if record.status != BirthboardRecord.Status.WAITING_APPROVE or record.second_approver:
                                error_concurrency = True
                            else:
                                # 并发安全：夜间同步窗口（23:45-24:00）内禁止终审通过，
                                # 避免产生的新 READY 错过当夜投放；与撤销/中止的同步锁检查一致。
                                try:
                                    update_in_progress = bool(cache.get(_BB_UPDATE_LOCK_KEY))
                                except Exception:
                                    logger.exception(
                                        'cannot verify display lock before '
                                        'final approval'
                                    )
                                    update_in_progress = True
                                if update_in_progress:
                                    error_concurrency = True
                                else:
                                    before_status = record.status
                                    record.status = BirthboardRecord.Status.READY
                                    record.second_approver = request.user
                                    record.second_approved_at = datetime.now()
                                    record.save(update_fields=["status", "second_approver", "second_approved_at"])
                                    transaction.on_commit(
                                        lambda record=record:
                                        cancel_approval_reminders(
                                            record,
                                            stage='second',
                                        )
                                    )
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
                                error_concurrency = True
                            else:
                                reasons = reject_form.cleaned_data['reasons']
                                detail = reject_form.cleaned_data['detail']
                                _reject_record_by_admin(record, reasons, detail, actor=request.user, restrict=restrict)
                                transaction.on_commit(
                                    lambda record=record:
                                    cancel_approval_reminders(
                                        record,
                                        stage='second',
                                    )
                                )
                                message = f"活动 {record.receiver_name}({record.receiver_username}) 已被驳回。"
                elif action == "reject":
                    # 审核通过后仅 READY/ONGOING/FINISHED 可因违规驳回。
                    if record.status not in {
                        BirthboardRecord.Status.READY,
                        BirthboardRecord.Status.ONGOING,
                        BirthboardRecord.Status.FINISHED,
                    }:
                        error_concurrency = True
                    elif _is_user_related_to_record(record, request.user):
                        message = "此投放活动与你有关，你不能参与审核。"
                    else:
                        reasons = reject_form.cleaned_data['reasons']
                        detail = reject_form.cleaned_data['detail']
                        _reject_record_by_admin(record, reasons, detail, actor=request.user, restrict=restrict)
                        message = f"活动 {record.receiver_name}({record.receiver_username}) 已被驳回。"
        except (BirthboardRecord.DoesNotExist, TypeError, ValueError):
            message = "未找到该记录。"
        # 防止重复提交，POST-Redirect-GET；并发冲突时带 error=concurrency，前端弹窗提示刷新。
        if error_concurrency:
            return redirect(f"{request.path}?error=concurrency")
        return redirect(request.path)

    try:
        birthboard_update_in_progress = bool(cache.get(_BB_UPDATE_LOCK_KEY))
    except Exception:
        birthboard_update_in_progress = False

    current_activity = _get_next_birthboard_approval_activity(request.user, is_first, is_second)
    activity_list = _build_approval_activity_list(request.user, is_first, is_second)

    template_name = (
        "birthboard/birthboard_approve_mobile.html"
        if _is_mobile_request(request)
        else "birthboard/birthboard_approve.html"
    )
    return render(request, template_name, {
        "current_activity": current_activity,
        "activity_list": activity_list,
        "message": message,
        "is_first": is_first,
        "is_second": is_second,
        "birthboard_update_in_progress": birthboard_update_in_progress,
    })
