class ServiceError(Exception):
    """Ошибка бизнес-логики приложения: запись не найдена в БД, недопустимое состояние данных и т.п."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f'{status}: {detail}')
