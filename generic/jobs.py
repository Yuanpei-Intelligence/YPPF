from scheduler.periodic import periodical
from generic.models import User


@periodical('cron', 'recover_credits_per_month', day=1, hour=6)
def recover_credits_per_month():
    User.objects.bulk_recover_credit(User.objects.all(), 1, "每月恢复信用分")
