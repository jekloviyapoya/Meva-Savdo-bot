"""Admin bot — bizneslarni ro'yxatdan o'tkazadi va oylik obunani boshqaradi.

Muallif: Ulug'bek Bekbergenov — NM GROUP
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from app.config import AUTHOR, COMPANY, settings
from app.db import SessionMaker, init_db
from app.models import LicensePayment, Role, Shop, User, UserStatus
from app.services import (
    create_shop, extend_license, generate_password, hash_password, money,
    normalize_phone,
)

logging.basicConfig(level=logging.INFO)
dp = Dispatcher(storage=MemoryStorage())


class NewBusiness(StatesGroup):
    name = State()
    owner_name = State()
    owner_phone = State()


def is_super(user_id: int) -> bool:
    return user_id in settings.super_admins


def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏢 Yangi biznes"), KeyboardButton(text="📋 Bizneslar")],
        ],
        resize_keyboard=True,
    )


def shops_kb(shops: list[Shop]):
    kbd = InlineKeyboardBuilder()
    for shop in shops:
        mark = "✅" if shop.license_ok else "⛔️"
        kbd.button(text=f"{mark} {shop.name} ({max(shop.days_left, 0)} kun)",
                   callback_data=f"shop:{shop.id}")
    kbd.adjust(1)
    return kbd.as_markup()


def shop_kb(shop_id: int):
    kbd = InlineKeyboardBuilder()
    kbd.button(text="➕ 1 oy", callback_data=f"ext:1:{shop_id}")
    kbd.button(text="➕ 3 oy", callback_data=f"ext:3:{shop_id}")
    kbd.button(text="➕ 12 oy", callback_data=f"ext:12:{shop_id}")
    kbd.button(text="🔑 Egasining parolini yangilash", callback_data=f"pwd:{shop_id}")
    kbd.button(text="⛔️ To'xtatish", callback_data=f"ext:stop:{shop_id}")
    kbd.button(text="⬅️ Ro'yxat", callback_data="list")
    kbd.adjust(3, 1, 1, 1)
    return kbd.as_markup()


PAYMENT_INFO = (
    "💳 <b>Oylik to'lov</b>\n\n"
    f"Narx: <b>{money(settings.license_monthly_price)} so'm / oy</b>\n"
    f"Karta: <code>{settings.license_card or '—'}</code>\n\n"
    "To'lovni amalga oshirib, chek rasmini shu botga yuboring.\n\n"
    f"👨‍💻 {AUTHOR} — {COMPANY}"
)


@dp.message(CommandStart())
async def start(message: Message):
    if not is_super(message.from_user.id):
        await message.answer(
            "🔐 <b>Admin bot</b>\n\n"
            "Bu bot orqali bizneslar ro'yxatdan o'tkaziladi va obuna boshqariladi.\n"
            "Biznesingizni ulash uchun quyidagi ma'lumotlarni yuboring:\n"
            "• Biznes nomi\n• Ism-familiyangiz\n• Telefon raqamingiz (login bo'ladi)\n\n"
            + PAYMENT_INFO
        )
        return
    await message.answer(
        f"👋 Salom! Sizning Telegram ID: <code>{message.from_user.id}</code>",
        reply_markup=admin_menu(),
    )
    await show_list(message)


# ------------------------- Yangi biznes -------------------------

@dp.message(F.text == "🏢 Yangi biznes")
@dp.message(Command("new"))
async def new_business(message: Message, state: FSMContext):
    if not is_super(message.from_user.id):
        return
    await message.answer("🏢 Biznes (do'kon) nomini yozing:")
    await state.set_state(NewBusiness.name)


@dp.message(NewBusiness.name, F.text)
async def nb_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("👤 Biznes egasining ism-familiyasini yozing:")
    await state.set_state(NewBusiness.owner_name)


@dp.message(NewBusiness.owner_name, F.text)
async def nb_owner(message: Message, state: FSMContext):
    await state.update_data(owner_name=message.text.strip())
    await message.answer(
        "📱 Egasining telefon raqamini yozing — <b>shu raqam uning logini</b> bo'ladi.\n"
        "Masalan: +998901234567"
    )
    await state.set_state(NewBusiness.owner_phone)


@dp.message(NewBusiness.owner_phone, F.text)
async def nb_phone(message: Message, state: FSMContext):
    phone = normalize_phone(message.text)
    if not phone:
        await message.answer("Raqamni to'g'ri kiriting. Masalan: +998901234567")
        return
    data = await state.get_data()
    await state.clear()

    async with SessionMaker() as session:
        clash = await session.scalar(select(User).where(User.phone == phone))
        shop, owner, password = await create_shop(
            session, data["name"], data["owner_name"], phone
        )
        await session.commit()
        shop_name, code, until = shop.name, shop.code, shop.license_until

    bot_link = f"https://t.me/{settings.bot_username.lstrip('@')}" if settings.bot_username else "savdo boti"
    warning = ("\n\n⚠️ Diqqat: bu raqam boshqa biznesda ham ishlatilgan. "
               "Egasi kirganda qaysi biznesga o'tishni tanlaydi.") if clash else ""

    await message.answer(
        f"✅ <b>{shop_name}</b> ro'yxatdan o'tkazildi.\n\n"
        f"🔑 Login: <code>{phone}</code>\n"
        f"🔒 Web parol: <code>{password}</code>\n"
        f"🏷 Biznes kodi: <code>{code}</code>\n"
        f"🗓 Sinov muddati: {until:%d.%m.%Y} gacha\n\n"
        f"Egasi {bot_link} ga <b>/start</b> yuborib, login raqamini kiritsa "
        f"biznesiga kiradi. Hodim va mijozlarni o'zi taklif havolasi orqali qo'shadi."
        + warning,
        reply_markup=admin_menu(),
    )


# ------------------------- Ro'yxat -------------------------

@dp.message(F.text == "📋 Bizneslar")
@dp.message(Command("shops"))
async def show_list(message: Message):
    if not is_super(message.from_user.id):
        return
    async with SessionMaker() as session:
        shops = list(await session.scalars(select(Shop).order_by(Shop.name)))
    if not shops:
        await message.answer("Hozircha biznes ro'yxatdan o'tmagan. «🏢 Yangi biznes» ni bosing.")
        return
    await message.answer("🏬 <b>Bizneslar</b>", reply_markup=shops_kb(shops))


@dp.callback_query(F.data == "list")
async def back_to_list(call: CallbackQuery):
    async with SessionMaker() as session:
        shops = list(await session.scalars(select(Shop).order_by(Shop.name)))
    await call.message.edit_text("🏬 <b>Bizneslar</b>", reply_markup=shops_kb(shops))
    await call.answer()


@dp.callback_query(F.data.startswith("shop:"))
async def shop_card(call: CallbackQuery):
    if not is_super(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    shop_id = int(call.data.split(":")[1])
    async with SessionMaker() as session:
        shop = await session.get(Shop, shop_id)
        owner = await session.scalar(
            select(User).where(User.shop_id == shop_id, User.role == Role.OWNER)
        )
        staff_count = len(list(await session.scalars(
            select(User).where(User.shop_id == shop_id, User.status == UserStatus.APPROVED)
        )))
        payments = list(await session.scalars(
            select(LicensePayment).where(LicensePayment.shop_id == shop_id)
            .order_by(LicensePayment.created_at.desc()).limit(5)
        ))
    until = shop.license_until.strftime("%d.%m.%Y") if shop.license_until else "—"
    history = "\n".join(
        f"• {p.created_at:%d.%m.%Y} — {p.months} oy, {money(p.amount)} so'm" for p in payments
    ) or "To'lovlar yo'q"
    await call.message.edit_text(
        f"🏬 <b>{shop.name}</b>\n"
        f"Kodi: <code>{shop.code}</code>\n"
        f"Egasi: {owner.full_name if owner else '—'}\n"
        f"Login: <code>{shop.owner_phone or '—'}</code>\n"
        f"Botga ulangan: {'✅' if owner and owner.tg_id else '❌ hali kirmagan'}\n"
        f"Foydalanuvchilar: {staff_count} ta\n"
        f"Holati: {'✅ Faol' if shop.license_ok else '⛔️ To`xtatilgan'}\n"
        f"Muddat: {until}\n\n"
        f"<b>Oxirgi to'lovlar</b>\n{history}",
        reply_markup=shop_kb(shop_id),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("ext:"))
async def extend(call: CallbackQuery, bot: Bot):
    if not is_super(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    _, action, shop_id = call.data.split(":")
    async with SessionMaker() as session:
        shop = await session.get(Shop, int(shop_id))
        if action == "stop":
            shop.is_active = False
            text = f"⛔️ «{shop.name}» obunasi to'xtatildi."
        else:
            months = int(action)
            until = await extend_license(session, shop, months)
            session.add(LicensePayment(
                shop_id=shop.id, months=months,
                amount=Decimal(settings.license_monthly_price) * months,
                note=f"Admin: {call.from_user.id}",
            ))
            text = (f"✅ «{shop.name}» obunasi {months} oyga uzaytirildi.\n"
                    f"Yangi muddat: {until:%d.%m.%Y}")
        owner_tg = shop.owner_tg_id
        await session.commit()

    await call.message.edit_text(text, reply_markup=shop_kb(int(shop_id)))
    if owner_tg:
        try:
            await bot.send_message(owner_tg, "🔐 " + text)
        except Exception:
            pass
    await call.answer()


@dp.callback_query(F.data.startswith("pwd:"))
async def reset_password(call: CallbackQuery):
    if not is_super(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    shop_id = int(call.data.split(":")[1])
    password = generate_password()
    async with SessionMaker() as session:
        owner = await session.scalar(
            select(User).where(User.shop_id == shop_id, User.role == Role.OWNER)
        )
        if not owner:
            await call.answer("Egasi topilmadi", show_alert=True)
            return
        owner.password_hash = hash_password(password)
        login = owner.phone
        await session.commit()
    await call.message.answer(
        f"🔑 Yangi parol tayyor.\n\nLogin: <code>{login}</code>\n"
        f"Parol: <code>{password}</code>"
    )
    await call.answer()


@dp.message(F.photo)
async def payment_receipt(message: Message, bot: Bot):
    for admin_id in settings.super_admins:
        try:
            await bot.send_photo(
                admin_id, message.photo[-1].file_id,
                caption=("🧾 <b>To'lov cheki</b>\n"
                         f"👤 {message.from_user.full_name}\n"
                         f"🆔 <code>{message.from_user.id}</code>\n"
                         f"@{message.from_user.username or '—'}"),
            )
        except Exception:
            continue
    await message.answer("✅ Chek qabul qilindi. Tez orada obuna faollashtiriladi.")


async def main() -> None:
    if not settings.license_bot_token:
        raise SystemExit("LICENSE_BOT_TOKEN .env faylida ko'rsatilmagan")
    await init_db()
    bot = Bot(settings.license_bot_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    logging.info("Admin bot ishga tushdi")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
