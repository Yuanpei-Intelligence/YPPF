import os
from datetime import datetime, timedelta
import copy

import pymssql
from django.db.models import Max, Q
from django.db import transaction

from scheduler.scheduler import periodical
from yp_library.models import Reader, Book, LendRecord
from yp_library.utils import days_reminder, violate_reminder


def update_reader():
    """
    更新读者信息
    """
    with pymssql.connect(server=os.environ["LIB_DB_HOST"],
                         user=os.environ["LIB_DB_USER"],
                         password=os.environ["LIB_DB_PASSWORD"],
                         database=os.environ["LIB_DB"],
                         login_timeout=5) as conn:
        with conn.cursor(as_dict=True) as cursor:
            cursor.execute('SELECT ID,IDCardNo FROM Readers')
            # 暂时采用全部遍历的更新方式，因为存在空缺的数据较多，待书房的数据修订完成后，
            # 可以更改为只考虑新增数据
            with transaction.atomic():
                for row in cursor:
                    Reader.objects.update_or_create(
                        id=row['ID'], defaults={'student_id': row['IDCardNo']})


def update_book():
    """
    更新书籍信息
    """
    largest_id = Book.objects.aggregate(Max('id'))['id__max']
    if not largest_id:
        largest_id = 0

    with pymssql.connect(server=os.environ["LIB_DB_HOST"],
                         user=os.environ["LIB_DB_USER"],
                         password=os.environ["LIB_DB_PASSWORD"],
                         database=os.environ["LIB_DB"],
                         login_timeout=5) as conn:
        with conn.cursor(as_dict=True) as cursor:
            # 筛选新增数据
            cursor.execute(f'''SELECT MarcID,Title,Author,Publisher,ReqNo
                            FROM CircMarc WHERE MarcID>{largest_id}''')
            new_books = []
            for row in cursor:
                new_books.append(
                    Book(
                        id=row['MarcID'],
                        identity_code=row['ReqNo'],
                        title=row['Title'],
                        author=row['Author'],
                        publisher=row['Publisher'],
                    ))

            with transaction.atomic():
                Book.objects.bulk_create(new_books)


def update_records():
    """
    更新借书记录
    """
    # 本地最新记录的时间
    latest_record_time = LendRecord.objects.aggregate(
        Max('lend_time'))['lend_time__max']
    if not latest_record_time:
        latest_record_time = datetime.now() - timedelta(days=3650)
    else:
        latest_record_time += timedelta(seconds=1)

    with pymssql.connect(server=os.environ["LIB_DB_HOST"],
                         user=os.environ["LIB_DB_USER"],
                         password=os.environ["LIB_DB_PASSWORD"],
                         database=os.environ["LIB_DB"],
                         login_timeout=5) as conn:
        with conn.cursor(as_dict=True) as cursor:
            # 新增借书记录
            cursor.execute(f'''SELECT ID,ReaderID,BarCode,LendTM,DueTm 
                               FROM LendHist 
                               WHERE LendTM > convert(datetime, '{latest_record_time.strftime('%Y-%m-%d %H:%M:%S')}')'''
                           )
            results = copy.copy(cursor.fetchall())
            with transaction.atomic():
                for row in results:
                    bar_code = row['BarCode'].strip()[-6:]
                    # 根据BarCode查询书的编号
                    cursor.execute(f"""SELECT MarcID FROM Items 
                                       WHERE BarCode LIKE '%{bar_code}%'""")
                    book_id = cursor.fetchone()
                    if not book_id:
                        book_id = None
                    else:
                        book_id = book_id['MarcID']

                    reader_id = row['ReaderID']
                    if not Reader.objects.filter(id=reader_id).exists():
                        continue
                    LendRecord.objects.update_or_create(id=row['ID'],
                                                        defaults={
                                                            'reader_id_id':
                                                            reader_id,
                                                            'book_id_id':
                                                            book_id,
                                                            'lend_time':
                                                            row['LendTM'],
                                                            'due_time':
                                                            row['DueTm'],
                    })

            # 未归还的借书记录
            unreturned_records = LendRecord.objects.filter(returned=False)
            # 转换为方便sql查询的形式
            unreturned_record_id = list(
                unreturned_records.values_list('id', flat=True))
            unreturned_record_id = ', '.join(
                list(map(str, unreturned_record_id)))

            # 更新未归还记录
            cursor.execute(f'''SELECT ID,IsReturn,ReturnTime
                               FROM LendHist 
                               WHERE ID IN ({unreturned_record_id})''')

            updated_records = []
            for row in cursor:
                record: LendRecord = unreturned_records.get(id=row['ID'])
                if row['IsReturn'] == 1:
                    record.returned = True
                    record.return_time = row['ReturnTime']
                    updated_records.append(record)

            with transaction.atomic():
                LendRecord.objects.bulk_update(
                    updated_records,
                    fields=['returned', 'return_time'],
                )


def update_book_status():
    time_lower_bound = datetime.now() - timedelta(days=1)
    recent_records = LendRecord.objects.filter(
        Q(lend_time__gt=time_lower_bound)
        | Q(return_time__gt=time_lower_bound)).values_list('book_id',
                                                           flat=True)
    books = Book.objects.filter(id__in=recent_records)
    for book in books:
        book.returned = not book.lendrecord_set.filter(returned=False).exists()

    with transaction.atomic():
        Book.objects.bulk_update(books, fields=['returned'])


@periodical('cron', minute=50)
def update_lib_data():
    update_book_status()
    update_reader()
    update_book()
    update_records()


@periodical('cron', minute=0)
def bookreturn_notification():
    """
    该函数每小时在外部被调用，对每一条未归还的借阅记录进行检查
    在应还书时间前1天、应还书时间、应还书时间逾期5天发送还书提醒，提醒链接到“我的借阅”界面
    在应还书时间逾期7天，将借阅信息改为“超时扣分”，扣除1信用分并发送提醒
    """
    # 调用days_reminder()发送
    days_reminder(-1, '您好！您现有未归还的图书，将于一天内借阅到期，请按时归还至元培书房！')
    days_reminder(0, '您好！您现有未归还的图书，已经借阅到期，请及时归还至元培书房！')
    days_reminder(5, '您好！您现有未归还的图书，已经借阅到期五天，请尽快归还至元培书房！到期一周未归还将扣除您的信用分1分！')
    days_reminder(7, '您好！您现有未归还的图书，已经借阅到期一周，请尽快归还至元培书房！')
    violate_reminder(7, '由于借阅超时一周，您已被扣除信用分1分！')
