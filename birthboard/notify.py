"""
生日祝福投放板 - 企业微信通知函数

所有 send_wechat 调用统一封装在此，供 views.py 和 jobs.py 使用。
每个函数内部自行处理异常，调用方无需 try/except。
"""
import logging

from birthboard.models import BirthboardRecord, BirthboardParticipant
from extern.wechat import send_wechat

logger = logging.getLogger(__name__)


def _recipients_all(record: BirthboardRecord) -> list[str]:
    """寿星 + 所有送出人 的用户名列表"""
    sender_usernames = list(record.participants.filter(
        role=BirthboardParticipant.Role.SENDER
    ).values_list('user__username', flat=True))
    return [record.receiver_username] + sender_usernames


def _sender_usernames(record: BirthboardRecord) -> list[str]:
    """所有送出人用户名列表"""
    return list(record.participants.filter(
        role=BirthboardParticipant.Role.SENDER
    ).values_list('user__username', flat=True))


# ========== 用户操作通知 ==========

def notify_revoke(record: BirthboardRecord):
    """撤销/取消投放时，通知寿星和所有送出人"""
    try:
        recipients = _recipients_all(record)
        send_wechat(
            recipients,
            "生日祝福投放已取消",
            f"你参与的 {record.receiver_name} 的生日祝福投放（{record.date}）已被撤销。",
            url="/birthboard/confirm", btntxt="查看详情",
        )
    except Exception:
        logger.exception("wechat notify: revoke failed")


def notify_refund(record: BirthboardRecord, paid_users: dict):
    """管理员驳回/终止时退款，通知每个已支付者"""
    try:
        for user_id, paid_user in paid_users.items():
            if paid_user is None:
                continue
            send_wechat(
                [paid_user.username],
                "生日祝福投放退款通知",
                f"你参与的 {record.receiver_name} 的生日祝福投放（{record.date}）已终止，"
                f"已退还 {record.per_cost} 元气值。",
                url="/birthboard/confirm", btntxt="查看详情",
            )
    except Exception:
        logger.exception("wechat notify: refund failed")


def notify_auto_reject_refund(record: BirthboardRecord, paid_users: dict):
    """超时自动拒绝时退款，通知每个已支付者"""
    try:
        for user_id, paid_user in paid_users.items():
            if paid_user is None:
                continue
            send_wechat(
                [paid_user.username],
                "生日祝福投放退款通知",
                f"你参与的 {record.receiver_name} 的生日祝福投放（{record.date}）"
                f"因超时未确认已自动取消，已退还 {record.per_cost} 元气值。",
                url="/birthboard/confirm", btntxt="查看详情",
            )
    except Exception:
        logger.exception("wechat notify: auto reject refund failed")


def notify_invite_sender(record: BirthboardRecord, sender, initiator_name: str, per_cost: int):
    """邀请某人成为送出者时，单独通知该用户"""
    try:
        send_wechat(
            [sender.username],
            "生日祝福投放邀请",
            f"{initiator_name} 邀请你参与 {record.receiver_name} 的"
            f"生日祝福投放（{record.date}），每人 {per_cost} 元气值。",
            url="/birthboard/confirm?tab=participation", btntxt="去确认",
        )
    except Exception:
        logger.exception("wechat notify: invite sender failed")


def notify_receiver_confirmed(record: BirthboardRecord):
    """寿星确认后，通知所有送出人"""
    try:
        send_wechat(
            _sender_usernames(record),
            "生日祝福已确认",
            f"{record.receiver_name} 已确认 {record.date} 的生日祝福投放，将进入审核流程。",
            url="/birthboard/confirm?tab=participation", btntxt="查看详情",
        )
    except Exception:
        logger.exception("wechat notify: receiver confirmed failed")


def notify_payment_success(record: BirthboardRecord, payer_username: str, all_paid: bool):
    """扣款成功：先通知付款人；若全部付完再通知寿星"""
    try:
        send_wechat(
            [payer_username],
            "扣款成功",
            f"你为 {record.receiver_name} 的生日祝福投放（{record.date}）"
            f"已成功支付 {record.per_cost} 元气值。",
            url="/birthboard/confirm?tab=participation", btntxt="查看详情",
        )
        if all_paid:
            send_wechat(
                [record.receiver_username],
                "生日祝福待确认",
                f"你收到新的生日祝福投放（{record.date}），请前往页面确认。",
                url="/birthboard/confirm?tab=received", btntxt="去确认",
            )
    except Exception:
        logger.exception("wechat notify: payment success failed")


def notify_waiting_reminder(participant: BirthboardParticipant):
    """D-3 提醒：通知待确认的送出人或寿星"""
    record = participant.record
    try:
        if participant.role == BirthboardParticipant.Role.SENDER:
            title = "生日祝福待确认提醒"
            content = (
                f"你参与的生日祝福投放（寿星：{record.receiver_name}，投放日期：{record.date}）"
                "距投放还有3天，当前仍待你确认，请尽快处理。"
            )
            url = "/birthboard/confirm?tab=participation"
        else:
            title = "生日祝福待确认提醒"
            content = (
                f"你收到的生日祝福投放（投放日期：{record.date}）"
                "距投放还有3天，当前仍待你确认，请尽快处理。"
            )
            url = "/birthboard/confirm?tab=received"
        send_wechat(
            [participant.user.username],
            title, content,
            url=url, btntxt="去处理",
        )
    except Exception:
        logger.exception(
            "wechat notify: waiting reminder failed user=%s part_id=%s",
            participant.user.username, participant.id,
        )


# ========== 夜间批量任务通知 ==========

def notify_broadcast_starting_tomorrow(record: BirthboardRecord, target_date):
    """投放开始前一天，通知寿星和所有送出人"""
    try:
        send_wechat(
            _recipients_all(record),
            "生日祝福投放即将开始",
            f"{record.receiver_name} 的生日祝福投放将于明天（{target_date}）开始展示！",
            url="/birthboard/confirm", btntxt="查看详情",
        )
    except Exception:
        logger.exception("wechat notify: broadcast starting tomorrow failed")


def notify_broadcast_started(record: BirthboardRecord):
    """投放开始：通知所有相关人 + 寿星单独生日祝福"""
    try:
        send_wechat(
            _recipients_all(record),
            "生日祝福投放已开始",
            f"{record.receiver_name} 的生日祝福投放已正式开始展示！",
            url="/birthboard/confirm", btntxt="查看详情",
        )
        send_wechat(
            [record.receiver_username],
            "书院祝你生日快乐！",
            "今天是你的生日，书院祝你生日快乐！你的生日祝福投放已开始展示。",
            url="/birthboard/confirm?tab=received", btntxt="查看详情",
        )
    except Exception:
        logger.exception("wechat notify: broadcast start failed")


def notify_broadcast_ended(record: BirthboardRecord, end_date):
    """投放结束时通知所有相关人"""
    try:
        send_wechat(
            _recipients_all(record),
            "生日祝福投放已结束",
            f"{record.receiver_name} 的生日祝福投放（{record.date} ~ {end_date}）已结束展示。",
            url="/birthboard/confirm", btntxt="查看详情",
        )
    except Exception:
        logger.exception("wechat notify: broadcast end failed")


def notify_broadcast_ending_soon(record: BirthboardRecord, end_date):
    """多日投放结束前一天通知"""
    try:
        send_wechat(
            _recipients_all(record),
            "生日祝福投放即将结束",
            f"{record.receiver_name} 的生日祝福投放（{record.date} ~ {end_date}）将于明天结束。",
            url="/birthboard/confirm", btntxt="查看详情",
        )
    except Exception:
        logger.exception("wechat notify: broadcast ending soon failed")
