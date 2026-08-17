from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.states import StaffForm
from app.models import Customer, Role, Sale, SaleItem, Shop, User, UserStatus
from app.services import (
    belongs_to, generate_password, hash_password, invite_link, money, normalize_phone,
)

router = Router()

ROLE_LABEL = {
    Role.OWNER: "👑 Egasi",
    Role.ADMIN: "👑 Admin",
    Role.SELLER: "🧑‍💼 Sotuvchi",
    Role.CUSTOMER: "🙍 Mijoz",
}


@router.message(F.text == "👤 Hodimlar")
async def staff_root(message: Message, session: AsyncSession, shop: Shop, user: User):
    if not user.is_manager:
        await message.answer("Bu bo'lim faqat admin uchun.")
        return
    users = list(await session.scalars(
        select(User).where(User.shop_id == shop.id).order_by(User.role, User.full_name).limit(60)
    ))
    lines = [
        f"{ROLE_LABEL[u.role]} <b>{u.full_name}</b> — <code>{u.phone or '—'}</code>"
        f"{'' if u.status == UserStatus.APPROVED else ' ⏳'}"
        f"{'' if u.tg_id else ' · botga kirmagan'}"
        for u in users
    ]
    items = [(u.id, f"{ROLE_LABEL[u.role]} {u.full_name}") for u in users]
    items.insert(0, (0, "➕ Hodimga login yaratish"))
    await message.answer(
        "👤 <b>Foydalanuvchilar</b>\n\n" + "\n".join(lines) +
        "\n\nRolini o'zgartirish uchun tanlang:",
        reply_markup=kb.inline_list("staff", items),
    )


@router.callback_query(F.data.startswith("staff:"))
async def staff_pick(call: CallbackQuery, state: FSMContext, session: AsyncSession,
                     shop: Shop, user: User):
    if not user.is_manager:
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    uid = int(call.data.split(":")[1])
    if uid == 0:
        await call.message.answer(
            "Hodimning <b>telefon raqamini</b> yozing — shu raqam uning logini bo'ladi.\n"
            "Masalan: +998901234567",
            reply_markup=kb.cancel_kb(),
        )
        await state.set_state(StaffForm.phone)
        await call.answer()
        return
    target = await session.get(User, uid)
    if not belongs_to(target, shop):
        await call.answer("Foydalanuvchi topilmadi", show_alert=True)
        return
    await call.message.answer(
        f"👤 <b>{target.full_name}</b>\nHozirgi roli: {ROLE_LABEL[target.role]}\n\nYangi rolni tanlang:",
        reply_markup=kb.role_kb(target.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("role:"))
async def staff_role(call: CallbackQuery, bot: Bot, session: AsyncSession,
                     shop: Shop, user: User):
    if not user.is_manager:
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    _, action, uid = call.data.split(":")
    target = await session.get(User, int(uid))
    if not belongs_to(target, shop):
        await call.answer("Topilmadi", show_alert=True)
        return
    if target.role == Role.OWNER and user.role != Role.OWNER:
        await call.answer("Egasining rolini o'zgartirib bo'lmaydi", show_alert=True)
        return

    if action == "block":
        target.status = UserStatus.BLOCKED
        await call.message.edit_text(f"🚫 {target.full_name} bloklandi.")
    else:
        target.role = Role(action)
        target.status = UserStatus.APPROVED
        await call.message.edit_text(
            f"✅ {target.full_name} — {ROLE_LABEL[target.role]} qilib belgilandi."
        )
        try:
            await bot.send_message(
                target.tg_id,
                f"ℹ️ Sizning rolingiz o'zgardi: {ROLE_LABEL[target.role]}",
                reply_markup=kb.main_menu(target.role),
            )
        except Exception:
            pass
    await call.answer()


@router.message(StaffForm.phone, F.text)
async def staff_add_phone(message: Message, state: FSMContext):
    phone = normalize_phone(message.text)
    if not phone:
        await message.answer("Raqamni to'g'ri kiriting. Masalan: +998901234567")
        return
    await state.update_data(phone=phone)
    await message.answer("Ism-familiyasini yozing:", reply_markup=kb.cancel_kb())
    await state.set_state(StaffForm.full_name)


@router.message(StaffForm.full_name, F.text)
async def staff_add_name(message: Message, state: FSMContext,
                         session: AsyncSession, shop: Shop):
    data = await state.get_data()
    await state.clear()
    password = generate_password()
    existing = await session.scalar(
        select(User).where(User.shop_id == shop.id, User.phone == data["phone"])
    )
    if existing:
        existing.full_name = message.text.strip()
        existing.status = UserStatus.APPROVED
        existing.password_hash = hash_password(password)
        target = existing
    else:
        target = User(
            shop_id=shop.id, phone=data["phone"], full_name=message.text.strip(),
            password_hash=hash_password(password),
            role=Role.SELLER, status=UserStatus.APPROVED,
        )
        session.add(target)
        await session.flush()

    await message.answer(
        f"✅ <b>{target.full_name}</b> uchun login yaratildi.\n\n"
        f"🔑 Login: <code>{target.phone}</code>\n"
        f"🔒 Web parol: <code>{password}</code>\n\n"
        "Hodim botga <b>/start</b> yuborib shu raqamni kiritsa, "
        "avtomatik sizning biznesingizga ulanadi.\n\n"
        "Rolni tanlang:",
        reply_markup=kb.role_kb(target.id),
    )


# ------------------------- Hisobot -------------------------

@router.message(F.text == "📊 Hisobot")
async def report(message: Message, session: AsyncSession, shop: Shop, user: User):
    if not user.is_manager:
        return
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    month_ago = now - timedelta(days=30)

    async def sums(since):
        row = await session.execute(
            select(func.coalesce(func.sum(Sale.total), 0),
                   func.coalesce(func.sum(Sale.paid), 0),
                   func.count(Sale.id))
            .where(Sale.shop_id == shop.id, Sale.created_at >= since)
        )
        return row.one()

    d_total, d_paid, d_count = await sums(day_ago)
    m_total, m_paid, m_count = await sums(month_ago)

    debt_total = await session.scalar(
        select(func.coalesce(func.sum(Customer.balance), 0))
        .where(Customer.shop_id == shop.id, Customer.balance > 0)
    )

    top = list(await session.execute(
        select(SaleItem.name, func.sum(SaleItem.amount).label("s"))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(Sale.shop_id == shop.id, Sale.created_at >= month_ago)
        .group_by(SaleItem.name).order_by(func.sum(SaleItem.amount).desc()).limit(5)
    ))
    top_lines = [f"{i}. {name} — {money(total)} so'm" for i, (name, total) in enumerate(top, 1)]

    await message.answer(
        f"📊 <b>Hisobot — {shop.name}</b>\n\n"
        f"<b>Oxirgi 24 soat</b>\n"
        f"• Savdolar: {d_count} ta\n"
        f"• Aylanma: {money(d_total)} so'm\n"
        f"• To'landi: {money(d_paid)} so'm\n\n"
        f"<b>Oxirgi 30 kun</b>\n"
        f"• Savdolar: {m_count} ta\n"
        f"• Aylanma: {money(m_total)} so'm\n"
        f"• To'landi: {money(m_paid)} so'm\n\n"
        f"💸 Umumiy qarzdorlik: <b>{money(debt_total)} so'm</b>\n\n"
        + ("<b>Eng ko'p sotilganlar (30 kun)</b>\n" + "\n".join(top_lines) if top_lines else "")
    )
