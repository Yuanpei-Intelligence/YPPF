from scheduler.periodic import periodical
from generic.models import User


@periodical('cron', 'recover_credits_per_month', day=1, hour=6)
def recover_credits_per_month():
    from Appointment.models import Participant
    from utils.models.query import qsvlist, sfilter, sq
    appointers = sfilter(Participant.hidden, False)
    users = User.objects.filter(sq(User.active, True))
    users = users.filter(id__in=qsvlist(appointers, Participant.Sid, User.id))
    User.objects.bulk_recover_credit(User.objects.all(), 1, "每月恢复信用分")
