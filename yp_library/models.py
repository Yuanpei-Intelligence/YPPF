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
    student_id = models.CharField("学号", max_length=30, blank=True, null=True)


class Book(models.Model):
    class Meta:
        verbose_name = "书"
        verbose_name_plural = verbose_name
        
    id = models.IntegerField("书籍编号", primary_key=True)
    identity_code = models.CharField("索书号", max_length=254, blank=True, null=True)
    title = models.CharField("书名", max_length=500, blank=True, null=True)
    author = models.CharField("作者", max_length=254, blank=True, null=True)
    publisher = models.CharField("出版商", max_length=254, blank=True, null=True)
    returned = models.BooleanField("是否已还", default=True)
    
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
    return_time = models.DateTimeField("还书时间", blank=True, null=True)
    returned = models.BooleanField("是否已还", default=False)
    
    class Status(models.IntegerChoices):
        NORMAL = (0, "正常")
        OVERTIME = (1, "超时扣分")
        APPEALING = (2, "申诉中")
        ACCEPTED = (3, "申诉通过")
        REJECTED = (4, "申诉失败")
    
    status = models.SmallIntegerField(
        "借阅记录状态", choices=Status.choices, default=Status.NORMAL
    )
