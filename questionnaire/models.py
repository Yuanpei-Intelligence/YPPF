from django.db import models

from generic.models import User

from utils.models.choice import choice
from utils.models.descriptor import admin_only


__all__ = [
    'Survey',
    'AnswerSheet',
    'Question',
    'Choice',
    'AnswerText',
]


class Survey(models.Model):
    class Meta:
        verbose_name = "问卷"
        verbose_name_plural = verbose_name

    class Status(models.IntegerChoices):
        REVIEWING = choice(0, "审核中")
        PUBLISHED = choice(1, "发布中")
        ENDED = choice(2, "已结束")
        DRAFT = choice(3, "草稿")

    title = models.CharField("标题", max_length=50, blank=False, null=False)
    description = models.TextField("描述", blank=True)
    creator = models.ForeignKey(
        User, on_delete=models.CASCADE, verbose_name="创建人")
    status = models.SmallIntegerField(
        "状态", choices=Status.choices, default=Status.REVIEWING)
    start_time = models.DateTimeField("起始时间")
    end_time = models.DateTimeField("截止时间")
    time = models.DateTimeField("创建时间", auto_now_add=True)

    questions: models.manager.BaseManager['Question']

    @admin_only
    def __str__(self):
        return self.title


class AnswerSheet(models.Model):
    class Meta:
        verbose_name = "答卷"
        verbose_name_plural = verbose_name

    class Status(models.IntegerChoices):
        DRAFT = choice(0, "存为草稿")
        SUBMITTED = choice(1, "提交")

    survey = models.ForeignKey(
        Survey, on_delete=models.CASCADE, verbose_name="对应问卷")
    creator = models.ForeignKey(
        User, on_delete=models.CASCADE, verbose_name="答卷人")
    create_time = models.DateTimeField("填写时间", auto_now_add=True)
    status = models.SmallIntegerField(
        "状态", choices=Status.choices, default=Status.DRAFT)

    @admin_only
    def __str__(self):
        # TODO: 关联查询太多时会很慢，主要用于后台显示（如答案和问卷），暂未优化
        return self.survey.title + " - " + self.creator.username + "的答卷"


class Question(models.Model):
    class Meta:
        verbose_name = "题目"
        verbose_name_plural = verbose_name
        ordering = ["survey", "order"]

    class Type(models.TextChoices):
        TEXT = choice("TEXT", "填空题")
        SINGLE = choice("SINGLE", "单选题")
        MULTIPLE = choice("MULTIPLE", "多选题")
        RANKING = choice("RANKING", "排序题")

        @classmethod
        def WithChoice(cls) -> list['Question.Type']:
            return [cls.SINGLE, cls.MULTIPLE, cls.RANKING]

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE,
                               related_name="questions",
                               verbose_name="所属问卷")
    order = models.IntegerField("序号")
    topic = models.CharField("简介", max_length=50)
    description = models.TextField("题目描述", blank=True)
    type = models.CharField("类型", max_length=10,
                            choices=Type.choices, default=Type.SINGLE)
    required = models.BooleanField("必填", default=True)

    choices: models.manager.BaseManager['Choice']

    def have_choice(self):
        return self.type in self.Type.WithChoice()

    @admin_only
    def __str__(self):
        return self.topic


class Choice(models.Model):
    class Meta:
        verbose_name = "选项"
        verbose_name_plural = verbose_name
        ordering = ["question", "order"]

    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="choices", verbose_name="问题")
    order = models.IntegerField("序号")
    text = models.TextField("内容")

    @admin_only
    def __str__(self):
        return self.text


class AnswerText(models.Model):
    '''
    回答，按字符串形式储存
    '''
    class Meta:
        verbose_name = "回答"
        verbose_name_plural = verbose_name

    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, verbose_name="问题")
    # TODO: 后台显示有潜在的性能问题
    answersheet = models.ForeignKey(
        AnswerSheet, on_delete=models.CASCADE, verbose_name="所属答卷")
    body = models.TextField("内容")
