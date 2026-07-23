import json
import os
from datetime import datetime, timedelta
import logging

from django.db import transaction
from django.db.models import Q, OuterRef, Subquery, DateTimeField
from django.db.models.functions import Coalesce
from django.core.files.images import get_image_dimensions
from django.contrib import messages

from django.views.decorators.clickjacking import xframe_options_exempt

from app.views_dependency import *
from birthboard.models import (
    BirthboardRecord,
    ChangeRecord,
    BirthboardApprover,
    BirthboardParticipant,
    BirthboardRejectedIssue,
    BirthboardSecondApprover,
    BirthboardContract,
    BirthboardConfirmSeen,
)
from django.views.decorators.http import require_http_methods
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.http import JsonResponse

from birthboard.forms import BirthboardForm
from birthboard.utils import calculate_per_cost, generate_thumbnail

User = get_user_model()

# 审核员ID白名单

from django.shortcuts import redirect
from django.urls import reverse
from functools import wraps

from django.core.cache import cache

from birthboard.web_controller import open_and_login, _run_update_cycle
from birthboard.jobs import _get_abs_image_path
from birthboard.notify import (
    notify_revoke,
    notify_refund,
    notify_invite_sender,
    notify_receiver_confirmed,
    notify_payment_success,
)
from playwright.sync_api import sync_playwright

from boot.config import shihannet

_BB_UPDATE_LOCK_KEY = "birthboard:update_in_progress"
logger = logging.getLogger(__name__)


def require_contract(view_func):
    """装饰器：要求用户已签署协议才能访问。"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("birthboard_contract")
        contract, _ = BirthboardContract.objects.get_or_create(user=request.user)
        if not contract.signed:
            return redirect("birthboard_contract")
        return view_func(request, *args, **kwargs)
    return wrapper


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
            notify_revoke(record)
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


STATUS_DISPLAY = {
    'waiting_confirm': '等待确认',
    'waiting_receiver': '等待接收',
    'waiting_approve': '等待初审',
    'ready': '待投放',
    'ongoing': '进行中',
    'finished': '已完成',
    'terminated': '中止',
    'terminated_by_admin': '驳回',
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
    latest_change = record.change_records.order_by('-created_at').first()
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
        'image': record.image.url if record.image else '',
        'thumbnail_url': record.thumbnail.url if record.thumbnail else (record.image.url if record.image else ''),
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
    """退还活动中所有已扣款参与者，并将活动置为中止。"""
    from generic.models import YQPointRecord

    before_status = record.status
    paid_parts = list(
        BirthboardParticipant.objects.select_for_update().filter(
            record=record,
            status=BirthboardParticipant.Status.PAID,
            role=BirthboardParticipant.Role.SENDER,
        )
    )
    paid_users = {}
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
    notify_refund(record, paid_users)


def _get_today_entry_reminders(user):
    now = timezone.now()
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


@login_required(redirect_field_name="origin")
@require_http_methods(["GET"])
def birthboard_contract(request):
    """协议签署页面"""
    return render(request, "birthboard/contract.html")


@login_required(redirect_field_name="origin")
@require_http_methods(["POST"])
def birthboard_sign_contract(request):
    """签署协议 API：将当前用户 contract 设为 True"""
    contract, _ = BirthboardContract.objects.get_or_create(user=request.user)
    contract.signed = True
    contract.signed_at = timezone.now()
    contract.save(update_fields=["signed", "signed_at"])
    return JsonResponse({"ok": True})


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
@require_contract
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
                    for sender in senders:
                        if sender == request.user:
                            continue
                        notify_invite_sender(record, sender, initiator_name, per)
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
    records = _order_records_by_last_change(records)[:100]
    return _build_activity_list(records, current_user, "participation")


def _build_received_activity_list(current_user):
    valid_status = [
        BirthboardRecord.Status.WAITING_RECEIVER,
        BirthboardRecord.Status.WAITING_APPROVE,
        BirthboardRecord.Status.READY,
        BirthboardRecord.Status.ONGOING,
    ]
    records = BirthboardRecord.objects.filter(receiver_username=current_user.username, status__in=valid_status)
    records = _order_records_by_last_change(records)[:100]
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
    all_records = _order_records_by_last_change(all_records)[:200]
    
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
@require_contract
def confirm_tab_count_api(request):
    """返回确认页面三个tab的未读计数之和 (JSON)。"""
    count = _get_confirm_tab_total_count(request, request.user)
    return JsonResponse({"total": count})


@login_required(redirect_field_name="origin")
@require_contract
@xframe_options_exempt
def birthboard_confirm(request):
    # 禁止直接通过网页访问，必须从 birthboard 页面进入（含 iframe）
    if request.method == "GET":
        referer = request.META.get('HTTP_REFERER', '')
        if not referer:
            return redirect('birthboard')
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
                        notify_receiver_confirmed(record)
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
                    # ========== 企业微信通知：扣款成功时发送 ==========
                    notify_payment_success(record, request.user.username, all_paid)
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
                    # 发起人中止 或 被祝福者在等待初审时中止
                    is_initiator_abort = BirthboardParticipant.objects.filter(
                        record=record, user=request.user,
                        role=BirthboardParticipant.Role.SENDER, is_initiator=True,
                    ).exists()
                    is_receiver_abort = (record.receiver_username == request.user.username
                                         and record.status == record.Status.WAITING_APPROVE)
                    if is_initiator_abort:
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
@require_contract
def birthboard_accept(request):
    return redirect(f"{reverse('birthboard_confirm')}?tab=received")


@login_required(redirect_field_name="origin")
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
    records = (
        BirthboardRecord.objects.filter(waiting_q | Q(status__in=other_statuses))
        .select_related("first_approver", "second_approver")
        .prefetch_related("participants__user", "change_records")
        .order_by("-created_at", "-id")
    )[:200]  # 最多展示最近 200 条，防止数据量过大

    activity_list = []
    for record in records:
        activity = _build_activity_base(record)
        activity["is_related"] = _is_user_related_to_record(record, current_user)
        activity["first_approved"] = record.first_approved
        senders = list(record.participants.filter(role=BirthboardParticipant.Role.SENDER).select_related("user"))
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
    records = (
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
        senders = list(record.participants.filter(role=BirthboardParticipant.Role.SENDER).select_related("user"))
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
        if is_second and record.first_approved:
            return {
                "record": record,
                "is_related": False,
                "sender_names": sender_names,
                "initiator_name": initiator_name,
            }
    return None

@login_required(redirect_field_name="origin")
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
        if revoke_id:
            _handle_revoke(revoke_id, actor=request.user)
            return redirect(request.path)
        try:
            record = BirthboardRecord.objects.get(id=record_id)
        except BirthboardRecord.DoesNotExist:
            message = "未找到该记录。"
        else:
            if record.status == BirthboardRecord.Status.WAITING_APPROVE:
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
            elif action == "reject":
                # READY/ONGOING 等非待审核状态的驳回
                if _is_user_related_to_record(record, request.user):
                    message = "此投放活动与你有关，你不能参与审核。"
                else:
                    reasons = request.POST.getlist("reasons")
                    detail = request.POST.get("detail", "")
                    _reject_record_by_admin(record, reasons, detail, actor=request.user)
                    message = f"活动 {record.receiver_name}({record.receiver_username}) 已被驳回。"
        # 防止重复提交，POST-Redirect-GET
        return redirect(request.path)

    try:
        birthboard_update_in_progress = bool(cache.get(_BB_UPDATE_LOCK_KEY))
    except Exception:
        birthboard_update_in_progress = False

    current_activity = _get_next_birthboard_approval_activity(request.user, is_first, is_second)
    activity_list = _build_approval_activity_list(request.user, is_first, is_second)

    return render(request, "birthboard/birthboard_approve.html", {
        "current_activity": current_activity,
        "activity_list": activity_list,
        "message": message,
        "is_first": is_first,
        "is_second": is_second,
        "birthboard_update_in_progress": birthboard_update_in_progress,
    })