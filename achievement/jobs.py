from scheduler.periodic import periodical


# 未扣除信用分
@periodical('cron', day=1, hour=6, minute=0)
def unlock_credit_achievements():
    raise NotImplementedError
