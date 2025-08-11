from datetime import datetime, timedelta

from django.db import transaction

from app.models import (
    User,
)
from app.config import *
from generic.models import YQPointRecord
from scheduler.periodic import periodical
from feedback.feedback_utils import inform_notification
from feedback.models import Feedback

__all__ = [
    'public_feedback_per_hour',
]


@periodical('cron', 'feedback_public_updater', minute=5)
@transaction.atomic
def public_feedback_per_hour():
    '''查找距离组织公开反馈24h内没被审核的反馈，将其公开'''
    time = datetime.now() - timedelta(days=1)
    feedbacks = Feedback.objects.filter(
        issue_status=Feedback.IssueStatus.ISSUED,
        public_status=Feedback.PublicStatus.PRIVATE,
        publisher_public=True,
        org_public=True,
        public_time__lte=time,
    )
    feedbacks.select_for_update().update(
        public_status=Feedback.PublicStatus.PUBLIC)
    for feedback in feedbacks:
        User.objects.modify_YQPoint(feedback.person.get_user(),
                                    CONFIG.yqpoint.per_feedback,
                                    "问题反馈", YQPointRecord.SourceType.FEEDBACK)
        inform_notification(feedback.org.otype.incharge, feedback.person,
                            f"您的反馈[{feedback.title}]已被公开",
                            feedback, anonymous=False)
        inform_notification(feedback.org.otype.incharge, feedback.org,
                            f"您处理的反馈[{feedback.title}]已自动公开",
                            feedback, anonymous=False)