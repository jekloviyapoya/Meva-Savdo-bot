"""Savdo boti — Mini App'ga kirish nuqtasi.

Muallif: Ulug'bek Bekbergenov — NM GROUP
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonWebApp, WebAppInfo

from app.bot.handlers import entry
from app.bot.middlewares import DataMiddleware
from app.config import settings
from app.db import init_db

log = logging.getLogger("bot")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    for observer in (dp.message, dp.callback_query):
        observer.middleware(DataMiddleware())
    dp.include_router(entry.router)
    return dp


async def setup_menu_button(bot: Bot) -> None:
    """Telegramdagi pastki «Menu» tugmasini ilovaga bog'laydi."""
    url = entry.app_url()
    if not url.startswith("https://"):
        log.warning("WEBAPP_URL sozlanmagan — Menu tugmasi qo'yilmadi")
        return
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Savdo", web_app=WebAppInfo(url=url))
        )
        log.info("Menu tugmasi ilovaga bog'landi: %s", url)
    except Exception as exc:
        log.warning("Menu tugmasi qo'yilmadi: %s", exc)


async def main() -> None:
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN .env faylida ko'rsatilmagan")
    logging.basicConfig(level=logging.INFO)
    await init_db()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await setup_menu_button(bot)
    await build_dispatcher().start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
