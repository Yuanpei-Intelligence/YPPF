"""
元培书房数据库模型
"""
from django.db import models


class LendRecords(models.Model):
    """
    图书的借阅记录
    """
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

    # 以下为无关数据
    id = models.IntegerField(db_column='ID', primary_key=True)
    place = models.IntegerField(db_column='Place', blank=True, null=True)
    pressdate = models.DateTimeField(db_column='PressDate')
    presstime = models.IntegerField(db_column='PressTime')
    renewtime = models.IntegerField(db_column='RenewTime')
    lttype = models.IntegerField(db_column='LTType', blank=True, null=True)
    lendmember = models.IntegerField(db_column='LendMember',
                                     blank=True,
                                     null=True)
    lendopid = models.CharField(db_column='LendOpID', max_length=20)

    returnmember = models.IntegerField(db_column='ReturnMember',
                                       blank=True,
                                       null=True)
    returnopid = models.CharField(db_column='ReturnOpID',
                                  max_length=20,
                                  blank=True,
                                  null=True)
    lendstation = models.IntegerField(db_column='LendStation',
                                      blank=True,
                                      null=True)
    returnstation = models.IntegerField(db_column='ReturnStation',
                                        blank=True,
                                        null=True)
    lendid = models.IntegerField(db_column='LendID', blank=True, null=True)
    overcash = models.DecimalField(db_column='OverCash',
                                   max_digits=19,
                                   decimal_places=4,
                                   blank=True,
                                   null=True)
    dirtycash = models.DecimalField(db_column='DirtyCash',
                                    max_digits=19,
                                    decimal_places=4,
                                    blank=True,
                                    null=True)
    lostcash = models.DecimalField(db_column='LostCash',
                                   max_digits=19,
                                   decimal_places=4,
                                   blank=True,
                                   null=True)
    cashflag = models.IntegerField(db_column='CashFlag', blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'LendHist'


class Readers(models.Model):
    """
    读者信息
    """
    # 读者编号与姓名一一对应
    id = models.AutoField("编号", db_column='ID', primary_key=True)
    name = models.CharField("姓名", db_column='Name', max_length=100)

    # 以下为无关数据
    sex = models.IntegerField(db_column='Sex', blank=True, null=True)
    cardcode = models.IntegerField(db_column='CardCode', blank=True, null=True)
    certid = models.CharField(db_column='CertID',
                              max_length=50,
                              blank=True,
                              null=True)
    cardserialno = models.CharField(db_column='CardSerialNo',
                                    max_length=20,
                                    blank=True,
                                    null=True)
    idcardtype = models.IntegerField(db_column='IDCardType',
                                     blank=True,
                                     null=True)
    idcardno = models.CharField(db_column='IDCardNo',
                                max_length=30,
                                blank=True,
                                null=True)
    levelr = models.IntegerField(db_column='LevelR', blank=True, null=True)
    readertype = models.IntegerField(db_column='ReaderType',
                                     blank=True,
                                     null=True)
    workr = models.IntegerField(db_column='WorkR', blank=True, null=True)
    degree = models.IntegerField(db_column='Degree', blank=True, null=True)
    headship = models.IntegerField(db_column='HeadShip', blank=True, null=True)
    title = models.IntegerField(db_column='Title', blank=True, null=True)
    unitid = models.CharField(db_column='UnitID',
                              max_length=30,
                              blank=True,
                              null=True)
    unitname = models.CharField(db_column='UnitName',
                                max_length=100,
                                blank=True,
                                null=True)
    address = models.CharField(db_column='Address',
                               max_length=100,
                               blank=True,
                               null=True)
    postalcode = models.CharField(db_column='Postalcode',
                                  max_length=10,
                                  blank=True,
                                  null=True)
    tel = models.CharField(db_column='Tel',
                           max_length=30,
                           blank=True,
                           null=True)
    email = models.CharField(db_column='EMail',
                             max_length=50,
                             blank=True,
                             null=True)
    registerdate = models.DateTimeField(db_column='RegisterDate',
                                        blank=True,
                                        null=True)
    operatorid = models.CharField(db_column='OperatorID',
                                  max_length=20,
                                  blank=True,
                                  null=True)
    remark = models.CharField(db_column='Remark',
                              max_length=200,
                              blank=True,
                              null=True)
    birthday = models.DateTimeField(db_column='BirthDay',
                                    blank=True,
                                    null=True)
    barcode = models.CharField(db_column='Barcode',
                               max_length=20,
                               blank=True,
                               null=True)
    startdate = models.DateTimeField(db_column='StartDate',
                                     blank=True,
                                     null=True)
    enddate = models.DateTimeField(db_column='EndDate', blank=True, null=True)
    status = models.IntegerField(db_column='Status', blank=True, null=True)
    memberunitid = models.IntegerField(db_column='MemberUnitID',
                                       blank=True,
                                       null=True)
    libcardtype = models.IntegerField(db_column='LibCardType',
                                      blank=True,
                                      null=True)
    updatedate = models.DateTimeField(db_column='UpdateDate',
                                      blank=True,
                                      null=True)
    updateuser = models.CharField(db_column='UpdateUser',
                                  max_length=20,
                                  blank=True,
                                  null=True)
    updateunitid = models.IntegerField(db_column='UpdateUnitID',
                                       blank=True,
                                       null=True)
    password = models.CharField(db_column='Password',
                                max_length=30,
                                blank=True,
                                null=True)
    deposit = models.DecimalField(db_column='Deposit',
                                  max_digits=19,
                                  decimal_places=4,
                                  blank=True,
                                  null=True)
    debt = models.DecimalField(db_column='Debt',
                               max_digits=19,
                               decimal_places=4,
                               blank=True,
                               null=True)
    inilibcardtype = models.IntegerField(db_column='IniLibcardType',
                                         blank=True,
                                         null=True)
    curlend = models.IntegerField(db_column='CurLend', blank=True, null=True)
    wechatid = models.CharField(db_column='WeChatID',
                                max_length=50,
                                blank=True,
                                null=True)
    wechatnickname = models.CharField(db_column='WeChatNickName',
                                      max_length=50,
                                      blank=True,
                                      null=True)

    class Meta:
        managed = False
        db_table = 'Readers'


class BookInfo(models.Model):
    """
    记录书的信息
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
    pages = models.CharField("页数",
                             db_column='Pages',
                             max_length=100,
                             blank=True,
                             null=True)

    # 以下为无关数据
    reqno = models.CharField(db_column='ReqNo',
                             max_length=254,
                             blank=True,
                             null=True)
    imageurl = models.CharField(db_column='ImageUrl',
                                max_length=500,
                                blank=True,
                                null=True)
    authorno = models.CharField(db_column='AuthorNo',
                                max_length=254,
                                blank=True,
                                null=True)
    batchno = models.CharField(db_column='BatchNo',
                               max_length=20,
                               blank=True,
                               null=True)

    class Meta:
        managed = False
        db_table = 'CircMarc'


# * 下面的表暂时不需要使用

# class Alllibrary(models.Model):
#     id = models.AutoField(db_column='ID', primary_key=True)
#     name = models.CharField(db_column='Name', max_length=254)
#     enname = models.CharField(db_column='EnName',
#                               max_length=254,
#                               blank=True,
#                               null=True)
#     code = models.CharField(db_column='Code',
#                             max_length=8,
#                             blank=True,
#                             null=True)
#     superiorid = models.IntegerField(db_column='SuperiorID')
#     address = models.CharField(db_column='Address',
#                                max_length=50,
#                                blank=True,
#                                null=True)
#     postcode = models.CharField(db_column='PostCode',
#                                 max_length=8,
#                                 blank=True,
#                                 null=True)
#     tel = models.CharField(db_column='Tel',
#                            max_length=16,
#                            blank=True,
#                            null=True)
#     fax = models.CharField(db_column='Fax',
#                            max_length=16,
#                            blank=True,
#                            null=True)
#     email = models.CharField(db_column='EMail',
#                              max_length=30,
#                              blank=True,
#                              null=True)
#     mainip = models.CharField(db_column='MainIP',
#                               max_length=20,
#                               blank=True,
#                               null=True)
#     mainport = models.IntegerField(db_column='MainPort', blank=True, null=True)
#     secondip = models.CharField(db_column='SecondIP',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)
#     secondport = models.IntegerField(db_column='SecondPort',
#                                      blank=True,
#                                      null=True)
#     rightword1 = models.IntegerField(db_column='RightWord1',
#                                      blank=True,
#                                      null=True)
#     rightword2 = models.IntegerField(db_column='RightWord2',
#                                      blank=True,
#                                      null=True)
#     opid = models.CharField(db_column='OpID', max_length=12)
#     opdate = models.DateTimeField(db_column='OpDate', blank=True, null=True)
#     webip = models.CharField(db_column='WebIP',
#                              max_length=20,
#                              blank=True,
#                              null=True)
#     webport = models.IntegerField(db_column='WebPort', blank=True, null=True)
#     memberlevel = models.IntegerField(db_column='MemberLevel')

#     class Meta:
#         managed = False
#         db_table = 'ALLLibrary'

# class Acnthist(models.Model):
#     id = models.AutoField(db_column='ID', primary_key=True)
#     readerid = models.IntegerField(db_column='ReaderID')
#     sumr = models.DecimalField(db_column='SumR',
#                                max_digits=19,
#                                decimal_places=4)
#     type = models.IntegerField(db_column='Type')
#     total = models.DecimalField(db_column='Total',
#                                 max_digits=19,
#                                 decimal_places=4)
#     opid = models.CharField(db_column='OpID',
#                             max_length=50,
#                             blank=True,
#                             null=True)
#     dealdate = models.DateTimeField(db_column='DealDate',
#                                     blank=True,
#                                     null=True)
#     memberunitid = models.IntegerField(db_column='MemberUnitID',
#                                        blank=True,
#                                        null=True)
#     ysunitid = models.IntegerField(db_column='YSUnitID', blank=True, null=True)
#     cashflag = models.IntegerField(db_column='CashFlag', blank=True, null=True)
#     lenddate = models.DateTimeField(db_column='LendDate',
#                                     blank=True,
#                                     null=True)
#     duedate = models.DateTimeField(db_column='DueDate', blank=True, null=True)
#     retdate = models.DateTimeField(db_column='RetDate', blank=True, null=True)
#     barcode = models.CharField(db_column='Barcode',
#                                max_length=30,
#                                blank=True,
#                                null=True)
#     location = models.CharField(db_column='Location',
#                                 max_length=100,
#                                 blank=True,
#                                 null=True)
#     accountno = models.CharField(db_column='AccountNo',
#                                  max_length=50,
#                                  blank=True,
#                                  null=True)
#     accountremark = models.CharField(db_column='AccountRemark',
#                                      max_length=200,
#                                      blank=True,
#                                      null=True)
#     billno = models.CharField(db_column='BillNo',
#                               max_length=50,
#                               blank=True,
#                               null=True)
#     actualmoney = models.DecimalField(db_column='ActualMoney',
#                                       max_digits=19,
#                                       decimal_places=4,
#                                       blank=True,
#                                       null=True)
#     paydate = models.DateTimeField(db_column='PayDate', blank=True, null=True)
#     payflag = models.CharField(db_column='PayFlag',
#                                max_length=1,
#                                blank=True,
#                                null=True)
#     paystation = models.CharField(db_column='PayStation',
#                                   max_length=100,
#                                   blank=True,
#                                   null=True)
#     payopid = models.CharField(db_column='PayOpID',
#                                max_length=50,
#                                blank=True,
#                                null=True)
#     remark = models.CharField(db_column='Remark',
#                               max_length=200,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'AcntHist'

# class Acntitem(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)
#     iotype = models.IntegerField(db_column='IOType', blank=True, null=True)
#     vflag = models.CharField(db_column='VFlag',
#                              max_length=1,
#                              blank=True,
#                              null=True)

#     class Meta:
#         managed = False
#         db_table = 'AcntItem'

# class Acntlist(models.Model):
#     id = models.AutoField(db_column='ID', primary_key=True)
#     accountno = models.CharField(db_column='AccountNo',
#                                  max_length=50,
#                                  blank=True,
#                                  null=True)
#     accountremark = models.CharField(db_column='AccountRemark',
#                                      max_length=200,
#                                      blank=True,
#                                      null=True)
#     readerid = models.IntegerField(db_column='ReaderID')
#     sumr = models.DecimalField(db_column='SumR',
#                                max_digits=19,
#                                decimal_places=4)
#     type = models.IntegerField(db_column='Type')
#     total = models.DecimalField(db_column='Total',
#                                 max_digits=19,
#                                 decimal_places=4)
#     opid = models.CharField(db_column='OpID',
#                             max_length=50,
#                             blank=True,
#                             null=True)
#     dealdate = models.DateTimeField(db_column='DealDate',
#                                     blank=True,
#                                     null=True)
#     memberunitid = models.IntegerField(db_column='MemberUnitID',
#                                        blank=True,
#                                        null=True)
#     ysunitid = models.IntegerField(db_column='YSUnitID', blank=True, null=True)
#     cashflag = models.IntegerField(db_column='CashFlag', blank=True, null=True)
#     lenddate = models.DateTimeField(db_column='LendDate',
#                                     blank=True,
#                                     null=True)
#     duedate = models.DateTimeField(db_column='DueDate', blank=True, null=True)
#     retdate = models.DateTimeField(db_column='RetDate', blank=True, null=True)
#     barcode = models.CharField(db_column='Barcode',
#                                max_length=30,
#                                blank=True,
#                                null=True)
#     location = models.CharField(db_column='Location',
#                                 max_length=100,
#                                 blank=True,
#                                 null=True)
#     billno = models.CharField(db_column='BillNo',
#                               max_length=50,
#                               blank=True,
#                               null=True)
#     actualmoney = models.DecimalField(db_column='ActualMoney',
#                                       max_digits=19,
#                                       decimal_places=4,
#                                       blank=True,
#                                       null=True)
#     paydate = models.DateTimeField(db_column='PayDate', blank=True, null=True)
#     paystation = models.CharField(db_column='PayStation',
#                                   max_length=100,
#                                   blank=True,
#                                   null=True)
#     payflag = models.CharField(db_column='PayFlag',
#                                max_length=1,
#                                blank=True,
#                                null=True)
#     payopid = models.CharField(db_column='PayOpID',
#                                max_length=50,
#                                blank=True,
#                                null=True)
#     remark = models.CharField(db_column='Remark',
#                               max_length=200,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'AcntList'

# class Bmdb(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     name = models.CharField(db_column='Name', max_length=254)
#     classfield = models.IntegerField(db_column='ClassField',
#                                      blank=True,
#                                      null=True)
#     classsfield = models.IntegerField(db_column='ClassSField',
#                                       blank=True,
#                                       null=True)
#     fieldno = models.IntegerField(db_column='FieldNo', blank=True, null=True)
#     enname = models.CharField(db_column='EnName',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'BMDB'

# class Bmindex1003(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'BMIndex1003'

# class Bmindex1018(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'BMIndex1018'

# class Bmindex20(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'BMIndex20'

# class Bmindex21(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'BMIndex21'

# class Bmindex31(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'BMIndex31'

# class Bmindex4(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'BMIndex4'

# class Bmindex53(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'BMIndex53'

# class Bmindex7(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'BMIndex7'

# class Bminforetrieval(models.Model):
#     indexid = models.IntegerField(db_column='IndexID', primary_key=True)
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField')
#     marctype = models.IntegerField(db_column='MarcType')
#     dbid = models.IntegerField(db_column='DBID')

#     class Meta:
#         managed = False
#         db_table = 'BMInfoRetrieval'
#         unique_together = (('indexid', 'field', 'subfield', 'marctype',
#                             'dbid'), )

# class Bmmarc(models.Model):
#     marcid = models.IntegerField(db_column='MarcID', primary_key=True)
#     content = models.TextField(db_column='Content', blank=True, null=True)
#     marctype = models.IntegerField(db_column='MarcType')
#     dbid = models.IntegerField(db_column='DBID')
#     indate = models.DateTimeField(db_column='InDate', blank=True, null=True)
#     state = models.IntegerField(db_column='State', blank=True, null=True)
#     classno = models.CharField(db_column='ClassNo',
#                                max_length=50,
#                                blank=True,
#                                null=True)

#     class Meta:
#         managed = False
#         db_table = 'BMMarc'

# class Bmmodifylog(models.Model):
#     dbid = models.IntegerField(db_column='DBID', primary_key=True)
#     marcid = models.IntegerField(db_column='MarcID')
#     operator = models.CharField(db_column='Operator', max_length=20)
#     inittime = models.DateTimeField(db_column='InitTime')
#     comments = models.CharField(db_column='Comments',
#                                 max_length=100,
#                                 blank=True,
#                                 null=True)

#     class Meta:
#         managed = False
#         db_table = 'BMModifyLog'
#         unique_together = (('dbid', 'marcid', 'operator'), )

# class Bmoperate(models.Model):
#     intime = models.DateTimeField(db_column='InTime', primary_key=True)
#     optype = models.IntegerField(db_column='OPType')
#     operater = models.CharField(db_column='Operater', max_length=20)
#     content = models.CharField(db_column='Content',
#                                max_length=500,
#                                blank=True,
#                                null=True)

#     class Meta:
#         managed = False
#         db_table = 'BMOperate'
#         unique_together = (('intime', 'optype', 'operater'), )

# class Bmoperation(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'BMOperation'

# class Bmsubmitcat(models.Model):
#     subfrmno = models.IntegerField(db_column='SubFrmNo', primary_key=True)
#     storeplace = models.IntegerField(db_column='StorePlace')
#     submittm = models.DateTimeField(db_column='SubmitTm',
#                                     blank=True,
#                                     null=True)
#     submiter = models.CharField(db_column='Submiter',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)
#     state = models.IntegerField(db_column='State', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'BMSubmitCat'

# class Bmsubmitcatdetail(models.Model):
#     subfrmno = models.IntegerField(db_column='SubFrmNo')
#     serialno = models.IntegerField(db_column='SerialNo', primary_key=True)
#     handler = models.CharField(db_column='Handler',
#                                max_length=20,
#                                blank=True,
#                                null=True)
#     received = models.IntegerField(db_column='Received', blank=True, null=True)
#     receiver = models.CharField(db_column='Receiver',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)

#     class Meta:
#         managed = False
#         db_table = 'BMSubmitCatDetail'

# class Bmtemplate(models.Model):
#     tpid = models.IntegerField(db_column='TPID', primary_key=True)
#     gname = models.CharField(db_column='GName', max_length=50)
#     content = models.CharField(db_column='Content', max_length=2000)
#     marctype = models.IntegerField(db_column='MarcType', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'BMTemplate'

# class Cfaccept(models.Model):
#     rid = models.IntegerField(db_column='RID', primary_key=True)
#     batchno = models.CharField(db_column='BatchNo',
#                                max_length=20,
#                                blank=True,
#                                null=True)
#     ordersource = models.IntegerField(db_column='OrderSource')
#     ordernum = models.IntegerField(db_column='OrderNum', blank=True, null=True)
#     marcid = models.IntegerField(db_column='MarcID')
#     issuer = models.IntegerField(db_column='Issuer', blank=True, null=True)
#     setnum = models.IntegerField(db_column='SetNum', blank=True, null=True)
#     volnum = models.IntegerField(db_column='VolNum', blank=True, null=True)
#     setprice = models.DecimalField(db_column='SetPrice',
#                                    max_digits=19,
#                                    decimal_places=4,
#                                    blank=True,
#                                    null=True)
#     volprice = models.DecimalField(db_column='VolPrice',
#                                    max_digits=19,
#                                    decimal_places=4,
#                                    blank=True,
#                                    null=True)
#     coin = models.IntegerField(db_column='Coin', blank=True, null=True)
#     indate = models.DateTimeField(db_column='InDate', blank=True, null=True)
#     operater = models.CharField(db_column='Operater',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFAccept'

# class Cfadvice(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     marcid = models.IntegerField(db_column='MarcID', blank=True, null=True)
#     content = models.CharField(db_column='Content',
#                                max_length=254,
#                                blank=True,
#                                null=True)
#     indate = models.DateTimeField(db_column='InDate', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFAdvice'

# class Cfback(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     rid = models.IntegerField(db_column='RID', blank=True, null=True)
#     issuer = models.IntegerField(db_column='Issuer', blank=True, null=True)
#     marcid = models.IntegerField(db_column='MarcID', blank=True, null=True)
#     setnum = models.IntegerField(db_column='SetNum', blank=True, null=True)
#     volnum = models.IntegerField(db_column='VolNum', blank=True, null=True)
#     indate = models.DateTimeField(db_column='InDate', blank=True, null=True)
#     reason = models.CharField(db_column='Reason',
#                               max_length=254,
#                               blank=True,
#                               null=True)
#     opid = models.CharField(db_column='OPID',
#                             max_length=20,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFBack'

# class Cfbackaccept(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFBackAccept'

# class Cfdb(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     name = models.CharField(db_column='Name', max_length=254)
#     classfield = models.IntegerField(db_column='ClassField',
#                                      blank=True,
#                                      null=True)
#     classsfield = models.IntegerField(db_column='ClassSField',
#                                       blank=True,
#                                       null=True)
#     fieldno = models.IntegerField(db_column='FieldNo', blank=True, null=True)
#     enname = models.CharField(db_column='EnName',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFDB'

# class Cfindex1003(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'CFIndex1003'

# class Cfindex1018(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'CFIndex1018'

# class Cfindex20(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'CFIndex20'

# class Cfindex21(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'CFIndex21'

# class Cfindex31(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'CFIndex31'

# class Cfindex4(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'CFIndex4'

# class Cfindex53(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'CFIndex53'

# class Cfindex7(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'CFIndex7'

# class Cfinforetrieval(models.Model):
#     indexid = models.IntegerField(db_column='IndexID', primary_key=True)
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField')
#     marctype = models.IntegerField(db_column='MarcType')
#     dbid = models.IntegerField(db_column='DBID')

#     class Meta:
#         managed = False
#         db_table = 'CFInfoRetrieval'
#         unique_together = (('indexid', 'field', 'subfield', 'marctype',
#                             'dbid'), )

# class Cfmarc(models.Model):
#     marcid = models.IntegerField(db_column='MarcID', primary_key=True)
#     content = models.TextField(db_column='Content', blank=True, null=True)
#     source = models.IntegerField(db_column='Source', blank=True, null=True)
#     marctype = models.IntegerField(db_column='MarcType')
#     dbid = models.IntegerField(db_column='DBID')
#     indate = models.DateTimeField(db_column='InDate', blank=True, null=True)
#     classno = models.CharField(db_column='ClassNo',
#                                max_length=50,
#                                blank=True,
#                                null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFMarc'

# class Cfoperate(models.Model):
#     intime = models.DateTimeField(db_column='InTime', primary_key=True)
#     optype = models.IntegerField(db_column='OPType')
#     operater = models.CharField(db_column='Operater', max_length=20)
#     content = models.CharField(db_column='Content',
#                                max_length=500,
#                                blank=True,
#                                null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFOperate'
#         unique_together = (('intime', 'optype', 'operater'), )

# class Cfoperation(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFOperation'

# class Cforder(models.Model):
#     ordernum = models.IntegerField(db_column='OrderNum', primary_key=True)
#     ordername = models.CharField(db_column='OrderName',
#                                  max_length=100,
#                                  blank=True,
#                                  null=True)
#     issuer = models.IntegerField(db_column='Issuer', blank=True, null=True)
#     ordertm = models.DateTimeField(db_column='OrderTM', blank=True, null=True)
#     operater = models.CharField(db_column='Operater',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFOrder'

# class Cforderdetail(models.Model):
#     ordernum = models.IntegerField(db_column='OrderNum')
#     marcid = models.IntegerField(db_column='MarcID')
#     reqnum = models.CharField(db_column='ReqNum',
#                               max_length=50,
#                               blank=True,
#                               null=True)
#     setnum = models.IntegerField(db_column='SetNum')
#     volnum = models.IntegerField(db_column='VolNum')
#     price = models.DecimalField(db_column='Price',
#                                 max_digits=19,
#                                 decimal_places=4)
#     volprice = models.DecimalField(db_column='VolPrice',
#                                    max_digits=19,
#                                    decimal_places=4,
#                                    blank=True,
#                                    null=True)
#     coin = models.IntegerField(db_column='Coin', blank=True, null=True)
#     pubdate = models.DateTimeField(db_column='PubDate', blank=True, null=True)
#     arrivedset = models.IntegerField(db_column='ArrivedSet',
#                                      blank=True,
#                                      null=True)
#     arrivedvol = models.IntegerField(db_column='ArrivedVol',
#                                      blank=True,
#                                      null=True)
#     askcount = models.IntegerField(db_column='AskCount', blank=True, null=True)
#     askdate = models.DateTimeField(db_column='AskDate', blank=True, null=True)
#     prearrset = models.IntegerField(db_column='PreArrSet',
#                                     blank=True,
#                                     null=True)
#     prearrvol = models.IntegerField(db_column='PreArrVol',
#                                     blank=True,
#                                     null=True)
#     id = models.AutoField(db_column='ID', primary_key=True)

#     class Meta:
#         managed = False
#         db_table = 'CFOrderDetail'
#         unique_together = (('ordernum', 'marcid'), )

# class Cforderpreaccept(models.Model):
#     ordernum = models.IntegerField(db_column='OrderNum')
#     premarcid = models.IntegerField(db_column='PreMarcID')
#     setnum = models.IntegerField(db_column='SetNum')
#     volnum = models.IntegerField(db_column='VolNum')
#     setarrived = models.IntegerField(db_column='SetArrived')
#     volarrived = models.IntegerField(db_column='VolArrived')

#     class Meta:
#         managed = False
#         db_table = 'CFOrderPreAccept'

# class Cforderpreacceptlog(models.Model):
#     logid = models.AutoField(db_column='LogID', primary_key=True)
#     id = models.IntegerField(db_column='ID')
#     setnum = models.IntegerField(db_column='SetNum', blank=True, null=True)
#     volnum = models.IntegerField(db_column='VolNum', blank=True, null=True)
#     opdate = models.DateTimeField(db_column='OPDate', blank=True, null=True)
#     opid = models.CharField(db_column='OPID',
#                             max_length=20,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFOrderPreAcceptLog'

# class Cfriches(models.Model):
#     serialno = models.IntegerField(db_column='SerialNo', primary_key=True)
#     barcode = models.CharField(db_column='BarCode',
#                                unique=True,
#                                max_length=20,
#                                blank=True,
#                                null=True)
#     marcid = models.IntegerField(db_column='MarcID', blank=True, null=True)
#     batchno = models.CharField(db_column='BatchNo',
#                                max_length=20,
#                                blank=True,
#                                null=True)
#     source = models.IntegerField(db_column='Source', blank=True, null=True)
#     volprice = models.DecimalField(db_column='VolPrice',
#                                    max_digits=19,
#                                    decimal_places=4,
#                                    blank=True,
#                                    null=True)
#     coin = models.IntegerField(db_column='Coin', blank=True, null=True)
#     rid = models.IntegerField(db_column='RID', blank=True, null=True)
#     fjmemo = models.CharField(db_column='FJMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFRiches'

# class Cfsubmit(models.Model):
#     submitno = models.IntegerField(db_column='SubmitNo', primary_key=True)
#     indate = models.DateTimeField(db_column='InDate', blank=True, null=True)
#     operater = models.CharField(db_column='Operater',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)
#     state = models.IntegerField(db_column='State', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFSubmit'

# class Cfsubmitdetail(models.Model):
#     submitno = models.IntegerField(db_column='SubmitNo')
#     serialno = models.IntegerField(db_column='SerialNo', primary_key=True)
#     state = models.IntegerField(db_column='State')
#     receiver = models.CharField(db_column='Receiver',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)

#     class Meta:
#         managed = False
#         db_table = 'CFSubmitDetail'

# class Chargeaction(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'ChargeAction'

# class Chargedetail(models.Model):
#     actionid = models.IntegerField(db_column='ActionID')
#     readercardtype = models.IntegerField(db_column='ReaderCardType')
#     payitemid = models.IntegerField(db_column='PayItemID')
#     payitemsum = models.DecimalField(db_column='PayItemSum',
#                                      max_digits=19,
#                                      decimal_places=4)
#     id = models.IntegerField(db_column='ID')

#     class Meta:
#         managed = False
#         db_table = 'ChargeDetail'

# class Cirgpdetail(models.Model):
#     groupid = models.IntegerField(db_column='GroupID', primary_key=True)
#     lttype = models.IntegerField(db_column='LTType')

#     class Meta:
#         managed = False
#         db_table = 'CirGpDetail'
#         unique_together = (('groupid', 'lttype'), )

# class Cirtype(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)
#     fine = models.DecimalField(db_column='Fine',
#                                max_digits=19,
#                                decimal_places=4,
#                                blank=True,
#                                null=True)
#     maxfine = models.DecimalField(db_column='MaxFine',
#                                   max_digits=19,
#                                   decimal_places=4,
#                                   blank=True,
#                                   null=True)

#     class Meta:
#         managed = False
#         db_table = 'CirType'

# class Cirtypegroup(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'CirTypeGroup'

# class Cirtypegroupdetail(models.Model):
#     groupid = models.IntegerField(db_column='GroupID', primary_key=True)
#     lttype = models.IntegerField(db_column='LTType')

#     class Meta:
#         managed = False
#         db_table = 'CirTypeGroupDetail'
#         unique_together = (('groupid', 'lttype'), )

# class Circoptinfo(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'CircOptInfo'

# class Circoptlog(models.Model):
#     intime = models.DateTimeField(db_column='InTime')
#     optype = models.IntegerField(db_column='OpType')
#     operater = models.CharField(db_column='Operater', max_length=20)
#     content = models.CharField(db_column='Content',
#                                max_length=500,
#                                blank=True,
#                                null=True)

#     class Meta:
#         managed = False
#         db_table = 'CircOptLog'

# class Circstat(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'CircStat'

# class Classinfo(models.Model):
#     ciindex = models.CharField(db_column='CIIndex', max_length=10)
#     cititle = models.CharField(db_column='CITitle', max_length=100)
#     citype = models.CharField(db_column='CIType', max_length=20)

#     class Meta:
#         managed = False
#         db_table = 'ClassInfo'

# class Classnocount(models.Model):
#     classno = models.CharField(db_column='ClassNo',
#                                max_length=50,
#                                blank=True,
#                                null=True)
#     count = models.IntegerField(db_column='Count', blank=True, null=True)
#     qkcount = models.IntegerField(db_column='QKCount', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'ClassNoCount'

# class Closeday(models.Model):
#     dateday = models.DateTimeField(db_column='DateDay', primary_key=True)

#     class Meta:
#         managed = False
#         db_table = 'CloseDay'

# class Closeweek(models.Model):
#     weekid = models.IntegerField(db_column='WeekID')

#     class Meta:
#         managed = False
#         db_table = 'CloseWeek'

# class Comments(models.Model):
#     id = models.IntegerField(db_column='ID')
#     marcid = models.IntegerField(db_column='MarcID')
#     parentid = models.IntegerField(db_column='ParentID', blank=True, null=True)
#     content = models.CharField(db_column='Content',
#                                max_length=254,
#                                blank=True,
#                                null=True)
#     category = models.CharField(db_column='Category',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)
#     count = models.IntegerField(db_column='Count', blank=True, null=True)
#     readerid = models.IntegerField(db_column='ReaderID', blank=True, null=True)
#     commenttime = models.DateTimeField(db_column='CommentTime',
#                                        blank=True,
#                                        null=True)

#     class Meta:
#         managed = False
#         db_table = 'Comments'

# class Damagelevel(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'DamageLevel'

# class Fourhorn(models.Model):
#     name = models.CharField(db_column='Name', primary_key=True, max_length=10)
#     namecode = models.CharField(db_column='NameCode', max_length=4)
#     addtime = models.DateTimeField(db_column='AddTime')

#     class Meta:
#         managed = False
#         db_table = 'FourHorn'

# class Gcser(models.Model):
#     date = models.CharField(max_length=100, blank=True, null=True)
#     username = models.CharField(max_length=100, blank=True, null=True)
#     serno = models.CharField(db_column='SERNO',
#                              max_length=1024,
#                              blank=True,
#                              null=True)

#     class Meta:
#         managed = False
#         db_table = 'GCSER'

# class Gnltmarc(models.Model):
#     marcid = models.IntegerField(db_column='MarcID', primary_key=True)
#     title = models.CharField(db_column='Title',
#                              max_length=500,
#                              blank=True,
#                              null=True)
#     reqno = models.CharField(db_column='ReqNo',
#                              max_length=254,
#                              blank=True,
#                              null=True)
#     author = models.CharField(db_column='Author',
#                               max_length=254,
#                               blank=True,
#                               null=True)
#     publisher = models.CharField(db_column='Publisher',
#                                  max_length=254,
#                                  blank=True,
#                                  null=True)
#     price = models.CharField(db_column='Price',
#                              max_length=254,
#                              blank=True,
#                              null=True)

#     class Meta:
#         managed = False
#         db_table = 'GNLTMarc'

# class Gnriches(models.Model):
#     serialno = models.IntegerField(db_column='SerialNo', primary_key=True)
#     barcode = models.CharField(db_column='BarCode', unique=True, max_length=20)
#     marcid = models.IntegerField(db_column='MarcID')
#     source = models.IntegerField(db_column='Source', blank=True, null=True)
#     coin = models.IntegerField(db_column='Coin', blank=True, null=True)
#     price = models.DecimalField(db_column='Price',
#                                 max_digits=19,
#                                 decimal_places=4,
#                                 blank=True,
#                                 null=True)
#     sflag = models.IntegerField(db_column='SFlag', blank=True, null=True)
#     rid = models.IntegerField(db_column='RID', blank=True, null=True)
#     memberunitid = models.IntegerField(db_column='MemberUnitID',
#                                        blank=True,
#                                        null=True)
#     place = models.IntegerField(db_column='Place', blank=True, null=True)
#     lttype = models.IntegerField(db_column='LTType', blank=True, null=True)
#     pslevel = models.IntegerField(db_column='PSLevel', blank=True, null=True)
#     pjh = models.CharField(db_column='PJH',
#                            max_length=50,
#                            blank=True,
#                            null=True)
#     inbatch = models.IntegerField(db_column='InBatch', blank=True, null=True)
#     intime = models.DateTimeField(db_column='InTime', blank=True, null=True)
#     ltsign = models.IntegerField(db_column='LTSign', blank=True, null=True)
#     ltstatus = models.IntegerField(db_column='LTStatus', blank=True, null=True)
#     yysign = models.IntegerField(db_column='YYSign', blank=True, null=True)
#     opid = models.CharField(db_column='OPID',
#                             max_length=20,
#                             blank=True,
#                             null=True)
#     fjmemo = models.CharField(db_column='FJMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'GNRiches'

# class Holdhist(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     holdno = models.CharField(db_column='HoldNo',
#                               max_length=20,
#                               blank=True,
#                               null=True)
#     readerid = models.IntegerField(db_column='ReaderID')
#     memberunitid = models.IntegerField(db_column='MemberUnitID',
#                                        blank=True,
#                                        null=True)
#     marcid = models.IntegerField(db_column='MarcID')
#     place = models.IntegerField(db_column='Place', blank=True, null=True)
#     requiredate = models.DateTimeField(db_column='RequireDate')
#     orderdate = models.DateTimeField(db_column='OrderDate')
#     pressdate = models.DateTimeField(db_column='PressDate',
#                                      blank=True,
#                                      null=True)
#     opid = models.CharField(db_column='OpID', max_length=20)
#     notify = models.IntegerField(db_column='Notify')
#     tel = models.CharField(db_column='Tel',
#                            max_length=30,
#                            blank=True,
#                            null=True)
#     fax = models.CharField(db_column='Fax',
#                            max_length=30,
#                            blank=True,
#                            null=True)
#     email = models.CharField(db_column='EMail',
#                              max_length=50,
#                              blank=True,
#                              null=True)
#     address = models.CharField(db_column='Address',
#                                max_length=100,
#                                blank=True,
#                                null=True)
#     postcode = models.CharField(db_column='Postcode',
#                                 max_length=15,
#                                 blank=True,
#                                 null=True)
#     queue = models.IntegerField(db_column='Queue', blank=True, null=True)
#     status = models.IntegerField(db_column='Status')
#     remark = models.CharField(db_column='Remark',
#                               max_length=200,
#                               blank=True,
#                               null=True)
#     presstime = models.IntegerField(db_column='PressTime',
#                                     blank=True,
#                                     null=True)
#     barcode = models.CharField(db_column='Barcode',
#                                max_length=20,
#                                blank=True,
#                                null=True)
#     arrivedate = models.DateTimeField(db_column='ArriveDate',
#                                       blank=True,
#                                       null=True)
#     arriveflag = models.CharField(db_column='ArriveFlag',
#                                   max_length=1,
#                                   blank=True,
#                                   null=True)
#     emailsenddate = models.DateTimeField(db_column='EmailSendDate',
#                                          blank=True,
#                                          null=True)
#     emailsendflag = models.CharField(db_column='EmailSendFlag',
#                                      max_length=1,
#                                      blank=True,
#                                      null=True)
#     noticesenddate = models.DateTimeField(db_column='NoticeSendDate',
#                                           blank=True,
#                                           null=True)
#     noticeno = models.CharField(db_column='NoticeNo',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)
#     keependdate = models.DateTimeField(db_column='KeepEndDate',
#                                        blank=True,
#                                        null=True)
#     arrivedealflag = models.CharField(db_column='ArriveDealFlag',
#                                       max_length=1,
#                                       blank=True,
#                                       null=True)
#     pickuplocation = models.CharField(db_column='PickupLocation',
#                                       max_length=100,
#                                       blank=True,
#                                       null=True)
#     pickupflag = models.CharField(db_column='PickupFlag',
#                                   max_length=1,
#                                   blank=True,
#                                   null=True)
#     pickupdate = models.DateTimeField(db_column='PickupDate',
#                                       blank=True,
#                                       null=True)
#     workstation = models.CharField(db_column='WorkStation',
#                                    max_length=100,
#                                    blank=True,
#                                    null=True)

#     class Meta:
#         managed = False
#         db_table = 'HoldHist'

# class Holdlist(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     holdno = models.CharField(db_column='HoldNo',
#                               max_length=20,
#                               blank=True,
#                               null=True)
#     readerid = models.IntegerField(db_column='ReaderID')
#     memberunitid = models.IntegerField(db_column='MemberUnitID',
#                                        blank=True,
#                                        null=True)
#     marcid = models.IntegerField(db_column='MarcID')
#     place = models.IntegerField(db_column='Place', blank=True, null=True)
#     requiredate = models.DateTimeField(db_column='RequireDate')
#     orderdate = models.DateTimeField(db_column='OrderDate')
#     pressdate = models.DateTimeField(db_column='PressDate',
#                                      blank=True,
#                                      null=True)
#     opid = models.CharField(db_column='OpID', max_length=20)
#     notify = models.IntegerField(db_column='Notify')
#     tel = models.CharField(db_column='Tel',
#                            max_length=30,
#                            blank=True,
#                            null=True)
#     fax = models.CharField(db_column='Fax',
#                            max_length=30,
#                            blank=True,
#                            null=True)
#     email = models.CharField(db_column='EMail',
#                              max_length=50,
#                              blank=True,
#                              null=True)
#     address = models.CharField(db_column='Address',
#                                max_length=100,
#                                blank=True,
#                                null=True)
#     postcode = models.CharField(db_column='Postcode',
#                                 max_length=15,
#                                 blank=True,
#                                 null=True)
#     queue = models.IntegerField(db_column='Queue', blank=True, null=True)
#     status = models.IntegerField(db_column='Status')
#     remark = models.CharField(db_column='Remark',
#                               max_length=200,
#                               blank=True,
#                               null=True)
#     presstime = models.IntegerField(db_column='PressTime',
#                                     blank=True,
#                                     null=True)
#     barcode = models.CharField(db_column='Barcode',
#                                max_length=20,
#                                blank=True,
#                                null=True)
#     arrivedate = models.DateTimeField(db_column='ArriveDate',
#                                       blank=True,
#                                       null=True)
#     arriveflag = models.CharField(db_column='ArriveFlag',
#                                   max_length=1,
#                                   blank=True,
#                                   null=True)
#     emailsenddate = models.DateTimeField(db_column='EmailSendDate',
#                                          blank=True,
#                                          null=True)
#     emailsendflag = models.CharField(db_column='EmailSendFlag',
#                                      max_length=1,
#                                      blank=True,
#                                      null=True)
#     noticesenddate = models.DateTimeField(db_column='NoticeSendDate',
#                                           blank=True,
#                                           null=True)
#     noticeno = models.CharField(db_column='NoticeNo',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)
#     keependdate = models.DateTimeField(db_column='KeepEndDate',
#                                        blank=True,
#                                        null=True)
#     arrivedealflag = models.CharField(db_column='ArriveDealFlag',
#                                       max_length=1,
#                                       blank=True,
#                                       null=True)
#     pickuplocation = models.CharField(db_column='PickupLocation',
#                                       max_length=100,
#                                       blank=True,
#                                       null=True)
#     pickupflag = models.CharField(db_column='PickupFlag',
#                                   max_length=1,
#                                   blank=True,
#                                   null=True)
#     pickupdate = models.DateTimeField(db_column='PickupDate',
#                                       blank=True,
#                                       null=True)
#     workstation = models.CharField(db_column='WorkStation',
#                                    max_length=100,
#                                    blank=True,
#                                    null=True)

#     class Meta:
#         managed = False
#         db_table = 'HoldList'

# class Inforetrieval(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     ename = models.CharField(db_column='EName', max_length=254)
#     cname = models.CharField(db_column='CName', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'InfoRetrieval'

# class Issuer(models.Model):
#     issuerid = models.IntegerField(db_column='IssuerID', primary_key=True)
#     gncode = models.CharField(db_column='GNCode',
#                               max_length=20,
#                               blank=True,
#                               null=True)
#     name = models.CharField(db_column='Name', max_length=254)
#     address = models.CharField(db_column='Address',
#                                max_length=254,
#                                blank=True,
#                                null=True)
#     zip = models.CharField(db_column='Zip',
#                            max_length=10,
#                            blank=True,
#                            null=True)
#     connecter = models.CharField(db_column='Connecter',
#                                  max_length=254,
#                                  blank=True,
#                                  null=True)
#     phone = models.CharField(db_column='Phone',
#                              max_length=254,
#                              blank=True,
#                              null=True)
#     fax = models.CharField(db_column='Fax',
#                            max_length=254,
#                            blank=True,
#                            null=True)
#     email = models.CharField(db_column='Email',
#                              max_length=254,
#                              blank=True,
#                              null=True)
#     www = models.CharField(db_column='WWW',
#                            max_length=254,
#                            blank=True,
#                            null=True)
#     bank = models.CharField(db_column='Bank',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     savename = models.CharField(db_column='SaveName',
#                                 max_length=254,
#                                 blank=True,
#                                 null=True)
#     accountno = models.CharField(db_column='AccountNo',
#                                  max_length=254,
#                                  blank=True,
#                                  null=True)
#     mem = models.CharField(db_column='Mem',
#                            max_length=254,
#                            blank=True,
#                            null=True)

#     class Meta:
#         managed = False
#         db_table = 'Issuer'

# class Items(models.Model):
#     serialno = models.IntegerField(db_column='SerialNo', primary_key=True)
#     barcode = models.CharField(db_column='BarCode', unique=True, max_length=20)
#     marcid = models.IntegerField(db_column='MarcID')
#     source = models.IntegerField(db_column='Source', blank=True, null=True)
#     coin = models.IntegerField(db_column='Coin', blank=True, null=True)
#     price = models.FloatField(db_column='Price', blank=True, null=True)
#     sflag = models.IntegerField(db_column='SFlag', blank=True, null=True)
#     rid = models.IntegerField(db_column='RID', blank=True, null=True)
#     memberunitid = models.IntegerField(db_column='MemberUnitID',
#                                        blank=True,
#                                        null=True)
#     place = models.IntegerField(db_column='Place', blank=True, null=True)
#     lttype = models.IntegerField(db_column='LTType', blank=True, null=True)
#     pslevel = models.IntegerField(db_column='PSLevel', blank=True, null=True)
#     pjh = models.CharField(db_column='PJH',
#                            max_length=50,
#                            blank=True,
#                            null=True)
#     inbatch = models.IntegerField(db_column='InBatch', blank=True, null=True)
#     intime = models.DateTimeField(db_column='InTime', blank=True, null=True)
#     ltsign = models.IntegerField(db_column='LTSign', blank=True, null=True)
#     ltstatus = models.IntegerField(db_column='LTStatus', blank=True, null=True)
#     yysign = models.IntegerField(db_column='YYSign', blank=True, null=True)
#     opid = models.CharField(db_column='OPID',
#                             max_length=20,
#                             blank=True,
#                             null=True)
#     fjmemo = models.CharField(db_column='FJMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)
#     bookshelffloorbarcode = models.CharField(db_column='BookshelfFloorBarcode',
#                                              max_length=50,
#                                              blank=True,
#                                              null=True)
#     hfid = models.CharField(db_column='HFID',
#                             max_length=50,
#                             blank=True,
#                             null=True)
#     uhfid = models.CharField(db_column='UHFID',
#                              max_length=50,
#                              blank=True,
#                              null=True)

#     class Meta:
#         managed = False
#         db_table = 'Items'

# class Lstacard(models.Model):
#     lendstation = models.IntegerField(db_column='LendStation',
#                                       primary_key=True)
#     cardtype = models.IntegerField(db_column='CardType')

#     class Meta:
#         managed = False
#         db_table = 'LStaCard'
#         unique_together = (('lendstation', 'cardtype'), )

# class Lstalendplace(models.Model):
#     lendstation = models.IntegerField(db_column='LendStation',
#                                       primary_key=True)
#     place = models.IntegerField(db_column='Place')

#     class Meta:
#         managed = False
#         db_table = 'LStaLendPlace'
#         unique_together = (('lendstation', 'place'), )

# class Lstaretplace(models.Model):
#     lendstation = models.IntegerField(db_column='LendStation',
#                                       primary_key=True)
#     place = models.IntegerField(db_column='Place')

#     class Meta:
#         managed = False
#         db_table = 'LStaRetPlace'
#         unique_together = (('lendstation', 'place'), )

# class Ltabnormallost(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     serialno = models.IntegerField(db_column='SerialNo')
#     reason = models.CharField(db_column='Reason', max_length=100)
#     lostdt = models.DateTimeField(db_column='LostDT')
#     opid = models.CharField(db_column='OpID', max_length=20)

#     class Meta:
#         managed = False
#         db_table = 'LTAbnormallost'

# class Ltbookin(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     serialno = models.IntegerField(db_column='SerialNo')
#     bkbc = models.CharField(db_column='BKBC', max_length=200)
#     outreason = models.IntegerField(db_column='OutReason')
#     inplace = models.IntegerField(db_column='InPlace')
#     opid = models.CharField(db_column='OpID', max_length=20)
#     intime = models.DateTimeField(db_column='InTime', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'LTBookin'

# class Ltbookout(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     serialno = models.IntegerField(db_column='SerialNo')
#     bkbc = models.CharField(db_column='BKBC', max_length=200)
#     outreason = models.IntegerField(db_column='OutReason')
#     outplace = models.IntegerField(db_column='OutPlace')
#     opid = models.CharField(db_column='OpID', max_length=20)
#     outtime = models.DateTimeField(db_column='OutTime', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'LTBookout'

# class Ltdcoperate(models.Model):
#     intime = models.DateTimeField(db_column='InTime', primary_key=True)
#     optype = models.IntegerField(db_column='OpType')
#     operater = models.CharField(db_column='Operater', max_length=20)
#     content = models.CharField(db_column='Content',
#                                max_length=500,
#                                blank=True,
#                                null=True)

#     class Meta:
#         managed = False
#         db_table = 'LTDCOperate'
#         unique_together = (('intime', 'optype', 'operater'), )

# class Ltdcoperation(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'LTDCOperation'

# class Ltmend(models.Model):
#     mendid = models.IntegerField(db_column='MendID', primary_key=True)
#     serialno = models.IntegerField(db_column='SerialNo')
#     pslevel = models.IntegerField(db_column='PSLevel')
#     mendman = models.CharField(db_column='MendMan', max_length=200)
#     menddate = models.DateTimeField(db_column='MendDate')
#     remark = models.CharField(db_column='Remark',
#                               max_length=200,
#                               blank=True,
#                               null=True)
#     opid = models.CharField(db_column='OpID', max_length=20)

#     class Meta:
#         managed = False
#         db_table = 'LTMend'

# class Ltweedout(models.Model):
#     serialno = models.IntegerField(db_column='SerialNo')
#     opid = models.CharField(db_column='OPID',
#                             max_length=20,
#                             blank=True,
#                             null=True)
#     outtm = models.DateTimeField(db_column='OutTM', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'LTWeedout'

# class Langcontrast(models.Model):
#     langcode = models.IntegerField(db_column='LangCode')
#     tablename = models.CharField(db_column='TableName',
#                                  max_length=254,
#                                  blank=True,
#                                  null=True)
#     fieldname = models.CharField(db_column='FieldName',
#                                  max_length=254,
#                                  blank=True,
#                                  null=True)

#     class Meta:
#         managed = False
#         db_table = 'LangContrast'

# class Languages(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     code = models.CharField(db_column='Code', max_length=30)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'Languages'

# class Lendlist(models.Model):
#     '''
#     记录借书信息
#     '''
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     readerid = models.IntegerField(db_column='ReaderID')
#     barcode = models.CharField(db_column='BarCode', max_length=20)
#     place = models.IntegerField(db_column='Place', blank=True, null=True)
#     lendtm = models.DateTimeField(db_column='LendTM')
#     duetm = models.DateTimeField(db_column='DueTm')
#     pressdate = models.DateTimeField(db_column='PressDate')
#     presstime = models.IntegerField(db_column='PressTime')
#     renewtime = models.IntegerField(db_column='RenewTime')
#     lttype = models.IntegerField(db_column='LTType', blank=True, null=True)
#     lendmember = models.IntegerField(db_column='LendMember',
#                                      blank=True,
#                                      null=True)
#     lendopid = models.CharField(db_column='LendOpID', max_length=20)
#     lendstation = models.IntegerField(db_column='LendStation',
#                                       blank=True,
#                                       null=True)

#     class Meta:
#         managed = False
#         db_table = 'LendList'

# class Lendlocation(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     descrip = models.CharField(db_column='Descrip',
#                                max_length=254,
#                                blank=True,
#                                null=True)
#     endescrip = models.CharField(db_column='EnDescrip',
#                                  max_length=254,
#                                  blank=True,
#                                  null=True)

#     class Meta:
#         managed = False
#         db_table = 'LendLocation'

# class Location(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'Location'

# class Mddb(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     name = models.CharField(db_column='Name',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enname = models.CharField(db_column='EnName',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'MDDB'

# class Mdindex1003(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'MDIndex1003'

# class Mdindex1018(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'MDIndex1018'

# class Mdindex20(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'MDIndex20'

# class Mdindex21(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'MDIndex21'

# class Mdindex31(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'MDIndex31'

# class Mdindex4(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'MDIndex4'

# class Mdindex53(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'MDIndex53'

# class Mdindex7(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'MDIndex7'

# class Mdinforetrieval(models.Model):
#     indexid = models.IntegerField(db_column='IndexID', primary_key=True)
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField')
#     marctype = models.IntegerField(db_column='MarcType')
#     dbid = models.IntegerField(db_column='DBID')

#     class Meta:
#         managed = False
#         db_table = 'MDInfoRetrieval'
#         unique_together = (('indexid', 'field', 'subfield', 'marctype',
#                             'dbid'), )

# class Mdmarc(models.Model):
#     marcid = models.IntegerField(db_column='MarcID', primary_key=True)
#     content = models.TextField(db_column='Content', blank=True, null=True)
#     marctype = models.IntegerField(db_column='MarcType')
#     indate = models.DateTimeField(db_column='InDate', blank=True, null=True)
#     dbid = models.IntegerField(db_column='DBID', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'MDMarc'

# class Moneytype(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'MoneyType'

# class Ordersource(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'OrderSource'

# class Othbmpara(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'OthBMPara'

# class Othsetparam(models.Model):
#     id = models.IntegerField(db_column='ID')
#     memo = models.CharField(db_column='Memo', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'OthSetParam'

# class Outstockreason(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'OutStockReason'

# class Paymtype(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'PaymType'

# class Pictures(models.Model):
#     id = models.IntegerField(db_column='ID')
#     picturename = models.CharField(db_column='PictureName',
#                                    max_length=254,
#                                    blank=True,
#                                    null=True)
#     commentid = models.IntegerField(db_column='CommentID')

#     class Meta:
#         managed = False
#         db_table = 'Pictures'

# class Qkarrlog(models.Model):
#     logid = models.IntegerField(db_column='LogID', primary_key=True)
#     arrid = models.IntegerField(db_column='ArrID', blank=True, null=True)
#     intime = models.DateTimeField(db_column='InTime', blank=True, null=True)
#     operator = models.CharField(db_column='Operator',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKArrLog'

# class Qkarrived(models.Model):
#     arrid = models.IntegerField(db_column='ArrID', primary_key=True)
#     orderid = models.IntegerField(db_column='OrderID', blank=True, null=True)
#     marcid = models.IntegerField(db_column='MarcID', blank=True, null=True)
#     source = models.IntegerField(db_column='Source', blank=True, null=True)
#     arryear = models.IntegerField(db_column='ArrYear', blank=True, null=True)
#     arrvol = models.CharField(db_column='ArrVol',
#                               max_length=20,
#                               blank=True,
#                               null=True)
#     arrper = models.CharField(db_column='ArrPer',
#                               max_length=20,
#                               blank=True,
#                               null=True)
#     arrtotal = models.CharField(db_column='ArrTotal',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)
#     price = models.DecimalField(db_column='Price',
#                                 max_digits=19,
#                                 decimal_places=4,
#                                 blank=True,
#                                 null=True)
#     moneytype = models.IntegerField(db_column='MoneyType',
#                                     blank=True,
#                                     null=True)
#     arrstate = models.IntegerField(db_column='ArrState', blank=True, null=True)
#     arrcount = models.IntegerField(db_column='ArrCount', blank=True, null=True)
#     arrorder = models.IntegerField(db_column='ArrOrder', blank=True, null=True)
#     arrtype = models.IntegerField(db_column='ArrType', blank=True, null=True)
#     kantype = models.IntegerField(db_column='KanType', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKArrived'

# class Qkbind(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     qkid = models.IntegerField(db_column='QKID', blank=True, null=True)
#     bindyear = models.IntegerField(db_column='BindYear', blank=True, null=True)
#     pubinfo = models.CharField(db_column='PubInfo',
#                                max_length=100,
#                                blank=True,
#                                null=True)
#     bindcount = models.IntegerField(db_column='BindCount',
#                                     blank=True,
#                                     null=True)
#     bindcolor = models.IntegerField(db_column='BindColor',
#                                     blank=True,
#                                     null=True)
#     perprice = models.DecimalField(db_column='PerPrice',
#                                    max_digits=19,
#                                    decimal_places=4,
#                                    blank=True,
#                                    null=True)
#     indate = models.DateTimeField(db_column='InDate', blank=True, null=True)
#     handler = models.CharField(db_column='Handler',
#                                max_length=20,
#                                blank=True,
#                                null=True)
#     bindfrmno = models.IntegerField(db_column='BindFrmNo',
#                                     blank=True,
#                                     null=True)
#     acccount = models.IntegerField(db_column='AccCount', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKBind'

# class Qkbinddetail(models.Model):
#     bindid = models.IntegerField(db_column='BindID')
#     serialno = models.IntegerField(db_column='Serialno', primary_key=True)

#     class Meta:
#         managed = False
#         db_table = 'QKBindDetail'

# class Qkbindform(models.Model):
#     bindfrmno = models.IntegerField(db_column='BindFrmNo', primary_key=True)
#     bindname = models.CharField(db_column='BindName',
#                                 max_length=100,
#                                 blank=True,
#                                 null=True)
#     indate = models.DateTimeField(db_column='InDate', blank=True, null=True)
#     operator = models.CharField(db_column='Operator',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)
#     frmstate = models.IntegerField(db_column='FrmState', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKBindForm'

# class Qkcheckin(models.Model):
#     barcode = models.CharField(db_column='Barcode',
#                                primary_key=True,
#                                max_length=20)
#     intime = models.DateTimeField(db_column='InTime', blank=True, null=True)
#     opid = models.CharField(db_column='OpID',
#                             max_length=20,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKCheckIn'

# class Qkclassserial(models.Model):
#     class_field = models.CharField(db_column='Class',
#                                    primary_key=True,
#                                    max_length=40)
#     serialno = models.IntegerField(db_column='SerialNo')
#     lang = models.CharField(db_column='Lang', max_length=3)
#     dbid = models.IntegerField(db_column='DBID')

#     class Meta:
#         managed = False
#         db_table = 'QKClassSerial'
#         unique_together = (('class_field', 'lang', 'dbid'), )

# class Qkcolor(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKColor'

# class Qkdb(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     name = models.CharField(db_column='Name',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     classfield = models.IntegerField(db_column='ClassField',
#                                      blank=True,
#                                      null=True)
#     classsfield = models.IntegerField(db_column='ClassSField',
#                                       blank=True,
#                                       null=True)
#     fieldno = models.IntegerField(db_column='FieldNo', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKDB'

# class Qkgetmode(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKGetMode'

# class Qkindex(models.Model):
#     id = models.IntegerField(db_column='ID')
#     ename = models.CharField(db_column='EName', max_length=254)
#     cname = models.CharField(db_column='CName', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'QKIndex'

# class Qkindex2001(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'QKIndex2001'

# class Qkindex2002(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'QKIndex2002'

# class Qkindex4(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'QKIndex4'

# class Qkindex53(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'QKIndex53'

# class Qkindex8(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'QKIndex8'

# class Qkindexpath(models.Model):
#     indexid = models.IntegerField(db_column='IndexID', primary_key=True)
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField')
#     marctype = models.IntegerField(db_column='MarcType')
#     dbid = models.IntegerField(db_column='DBID')

#     class Meta:
#         managed = False
#         db_table = 'QKIndexPath'
#         unique_together = (('indexid', 'field', 'subfield', 'marctype',
#                             'dbid'), )

# class Qkltstoreplace(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKLTStorePlace'

# class Qkmarc(models.Model):
#     marcid = models.IntegerField(db_column='MarcID', primary_key=True)
#     content = models.TextField(db_column='Content', blank=True, null=True)
#     marctype = models.IntegerField(db_column='MarcType', blank=True, null=True)
#     indate = models.DateTimeField(db_column='InDate', blank=True, null=True)
#     dbid = models.IntegerField(db_column='DBID', blank=True, null=True)
#     classno = models.CharField(db_column='ClassNo',
#                                max_length=50,
#                                blank=True,
#                                null=True)
#     kantype = models.IntegerField(db_column='KanType', blank=True, null=True)
#     nian = models.IntegerField(db_column='Nian', blank=True, null=True)
#     qi = models.CharField(db_column='Qi', max_length=20, blank=True, null=True)
#     zqi = models.CharField(db_column='ZQi',
#                            max_length=20,
#                            blank=True,
#                            null=True)
#     pubinfo = models.CharField(db_column='PubInfo',
#                                max_length=500,
#                                blank=True,
#                                null=True)
#     price = models.DecimalField(db_column='Price',
#                                 max_digits=19,
#                                 decimal_places=4,
#                                 blank=True,
#                                 null=True)
#     fjmemo = models.CharField(db_column='FJMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKMarc'

# class Qkoperate(models.Model):
#     intime = models.DateTimeField(db_column='InTime', primary_key=True)
#     optype = models.IntegerField(db_column='OpType')
#     operator = models.CharField(db_column='Operator', max_length=20)
#     content = models.CharField(db_column='Content',
#                                max_length=500,
#                                blank=True,
#                                null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKOperate'
#         unique_together = (('intime', 'optype', 'operator'), )

# class Qkoperation(models.Model):
#     id = models.IntegerField(db_column='ID')
#     memo = models.CharField(db_column='Memo',
#                             max_length=200,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKOperation'

# class Qkorderform(models.Model):
#     frmno = models.IntegerField(db_column='FrmNo', primary_key=True)
#     issuer = models.IntegerField(db_column='Issuer', blank=True, null=True)
#     ordertm = models.IntegerField(db_column='OrderTM', blank=True, null=True)
#     founder = models.CharField(db_column='Founder',
#                                max_length=20,
#                                blank=True,
#                                null=True)
#     modifier = models.CharField(db_column='Modifier',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)
#     ischecked = models.IntegerField(db_column='IsChecked',
#                                     blank=True,
#                                     null=True)
#     printcount = models.IntegerField(db_column='PrintCount',
#                                      blank=True,
#                                      null=True)
#     frmname = models.CharField(db_column='FrmName',
#                                max_length=100,
#                                blank=True,
#                                null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKOrderForm'

# class Qkorderformdetail(models.Model):
#     frmno = models.IntegerField(db_column='FrmNo')
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     qkid = models.IntegerField(db_column='QKID', blank=True, null=True)
#     source = models.IntegerField(db_column='Source', blank=True, null=True)
#     pubid = models.IntegerField(db_column='PubID', blank=True, null=True)
#     pubcycle = models.IntegerField(db_column='PubCycle', blank=True, null=True)
#     totalperyear = models.IntegerField(db_column='TotalPerYear',
#                                        blank=True,
#                                        null=True)
#     ordercount = models.IntegerField(db_column='OrderCount',
#                                      blank=True,
#                                      null=True)
#     moneytype = models.IntegerField(db_column='MoneyType',
#                                     blank=True,
#                                     null=True)
#     unitprice = models.DecimalField(db_column='UnitPrice',
#                                     max_digits=19,
#                                     decimal_places=4,
#                                     blank=True,
#                                     null=True)
#     yearprice = models.DecimalField(db_column='YearPrice',
#                                     max_digits=19,
#                                     decimal_places=4,
#                                     blank=True,
#                                     null=True)
#     totalprice = models.DecimalField(db_column='TotalPrice',
#                                      max_digits=19,
#                                      decimal_places=4,
#                                      blank=True,
#                                      null=True)
#     ordertime = models.DateTimeField(db_column='OrderTime',
#                                      blank=True,
#                                      null=True)
#     operator = models.CharField(db_column='Operator',
#                                 max_length=20,
#                                 blank=True,
#                                 null=True)
#     frmstatus = models.IntegerField(db_column='FrmStatus',
#                                     blank=True,
#                                     null=True)
#     timernge = models.IntegerField(db_column='TimeRnge', blank=True, null=True)
#     numarrived = models.IntegerField(db_column='NumArrived',
#                                      blank=True,
#                                      null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKOrderFormDetail'

# class Qkorderformstore(models.Model):
#     orderid = models.IntegerField(db_column='OrderID', primary_key=True)
#     place = models.IntegerField(db_column='Place')
#     incount = models.IntegerField(db_column='InCount', blank=True, null=True)
#     bcount = models.IntegerField(db_column='BCount', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKOrderFormStore'
#         unique_together = (('orderid', 'place'), )

# class Qkpubcycle(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     ycount = models.IntegerField(db_column='YCount', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKPubCycle'

# class Qktemp(models.Model):
#     marcid = models.IntegerField(db_column='MarcID', primary_key=True)
#     content = models.TextField(db_column='Content', blank=True, null=True)
#     marctype = models.IntegerField(db_column='MarcType', blank=True, null=True)
#     indate = models.DateTimeField(db_column='InDate', blank=True, null=True)
#     dbid = models.IntegerField(db_column='DBID', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKTemp'

# class Qktempdb(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     name = models.CharField(db_column='Name',
#                             max_length=254,
#                             blank=True,
#                             null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKTempDB'

# class Qktempindex2001(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'QKTempIndex2001'

# class Qktempindex2002(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'QKTempIndex2002'

# class Qktempindex4(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'QKTempIndex4'

# class Qktempindex53(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'QKTempIndex53'

# class Qktempindex8(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'QKTempIndex8'

# class Qktempindexpath(models.Model):
#     indexid = models.IntegerField(db_column='IndexID', primary_key=True)
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField')
#     marctype = models.IntegerField(db_column='MarcType')
#     dbid = models.CharField(db_column='DBID', max_length=10)

#     class Meta:
#         managed = False
#         db_table = 'QKTempIndexPath'
#         unique_together = (('indexid', 'field', 'subfield', 'marctype',
#                             'dbid'), )

# class Qkupqueue(models.Model):
#     serialno = models.IntegerField(db_column='SerialNo', primary_key=True)

#     class Meta:
#         managed = False
#         db_table = 'QKUpQueue'

# class Qkzsriches(models.Model):
#     serialno = models.IntegerField(db_column='SerialNo', primary_key=True)
#     barcode = models.CharField(db_column='Barcode',
#                                max_length=20,
#                                blank=True,
#                                null=True)
#     marcid = models.IntegerField(db_column='MarcID', blank=True, null=True)
#     logid = models.IntegerField(db_column='LogID', blank=True, null=True)
#     price = models.FloatField(db_column='Price', blank=True, null=True)
#     place = models.IntegerField(db_column='Place', blank=True, null=True)
#     sflag = models.IntegerField(db_column='SFlag', blank=True, null=True)
#     ltstatus = models.IntegerField(db_column='LTStatus', blank=True, null=True)
#     upflag = models.IntegerField(db_column='UPFlag', blank=True, null=True)
#     ltsign = models.IntegerField(db_column='LTSign', blank=True, null=True)
#     intime = models.DateTimeField(db_column='InTime', blank=True, null=True)
#     memberunitid = models.IntegerField(db_column='MemberUnitID',
#                                        blank=True,
#                                        null=True)

#     class Meta:
#         managed = False
#         db_table = 'QKZSRiches'

# class Rdrcardbook(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     ctid = models.IntegerField(db_column='CTID')
#     ltid = models.IntegerField(db_column='LTID')
#     booknum = models.IntegerField(db_column='BookNum')
#     backtime = models.IntegerField(db_column='BackTime')
#     retime = models.IntegerField(db_column='ReTime')
#     renum = models.IntegerField(db_column='ReNum', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrCardBook'

# class Rdrcardgroup(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     ctid = models.IntegerField(db_column='CTID')
#     groupid = models.IntegerField(db_column='GroupID')
#     maxbook = models.IntegerField(db_column='MaxBook')

#     class Meta:
#         managed = False
#         db_table = 'RdrCardGroup'

# class Rdrcardtype(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo', max_length=254)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)
#     valid = models.IntegerField(db_column='Valid')
#     deposit = models.DecimalField(db_column='Deposit',
#                                   max_digits=18,
#                                   decimal_places=2,
#                                   blank=True,
#                                   null=True)
#     maxlend = models.IntegerField(db_column='MaxLend', blank=True, null=True)
#     moneylimit = models.IntegerField(db_column='MoneyLimit',
#                                      blank=True,
#                                      null=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrCardType'

# class Rdrdegree(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrDegree'

# class Rdrheadship(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrHeadShip'

# class Rdridtype(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrIDType'

# class Rdroptinfo(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrOptInfo'

# class Rdroptlog(models.Model):
#     intime = models.DateTimeField(db_column='InTime')
#     optype = models.IntegerField(db_column='OpType')
#     operater = models.CharField(db_column='Operater', max_length=20)
#     content = models.CharField(db_column='Content',
#                                max_length=500,
#                                blank=True,
#                                null=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrOptLog'

# class Rdrreglog(models.Model):
#     station = models.IntegerField(db_column='Station')
#     barcode = models.CharField(db_column='Barcode', max_length=20)
#     indate = models.DateTimeField(db_column='InDate', primary_key=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrRegLog'

# class Rdrregisteritem(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=50,
#                             blank=True,
#                             null=True)
#     sflag = models.IntegerField(db_column='sFlag', blank=True, null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=200,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrRegisterItem'

# class Rdrstatus(models.Model):
#     id = models.IntegerField(primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=250,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=250,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrStatus'

# class Rdrtitle(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrTitle'

# class Rdrtype(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrType'

# class Rdrwork(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'RdrWork'

# class Readerimage(models.Model):
#     readerid = models.IntegerField(db_column='ReaderID', primary_key=True)
#     certid = models.CharField(db_column='CertID',
#                               max_length=50,
#                               blank=True,
#                               null=True)
#     picture = models.BinaryField(db_column='Picture', blank=True, null=True)
#     plen = models.IntegerField(db_column='pLen', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'ReaderImage'

# class Rights(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     name = models.CharField(db_column='Name', max_length=200)
#     enname = models.CharField(db_column='EnName',
#                               max_length=200,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'Rights'

# class Syncflag(models.Model):
#     tbname = models.CharField(db_column='tbName',
#                               primary_key=True,
#                               max_length=100)
#     lastchange = models.IntegerField(db_column='LastChange')

#     class Meta:
#         managed = False
#         db_table = 'SYNCFlag'

# class Serialno(models.Model):
#     serialno = models.IntegerField(db_column='SerialNo', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'SerialNo'

# class Tjclass(models.Model):
#     gridid = models.IntegerField(db_column='GridID', primary_key=True)
#     classno = models.CharField(db_column='ClassNo', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'TJClass'
#         unique_together = (('gridid', 'classno'), )

# class Ttindex1003(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'TTIndex1003'

# class Ttindex1018(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'TTIndex1018'

# class Ttindex20(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'TTIndex20'

# class Ttindex21(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'TTIndex21'

# class Ttindex31(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'TTIndex31'

# class Ttindex4(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'TTIndex4'

# class Ttindex53(models.Model):
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content', max_length=254)

#     class Meta:
#         managed = False
#         db_table = 'TTIndex53'

# class Ttindex7(models.Model):
#     id = models.AutoField(db_column='ID', primary_key=True)
#     marcid = models.IntegerField(db_column='MarcID')
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField', blank=True, null=True)
#     content = models.CharField(db_column='Content',
#                                max_length=254,
#                                blank=True,
#                                null=True)

#     class Meta:
#         managed = False
#         db_table = 'TTIndex7'

# class Ttinforetrieval(models.Model):
#     indexid = models.IntegerField(db_column='IndexID', primary_key=True)
#     field = models.IntegerField(db_column='Field')
#     subfield = models.IntegerField(db_column='SubField')
#     marctype = models.IntegerField(db_column='MarcType')
#     dbid = models.IntegerField(db_column='DBID')

#     class Meta:
#         managed = False
#         db_table = 'TTInfoRetrieval'
#         unique_together = (('indexid', 'field', 'subfield', 'marctype',
#                             'dbid'), )

# class Ttmarc(models.Model):
#     marcid = models.IntegerField(db_column='MarcID', primary_key=True)
#     content = models.TextField(db_column='Content', blank=True, null=True)
#     marctype = models.IntegerField(db_column='MarcType')
#     indate = models.DateTimeField(db_column='InDate', blank=True, null=True)
#     objflag = models.IntegerField(db_column='OBJFlag', blank=True, null=True)
#     dbid = models.IntegerField(db_column='DBID', blank=True, null=True)
#     richcount = models.IntegerField(db_column='RichCount',
#                                     blank=True,
#                                     null=True)
#     updatedate = models.DateTimeField(db_column='UpdateDate',
#                                       blank=True,
#                                       null=True)
#     classno = models.CharField(db_column='ClassNo',
#                                max_length=254,
#                                blank=True,
#                                null=True)

#     class Meta:
#         managed = False
#         db_table = 'TTMarc'

# class Thumbsuprecord(models.Model):
#     id = models.IntegerField(db_column='ID')
#     readerid = models.IntegerField(db_column='ReaderID')
#     commentid = models.IntegerField(db_column='CommentID')

#     class Meta:
#         managed = False
#         db_table = 'ThumbsupRecord'

# class Topic(models.Model):
#     classno = models.CharField(db_column='ClassNo',
#                                max_length=254,
#                                blank=True,
#                                null=True)
#     classname = models.CharField(db_column='ClassName',
#                                  max_length=254,
#                                  blank=True,
#                                  null=True)
#     classmemo = models.CharField(db_column='ClassMemo',
#                                  max_length=500,
#                                  blank=True,
#                                  null=True)
#     topic = models.CharField(db_column='Topic',
#                              max_length=255,
#                              blank=True,
#                              null=True)
#     topicmemo = models.CharField(db_column='TopicMemo',
#                                  max_length=254,
#                                  blank=True,
#                                  null=True)
#     topiclist = models.CharField(db_column='TopicList',
#                                  max_length=254,
#                                  blank=True,
#                                  null=True)
#     topiclistmemo = models.CharField(db_column='TopicListMemo',
#                                      max_length=500,
#                                      blank=True,
#                                      null=True)

#     class Meta:
#         managed = False
#         db_table = 'Topic'

# class Usercomp(models.Model):
#     wrkno = models.IntegerField(db_column='wrkNo')
#     stationid = models.IntegerField(db_column='StationID')
#     login = models.BooleanField(db_column='Login', blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'UserComp'

# class Usergp(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     name = models.CharField(db_column='Name', max_length=100)
#     enname = models.CharField(db_column='EnName',
#                               max_length=50,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'UserGp'

# class Usergpright(models.Model):
#     groupid = models.IntegerField(db_column='GroupID', primary_key=True)
#     rightid = models.IntegerField(db_column='RightID')

#     class Meta:
#         managed = False
#         db_table = 'UserGpRight'
#         unique_together = (('groupid', 'rightid'), )

# class Userlog(models.Model):
#     degree = models.AutoField()
#     loaddate = models.DateTimeField(db_column='LoadDate',
#                                     blank=True,
#                                     null=True)
#     username = models.CharField(db_column='UserName',
#                                 max_length=50,
#                                 blank=True,
#                                 null=True)
#     outdate = models.DateTimeField(db_column='OutDate', blank=True, null=True)
#     loginfo = models.CharField(db_column='LogInfo',
#                                max_length=300,
#                                blank=True,
#                                null=True)

#     class Meta:
#         managed = False
#         db_table = 'UserLog'

# class Usermarcdbright(models.Model):
#     name = models.CharField(db_column='Name', max_length=20)
#     dbtype = models.IntegerField(db_column='DBType')
#     dbid = models.IntegerField(db_column='DBID')
#     rightid = models.CharField(db_column='RightID', max_length=4)

#     class Meta:
#         managed = False
#         db_table = 'UserMarcDBRight'

# class Userright(models.Model):
#     name = models.CharField(db_column='Name', max_length=20)
#     rightid = models.IntegerField(db_column='RightID')

#     class Meta:
#         managed = False
#         db_table = 'UserRight'

# class Users(models.Model):
#     name = models.CharField(db_column='Name', primary_key=True, max_length=20)
#     password = models.CharField(db_column='Password', max_length=100)
#     wrkno = models.IntegerField(db_column='WRKNo')
#     memberunitid = models.IntegerField(db_column='MemberUnitID',
#                                        blank=True,
#                                        null=True)
#     enname = models.CharField(db_column='EnName',
#                               max_length=50,
#                               blank=True,
#                               null=True)

#     class Meta:
#         managed = False
#         db_table = 'Users'

# class Webactivity(models.Model):
#     acti_id = models.AutoField(primary_key=True)
#     acti_title = models.CharField(max_length=500)
#     acti_cotent = models.TextField(blank=True, null=True)
#     acti_address = models.CharField(max_length=300)
#     acti_organizer = models.CharField(max_length=200)
#     acti_btime = models.CharField(max_length=50)
#     acti_etime = models.CharField(max_length=50)

#     class Meta:
#         managed = False
#         db_table = 'WebActivity'

# class Webnewbook(models.Model):
#     nb_id = models.AutoField(primary_key=True)
#     nb_title = models.CharField(max_length=200, blank=True, null=True)
#     nb_author = models.CharField(max_length=100, blank=True, null=True)
#     nb_profile = models.CharField(max_length=500, blank=True, null=True)
#     nb_cover = models.CharField(max_length=500, blank=True, null=True)
#     marcid = models.IntegerField(blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'WebNewBook'

# class Webnotice(models.Model):
#     nt_id = models.AutoField(primary_key=True)
#     nt_title = models.CharField(max_length=500, blank=True, null=True)
#     nt_content = models.TextField(blank=True, null=True)
#     nt_author = models.CharField(max_length=100, blank=True, null=True)
#     nt_date = models.CharField(max_length=50, blank=True, null=True)
#     nt_header = models.CharField(max_length=50, blank=True, null=True)
#     nt_footer = models.CharField(max_length=50, blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'WebNotice'

# class Websearchhis(models.Model):
#     sh_id = models.AutoField(primary_key=True)
#     label = models.CharField(max_length=250)
#     times = models.IntegerField(blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'WebSearchHis'

# class Workstation(models.Model):
#     id = models.IntegerField(db_column='ID', primary_key=True)
#     memo = models.CharField(db_column='Memo',
#                             max_length=254,
#                             blank=True,
#                             null=True)
#     enmemo = models.CharField(db_column='EnMemo',
#                               max_length=254,
#                               blank=True,
#                               null=True)
#     printjst = models.IntegerField(db_column='PrintJST', blank=True, null=True)
#     printxjt = models.IntegerField(db_column='PrintXJT', blank=True, null=True)
#     printpsd = models.IntegerField(db_column='PrintPSD', blank=True, null=True)
#     confirmjs = models.IntegerField(db_column='ConfirmJS',
#                                     blank=True,
#                                     null=True)
#     confirmhs = models.IntegerField(db_column='ConfirmHS',
#                                     blank=True,
#                                     null=True)
#     confirmsf = models.IntegerField(db_column='ConfirmSF',
#                                     blank=True,
#                                     null=True)
#     confirmth = models.IntegerField(db_column='ConfirmTH',
#                                     blank=True,
#                                     null=True)
#     lttype = models.IntegerField(db_column='LTType', blank=True, null=True)
#     memojxt = models.CharField(db_column='MemoJXT',
#                                max_length=254,
#                                blank=True,
#                                null=True)
#     thflag = models.IntegerField(db_column='THFlag', blank=True, null=True)
#     distributer = models.IntegerField(db_column='Distributer',
#                                       blank=True,
#                                       null=True)
#     tempcard = models.IntegerField(db_column='TempCard', blank=True, null=True)
#     libraryid = models.IntegerField(db_column='LibraryID',
#                                     blank=True,
#                                     null=True)

#     class Meta:
#         managed = False
#         db_table = 'WorkStation'

# class Syncreaders(models.Model):
#     name = models.CharField(db_column='Name', max_length=100)
#     sex = models.IntegerField(db_column='Sex', blank=True, null=True)
#     cardcode = models.IntegerField(db_column='CardCode', blank=True, null=True)
#     certid = models.CharField(db_column='CertID',
#                               max_length=50,
#                               blank=True,
#                               null=True)
#     cardserialno = models.CharField(db_column='CardSerialNo',
#                                     max_length=20,
#                                     blank=True,
#                                     null=True)
#     idcardtype = models.IntegerField(db_column='IDCardType',
#                                      blank=True,
#                                      null=True)
#     idcardno = models.CharField(db_column='IDCardNo',
#                                 max_length=30,
#                                 blank=True,
#                                 null=True)
#     levelr = models.IntegerField(db_column='LevelR', blank=True, null=True)
#     readertype = models.IntegerField(db_column='ReaderType',
#                                      blank=True,
#                                      null=True)
#     workr = models.IntegerField(db_column='WorkR', blank=True, null=True)
#     degree = models.IntegerField(db_column='Degree', blank=True, null=True)
#     headship = models.IntegerField(db_column='HeadShip', blank=True, null=True)
#     title = models.IntegerField(db_column='Title', blank=True, null=True)
#     unitid = models.CharField(db_column='UnitID',
#                               max_length=30,
#                               blank=True,
#                               null=True)
#     unitname = models.TextField(db_column='UnitName', blank=True, null=True)
#     address = models.CharField(db_column='Address',
#                                max_length=100,
#                                blank=True,
#                                null=True)
#     postalcode = models.CharField(db_column='Postalcode',
#                                   max_length=10,
#                                   blank=True,
#                                   null=True)
#     tel = models.CharField(db_column='Tel',
#                            max_length=30,
#                            blank=True,
#                            null=True)
#     email = models.CharField(db_column='EMail',
#                              max_length=50,
#                              blank=True,
#                              null=True)
#     registerdate = models.DateTimeField(db_column='RegisterDate',
#                                         blank=True,
#                                         null=True)
#     operatorid = models.CharField(db_column='OperatorID',
#                                   max_length=20,
#                                   blank=True,
#                                   null=True)
#     remark = models.CharField(db_column='Remark',
#                               max_length=200,
#                               blank=True,
#                               null=True)
#     birthday = models.DateTimeField(db_column='BirthDay',
#                                     blank=True,
#                                     null=True)
#     barcode = models.CharField(db_column='Barcode',
#                                max_length=20,
#                                blank=True,
#                                null=True)
#     startdate = models.DateTimeField(db_column='StartDate',
#                                      blank=True,
#                                      null=True)
#     enddate = models.DateTimeField(db_column='EndDate', blank=True, null=True)
#     status = models.IntegerField(db_column='Status', blank=True, null=True)
#     memberunitid = models.IntegerField(db_column='MemberUnitID',
#                                        blank=True,
#                                        null=True)
#     libcardtype = models.IntegerField(db_column='LibCardType',
#                                       blank=True,
#                                       null=True)
#     updatedate = models.DateTimeField(db_column='UpdateDate',
#                                       blank=True,
#                                       null=True)
#     updateuser = models.CharField(db_column='UpdateUser',
#                                   max_length=20,
#                                   blank=True,
#                                   null=True)
#     updateunitid = models.IntegerField(db_column='UpdateUnitID',
#                                        blank=True,
#                                        null=True)
#     password = models.CharField(db_column='Password',
#                                 max_length=30,
#                                 blank=True,
#                                 null=True)
#     deposit = models.DecimalField(db_column='Deposit',
#                                   max_digits=19,
#                                   decimal_places=4,
#                                   blank=True,
#                                   null=True)
#     debt = models.DecimalField(db_column='Debt',
#                                max_digits=19,
#                                decimal_places=4,
#                                blank=True,
#                                null=True)
#     inilibcardtype = models.IntegerField(db_column='IniLibcardType',
#                                          blank=True,
#                                          null=True)
#     curlend = models.IntegerField(db_column='CurLend', blank=True, null=True)
#     wechatid = models.CharField(db_column='WeChatID',
#                                 max_length=50,
#                                 blank=True,
#                                 null=True)
#     wechatnickname = models.CharField(db_column='WeChatNickName',
#                                       max_length=50,
#                                       blank=True,
#                                       null=True)

#     class Meta:
#         managed = False
#         db_table = 'syncReaders'

# class Sysdiagrams(models.Model):
#     name = models.CharField(max_length=128)
#     principal_id = models.IntegerField()
#     diagram_id = models.AutoField(primary_key=True)
#     version = models.IntegerField(blank=True, null=True)
#     definition = models.BinaryField(blank=True, null=True)

#     class Meta:
#         managed = False
#         db_table = 'sysdiagrams'
#         unique_together = (('principal_id', 'name'), )
