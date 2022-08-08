from django.test import TestCase
from yp_library.models import Book, LendRecord, Reader
from yp_library.utils import get_my_records, get_lendinfo_by_readers


class GetLendRecordTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        Reader.objects.create(id=123456789, student_id='1900010000')
        Reader.objects.create(id=1234567, student_id='1900010000')
        Reader.objects.create(id=987654321, student_id='2000010000')

        Book.objects.create(id=1, identity_code="MATH-1-1",
                            title="数学分析I", author="伍胜健", publisher="北京大学出版社", returned=0)
        Book.objects.create(id=2, identity_code="MATH-1-2",
                            title="数学分析II", author="伍胜健", publisher="北京大学出版社")
        Book.objects.create(id=3, identity_code="MATH-2",
                            title="高等代数", author="丘维声", publisher="清华大学出版社", returned=0)

        LendRecord.objects.create(reader_id_id=123456789, book_id_id=1, lend_time='2022-07-22',
                                  due_time='2022-07-30', return_time='2022-07-23', returned=1, status=0)
        LendRecord.objects.create(reader_id_id=123456789, book_id_id=2, lend_time='2022-07-22',
                                  due_time='2022-07-30', return_time='2022-07-31', returned=1, status=1)
        LendRecord.objects.create(reader_id_id=123456789, book_id_id=3, lend_time='2022-07-22',
                                  due_time='2022-07-30', return_time='2022-07-31', returned=1, status=2)
        LendRecord.objects.create(reader_id_id=1234567, book_id_id=1, lend_time='2022-07-25',
                                  due_time='2022-08-01', returned=0, status=1)
        LendRecord.objects.create(reader_id_id=1234567, book_id_id=2, lend_time='2022-08-01',
                                  due_time='2022-08-07', returned=0, status=0)
        LendRecord.objects.create(reader_id_id=987654321, book_id_id=3, lend_time='2022-07-01',
                                  due_time='2022-07-07', return_time='2022-07-20', returned=0, status=4)

    def test_get_my_records(self):
        self.assertEqual(len(Book.objects.all().values()), 3)
        self.assertEqual(len(Reader.objects.all().values()), 3)
        self.assertEqual(len(LendRecord.objects.all().values()), 6)

        self.assertEqual(len(get_my_records(123456789, returned=0)), 0)
        self.assertEqual(len(get_my_records(123456789, returned=1)), 3)
        self.assertEqual(len(get_my_records(123456789, status=[0, 1])), 2)
        self.assertEqual(len(get_my_records(123456789, status=1)), 1)
        self.assertEqual(
            len(get_my_records(123456789, returned=0, status=2)), 0)
        self.assertEqual(
            len(get_my_records(123456789, returned=1, status=2)), 1)
        self.assertEqual(len(get_my_records(1234567, returned=1)), 0)
        self.assertEqual(
            len(get_my_records(1234567, returned=1, status=[3, 4])), 0)
        self.assertEqual(
            len(get_my_records(1234567, returned=0, status=[3, 1, 2])), 1)
        self.assertEqual(len(get_my_records(987654321, status=[4, ])), 1)

        records = get_my_records(123456789, returned=1, status=0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], 'normal')
        records = get_my_records(123456789, returned=1, status=1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], 'overtime')
        '''
        # 测试记录类型'type', 对于未归还记录，结果会随测试时的时间不同而变化
        records = get_my_records(1234567, returned=0, status=1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], 'approaching')
        records = get_my_records(1234567, returned=0, status=0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], 'normal')
        records = get_my_records(987654321, returned=0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], 'overtime')
        '''


    def test_get_lendinfo_by_readers(self):
        unreturned_records_list, returned_records_list = get_lendinfo_by_readers(
            Reader.objects.filter(student_id='1900010000'))
        self.assertEqual(len(unreturned_records_list), 2)
        self.assertEqual(len(returned_records_list), 3)
