from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT / ".env", ROOT / "backend" / ".env"),
        extra="ignore",
    )

    keitaro_api_key: str
    keitaro_url: str = "https://keitaro-for-tests.etolegko.com/admin_api/v1"
    database_url: str = f"sqlite:///{ROOT / 'backend' / 'adrobot.db'}"

    # Значения по умолчанию для стенда; если таких id нет в API — берётся первый элемент справочника
    default_domain_id: int = 1813
    default_group_id: int = 10332
    default_source_id: int = 836

    @property
    def api_base(self) -> str:
        url = self.keitaro_url.rstrip("/")
        if not url.endswith("/admin_api/v1"):
            url += "/admin_api/v1"
        return url

    @property
    def admin_base(self) -> str:
        return self.api_base[: -len("/admin_api/v1")]


settings = Settings()
