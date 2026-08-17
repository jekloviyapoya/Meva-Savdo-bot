"""Bot endi faqat Mini App'ga kirish nuqtasi.

Barcha amallar (savdo, mijozlar, buyurtmalar, hisobot) ilova ichida bajariladi.
Bot esa: ilovani ochish tugmasi, taklif havolalarini qabul qilish va bildirishnomalar.
"""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AUTHOR, COMPANY, VERSION, settings
from app.models import Customer, Role, Shop, User, UserStatus
from app.services import get_invite, managers, memberships, resolve_context

router = Router()


def app_url() -> str:
    base = settings.public_url
    return f"{base}/app" if base else ""


def open_kb(text: str = "🚀 Ilovani ochish") -> InlineKeyboardMarkup | None:
    url = app_url()
    if not url.startswith("https://"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]
    ])


NO_URL = (
    "⚠️ Ilova manzili sozlanmagan.\n"
    "Administrator <code>WEBAPP_URL</code> muhit o'zgaruvchisini "
    "(https://... ko'rinishida) qo'shishi kerak."
)


@router.message(CommandStart(deep_link=True))
async def start_invite(message: Message, command: CommandObject, bot: Bot,
                       session: AsyncSession):
    payload = (command.args or "").strip()
    if not payload.startswith("inv"):
        return await start(message, session)

    invite = await get_invite(session, payload[3:])
    if invite is None:
        await message.answer("🚫 Havola yaroqsiz yoki muddati tugagan. "
                             "Biznes egasidan yangi havola so'rang.")
        return

    shop = await session.get(Shop, invite.shop_id)
    already = next((u for u in await memberships(session, message.from_user.id)
                    if u.shop_id == shop.id), None)
    if already:
        await message.answer(f"Siz allaqachon «{shop.name}» ga ulangansiz.",
                             reply_markup=open_kb())
        return

    full_name = message.from_user.full_name or "Foydalanuvchi"
    customer = None
    if invite.role == Role.CUSTOMER:
        customer = Customer(shop_id=shop.id, name=full_name, tg_id=message.from_user.id)
        session.add(customer)
        await session.flush()

    user = User(
        shop_id=shop.id, tg_id=message.from_user.id,
        username=message.from_user.username, full_name=full_name,
        role=invite.role,
        status=UserStatus.APPROVED if invite.auto_approve else UserStatus.PENDING,
        customer_id=customer.id if customer else None,
    )
    session.add(user)
    invite.uses += 1
    await session.commit()

    if user.status == UserStatus.APPROVED:
        await message.answer(f"✅ «{shop.name}» ga qo'shildingiz!", reply_markup=open_kb())
    else:
        await message.answer(
            f"✅ Arizangiz «{shop.name}» ga yuborildi.\n"
            "⏳ Biznes egasi tasdiqlagach ilova ochiladi — sizga xabar keladi."
        )

    for manager in await managers(session, shop.id):
        try:
            await bot.send_message(
                manager.tg_id,
                f"🆕 <b>Yangi ariza</b>\n\n🏬 {shop.name}\n👤 {full_name}\n"
                f"🎭 Rol: {invite.role.value}\n\n"
                "Ilovadagi «Yana → Hodimlar» bo'limidan tasdiqlang.",
                reply_markup=open_kb("👤 Hodimlarni ochish"),
            )
        except Exception:
            continue


@router.message(CommandStart())
async def start(message: Message, session: AsyncSession):
    shop, user = await resolve_context(session, message.from_user.id)
    await session.commit()
    kb = open_kb()

    if not kb:
        await message.answer(NO_URL)
        return

    if user and user.status == UserStatus.PENDING:
        await message.answer("⏳ Arizangiz ko'rib chiqilmoqda. Tasdiqlangach xabar beramiz.")
        return

    if user and shop:
        await message.answer(
            f"🏬 <b>{shop.name}</b>\n"
            f"👤 {user.full_name} · {user.role.value}\n\n"
            "Barcha amallar ilovada: savdo, mijozlar, buyurtmalar, hisobot.",
            reply_markup=kb,
        )
        return

    await message.answer(
        "👋 <b>Savdo tizimiga xush kelibsiz!</b>\n\n"
        "Ilovani oching va login raqamingizni kiriting.\n"
        "Login — telefon raqamingiz, uni biznes egangiz yoki admin bergan.\n\n"
        "Login yo'q bo'lsa, biznes egasidan taklif havolasini so'rang.",
        reply_markup=kb,
    )


@router.message(Command("app"))
async def open_app(message: Message):
    kb = open_kb()
    await message.answer("Ilovani oching:" if kb else NO_URL, reply_markup=kb)


@router.message(Command("about"))
async def about(message: Message):
    await message.answer(
        "ℹ️ <b>Savdo tizimi</b>\n"
        f"Versiya {VERSION}\n\n"
        "━━━━━━━━━━━━━━━\n"
        f"👨‍💻 <b>Dasturchi: {AUTHOR}</b>\n"
        f"🏢 <b>{COMPANY}</b>\n"
        "━━━━━━━━━━━━━━━",
        reply_markup=open_kb(),
    )


@router.message(F.text)
async def fallback(message: Message):
    kb = open_kb()
    await message.answer(
        "Barcha amallar ilovada bajariladi 👇" if kb else NO_URL,
        reply_markup=kb,
    )
