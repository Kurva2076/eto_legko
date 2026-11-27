from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Настройки сервера"""

    model_config = SettingsConfigDict(
        env_file=(ROOT / '.env', ROOT / 'backend' / '.env'),
        extra='ignore',
    )

    keitaro_api_key: str
    keitaro_url: str = 'https://keitaro-for-tests.etolegko.com/admin_api/v1'
    database_url: str = f'sqlite:///{ROOT / "backend" / "adrobot.db"}'

    default_domain_id: int = 1813
    default_group_id: int = 10332
    default_source_id: int = 836

    @cached_property
    def api_base(self) -> str:
        """Базовый URL для обращения к Keitaro API"""
        stripped_url = self.keitaro_url.rstrip('/')
        if not stripped_url.endswith('/admin_api/v1'):
            return f'{stripped_url}/admin_api/v1'
        return stripped_url

    @cached_property
    def admin_base(self) -> str:
        """Базовый URL для обращения к админке Keitaro"""
        return self.api_base[: -len('/admin_api/v1')]


settings = Settings()
