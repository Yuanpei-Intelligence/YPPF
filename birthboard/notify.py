"""
生日祝福投放板 - 站内信 + 企业微信通知函数

所有通知统一通过 app.notification_utils.notification_create /
bulk_notification_create 创建站内信，并设置 to_wechat 同步推送企业微信
（重要消息等级 IMPORTANT）。
每个函数内部自行处理异常，调用方无需 try/except。
发件人为 birthboard 官方组织账号（config.birthboard.sender_username），
默认 yppf_birthboard（组织名 生日灯牌），可用
`python manage.py ensure_birthboard_sender` 幂等创建；切换发件人只需改 config。
异常统一经 record.log logger 写入 log/birthboard.notify.log，避免静默失败。
"""
from generic.models import User
from app.models import Notification
from app.extern.wechat import WechatMessageLevel
from app.notification_utils import (
    bulk_notification_create,
    notification_create,
)
from record.log.utils import get_logger

from birthboard.config import CONFIG
from birthboard.models import (
    BirthboardApprover,
    BirthboardParticipant,
    BirthboardRecord,
    BirthboardSecondApprover,
)

logger = get_logger(__name__)

__all__ = [
    'notify_revoke',
    'notify_refund',
    'notify_auto_reject_refund',
    'notify_invite_sender',
    'notify_receiver_confirmed',
    'notify_payment_success',
    'notify_waiting_reminder',
    'notify_broadcast_starting_tomorrow',
    'notify_broadcast_started',
    'notify_broadcast_ended',
    'notify_broadcast_ending_soon',
    'notify_approval_reminder',
]


def _sender_user() -> User:
    """birthboard 通知发件人账号（读取 config.birthboard.sender_username）。

    发件人账号缺失属于部署/配置错误：抛出异常后由各函数的异常日志记录
    （统一 logger 写入 log/birthboard.notify.log），可用管理命令
    `python manage.py ensure_birthboard_sender` 幂等创建。
    """
    sender = User.objects.filter(username=CONFIG.sender_username).first()
    if sender is None:
        raise LookupError(
            f'birthboard 发送账号不存在: {CONFIG.sender_username!r}，'
            '请运行 python manage.py ensure_birthboard_sender')
    return sender


def _receiver_user(record: BirthboardRecord):
    """寿星账号对象；账号不存在时返回 None。"""
    receiver_id = record.participants.filter(
        role=BirthboardParticipant.Role.RECEIVER,
    ).values_list('user_id', flat=True).first()
    if receiver_id is None:
        return None
    return User.objects.filter(pk=receiver_id).first()


def _sender_users(record: BirthboardRecord) -> list[User]:
    """所有送出人账号对象列表。"""
    user_ids = record.participants.filter(
        role=BirthboardParticipant.Role.SENDER
    ).values_list('user_id', flat=True)
    return list(User.objects.filter(id__in=user_ids))


def _recipient_users(record: BirthboardRecord) -> list[User]:
    """寿星 + 所有送出人的账号对象列表。"""
    recipients = _sender_users(record)
    receiver = _receiver_user(record)
    if receiver is not None:
        recipients.insert(0, receiver)
    return recipients


# ========== 用户操作通知 ==========

def notify_revoke(record: BirthboardRecord):
    """撤销/取消投放时，通知寿星和所有送出人"""
    try:
        bulk_notification_create(
            _recipient_users(record),
            _sender_user(),
            Notification.Type.NEEDREAD,
            '生日祝福投放已取消',
            f'你参与的 {record.receiver_name} 的生日祝福投放（{record.date}）已被撤销。',
            URL='/birthboard/confirm',
            to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
        )
    except Exception:
        logger.exception('wechat notify: revoke failed')


def notify_refund(record: BirthboardRecord, paid_users: dict):
    """管理员驳回/终止时退款，通知每个已支付者"""
    try:
        receivers = [user for user in paid_users.values() if user is not None]
        if receivers:
            bulk_notification_create(
                receivers,
                _sender_user(),
                Notification.Type.NEEDREAD,
                '生日祝福投放退款通知',
                f'你参与的 {record.receiver_name} 的生日祝福投放（{record.date}）已终止，'
                '已按你的实际支付记录退还元气值。',
                URL='/birthboard/confirm',
                to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
            )
    except Exception:
        logger.exception('wechat notify: refund failed')


def notify_auto_reject_refund(record: BirthboardRecord, paid_users: dict):
    """超时自动拒绝时退款，通知每个已支付者"""
    try:
        receivers = [user for user in paid_users.values() if user is not None]
        if receivers:
            bulk_notification_create(
                receivers,
                _sender_user(),
                Notification.Type.NEEDREAD,
                '生日祝福投放退款通知',
                f'你参与的 {record.receiver_name} 的生日祝福投放（{record.date}）'
                '因超时未确认已自动取消，已按实际支付记录退还元气值。',
                URL='/birthboard/confirm',
                to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
            )
    except Exception:
        logger.exception('wechat notify: auto reject refund failed')


def notify_invite_sender(record: BirthboardRecord, sender, initiator_name: str, per_cost: int):
    """邀请某人成为送出者时，单独通知该用户"""
    try:
        notification_create(
            sender,
            _sender_user(),
            Notification.Type.NEEDREAD,
            '生日祝福投放邀请',
            f'{initiator_name} 邀请你参与 {record.receiver_name} 的'
            f'生日祝福投放（{record.date}），每人 {per_cost} 元气值。',
            URL='/birthboard/confirm?tab=participation',
            to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
        )
    except Exception:
        logger.exception('wechat notify: invite sender failed')


def notify_receiver_confirmed(record: BirthboardRecord):
    """寿星确认后，通知所有送出人"""
    try:
        bulk_notification_create(
            _sender_users(record),
            _sender_user(),
            Notification.Type.NEEDREAD,
            '生日祝福已确认',
            f'{record.receiver_name} 已确认 {record.date} 的生日祝福投放，将进入审核流程。',
            URL='/birthboard/confirm?tab=participation',
            to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
        )
    except Exception:
        logger.exception('wechat notify: receiver confirmed failed')


def notify_payment_success(record: BirthboardRecord, payer_username: str, all_paid: bool):
    """扣款成功：先通知付款人；若全部付完再通知寿星"""
    try:
        payer = User.objects.filter(username=payer_username).first()
        if payer is not None:
            notification_create(
                payer,
                _sender_user(),
                Notification.Type.NEEDREAD,
                '扣款成功',
                f'你为 {record.receiver_name} 的生日祝福投放（{record.date}）'
                f'已成功支付 {record.per_cost} 元气值。',
                URL='/birthboard/confirm?tab=participation',
                to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
            )
        if all_paid:
            receiver = _receiver_user(record)
            if receiver is not None:
                notification_create(
                    receiver,
                    _sender_user(),
                    Notification.Type.NEEDREAD,
                    '生日祝福待确认',
                    f'你收到新的生日祝福投放（{record.date}），请前往页面确认。',
                    URL='/birthboard/confirm?tab=received',
                    to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
                )
    except Exception:
        logger.exception('wechat notify: payment success failed')


def notify_waiting_reminder(participant: BirthboardParticipant):
    """D-3 提醒：通知待确认的送出人或寿星"""
    record = participant.record
    try:
        if participant.role == BirthboardParticipant.Role.SENDER:
            title = '生日祝福待确认提醒'
            content = (
                f'你参与的生日祝福投放（寿星：{record.receiver_name}，投放日期：{record.date}）'
                '距投放还有3天，当前仍待你确认，请尽快处理。'
            )
            url = '/birthboard/confirm?tab=participation'
        else:
            title = '生日祝福待确认提醒'
            content = (
                f'你收到的生日祝福投放（投放日期：{record.date}）'
                '距投放还有3天，当前仍待你确认，请尽快处理。'
            )
            url = '/birthboard/confirm?tab=received'
        notification_create(
            participant.user,
            _sender_user(),
            Notification.Type.NEEDREAD,
            title,
            content,
            URL=url,
            to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
        )
    except Exception:
        logger.exception(
            'wechat notify: waiting reminder failed user=%s part_id=%s',
            participant.user.username, participant.id,
        )


# ========== 夜间批量任务通知 ==========

def notify_broadcast_starting_tomorrow(record: BirthboardRecord, target_date):
    """投放开始前一天，通知寿星和所有送出人"""
    try:
        bulk_notification_create(
            _recipient_users(record),
            _sender_user(),
            Notification.Type.NEEDREAD,
            '生日祝福投放即将开始',
            f'{record.receiver_name} 的生日祝福投放将于明天（{target_date}）开始展示！',
            URL='/birthboard/confirm',
            to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
        )
    except Exception:
        logger.exception('wechat notify: broadcast starting tomorrow failed')


def notify_broadcast_started(record: BirthboardRecord):
    """投放开始：通知所有相关人 + 寿星单独生日祝福"""
    try:
        bulk_notification_create(
            _recipient_users(record),
            _sender_user(),
            Notification.Type.NEEDREAD,
            '生日祝福投放已开始',
            f'{record.receiver_name} 的生日祝福投放已正式开始展示！',
            URL='/birthboard/confirm',
            to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
        )
        receiver = _receiver_user(record)
        if receiver is not None:
            notification_create(
                receiver,
                _sender_user(),
                Notification.Type.NEEDREAD,
                '书院祝你生日快乐！',
                '今天是你的生日，书院祝你生日快乐！你的生日祝福投放已开始展示。',
                URL='/birthboard/confirm?tab=received',
                to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
            )
    except Exception:
        logger.exception('wechat notify: broadcast start failed')


def notify_broadcast_ended(record: BirthboardRecord, end_date):
    """投放结束时通知所有相关人"""
    try:
        bulk_notification_create(
            _recipient_users(record),
            _sender_user(),
            Notification.Type.NEEDREAD,
            '生日祝福投放已结束',
            f'{record.receiver_name} 的生日祝福投放（{record.date} ~ {end_date}）已结束展示。',
            URL='/birthboard/confirm',
            to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
        )
    except Exception:
        logger.exception('wechat notify: broadcast end failed')


def notify_broadcast_ending_soon(record: BirthboardRecord, end_date):
    """多日投放结束前一天通知"""
    try:
        bulk_notification_create(
            _recipient_users(record),
            _sender_user(),
            Notification.Type.NEEDREAD,
            '生日祝福投放即将结束',
            f'{record.receiver_name} 的生日祝福投放（{record.date} ~ {end_date}）将于明天结束。',
            URL='/birthboard/confirm',
            to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
        )
    except Exception:
        logger.exception('wechat notify: broadcast ending soon failed')


# ========== 审核提醒通知 ==========

def notify_approval_reminder(record: BirthboardRecord, stage: str):
    """审核提醒：通知该阶段所有活跃且开启重复提醒的审核员。stage: 'first' | 'second'

    是否收到提醒由每名审核员的 reminder_enabled 独立控制（关闭不影响其审核权限）。
    """
    try:
        if stage == 'first':
            approver_qs = BirthboardApprover.objects.filter(
                is_active=True, reminder_enabled=True)
            title = '生日祝福投放待初审'
            content = (
                f'{record.receiver_name} 的生日祝福投放（{record.date}）'
                '等待你初审，请尽快处理。'
            )
        else:
            approver_qs = BirthboardSecondApprover.objects.filter(
                is_active=True, reminder_enabled=True)
            title = '生日祝福投放待终审'
            content = (
                f'{record.receiver_name} 的生日祝福投放（{record.date}）'
                '等待你终审，请尽快处理。'
            )
        approver_ids = list(approver_qs.values_list('user_id', flat=True))
        if not approver_ids:
            return
        approvers = list(User.objects.filter(id__in=approver_ids))
        bulk_notification_create(
            approvers,
            _sender_user(),
            Notification.Type.NEEDREAD,
            title,
            content,
            URL='/birthboard/approve',
            to_wechat=dict(level=WechatMessageLevel.IMPORTANT),
        )
    except Exception:
        logger.exception(
            'wechat notify: approval reminder failed stage=%s record_id=%s',
            stage, record.id,
        )
