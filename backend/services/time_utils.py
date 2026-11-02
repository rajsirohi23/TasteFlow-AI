from datetime import date, datetime, timedelta

import config


def local_now() -> datetime:
    return datetime.utcnow() + timedelta(minutes=config.RESTAURANT_UTC_OFFSET_MINUTES)


def local_today() -> date:
    return local_now().date()


def to_local(dt: datetime) -> datetime:
    return dt + timedelta(minutes=config.RESTAURANT_UTC_OFFSET_MINUTES)
