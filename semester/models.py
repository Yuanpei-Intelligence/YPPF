from django.db import models


__all__ = ['SemesterType', 'Semester']


class SemesterType(models.Model):
    class Meta:
        verbose_name = '学期类型'
        verbose_name_plural = verbose_name

    name = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class Semester(models.Model):
    '''学期

    不同的学期时间不应重叠

    Attributes:
        year(int): 学年的起始年份，如2019-2020学年为2019
        type(SemesterType): 学期类型
        start_date(date): 开学日期
        end_date(date): 放假日期
    '''
    class Meta:
        verbose_name = '学期'
        verbose_name_plural = verbose_name
        unique_together = ['year', 'type']

    year = models.IntegerField('学年', help_text='学年的起始年份，如2019-2020学年为2019')
    type = models.ForeignKey(SemesterType, on_delete=models.CASCADE)
    start_date = models.DateField('开学日期')
    end_date = models.DateField('放假日期')
