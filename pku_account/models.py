"""
北大账号绑定: one PKU (IAAA) account per YPPF user plus the encrypted portal
session that was obtained with it. Contract: ``timetable/README.md`` §3.2.

Passwords are never persisted, not even encrypted. What is kept is the portal
cookie jar, encrypted with Fernet (:mod:`pku_account.crypto`).
"""
from __future__ import annotations

from datetime import datetime

from django.db import models

from generic.models import User

__all__ = ['PkuAccount', 'PkuPortalSession']


class PkuAccount(models.Model):
    """
    The binding between a YPPF user and a PKU account.

    ``login_failures`` / ``locked_until`` implement the per-binding brute-force
    guard of ``services.login_and_bind``; the consent flags record what the
    student allowed the platform to fetch and store.
    """

    class Meta:
        verbose_name = '北大账号绑定'
        verbose_name_plural = verbose_name

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='pku_account',
        verbose_name='用户',
    )
    pku_username = models.CharField('北大账号', max_length=32, unique=True)
    verified_at = models.DateTimeField('首次验证时间')
    last_login_at = models.DateTimeField('最近登录时间', null=True, blank=True)
    last_sync_at = models.DateTimeField('最近同步时间', null=True, blank=True)
    login_failures = models.PositiveSmallIntegerField('连续失败次数', default=0)
    locked_until = models.DateTimeField('锁定至', null=True, blank=True)
    consent_timetable = models.BooleanField('同意获取课表', default=False)
    consent_timetable_at = models.DateTimeField(
        '课表授权时间', null=True, blank=True)
    consent_grades = models.BooleanField('同意获取成绩', default=False)
    consent_grades_at = models.DateTimeField(
        '成绩授权时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    def __str__(self) -> str:
        return f'PkuAccount({self.pku_username})'

    def is_locked(self, now: datetime | None = None) -> bool:
        """Whether ``locked_until`` is still in the future."""
        if self.locked_until is None:
            return False
        if now is None:
            now = datetime.now()
        return self.locked_until > now


class PkuPortalSession(models.Model):
    """
    The encrypted portal cookie jar of a binding (at most one per binding).

    ``cookies_encrypted`` is ``Fernet(json.dumps(cookies))``; it must never be
    displayed or logged. ``invalid`` is set by ``services.invalidate_session``
    once the portal stops accepting the cookies.
    """

    class Meta:
        verbose_name = '北大门户会话'
        verbose_name_plural = verbose_name

    account = models.OneToOneField(
        PkuAccount, on_delete=models.CASCADE, related_name='portal_session',
        verbose_name='绑定',
    )
    cookies_encrypted = models.BinaryField('加密的 Cookie')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    last_ok_at = models.DateTimeField('最近可用时间', null=True, blank=True)
    last_checked_at = models.DateTimeField('最近检查时间', null=True, blank=True)
    invalid = models.BooleanField('已失效', default=False)
    invalid_reason = models.CharField('失效原因', max_length=64, blank=True)

    def __str__(self) -> str:
        state = 'invalid' if self.invalid else 'ok'
        return f'PkuPortalSession(account={self.account_id}, {state})'
