from typing import Optional
from datetime import datetime

from django.db.models import Sum, Count

from app.models import Activity
from generic.models import YQPointRecord

__all__ = [
    "query_point_records",
    "query_course_activities",
]

def query_point_records(start_time: Optional[datetime], end_time: Optional[datetime]):
    """
    :param start_time, end_time: 查询起止时间
    :type start_time, end_time: Optional[datetime] 
    :return [("来源", 变化量), ...]
    """
    records = YQPointRecord.objects.all()
    if start_time is not None:
        records = records.filter(time__gte=start_time)
    if end_time is not None:
        records = records.filter(time__lte=end_time)
    
    type_amount = records.values("source_type").annotate(Sum("delta"))
    return [(YQPointRecord.SourceType(x["source_type"]).label, x["delta__sum"])
            for x in type_amount]


def query_course_activities(start_time: Optional[datetime],
                            end_time: Optional[datetime]):
    activities = Activity.objects.filter(
        category=Activity.ActivityCategory.COURSE)
    if start_time is not None:
        activities = activities.filter(start__gte=start_time)
    if end_time is not None:
        activities = activities.filter(start__lte=end_time)

    type_amount = activities.values(
        "organization_id__oname").annotate(times=Count("*"))
    return [(x["organization_id__oname"], x["times"])
            for x in type_amount]


