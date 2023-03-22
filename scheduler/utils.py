from datetime import datetime, timedelta


def as_schedule_time(run_time: datetime | timedelta | None = None):
    if isinstance(run_time, datetime):
        return run_time
    elif isinstance(run_time, timedelta):
        return datetime.now() + run_time
    else:
        return datetime.now() + timedelta(seconds=5)
