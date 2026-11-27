from collections.abc import Generator
from datetime import datetime

from sqlalchemy import create_engine, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker

from app.config import settings
from app.utils import now

connect_args = {'check_same_thread': False} if settings.database_url.startswith('sqlite') else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
local_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Базовый класс для моделей"""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def get_db() -> Generator[Session, None, None]:
    """Обеспечивает сессию базы данных на время выполнения запроса"""
    db = local_session()
    try:
        yield db
    finally:
        db.close()
