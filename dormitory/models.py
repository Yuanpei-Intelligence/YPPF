from django.db import models
from generic.models import User

# 问卷
class Survey(models.Model):
    title = models.CharField(max_length=20)
    description = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)


# 答卷
class Answer(models.Model):
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE)
    answered_by = models.ForeignKey(User, on_delete=models.CASCADE)
    answered_at = models.DateTimeField(auto_now_add=True)


# 问题
class Question(models.Model):
    Qtype = (
        ('Text', '填空'), 
        ('Single', '单选'), 
        ('Multi', '多选'), 
        ('Ranking', '排序'), 
    )

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE)
    id = models.IntegerField()    
    text = models.CharField(max_length=50) # 题干
    description = models.TextField() # 题目描述
    type = models.CharField(max_length=10, choices=Qtype)


# 选项
class Choice(models.Model):
    question = models.ForeignKey(Question, related_name='choices', on_delete=models.CASCADE)
    id = models.IntegerField()
    text = models.TextField()


# 回答，按字符串形式储存，与user&question建立连接
class AnswerText(models.Model):
    question = models.ForeignKey(Question, related_name='answers', on_delete=models.CASCADE)
    survey = models.ForeignKey(Answer, on_delete=models.CASCADE)
    answer = models.TextField()