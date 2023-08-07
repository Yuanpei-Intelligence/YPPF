from django.db import models

from generic.models import User

from utils.models.choice import choice
from utils.models.descriptor import debug_only


__all__ = [
    'Survey', 
    'AnswerSheet', 
    'Question', 
    'Choice', 
    'AnswerText'
]


class Survey(models.Model):
    '''
    调查问卷
    '''
    class Status(models.IntegerChoices):
        REVIEWING = choice(0, "审核中")
        PUBLISHED = choice(1, "发布中")
        ENDED = choice(2, "已结束")
        DRAFT = choice(3, "草稿")

    title = models.CharField("问卷标题", max_length=50, blank=False, null=False)
    description = models.TextField("问卷描述", blank=True)
    creator = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="创建人")
    status = models.SmallIntegerField("问卷状态", choices=Status.choices, default=Status.REVIEWING)
    start_time = models.DateTimeField("起始时间")
    end_time = models.DateTimeField("截止时间")
    time = models.DateTimeField("创建时间", auto_now_add=True)

    @debug_only
    def __str__(self):
        return self.title


class AnswerSheet(models.Model):
    '''
    答卷
    '''
    class Status(models.IntegerChoices):
        DRAFT = choice(0, "存为草稿")
        SUBMITTED = choice(1, "提交")

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, verbose_name="对应问卷")
    creator = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="答卷人")
    create_time = models.DateTimeField("填写时间", auto_now_add=True)
    status = models.SmallIntegerField("问卷状态", choices=Status.choices, default=Status.DRAFT)

    @debug_only
    def __str__(self):
        return self.survey.title + " - " + self.creator.username + "的答卷" # 关联查询太多时会很慢


class Question(models.Model):
    '''
    问题
    '''
    class Type(models.TextChoices):
        TEXT = choice("TEXT", "填空题")
        SINGLE = choice("SINGLE", "单选题")
        MULTIPLE = choice("MULTIPLE", "多选题")
        RANKING = choice("RANKING", "排序题")

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, verbose_name="所属问卷")
    order = models.IntegerField("题目序号")
    topic = models.CharField("题目简介", max_length=50)
    description = models.TextField("题目描述", blank=True)
    type = models.CharField("问题类型", max_length=10, choices=Type.choices, default=Type.SINGLE)

    def have_choice(self):
        return self.type in ["SINGLE", "MULTIPLE", "RANKING"]

    @debug_only
    def __str__(self):
        return self.topic


# 选项
class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices', verbose_name="所属问题")
    order = models.IntegerField("选项序号")
    text = models.TextField("选项内容")

    @debug_only
    def __str__(self):
        return self.text


class AnswerText(models.Model):
    '''
    回答，按字符串形式储存，与user&question建立连接
    '''
    question = models.ForeignKey(Question, on_delete=models.CASCADE, verbose_name="对应问题")
    answersheet = models.ForeignKey(AnswerSheet, on_delete=models.CASCADE, verbose_name="所属答卷")
    body = models.TextField("答案内容")
