from django.db import models
from generic.models import User


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
    title = models.CharField(max_length=50) # 标题
    description = models.TextField() # 描述
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='creator_survey') # 创建人
    date = models.DateTimeField(auto_now_add=True, verbose_name='创建时间') # 创建时间
    is_published = models.BooleanField(default=False) # 是否发布

    def __str__(self):
        return f'[问卷] 标题:{self.title};创建人:{self.creator.username};创建时间:{self.date}'
    
    class Meta:
        ordering = ['-date']


# 答卷
class AnswerSheet(models.Model):
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name='survey_answersheet') # 对应问卷
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='creator_answersheet') # 答卷人
    date = models.DateTimeField(auto_now_add=True, verbose_name='填写时间') # 填写时间

    def __str__(self):
        return f'[答卷] 标题:{self.survey.title};答卷人:{self.creator.username};填写时间:{self.date}'

    class Meta:
        ordering = ['-date']


# 问题
class Question(models.Model):
    QTYPE = (
        ('Text', '填空'), 
        ('Single', '单选'), 
        ('Multi', '多选'), 
        ('Ranking', '排序'), 
    )

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name='survey_question') # 对应问卷
    id = models.IntegerField() # 题目序号
    text = models.CharField(max_length=50) # 题干
    description = models.TextField() # 题目描述
    type = models.CharField(max_length=10, choices=QTYPE) # 问题类型

    def __str__(self):
        return f'[问题] 题干:{self.text};序号:{self.id};类型:{self.type}'
    
    class Meta:
        ordering = ['id']

# 选项
class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='question_choice') # 对应问题
    id = models.IntegerField() # 选项序号
    text = models.TextField() # 选项内容

    def __str__(self):
        return f'[选项] 内容:{self.text};序号:{self.id}'
    
    class Meta:
        ordering = ['id']


# 回答，按字符串形式储存，与user&question建立连接
class AnswerText(models.Model):
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name='survey_answertext') # 对应问卷
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='question_answertext') # 对应问题
    answer = models.TextField() # 答案内容

    def __str__(self):
        return f'[答案] 问卷:{self.survey.title};问题:{self.question.text};答案:{self.answer}'
    
    class Meta:
        ordering = ['question__id']


# 问卷的统计信息
class SurveyStatistics(models.Model):
    pass


# 补充事项
# related_name名字起的有点怪，建议修改，但不要重复
# survey与answersheet应该加上编号 用于url查询