from django.test import TestCase
from django.contrib.auth.models import User
from app.models import (
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
        u1 = User.objects.create(username="11", password="111")
        u2 = User.objects.create(username="22", password="222")
        u3 = User.objects.create(username="33", password="333")
        
        NaturalPerson.objects.create(person_id=u1, name="1", stu_grade="2018")
        NaturalPerson.objects.create(person_id=u2, name="2", stu_grade="2018")
        NaturalPerson.objects.create(person_id=u3, name="3", stu_grade="2019")

        AcademicTag.objects.create(atype=AcademicTag.AcademicTagType.MAJOR, tag_content="数学")
        AcademicTag.objects.create(atype=AcademicTag.AcademicTagType.MAJOR, tag_content="物理")
        AcademicTag.objects.create(atype=AcademicTag.AcademicTagType.MAJOR, tag_content="中文")
        AcademicTag.objects.create(atype=AcademicTag.AcademicTagType.MINOR, tag_content="数学")
        AcademicTag.objects.create(atype=AcademicTag.AcademicTagType.MINOR, tag_content="物理")
        AcademicTag.objects.create(atype=AcademicTag.AcademicTagType.MINOR, tag_content="中文")
        AcademicTag.objects.create(atype=AcademicTag.AcademicTagType.DOUBLE_DEGREE, tag_content="数学")
        AcademicTag.objects.create(atype=AcademicTag.AcademicTagType.DOUBLE_DEGREE, tag_content="物理")
        AcademicTag.objects.create(atype=AcademicTag.AcademicTagType.DOUBLE_DEGREE, tag_content="中文")
        
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="1"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.AcademicTagType.MAJOR, 
                tag_content="数学",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="1"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.AcademicTagType.MINOR, 
                tag_content="中文",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="2"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.AcademicTagType.MAJOR, 
                tag_content="物理",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="2"),
            status=AcademicEntry.EntryStatus.PRIVATE,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.AcademicTagType.DOUBLE_DEGREE, 
                tag_content="数学",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="3"),
            status=AcademicEntry.EntryStatus.PRIVATE,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.AcademicTagType.MAJOR, 
                tag_content="中文",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="3"),
            status=AcademicEntry.EntryStatus.PRIVATE,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.AcademicTagType.MINOR,
                tag_content="物理",
        ))
        
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="1"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            atype=AcademicTextEntry.AcademicTextType.INTERNSHIP,
            content="数学物理方法qwq",
        )
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="1"),
            status=AcademicEntry.EntryStatus.PRIVATE,
            atype=AcademicTextEntry.AcademicTextType.SCIENTIFIC_RESEARCH,
            content="浩浩中文，卷帙浩繁。",
        )
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="2"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            atype=AcademicTextEntry.AcademicTextType.SCIENTIFIC_RESEARCH,
            content="数学分析123456789",
        )
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="2"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            atype=AcademicTextEntry.AcademicTextType.SCIENTIFIC_RESEARCH,
            content="物理物理物理物理物理11111111的",
        )
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="3"),
            status=AcademicEntry.EntryStatus.PRIVATE,
            atype=AcademicTextEntry.AcademicTextType.INTERNSHIP,
            content="中文实习",
        )
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="3"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            atype=AcademicTextEntry.AcademicTextType.CHALLENGE_CUP,
            content="离散数学的原理是非常美妙的",
        )

    def test_models(self):
        self.assertEqual(len(NaturalPerson.objects.all().values()), 3)
        self.assertEqual(len(AcademicTag.objects.all().values()), 9)
        self.assertEqual(len(AcademicTag.objects.filter(
            atype=AcademicTag.AcademicTagType.DOUBLE_DEGREE
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
        self.assertEqual(len(get_search_results("数学")), 3)
        self.assertEqual(len(get_search_results("物理")), 2)
        self.assertEqual(len(get_search_results("中文")), 1)
        self.assertEqual(len(get_search_results("1")), 1)
        self.assertEqual(len(get_search_results("Q")), 1)
        self.assertEqual(len(get_search_results("理")), 3)
    
    def test_results_type(self):
        result_chinese = get_search_results("中文")
        self.assertEqual(result_chinese[0].__contains__("辅修专业"), True)
        results_physics = get_search_results("物理")
        for result in results_physics:
            if result["姓名"] == "1":
                self.assertEqual(result.__contains__("实习经历"), True)
            else:
                self.assertEqual(result.__contains__("主修专业"), True)
                self.assertEqual(result.__contains__("科研经历"), True)
    
    def test_results_entry(self):
        result_1 = get_search_results("1")
        self.assertEqual(len(result_1[0].keys()), 3)
        self.assertEqual(len(result_1[0]["科研经历"]), 2)
        results_de = get_search_results("的")
        for result in results_de:
            if result["姓名"] == "2":
                self.assertEqual(result["年级"], "2018")
                self.assertEqual(type(result["科研经历"]), tuple)
                self.assertEqual(result["科研经历"][0], "物理物理物理物理物理11111111的")
            else:
                self.assertEqual(result["年级"], "2019")
                self.assertEqual(result["挑战杯经历"], ("离散数学的原理是非常美妙的",))        
