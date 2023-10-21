from typing import Dict
from datetime import datetime, date, time

from app.views_dependency import *
from app.models import NaturalPerson
from app.report_utils import *
from app.utils import get_person_or_org

class ReportView(ProfileTemplateView):
    template_name = "report.html"
    page_name = "使用报告"
    need_prepare = False
    
    def check_perm(self) -> None:
        super().check_perm()
        user = self.request.user
        if not user.is_person() or not get_person_or_org(user).is_teacher():
            return self.redirect("welcome")

    def get(self):
        return self.render()
    
    def _get_period(self, d: Dict[str, date]):
        def transform(x: str):
            try: 
                return datetime.strptime(x, "%Y-%m-%d")
            except:
                return None
        return tuple(map(transform, (
                d.get("yqp_start", None), d.get("yqp_end", None), 
                d.get("course_start", None), d.get("course_end", None))))

    def post(self):
        yqp_start, yqp_end, course_start, course_end = self._get_period(self.request.POST)
        self.extra_context.update({
            "yqp_records": query_point_records(yqp_start, yqp_end),
            "course_activities": query_course_activities(course_start, course_end)
        })
        return self.render()
