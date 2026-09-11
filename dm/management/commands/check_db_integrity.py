from django.core.management.base import BaseCommand
from django.db.models import Count, Exists, OuterRef

from app.models import Position, CourseParticipant
from utils.models.semester import Semester


class Command(BaseCommand):
    help = "只读检查数据库中未在模型中表达的隐性约束，输出违规记录（不修改任何数据）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--verbose", action="store_true",
            help="打印每条违规记录的具体字段（默认只打印数量）",
        )
        parser.add_argument(
            "--output", type=str, default=None,
            help="将检查结果导出为文本文件的路径",
        )

    # ---- 约束检查：每个方法返回违规的 Position QuerySet ----

    def _check_annual_and_single(self):
        """C1 (issue #957 原文): 同一人+小组+学年，不应同时存在在职的 ANNUAL
        职务与单学期（Fall/Spring）职务。UniqueConstraint 无法表达这种
        “ANNUAL 与单学期不同时 active”的约束。"""
        single = Position.objects.filter(
            status=Position.Status.INSERVICE,
            semester__in=[Semester.FALL, Semester.SPRING],
        )
        sub = single.filter(
            person=OuterRef("person"),
            org=OuterRef("org"),
            year=OuterRef("year"),
        )
        return (
            Position.objects.filter(
                status=Position.Status.INSERVICE,
                semester=Semester.ANNUAL,
            )
            .filter(Exists(sub))
        )

    def _check_duplicate_position(self):
        """C2 (#968 同类): 同一人+小组+学年+学期不应出现重复 Position。
        历史脏数据可能绕过 UniqueConstraint(person, org, semester, year)。"""
        dups = (
            Position.objects.values("person", "org", "year", "semester")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        ids = []
        for d in dups:
            rows = Position.objects.filter(
                person=d["person"],
                org=d["org"],
                year=d["year"],
                semester=d["semester"],
            ).values_list("id", flat=True)
            ids.extend(rows)
        return Position.objects.filter(id__in=ids)

    def _check_course_with_annual(self):
        """C3 (issue #957 评论补充, Deophius): 同一人+学年，选了书院课程不应
        同时拥有在职的 ANNUAL 职务。
        业务假设：CourseParticipant.course.year 与 Position.year 对应；
        若实际语义不同（如仅限特定 CourseType），需据此调整子查询。

        修正：限定 status=SUCCESS，排除 FAILED/UNSELECT 等无效选课记录，
        避免虚增违规数。"""
        sub = CourseParticipant.objects.filter(
            person=OuterRef("person"),
            course__year=OuterRef("year"),
            status=CourseParticipant.Status.SUCCESS,
        )
        return (
            Position.objects.filter(
                status=Position.Status.INSERVICE,
                semester=Semester.ANNUAL,
            )
            .filter(Exists(sub))
        )

    def _format_row(self, p):
        return (
            f"  id={p.id} person={p.person_id} org={p.org_id} "
            f"year={p.year} semester={p.get_semester_display()} "
            f"status={p.get_status_display()}"
        )

    def handle(self, *args, **options):
        verbose = options["verbose"]
        output_path = options["output"]
        lines = []

        checks = [
            (
                "C1",
                "同一人+小组+学年不可同时拥有在职的 ANNUAL 与单学期职务",
                self._check_annual_and_single,
            ),
            (
                "C2",
                "同一人+小组+学年+学期不应出现重复 Position (#968 同类)",
                self._check_duplicate_position,
            ),
            (
                "C3",
                "同一人+学年选书院课程不应同时拥有在职的 ANNUAL 职务",
                self._check_course_with_annual,
            ),
        ]

        total_violations = 0
        for cid, desc, fn in checks:
            qs = fn()
            count = qs.count()
            total_violations += count
            if count:
                header = f"[{cid}] {desc} —— 违规 {count} 条"
                self.stdout.write(self.style.WARNING(header))
            else:
                header = f"[{cid}] {desc} —— 通过（0 条违规）"
                self.stdout.write(self.style.SUCCESS(header))
            lines.append(header)
            if verbose:
                for p in qs[:200]:
                    row = self._format_row(p)
                    self.stdout.write(row)
                    lines.append(row)

        summary = f"=== 合计违规记录：{total_violations} 条 ==="
        self.stdout.write(self.style.NOTICE(summary))
        lines.append(summary)

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self.stdout.write(self.style.SUCCESS(f"报告已导出：{output_path}"))
