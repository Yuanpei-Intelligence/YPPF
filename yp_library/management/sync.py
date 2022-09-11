from yp_library.models import Reader, Book, LendRecord
from yp_library.utils import bookreturn_notification

from django.db.models import Max, Q
from django.db import transaction

from datetime import datetime, timedelta
import pymssql
import copy
import os


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
            current_time = datetime.now()
            for row in cursor:
                record: LendRecord = unreturned_records.get(id=row['ID'])
                if row['IsReturn'] == 1:
                    record.returned = True
                    record.return_time = row['ReturnTime']
                elif current_time - record.due_time > timedelta(days=7):
                    record.status = LendRecord.Status.OVERTIME

                updated_records.append(record)

            with transaction.atomic():
                LendRecord.objects.bulk_update(
                    updated_records,
                    fields=['returned', 'return_time', 'status'],
                )

    # 发送还书提醒
    bookreturn_notification()


def update_lib_data():
    update_reader()
    update_book()
    update_records()
