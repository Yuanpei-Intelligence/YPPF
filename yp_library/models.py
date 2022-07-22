from django.db import models
from django.contrib.auth.models import User

__all__ = [
    "Reader",
    "Book",
    "LendRecord",
]


class Reader(models.Model):
    class Meta:
        verbose_name = "读者"
        verbose_name_plural = verbose_name
    
    id = models.AutoField("编号", primary_key=True)
    stu_id = models.OneToOneField(
        User,
        related_name='+',
        on_delete=models.CASCADE,
        to_field='username',
        verbose_name='学号',
    )
    
    def __str__(self):
        return str(self.name)


class Book(models.Model):
    class Meta:
        verbose_name = "书"
        verbose_name_plural = verbose_name
        
    id = models.IntegerField("书籍编号", primary_key=True)
    title = models.CharField("书名", max_length=500, blank=True, null=True)
    author = models.CharField("作者", max_length=254, blank=True, null=True)
    publisher = models.CharField("出版商", max_length=254, blank=True, null=True)
    returned = models.BooleanField("是否已还", default=False)
    
    def __str__(self):
        return str(self.title)


class LendRecord(models.Model):
    class Meta:
        verbose_name = "借阅记录"
        verbose_name_plural = verbose_name
        ordering = ["-lend_time"]
    
    reader_id = models.ForeignKey(
        Reader, on_delete=models.CASCADE, verbose_name="读者编号"
    )
    book_id = models.ForeignKey(
        Book, on_delete=models.CASCADE, verbose_name="书籍编号"
    )
    lend_time = models.DateTimeField("借出时间")
    due_time = models.DateTimeField("还书截止时间")
    return_time = models.DateTimeField("还书时间")
    returned = models.BooleanField("是否已还", default=False)
    
    class AppealStatus(models.IntegerChoices):
        NORMAL = (0, "未申诉")
        APPEALING = (1, "申诉中")
        ACCEPTED = (2, "申诉通过")
        REJECTED = (3, "申诉不通过")
    
    appeal_status = models.SmallIntegerField(
        "申诉状态", choices=AppealStatus.choices, default=AppealStatus.NORMAL
    )
