from django.test import TestCase
from app.models import (
    User,
    NaturalPerson,
    AcademicTag,
    AcademicEntry,
    AcademicTagEntry,
    AcademicTextEntry,                        
)
from app.academic_utils import get_wait_audit_student


class GetWaitAuditStudentsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        u1 = User.objects.create_user("11", "1", password="111")
        u2 = User.objects.create_user("22", "2", password="222")
        u3 = User.objects.create_user("33", "1", password="333")
        u4 = User.objects.create_user("44", "1", password="333")
        u5 = User.objects.create_user("55", "1", password="333")
        
        NaturalPerson.objects.create(u1, name="1", stu_grade="2018")
        NaturalPerson.objects.create(u2, name="2", stu_grade="2018")
        NaturalPerson.objects.create(u3, name="3", stu_grade="2019")
        NaturalPerson.objects.create(u4, name="4", stu_grade="2020")
        NaturalPerson.objects.create(u5, name="5", stu_grade="2021")

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
            status=AcademicEntry.EntryStatus.PRIVATE,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.Type.MINOR, 
                tag_content="中文",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="2"),
            status=AcademicEntry.EntryStatus.WAIT_AUDIT,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.Type.MAJOR, 
                tag_content="物理",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="2"),
            status=AcademicEntry.EntryStatus.WAIT_AUDIT,
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
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="4"),
            status=AcademicEntry.EntryStatus.WAIT_AUDIT,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.Type.MINOR,
                tag_content="物理",
        ))
        AcademicTagEntry.objects.create(
            person=NaturalPerson.objects.get(name="5"),
            status=AcademicEntry.EntryStatus.OUTDATE,
            tag=AcademicTag.objects.get(
                atype=AcademicTag.Type.MINOR,
                tag_content="物理",
        ))
        
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="1"),
            status=AcademicEntry.EntryStatus.WAIT_AUDIT,
            atype=AcademicTextEntry.Type.INTERNSHIP,
            content="数学物理方法qwq",
        )
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="1"),
            status=AcademicEntry.EntryStatus.OUTDATE,
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
            status=AcademicEntry.EntryStatus.WAIT_AUDIT,
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
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="4"),
            status=AcademicEntry.EntryStatus.PUBLIC,
            atype=AcademicTextEntry.Type.CHALLENGE_CUP,
            content="离散数学的原理是非常美妙的",
        )
        AcademicTextEntry.objects.create(
            person=NaturalPerson.objects.get(name="5"),
            status=AcademicEntry.EntryStatus.WAIT_AUDIT,
            atype=AcademicTextEntry.Type.CHALLENGE_CUP,
            content="离散数学的原理是非常美妙的",
        )


    def test_models(self):
        self.assertEqual(len(NaturalPerson.objects.all().values()), 5)
        self.assertEqual(len(AcademicTag.objects.all().values()), 9)
        self.assertEqual(len(AcademicTagEntry.objects.all().values()), 8)
        self.assertEqual(len(AcademicTextEntry.objects.all().values()), 8)

    def test_result(self):
        result = get_wait_audit_student()
        self.assertEqual(len(result), 4)
        id_set = set([person.get_user().id for person in result])
        self.assertEqual(id_set, set([1, 2, 4, 5]))

    def test_result_after_status_change(self):
        entry1 = AcademicTextEntry.objects.select_for_update().get(content="数学物理方法qwq")
        entry1.status = AcademicEntry.EntryStatus.PUBLIC
        entry1.save()
        entry2 = AcademicTagEntry.objects.select_for_update().get(
            tag=AcademicTag.objects.get(
                atype=AcademicTag.Type.DOUBLE_DEGREE, 
                tag_content="数学"
            )
        )
        entry2.status = AcademicEntry.EntryStatus.PUBLIC
        entry2.save()
        entry3 = AcademicTextEntry.objects.select_for_update().get(
            content="离散数学的原理是非常美妙的",
            person=NaturalPerson.objects.get(name="3"))
        entry3.status = AcademicEntry.EntryStatus.OUTDATE
        entry3.save()

        result = get_wait_audit_student()
        self.assertEqual(len(result), 3)
        id_set = set([person.get_user().id for person in result])
        self.assertEqual(id_set, set([2, 4, 5]))
