"""Railway / server uchun yagona ishga tushirish nuqtasi.

Uchala jarayonni bitta konteynerda birga yuritadi:
  • savdo boti      • admin (litsenziya) boti      • web panel

Kerak bo'lsa muhit o'zgaruvchilari orqali o'chirib qo'yiladi:
  RUN_BOT=false  RUN_LICENSE_BOT=false  RUN_WEB=false

Muallif: Ulug'bek Bekbergenov — NM GROUP
"""
from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings
from app.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nm")


def enabled(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


async def run_sales_bot() -> None:
    from app.bot.main import build_dispatcher

    bot = Bot(settings.bot_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher()
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Savdo boti ishga tushdi")
    await dp.start_polling(bot, handle_signals=False)


async def run_admin_bot() -> None:
    from app.license_bot.main import dp

    bot = Bot(settings.license_bot_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Admin bot ishga tushdi")
    await dp.start_polling(bot, handle_signals=False)


async def run_web() -> None:
    import uvicorn

    from app.web.main import app

    config = uvicorn.Config(app, host="0.0.0.0", port=settings.port,
                            log_level="info", access_log=False)
    log.info("Web panel: 0.0.0.0:%s", settings.port)
    await uvicorn.Server(config).serve()


async def guard(coro, name: str) -> None:
    """Bitta bot yiqilsa ham qolgan xizmatlar ishlashda davom etsin."""
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.error("%s to'xtadi: %s", name, exc)


async def main() -> None:
    await init_db()

    tasks: list[asyncio.Task] = []
    if enabled("RUN_WEB"):
        tasks.append(asyncio.create_task(run_web(), name="web"))
    if enabled("RUN_BOT") and settings.bot_token:
        tasks.append(asyncio.create_task(guard(run_sales_bot(), "Savdo boti"), name="bot"))
    elif enabled("RUN_BOT"):
        log.warning("BOT_TOKEN yo'q — savdo boti ishga tushmadi")
    if enabled("RUN_LICENSE_BOT") and settings.license_bot_token:
        tasks.append(asyncio.create_task(guard(run_admin_bot(), "Admin bot"), name="admin-bot"))
    elif enabled("RUN_LICENSE_BOT"):
        log.warning("LICENSE_BOT_TOKEN yo'q — admin bot ishga tushmadi")

    if not tasks:
        raise SystemExit("Hech narsa yoqilmagan. .env dagi tokenlarni tekshiring.")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("To'xtatildi")
