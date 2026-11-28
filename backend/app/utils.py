from datetime import datetime, timezone


def now() -> datetime:
    """Получение текущего времени в нулевом часовом поясе (UTC+0)"""
    return datetime.now(timezone.utc)


def to_utc_iso(value: datetime | None) -> str | None:
    """
    Приводит время из БД к ISO-строке в UTC.

    :param value: Время из БД или None.
    :return: ISO-строка со смещением +00:00 или None, если времени нет.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
