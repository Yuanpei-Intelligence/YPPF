from django.test import TestCase
from yp_library.models import Book, LendRecord, Reader
from yp_library.utils import search_books


class BookSearchTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        Book.objects.create(id=1, identity_code="MATH-1-1",
                            title="数学分析I", author="伍胜健", publisher="北京大学出版社", returned=0)
        Book.objects.create(id=2, identity_code="MATH-1-2",
                            title="数学分析II", author="伍胜健", publisher="北京大学出版社")
        Book.objects.create(id=3, identity_code="MATH-2",
                            title="高等代数", author="丘维声", publisher="清华大学出版社", returned=0)
        Book.objects.create(id=4, identity_code="CS-1",
                            title="ICS", author="Alice", publisher="ABC")
        Book.objects.create(id=5, identity_code="CS-2",
                            title="数据结构与算法（A）", author="Bob", publisher="xyz", returned=0)
        Book.objects.create(id=6, identity_code="CS-3",
                            title="计算概论", author="北京大学", publisher="ABC")

    def test_search_books(self):
        self.assertEqual(len(Book.objects.all().values()), 6)
        query1 = ['1', '', '', '', '', '', '']
        query2 = ['', 'MATH', '数', '', '', '', '']
        query3 = ['', '', '', '伍胜健', '北京大学', '', '']
        query4 = ['0', '', '', '', '', '', '']
        query5 = ['1', 'CS', '', '', '', '', '']
        query6 = ['', '', '', '', '', True, '']
        query7 = ['', '', '数', '', '', True, '']
        query8 = ['', '', '', '', '', '', '']
        query9 = ['', '', '', '', '', '', ['学', ["kw_title", "kw_publisher"]]]
        query10 = ['', '', '', '', '', True, ['北京大学', ["kw_title", "kw_author", "kw_publisher"]]]
        query11 = ['', '', '数学', '', '', True, ['北京大学', ["kw_title", "kw_author", "kw_publisher"]]]
        keys = ["id", "identity_code", "title",
                "author", "publisher", "returned", "keywords"]
        
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query1)})), 1)
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query2)})), 3)
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query3)})), 2)
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query4)})), 0)
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query5)})), 0)
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query6)})), 3)
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query7)})), 1)
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query8)})), 6)
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query9)})), 3)
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query10)})), 2)
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query11)})), 1)
        self.assertEqual(len(search_books({})), 6)
