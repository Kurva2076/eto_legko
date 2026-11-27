import time
from typing import Any

import httpx

from app.config import settings


class KeitaroError(Exception):
    """"Ошибка, возникающая при обращении к Keitaro"""

    def __init__(self, status: int, detail: Any):
        self.status = status
        self.detail = detail
        super().__init__(f'Keitaro {status}: {detail}')


class KeitaroClient:
    """Класс-прослойка для взаимодействия с Keitaro"""

    def __init__(self, base_url: str, api_key: str):
        self.base = base_url.rstrip('/')
        self.http = httpx.Client(headers={'Api-Key': api_key}, timeout=20.0)
        self._offers_cache: tuple[float, list[dict]] | None = None

    def request(self, method: str, path: str, **kwargs) -> Any:
        """
        Запрос на Keitaro API

        :param method: HTTP метод.
        :param path: Путь к API-ресурсу.
        :param kwargs: Дополнительные параметры для запроса.
        :return: Результат запроса.
        :raises: KeitaroError: Возникает либо из-за некорректных данных, либо из-за ошибки сервера
        """
        new_path = path if path.startswith('/') else f'/{path}'
        try:
            response = self.http.request(method, f'{self.base}{new_path}', **kwargs)
        except httpx.HTTPError as e:
            raise KeitaroError(502, f'Keitaro недоступен: {e}') from e
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise KeitaroError(response.status_code, detail)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    def get(self, path: str, **params) -> Any:
        """
        Выполняет GET-запрос.

        :param path: Путь к API-ресурсу.
        :param params: Query-параметры для GET-запроса.
        :return: Ответ сервера.
        """
        return self.request('GET', path, params=params or None)

    def post(self, path: str, body: dict | None = None) -> Any:
        """
        Выполняет POST-запрос.

        :param path: Путь к API-ресурсу.
        :param body: Тело POST-запроса.
        :return: Ответ сервера.
        """
        return self.request('POST', path, json=body or {})

    def put(self, path: str, body: dict) -> Any:
        """
        Выполняет PUT-запрос.

        :param path: Путь к API-ресурсу.
        :param body: Тело PUT-запроса.
        :return: Ответ сервера.
        """
        return self.request('PUT', path, json=body)

    def delete(self, path: str) -> Any:
        """
        Выполняет DELETE-запрос.

        :param path: Путь к API-ресурсу.
        :return: Ответ сервера.
        """
        return self.request('DELETE', path)

    def offers(self, time_to_leave: float = 60.0) -> list[dict]:
        """
        Получение списка офферов.

        :param time_to_leave: Время, через которое список офферов будет считаться неактуальным.
        :return: Актуальный список офферов.
        """
        now = time.monotonic()
        if self._offers_cache and now - self._offers_cache[0] < time_to_leave:
            return self._offers_cache[1]
        data = self.get('/offers') or []
        self._offers_cache = (now, data)
        return data

    def offer(self, offer_id: int) -> dict:
        """
        Получение информации об оффере с id = offer_id.

        :param offer_id: ID-шник оффера.
        :return: Информация об оффере.
        """
        return self.get(f'/offers/{offer_id}')

    def domains(self) -> list[dict]:
        """Получение списка информации о доменах наших клиентов"""
        return self.get('/domains') or []

    def groups(self) -> list[dict]:
        """Получение списка групп кампаний"""
        return self.get('/groups', type='campaigns') or []

    def sources(self) -> list[dict]:
        """Получение списка источников"""
        return self.get('/traffic_sources') or []


client = KeitaroClient(settings.api_base, settings.keitaro_api_key)


def get_client() -> KeitaroClient:
    """Получение прослойки для взаимодействия с Keiя"""
    return client
