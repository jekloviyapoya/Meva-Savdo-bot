"""
NM GROUP — Savdo boti
Muallif: Ulug'bek Bekbergenov (NM GROUP)
"""
from pydantic_settings import BaseSettings, SettingsConfigDict

AUTHOR = "Ulug'bek Bekbergenov"
COMPANY = "NM GROUP"
VERSION = "1.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str = ""
    bot_username: str = ""   # taklif havolalari uchun, masalan: nm_savdo_bot

    license_bot_token: str = ""
    super_admin_ids: str = ""
    license_monthly_price: int = 300000
    license_card: str = ""

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/nm_savdo"

    web_secret: str = "change-me"
    web_admin_login: str = "admin"
    web_admin_password: str = "admin12345"
    web_host: str = "0.0.0.0"
    web_port: int = 8000

    @property
    def super_admins(self) -> list[int]:
        return [int(x) for x in self.super_admin_ids.replace(" ", "").split(",") if x]


settings = Settings()
