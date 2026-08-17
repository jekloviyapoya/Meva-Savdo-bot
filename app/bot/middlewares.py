"""Har bir so'rovda sessiya, faol biznes va foydalanuvchini aniqlaydi.

Bizneslar ajratilishi shu yerdan boshlanadi: handler faqat o'z `shop` obyektini
oladi, boshqa biznes ma'lumotiga umuman yo'l topa olmaydi.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import AUTHOR, COMPANY, settings
from app.db import SessionMaker
from app.models import Role, UserStatus
from app.services import resolve_context

# Login va taklif havolasi bosqichlari — bu paytda foydalanuvchi hali biznesga
# bog'lanmagan bo'ladi, shuning uchun ular tekshiruvdan o'tkazilmaydi.
OPEN_STATE_PREFIXES = ("LoginForm", "JoinForm")


class DataMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with SessionMaker() as session:
            tg_user = data.get("event_from_user")
            shop, user = (None, None)
            if tg_user:
                shop, user = await resolve_context(session, tg_user.id)

            data["session"] = session
            data["shop"] = shop
            data["user"] = user
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


class LicenseMiddleware(BaseMiddleware):
    """Obuna muddati tugagan biznesni to'xtatadi (egasidan tashqari)."""

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        shop, user = data.get("shop"), data.get("user")
        if shop and not shop.license_ok:
            tg_user = data.get("event_from_user")
            privileged = bool(user and user.role == Role.OWNER) or bool(
                tg_user and tg_user.id in settings.super_admins
            )
            if privileged:
                return await handler(event, data)
            text = (
                "🔐 <b>Obuna muddati tugagan.</b>\n\n"
                f"Biznes: {shop.name}\n"
                "Biznes egasi to'lovni amalga oshirgach bot yana ishlaydi.\n\n"
                f"👤 {AUTHOR} — {COMPANY}"
            )
            if isinstance(event, Message):
                await event.answer(text)
            elif isinstance(event, CallbackQuery):
                await event.answer("Obuna muddati tugagan", show_alert=True)
            return
        return await handler(event, data)


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("user")

        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)

        state = data.get("state")
        if state is not None:
            current = await state.get_state()
            if current and current.split(":")[0] in OPEN_STATE_PREFIXES:
                return await handler(event, data)

        if isinstance(event, CallbackQuery) and event.data:
            if event.data.startswith("switch:"):
                return await handler(event, data)

        if user is None:
            if isinstance(event, Message):
                await event.answer("Kirish uchun /start ni bosing.")
            return
        if user.status == UserStatus.PENDING:
            if isinstance(event, Message):
                await event.answer("⏳ Arizangiz ko'rib chiqilmoqda.")
            return
        if user.status == UserStatus.BLOCKED:
            if isinstance(event, Message):
                await event.answer("🚫 Sizning kirishingiz cheklangan.")
            return
        return await handler(event, data)
