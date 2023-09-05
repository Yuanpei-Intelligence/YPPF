from scheduler.periodic import periodical


__all__ = [
    'unlock_credit_achievements',
]


# 未扣除信用分
@periodical('cron', job_id='解锁信用分成就', day=1, hour=6, minute=0)
def unlock_credit_achievements():
    raise NotImplementedError
