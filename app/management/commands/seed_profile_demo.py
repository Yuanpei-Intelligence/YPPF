from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from app.models import (
    NaturalPerson,
    Participation,
    PersonProfileTag,
    ProfileTag,
    ProfileTagCategory,
)
from app.profile_utils import replace_person_profile_tags


class Command(BaseCommand):
    help = "为本地样本账号添加个人画像兴趣和技能演示数据"

    def add_arguments(self, parser):
        parser.add_argument("--username", help="指定样本账号；默认选择活动记录最多的学生")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("该命令只允许在 DEBUG 开发环境运行。")

        username = options.get("username")
        if username:
            try:
                person = NaturalPerson.objects.select_related("person_id").get(
                    person_id__username=username,
                    identity=NaturalPerson.Identity.STUDENT,
                )
            except NaturalPerson.DoesNotExist as exc:
                raise CommandError(f"找不到学生样本账号 {username}。") from exc
        else:
            eligible_statuses = [
                Participation.AttendStatus.APPLYSUCCESS,
                Participation.AttendStatus.ATTENDED,
            ]
            candidate = (
                Participation.objects.filter(status__in=eligible_statuses)
                .values("person_id")
                .annotate(activity_count=Count("id"))
                .order_by("-activity_count", "person_id")
                .first()
            )
            if candidate is None:
                raise CommandError("样本库中没有可用于画像展示的活动参与记录。")
            person = NaturalPerson.objects.select_related("person_id").get(
                pk=candidate["person_id"]
            )

        interest_names = ["摄影", "羽毛球", "桌游", "阅读", "旅行"]
        skill_names = ["编程", "数据分析", "演讲", "视频创作"]
        interest_tags = list(
            ProfileTag.objects.filter(
                name__in=interest_names,
                source=ProfileTag.Source.OFFICIAL,
                status=ProfileTag.Status.VISIBLE,
            )
        )
        skill_tags = list(
            ProfileTag.objects.filter(
                name__in=skill_names,
                source=ProfileTag.Source.OFFICIAL,
                status=ProfileTag.Status.VISIBLE,
            )
        )
        art_category = ProfileTagCategory.objects.get(slug="art")
        technology_category = ProfileTagCategory.objects.get(slug="technology")

        replace_person_profile_tags(
            person,
            interest_tags,
            skill_tags,
            {
                PersonProfileTag.Kind.INTEREST: [(art_category.pk, "城市漫游")],
                PersonProfileTag.Kind.SKILL: [(technology_category.pk, "提示词设计")],
            },
        )

        demo_user = person.person_id
        demo_user.set_password("test")
        demo_user.is_newuser = False
        demo_user.active = True
        demo_user.save(update_fields=["password", "is_newuser", "active"])

        self.stdout.write(self.style.SUCCESS("个人画像演示数据已导入。"))
        self.stdout.write(f"登录账号：{person.person_id.username}")
        self.stdout.write("样本密码：test")
        self.stdout.write("登录后访问：/stuinfo/")
