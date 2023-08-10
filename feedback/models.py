from datetime import datetime

from django.db import models

from app.models import (
    OrganizationType, 
    Organization,
    CommentBase,
    NaturalPerson,
)

__all__ = [
    'FeedbackType',
    'Feedback',
]

class FeedbackType(models.Model):
    class Meta:
        verbose_name = "#EX.反馈类型"
        verbose_name_plural = verbose_name

    id = models.SmallIntegerField("反馈类型编号", primary_key=True)
    name = models.CharField("反馈类型名称", max_length=20)
    org_type: OrganizationType = models.ForeignKey(
        OrganizationType, on_delete=models.CASCADE, null=True, blank=True)
    org: Organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=True, blank=True)

    class Flexible(models.IntegerChoices):
        NO_DEFAULT = (0, "无默认值")
        ORG_TYPE_DEFAULT = (1, "仅提供组织类型默认值")
        ALL_DEFAULT = (2, "全部提供默认值")

    flexible = models.SmallIntegerField(
        choices=Flexible.choices, default=Flexible.NO_DEFAULT
    )

    def __str__(self):
        return self.name
    

class Feedback(CommentBase):
    class Meta:
        verbose_name = "#EX.反馈"
        verbose_name_plural = verbose_name

    type = models.ForeignKey(FeedbackType, on_delete=models.CASCADE)
    title = models.CharField("标题", max_length=30, blank=False)
    content = models.TextField("内容", blank=False)
    person = models.ForeignKey(NaturalPerson, on_delete=models.CASCADE)
    org_type: OrganizationType = models.ForeignKey(
        OrganizationType, on_delete=models.CASCADE, null=True, blank=True)
    org: Organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=True, blank=True)
    url = models.URLField("相关链接", max_length=256, default="", blank=True)

    class IssueStatus(models.IntegerChoices):
        DRAFTED = (0, "草稿")
        ISSUED = (1, "已发布")
        DELETED = (2, "已删除")

    class ReadStatus(models.IntegerChoices):
        READ = (0, "已读")
        UNREAD = (1, "未读")

    class SolveStatus(models.IntegerChoices):
        SOLVED = (0, "已解决")
        SOLVING = (1, "解决中")
        UNSOLVABLE = (2, "无法解决")
        UNMARKED = (3, "未标记")

    issue_status = models.SmallIntegerField(
        '发布状态', choices=IssueStatus.choices, default=IssueStatus.DRAFTED
    )
    read_status = models.SmallIntegerField(
        '阅读情况', choices=ReadStatus.choices, default=ReadStatus.UNREAD
    )
    solve_status = models.SmallIntegerField(
        '解决进度', choices=SolveStatus.choices, default=SolveStatus.UNMARKED
    )

    feedback_time = models.DateTimeField('反馈时间', auto_now_add=True)
    # anonymous = models.BooleanField("发布者是否匿名", default=True)
    publisher_public = models.BooleanField('发布者是否公开', default=False)
    org_public = models.BooleanField('组织是否公开', default=False)
    public_time = models.DateTimeField('组织公开时间', default=datetime.now)

    class PublicStatus(models.IntegerChoices):
        PUBLIC = (0, '公开')
        PRIVATE = (1, '未公开')
        WITHDRAWAL = (2, '撤销公开')
        FORCE_PRIVATE = (3, '不予公开')

    public_status = models.SmallIntegerField(
        '公开状态', choices=PublicStatus.choices, default=PublicStatus.PRIVATE
    )

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.typename = "feedback"
        super().save(*args, **kwargs)

    def get_absolute_url(self, absolute=False) -> str:
        '''
        获取显示页面网址

        :param absolute: 是否返回绝对地址, defaults to False
        :type absolute: bool, optional
        :return: 显示页面的网址
        :rtype: str
        '''
        if self.issue_status == Feedback.IssueStatus.DRAFTED:
            url = f'/modifyFeedback/?feedback_id={self.id}'
        else:
            url = f'/viewFeedback/{self.id}'
        return url