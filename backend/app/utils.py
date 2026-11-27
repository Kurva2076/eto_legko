from datetime import datetime, timezone


def now() -> datetime:
    """Получение текущего времени в нулевом часовом поясе (UTC+0)"""
    return datetime.now(timezone.utc)
