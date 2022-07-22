"""
元培书房数据库模型
"""
from django.db import models


class LendRecords(models.Model):
    """
    图书的借阅记录
    """
    id = models.IntegerField(db_column='ID', primary_key=True)
    # 每个编号对应一个人，个人信息可以根据编号在Readers内部检索
    readerid = models.IntegerField("读者编号", db_column='ReaderID')
    # 形如'211046ZW005377'，最后六位代表书的编号，对应的书籍信息可以在BookInfo中查找
    barcode = models.CharField(db_column='BarCode', max_length=20)
    lendtm = models.DateTimeField("借出时间", db_column='LendTM')
    duetm = models.DateTimeField("还书截止时间", db_column='DueTm')
    isreturn = models.IntegerField("是否已还",
                                   db_column='IsReturn',
                                   blank=True,
                                   null=True)
    returntime = models.DateTimeField("还书时间",
                                      db_column='ReturnTime',
                                      blank=True,
                                      null=True)
    overdays = models.IntegerField("逾期天数",
                                   db_column='OverDays',
                                   blank=True,
                                   null=True)

    class Meta:
        managed = False
        db_table = 'LendHist'


class Readers(models.Model):
    """
    读者信息
    """
    # 该编号与借书记录中的readerid相对应
    id = models.AutoField("编号", db_column='ID', primary_key=True)
    # 学生姓名
    name = models.CharField("姓名", db_column='Name', max_length=100)
    # * 书房数据库还需整理，这一列暂时可能存在数据错误或缺失
    idcardno = models.CharField("学号",
                                db_column='IDCardNo',
                                max_length=30,
                                blank=True,
                                null=True)

    class Meta:
        managed = False
        db_table = 'Readers'


class BookInfo(models.Model):
    """
    书籍信息
    """
    marcid = models.IntegerField("书籍编号", db_column='MarcID', primary_key=True)
    title = models.CharField("书名",
                             db_column='Title',
                             max_length=500,
                             blank=True,
                             null=True)
    author = models.CharField("作者",
                              db_column='Author',
                              max_length=254,
                              blank=True,
                              null=True)
    publisher = models.CharField("出版商",
                                 db_column='Publisher',
                                 max_length=254,
                                 blank=True,
                                 null=True)
    price = models.FloatField("标价", db_column='Price', blank=True, null=True)
    profile = models.TextField("内容简介",
                               db_column='Profile',
                               blank=True,
                               null=True)
    # 存在空白数据，读取时需要进行处理                          
    pages = models.CharField("页数",
                             db_column='Pages',
                             max_length=100,
                             blank=True,
                             null=True)
    reqno = models.CharField("序列号", 
                             db_column='ReqNo',
                             max_length=254,
                             blank=True,
                             null=True)

    class Meta:
        managed = False
        db_table = 'CircMarc'

