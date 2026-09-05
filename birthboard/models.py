from datetime import datetime

from django.db import models
from generic.models import User

__all__ = [
    # 模型
    'BirthboardRecord',
    'ChangeRecord',
    'BirthboardParticipant',
    'BirthboardContract',
    'BirthboardConfirmSeen',
    'BirthboardLike',
    'BirthboardReminderSeen',
]

# Create your models here.
# 生日祝福投放记录模型，顶格定义
class BirthboardRecord(models.Model):
    class Meta:
        verbose_name = '灯牌记录'
        verbose_name_plural = '4.灯牌记录'

    receiver_username = models.CharField(max_length=64)
    receiver_name = models.CharField(max_length=64)
    date = models.DateField()
    mode = models.IntegerField()
    per_cost = models.IntegerField()
    image = models.ImageField(upload_to='birthboard_images/')
    thumbnail = models.ImageField(upload_to='birthboard_thumbnails/', null=True, blank=True)
    is_anonymous = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Status(models.TextChoices):
        WAITING_CONFIRM = 'waiting_confirm', '等待大家确认'
        WAITING_RECEIVER = 'waiting_receiver', '等待寿星确认'
        WAITING_APPROVE = 'waiting_approve', '等待管理员审批'
        READY = 'ready', '等待投放'
        ONGOING = 'ongoing', '投放进行中'
        FINISHED = 'finished', '投放完成'
        TERMINATED = 'terminated', '已终止'
        TERMINATED_BY_ADMIN = 'terminated_by_admin', '需要修改'
        CANCELED = 'canceled', '已撤销'

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.WAITING_CONFIRM,
        verbose_name='主流程状态'
    )

    # 一审/二审相关字段
    first_approved = models.BooleanField(default=False, verbose_name='一审已通过')
    first_approver = models.ForeignKey(User, null=True, blank=True, related_name='birthboard_first_approved', on_delete=models.SET_NULL, verbose_name='一审人')
    first_approved_at = models.DateTimeField(null=True, blank=True, verbose_name='一审时间')
    second_approver = models.ForeignKey(User, null=True, blank=True, related_name='birthboard_second_approved', on_delete=models.SET_NULL, verbose_name='二审人')
    second_approved_at = models.DateTimeField(null=True, blank=True, verbose_name='二审时间')
    display_takedown_pending = models.BooleanField(
        default=False,
        verbose_name='等待从投放屏下架',
    )


class ChangeRecord(models.Model):
    class Action(models.TextChoices):
        CREATE = 'create', '创建'
        PAY = 'pay', '付款'
        ABORT = 'abort', '中止'
        REVOKE = 'revoke', '撤销'
        REJECT = 'reject', '拒绝'
        APPROVE = 'approve', '审核通过'
        REFUND = 'refund', '退款'
        UPDATE = 'update', '更新'

    record = models.ForeignKey(BirthboardRecord, on_delete=models.CASCADE, related_name='change_records', verbose_name='投放记录')
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='birthboard_change_records', verbose_name='修改人')
    action = models.CharField(max_length=16, choices=Action.choices, verbose_name='操作类型')
    before_status = models.CharField(max_length=32, blank=True, default='', verbose_name='修改前状态')
    after_status = models.CharField(max_length=32, blank=True, default='', verbose_name='修改后状态')
    detail = models.JSONField(default=dict, blank=True, verbose_name='修改信息')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='修改时间')

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = '投放变更记录'
        verbose_name_plural = '投放变更记录'

    def __str__(self):
        return f"{self.record_id} {self.get_action_display()}"

    @classmethod
    def log(cls, record, actor=None, action='', before_status='', after_status='', detail=None):
        return cls.objects.create(
            record=record,
            actor=actor,
            action=action,
            before_status=before_status or '',
            after_status=after_status or '',
            detail=detail or {},
        )
# 二审员名单表
class BirthboardSecondApprover(models.Model):
    class Meta:
        verbose_name = '终审人员'
        verbose_name_plural = '2.终审人员'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='birthboard_second_approver')
    is_active = models.BooleanField(default=True)
    # 是否接收自动重复审核提醒；关闭后仍可正常审核，只是不再被提醒打扰
    reminder_enabled = models.BooleanField('接收重复提醒', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=64, blank=True, default='', help_text='备注')

    def __str__(self):
        return f"二审员: {self.user.get_full_name() or self.user.username} ({'有效' if self.is_active else '禁用'})"

#用户表
class BirthboardParticipant(models.Model):
    class Role(models.TextChoices):
        SENDER = 'sender', '送出人'
        RECEIVER = 'receiver', '寿星'

    class Status(models.TextChoices):
        WAIT = 'wait', '待确认'
        CONFIRMED = 'confirmed', '已确认'
        REJECTED = 'rejected', '已拒绝'
        PAID = 'paid', '已扣款'
        REFUNDED = 'refunded', '已退款'

    record = models.ForeignKey('BirthboardRecord', on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=Role.choices)
    is_initiator = models.BooleanField(default=False)
    cost = models.IntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.WAIT)
    action_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('record', 'user', 'role')

    def __str__(self):
        return f"{self.user}({self.get_role_display()}) in {self.record}"
    
# 管理员驳回原因表
class BirthboardRejectedIssue(models.Model):
    record = models.OneToOneField(BirthboardRecord, on_delete=models.CASCADE, related_name='rejected_issue')
    # 多选违规类型，存储为逗号分隔字符串
    REASON_CHOICES = [
        ('低俗恶搞', '低俗恶搞'),
        ('暴力色情恐怖', '暴力色情恐怖'),
        ('诋毁侮辱隐私', '诋毁侮辱隐私'),
        ('敏感引战', '敏感引战'),
        ('不适宜公开投放的内容', '不适宜公开投放的内容'),
    ]
    reasons = models.CharField(max_length=128, help_text='多选原因，逗号分隔')
    detail = models.TextField(help_text='具体违规内容')
    created_at = models.DateTimeField(auto_now_add=True)

    def get_reason_list(self):
        return self.reasons.split(',') if self.reasons else []

    def __str__(self):
        return f"需要修改-{self.record_id}: {self.reasons}" 

# 审核员名单表
class BirthboardApprover(models.Model):
    class Meta:
        verbose_name = '初审人员'
        verbose_name_plural = '1.初审人员'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='birthboard_approver')
    is_active = models.BooleanField(default=True)
    # 是否接收自动重复审核提醒；关闭后仍可正常审核，只是不再被提醒打扰
    reminder_enabled = models.BooleanField('接收重复提醒', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=64, blank=True, default='', help_text='备注')

    def __str__(self):
        return f"审核员: {self.user.get_full_name() or self.user.username} ({'有效' if self.is_active else '禁用'})"

# 用户协议签署记录
class BirthboardContract(models.Model):
    class Meta:
        verbose_name = '协议记录'
        verbose_name_plural = '3.协议记录与小黑屋'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='birthboard_contract')
    signed = models.BooleanField('已签署', default=False)
    signed_at = models.DateTimeField('签署时间', null=True, blank=True)
    restricted_until = models.DateTimeField(
        '限制参与至',
        null=True,
        blank=True,
    )

    def __str__(self):
        return f"{self.user.username} contract={'✓' if self.signed else '✗'}"

# 确认页面已读时间记录（持久化到DB，跨浏览器同步）
class BirthboardConfirmSeen(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='birthboard_confirm_seen')
    participation_seen = models.DateTimeField(default=datetime(1970, 1, 1, 8, 0))
    received_seen = models.DateTimeField(default=datetime(1970, 1, 1, 8, 0))
    finished_seen = models.DateTimeField(default=datetime(1970, 1, 1, 8, 0))

    def __str__(self):
        return f"{self.user.username} confirm_seen"

    @classmethod
    def get_seen_dt(cls, user, tab: str):
        """获取用户某tab的最后查看时间，无记录则返回epoch"""
        obj = cls.objects.filter(user=user).first()
        if obj is None:
            return datetime.fromtimestamp(0)
        return getattr(obj, f'{tab}_seen', datetime.fromtimestamp(0))

    @classmethod
    def mark_seen(cls, user, tab: str):
        """标记用户某tab为已读（设为当前时间）"""
        obj, _ = cls.objects.get_or_create(user=user)
        setattr(obj, f'{tab}_seen', datetime.now())
        obj.save(update_fields=[f'{tab}_seen'])

# 工具函数：录入指定用户为审核员（可用于shell或临时脚本）
def add_birthboard_approver_by_username(username):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.get(username=username)
    from birthboard.models import BirthboardApprover
    BirthboardApprover.objects.get_or_create(user=user, defaults={"is_active": True})


class BirthboardLike(models.Model):
    """制作名单累计点赞量（由业务层保证仅保留一条记录）。"""
    count = models.PositiveIntegerField('累计点赞量', default=0)

    class Meta:
        verbose_name = '制作名单点赞量'
        verbose_name_plural = '制作名单点赞量'


class BirthboardReminderSeen(models.Model):
    """今日提醒（happy/bless）已展示记录：服务端去重，跨设备有效。"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='birthboard_reminder_seen',
    )
    date = models.DateField('提醒日期')
    reminder_type = models.CharField('提醒类型', max_length=16)  # happy / bless
    seen_at = models.DateTimeField('标记时间', auto_now_add=True)

    class Meta:
        verbose_name = '生日提醒已读记录'
        verbose_name_plural = '生日提醒已读记录'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'date', 'reminder_type'],
                name='uniq_birthboard_reminder_seen',
            ),
        ]
