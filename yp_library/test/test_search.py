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
    
    def test_books_count(self):
        self.assertEqual(len(Book.objects.all().values()), 6)

    def test_normal_query(self):
        query1 = {"id": '1'}
        query2 = {"identity_code": "MATH", "title": "数"}
        query3 = {"author": "伍胜健", "publisher": "北京大学"}
        query4 = {"id": "0"}
        query5 = {"id": "1", "identity_code": "CS"}
        query6 = {"returned": True}
        query7 = {"title": "数", "returned": True}
        query8 = {}
        
        self.assertEqual(
            len(search_books(**query1)), 1)
        self.assertEqual(
            len(search_books(**query2)), 3)
        self.assertEqual(
            len(search_books(**query3)), 2)
        self.assertEqual(
            len(search_books(**query4)), 0)
        self.assertEqual(
            len(search_books(**query5)), 0)
        self.assertEqual(
            len(search_books(**query6)), 3)
        self.assertEqual(
            len(search_books(**query7)), 1)
        self.assertEqual(
            len(search_books(**query8)), 6)

    def test_keywords_query(self):
        query9 = {"keywords": "学"}
        query10 = {"returned": True, "keywords": "北京大学"}
        query11 = {"title": "数学", "returned": True, "keywords": "北京大学"}
        query12 = {"returned": True, "keywords": "A"}
        query13 = {"keywords": "CS"}
        
        self.assertEqual(
            len(search_books(**query9)), 4)
        self.assertEqual(
            len(search_books(**query10)), 2)
        self.assertEqual(
            len(search_books(**query11)), 1)
        self.assertEqual(
            len(search_books(**query12)), 3)
        self.assertEqual(
            len(search_books(**query13)), 3)
