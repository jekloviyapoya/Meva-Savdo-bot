"""Do'kon savdo boti — NM GROUP (Ulug'bek Bekbergenov)."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import (
    catalog, common, customer_side, customers, orders, sales, staff
)
from app.bot.middlewares import AuthMiddleware, DataMiddleware, LicenseMiddleware
from app.config import settings
from app.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    for observer in (dp.message, dp.callback_query):
        observer.middleware(DataMiddleware())
        observer.middleware(LicenseMiddleware())
        observer.middleware(AuthMiddleware())

    dp.include_router(common.router)
    dp.include_router(catalog.router)
    dp.include_router(staff.router)
    dp.include_router(customers.router)
    dp.include_router(sales.router)
    dp.include_router(orders.router)
    dp.include_router(customer_side.router)
    return dp


async def main() -> None:
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN .env faylida ko'rsatilmagan")

    await init_db()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher()
    logging.info("Savdo boti ishga tushdi (multi-tenant)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
