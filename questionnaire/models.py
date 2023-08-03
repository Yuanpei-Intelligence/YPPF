from django.db import models
from boot.settings import AUTH_USER_MODEL
from utils.models.choice import choice



"""
顶级模型:问卷和答卷 需要有创建人/答卷人、创建日期
答案暂时都按照text形式储存(若干choice的序号) 并外键关联到题目和答卷。
暂不考虑数据库级多选的统计 单选可以统计
题目不分类,只需要有:题目类型、描述 不包含选项等额外信息 
根据题目类型调取相应外键 选项choice等 做好反向关联(related_field关闭或显式写出) 矩阵题的各个题目(暂不做)也一样
序号信息:question和choice都需要 从而在未来可支持调整选项顺序
"""


# 调查问卷
class Survey(models.Model):
    class Status(models.IntegerChoices):
        REVIEWING = (0, "审核中")
        PUBLISHED = (1, "发布中")
        ENDED = (2, "已结束")

    title = models.CharField("问卷标题", max_length=50, unique=True, blank=False, null=False)
    description = models.TextField("问卷描述", blank=True)
    creator = models.ForeignKey(AUTH_USER_MODEL, on_delete=models.CASCADE, related_name = 'surveys', verbose_name="创建人")
    status = models.SmallIntegerField("问卷状态", choices=Status.choices, default=Status.REVIEWING)
    start_time = models.DateTimeField("起始时间", blank=True)
    end_time = models.DateTimeField("截止时间", blank=True)
    time = models.DateTimeField("创建时间", auto_now_add=True)

    def __str__(self):
        return self.title


# 答卷
class AnswerSheet(models.Model):
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, verbose_name="对应问卷")
    creator = models.ForeignKey(AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="答卷人")
    create_time = models.DateTimeField("填写时间", auto_now_add=True)

    def __str__(self):
        return self.survey.title + " - " + self.creator.username + "的答卷"


# 问题
class Question(models.Model):
    class Type(models.TextChoices):
        TEXT = choice("TEXT", "填空题")
        SINGLE = choice("SINGLE", "单选题")
        MULTI = choice("MULTI", "多选题")
        RANKING = choice("RANKING", "排序题")

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, verbose_name="所属问卷")
    order = models.IntegerField("题目序号")
    topic = models.CharField("题目简介", max_length=50)
    description = models.TextField("题目描述", blank=True)
    type = models.CharField("问题类型", max_length=10, choices=Type.choices, default=Type.SINGLE)

    def have_choice(self):
        return self.type in ["SINGLE", "MULT", "RANKING"]

    def __str__(self):
        return self.topic


# 选项
class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices', verbose_name="所属问题")
    order = models.IntegerField("选项序号")
    text = models.TextField("选项内容")

    def __str__(self):
        return self.text


# 回答，按字符串形式储存，与user&question建立连接
class AnswerText(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, verbose_name="对应问题")
    answersheet = models.ForeignKey(AnswerSheet, on_delete=models.CASCADE, verbose_name="所属答卷")
    body = models.TextField("答案内容")

