"""
NM GROUP — Savdo boti
Muallif: Ulug'bek Bekbergenov (NM GROUP)
"""
import os

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
    def async_database_url(self) -> str:
        """Railway `postgresql://...` beradi — asyncpg drayveriga o'giramiz."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        # asyncpg `sslmode` ni tushunmaydi, Railway ichki tarmog'ida kerak emas
        for junk in ("?sslmode=require", "&sslmode=require", "?sslmode=disable"):
            url = url.replace(junk, "")
        return url

    @property
    def port(self) -> int:
        """Railway/Heroku PORT ni beradi, aks holda WEB_PORT ishlatiladi."""
        return int(os.getenv("PORT") or self.web_port)

    @property
    def super_admins(self) -> list[int]:
        return [int(x) for x in self.super_admin_ids.replace(" ", "").split(",") if x]


settings = Settings()
