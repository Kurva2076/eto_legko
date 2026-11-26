import time
from typing import Any

import httpx

from .config import settings


class KeitaroError(Exception):
    def __init__(self, status: int, detail: Any):
        self.status = status
        self.detail = detail
        super().__init__(f"Keitaro {status}: {detail}")


class KeitaroClient:
    def __init__(self, base_url: str, api_key: str):
        self.base = base_url.rstrip("/")
        self.http = httpx.Client(headers={"Api-Key": api_key}, timeout=20.0)
        self._offers_cache: tuple[float, list[dict]] | None = None

    def request(self, method: str, path: str, **kwargs) -> Any:
        try:
            r = self.http.request(method, self.base + path, **kwargs)
        except httpx.HTTPError as e:
            raise KeitaroError(502, f"Keitaro недоступен: {e}") from e
        if r.status_code >= 400:
            try:
                detail = r.json()
            except ValueError:
                detail = r.text
            raise KeitaroError(r.status_code, detail)
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def get(self, path: str, **params) -> Any:
        return self.request("GET", path, params=params or None)

    def post(self, path: str, body: dict | None = None) -> Any:
        return self.request("POST", path, json=body or {})

    def put(self, path: str, body: dict) -> Any:
        return self.request("PUT", path, json=body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    # --- справочники ---
    def offers(self, ttl: float = 60.0) -> list[dict]:
        now = time.monotonic()
        if self._offers_cache and now - self._offers_cache[0] < ttl:
            return self._offers_cache[1]
        data = self.get("/offers") or []
        self._offers_cache = (now, data)
        return data

    def offer(self, offer_id: int) -> dict:
        return self.get(f"/offers/{offer_id}")

    def domains(self) -> list[dict]:
        return self.get("/domains") or []

    def groups(self) -> list[dict]:
        return self.get("/groups", type="campaigns") or []

    def sources(self) -> list[dict]:
        return self.get("/traffic_sources") or []


client = KeitaroClient(settings.api_base, settings.keitaro_api_key)


def get_client() -> KeitaroClient:
    return client
