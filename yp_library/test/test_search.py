from django.test import TestCase
from yp_library.models import Book, LendRecord, Reader
from yp_library.utils import search_books


class BookSearchTestCase(TestCase):
    def setUp(self):
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

    def test_search_books(self):
        self.assertEqual(len(Book.objects.all().values()), 5)
        query1 = ['1', '', '', '', '', '']
        query2 = ['', 'MATH', '数', '', '', '']
        query3 = ['', '', '', '伍胜健', '北京大学', '']
        query4 = ['0', '', '', '', '', '']
        query5 = ['1', 'CS', '', '', '', '']
        query6 = ['', '', '', '', '', True]
        query7 = ['', '', '数', '', '', True]
        query8 = ['', '', '', '', '', '']
        keys = ["id", "identity_code", "title",
                "author", "publisher", "returned"]
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
            len(search_books({k: v for (k, v) in zip(keys, query6)})), 2)
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query7)})), 1)
        self.assertEqual(
            len(search_books({k: v for (k, v) in zip(keys, query8)})), 5)
        self.assertEqual(len(search_books({})), 5)
