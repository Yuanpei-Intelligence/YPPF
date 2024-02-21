from django.test import TestCase
from app.models import (
    User,
    NaturalPerson,
    AcademicTag,
    AcademicEntry,
    AcademicTagEntry,
    AcademicTextEntry,                        
)
from app.academic_utils import get_search_results


class GetSearchAcademicTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        u1 = User.objects.create_user("11", "1", password="111")
        u2 = User.objects.create_user("22", "2", password="222")
        u3 = User.objects.create_user("33", "1", password="333")
        
        NaturalPerson.objects.create(u1, name="1", stu_grade="2018")
        NaturalPerson.objects.create(u2, name="2", stu_grade="2018")
        NaturalPerson.objects.create(u3, name="3", stu_grade="2019")

        AcademicTag.objects.create(atype=AcademicTag.Type.MAJOR, tag_content="数学")
        AcademicTag.objects.create(atype=AcademicTag.Type.MAJOR, tag_content="物理")
        AcademicTag.objects.create(atype=AcademicTag.Type.MAJOR, tag_content="中文")
        AcademicTag.objects.create(atype=AcademicTag.Type.MINOR, tag_content="数学")
        AcademicTag.objects.create(atype=AcademicTag.Type.MINOR, tag_content="物理")
        AcademicTag.objects.create(atype=AcademicTag.Type.MINOR, tag_content="中文")
        AcademicTag.objects.create(atype=AcademicTag.Type.DOUBLE_DEGREE, tag_content="数学")
        AcademicTag.objects.create(atype=AcademicTag.Type.DOUBLE_DEGREE, tag_content="物理")
        AcademicTag.objects.create(atype=AcademicTag.Type.DOUBLE_DEGREE, tag_content="中文")
        
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="1"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.Type.MAJOR, 
                tag_content="数学",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="1"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.Type.MINOR, 
                tag_content="中文",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="2"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.Type.MAJOR, 
                tag_content="物理",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="2"),
            status=AcademicEntry.EntryStatus.PRIVATE,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.Type.DOUBLE_DEGREE, 
                tag_content="数学",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="3"),
            status=AcademicEntry.EntryStatus.PRIVATE,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.Type.MAJOR, 
                tag_content="中文",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="3"),
            status=AcademicEntry.EntryStatus.PRIVATE,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.Type.MINOR,
                tag_content="物理",
        ))
        
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="1"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            atype=AcademicTextEntry.Type.INTERNSHIP,
            content="数学物理方法qwq",
        )
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="1"),
            status=AcademicEntry.EntryStatus.PRIVATE,
            atype=AcademicTextEntry.Type.SCIENTIFIC_RESEARCH,
            content="浩浩中文，卷帙浩繁。",
        )
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="2"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            atype=AcademicTextEntry.Type.SCIENTIFIC_RESEARCH,
            content="数学分析123456789",
        )
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="2"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            atype=AcademicTextEntry.Type.SCIENTIFIC_RESEARCH,
            content="物理物理物理物理物理11111111的",
        )
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="3"),
            status=AcademicEntry.EntryStatus.PRIVATE,
            atype=AcademicTextEntry.Type.INTERNSHIP,
            content="中文实习",
        )
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="3"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            atype=AcademicTextEntry.Type.CHALLENGE_CUP,
            content="离散数学的原理是非常美妙的",
        )

    def test_models(self):
        self.assertEqual(len(NaturalPerson.objects.all().values()), 3)
        self.assertEqual(len(AcademicTag.objects.all().values()), 9)
        self.assertEqual(len(AcademicTag.objects.filter(
            atype=AcademicTag.Type.DOUBLE_DEGREE
        ).values()), 3)
        self.assertEqual(len(AcademicTagEntry.objects.all().values()), 6)
        self.assertEqual(len(AcademicTagEntry.objects.filter(
            status=AcademicEntry.EntryStatus.PUBLIC
        ).values()), 3)
        self.assertEqual(len(AcademicTextEntry.objects.all().values()), 6)
        self.assertEqual(len(AcademicTextEntry.objects.filter(
            status=AcademicEntry.EntryStatus.PRIVATE
        ).values()), 2)

    def test_results_num(self):
        ...
        # self.assertEqual(len(get_search_results("数学")), 3)
        # self.assertEqual(len(get_search_results("物理")), 2)
        # self.assertEqual(len(get_search_results("中文")), 1)
        # self.assertEqual(len(get_search_results("1")), 1)
        # self.assertEqual(len(get_search_results("Q")), 1)
        # self.assertEqual(len(get_search_results("理")), 3)
    
    def test_results_type(self):
        ...
        # result_chinese = get_search_results("中文")
        # self.assertEqual("辅修专业" in result_chinese[0], True)
        # results_physics = get_search_results("物理")
        # for result in results_physics:
        #     if result["姓名"] == "1":
        #         self.assertEqual("实习经历" in result, True)
        #     else:
        #         self.assertEqual("主修专业" in result, True)
        #         self.assertEqual("本科生科研" in result, True)
    
    def test_results_entry(self):
        ...
        # result_1 = get_search_results("1")
        # self.assertEqual(len(result_1[0].keys()), 3)
        # self.assertEqual(len(result_1[0]["本科生科研"]), 2)
        # results_de = get_search_results("的")
        # for result in results_de:
        #     if result["姓名"] == "2":
        #         self.assertEqual(result["年级"], "2018")
        #         self.assertEqual(type(result["本科生科研"]), list)
        #         self.assertEqual(result["本科生科研"][0], "物理物理物理物理物理11111111的")
        #     else:
        #         self.assertEqual(result["年级"], "2019")
        #         self.assertEqual(result["挑战杯"], ["离散数学的原理是非常美妙的",])        
