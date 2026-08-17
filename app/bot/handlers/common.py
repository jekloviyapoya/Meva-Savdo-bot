"""Kirish, login, taklif havolasi va biznesni almashtirish."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.states import JoinForm, LoginForm
from app.config import AUTHOR, COMPANY, VERSION
from app.models import Customer, Invite, Role, Shop, User, UserStatus
from app.services import (
    create_invite, get_invite, invite_link, managers, memberships, normalize_phone,
    switch_shop,
)

router = Router()

ABOUT = (
    "ℹ️ <b>Bot haqida</b>\n\n"
    "Savdo, ombor, mijozlar va yetkazib berishni boshqarish tizimi.\n"
    "Har bir biznes o'z alohida bazasida ishlaydi.\n"
    f"Versiya: {VERSION}\n\n"
    "━━━━━━━━━━━━━━━\n"
    f"👨‍💻 <b>Dasturchi: {AUTHOR}</b>\n"
    f"🏢 <b>{COMPANY}</b>\n"
    "━━━━━━━━━━━━━━━"
)

WELCOME_NO_ACCOUNT = (
    "👋 Assalomu alaykum!\n\n"
    "Bu — bir nechta biznes uchun savdo tizimi. Kirish uchun ikki yo'l bor:\n\n"
    "1️⃣ <b>Biznes egasi bo'lsangiz</b> — admin bot orqali ro'yxatdan o'ting, "
    "sizga login (telefon raqamingiz) beriladi. So'ng shu raqamni yuboring.\n"
    "2️⃣ <b>Hodim yoki mijoz bo'lsangiz</b> — biznes egasidan taklif havolasini so'rang.\n\n"
    "Login raqamingizni yuboring:"
)


async def show_menu(message: Message, session: AsyncSession, shop: Shop, user: User):
    multi = len(await memberships(session, user.tg_id)) > 1
    await message.answer(
        f"🏬 <b>{shop.name}</b>\n"
        f"👤 {user.full_name} · {user.role.value}\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=kb.main_menu(user.role, multi=multi),
    )


# ------------------------- /start -------------------------

@router.message(CommandStart(deep_link=True))
async def start_deeplink(message: Message, command: CommandObject, state: FSMContext,
                         session: AsyncSession, shop: Shop | None, user: User | None):
    payload = (command.args or "").strip()
    if not payload.startswith("inv"):
        await start(message, state, session, shop, user)
        return

    invite = await get_invite(session, payload[3:])
    if invite is None:
        await message.answer("🚫 Havola yaroqsiz yoki muddati tugagan. "
                             "Biznes egasidan yangi havola so'rang.")
        return

    target_shop = await session.get(Shop, invite.shop_id)
    existing = next(
        (u for u in await memberships(session, message.from_user.id)
         if u.shop_id == invite.shop_id), None
    )
    if existing:
        await switch_shop(session, message.from_user.id, invite.shop_id)
        await message.answer(f"Siz allaqachon «{target_shop.name}» ga ulangansiz.")
        await show_menu(message, session, target_shop, existing)
        return

    await state.clear()
    await state.update_data(invite_id=invite.id)
    await message.answer(
        f"🏬 <b>{target_shop.name}</b> ga qo'shilmoqdasiz.\n"
        f"Rolingiz: {invite.role.value}\n\n"
        "Ism-familiyangizni yozing:",
        reply_markup=kb.remove,
    )
    await state.set_state(JoinForm.full_name)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, session: AsyncSession,
                shop: Shop | None, user: User | None):
    await state.clear()
    if user and shop and user.status == UserStatus.APPROVED:
        await show_menu(message, session, shop, user)
        return
    if user and user.status == UserStatus.PENDING:
        await message.answer("⏳ Arizangiz ko'rib chiqilmoqda. Tasdiqlangach xabar beramiz.")
        return
    await message.answer(WELCOME_NO_ACCOUNT, reply_markup=kb.login_kb())
    await state.set_state(LoginForm.phone)


# ------------------------- Login (telefon raqam) -------------------------

@router.message(LoginForm.phone, F.contact | F.text)
async def do_login(message: Message, state: FSMContext, session: AsyncSession):
    from app.services import find_login

    raw = message.contact.phone_number if message.contact else message.text
    phone = normalize_phone(raw)
    if not phone:
        await message.answer("Raqamni to'g'ri kiriting. Masalan: +998901234567")
        return

    accounts = await find_login(session, phone)
    free = [u for u in accounts if u.tg_id is None or u.tg_id == message.from_user.id]
    if not free:
        await message.answer(
            "🚫 Bu raqam bo'yicha login topilmadi.\n\n"
            "• Biznes egasi bo'lsangiz — admin bot orqali ro'yxatdan o'ting.\n"
            "• Hodim yoki mijoz bo'lsangiz — biznes egasidan taklif havolasini so'rang."
        )
        return

    for account in free:
        account.tg_id = message.from_user.id
        account.username = message.from_user.username
    await session.flush()
    await state.clear()

    if len(free) > 1:
        items = [(u.shop_id, (await session.get(Shop, u.shop_id)).name) for u in free]
        await message.answer(
            f"✅ Login tasdiqlandi. Sizda {len(free)} ta biznes bor — birini tanlang:",
            reply_markup=kb.inline_list("switch", items),
        )
        return

    user = free[0]
    await switch_shop(session, message.from_user.id, user.shop_id)
    shop = await session.get(Shop, user.shop_id)
    await message.answer(f"✅ Xush kelibsiz, {user.full_name}!", reply_markup=kb.remove)
    await show_menu(message, session, shop, user)


# ------------------------- Taklif orqali qo'shilish -------------------------

@router.message(JoinForm.full_name, F.text)
async def join_name(message: Message, state: FSMContext):
    if len(message.text.strip()) < 3:
        await message.answer("Ism-familiyani to'liqroq yozing.")
        return
    await state.update_data(full_name=message.text.strip())
    await message.answer("📱 Telefon raqamingizni yuboring:", reply_markup=kb.phone_kb())
    await state.set_state(JoinForm.phone)


@router.message(JoinForm.phone, F.contact | F.text)
async def join_phone(message: Message, state: FSMContext):
    raw = message.contact.phone_number if message.contact else message.text
    phone = normalize_phone(raw)
    if not phone:
        await message.answer("Raqamni to'g'ri kiriting. Masalan: +998901234567")
        return
    await state.update_data(phone=phone)
    await message.answer("🖼 Rasmingizni yuboring (ixtiyoriy) yoki o'tkazib yuboring:",
                         reply_markup=kb.cancel_kb([kb.SKIP]))
    await state.set_state(JoinForm.photo)


@router.message(JoinForm.photo, F.photo | F.text)
async def join_finish(message: Message, state: FSMContext, bot: Bot,
                      session: AsyncSession):
    photo_id = message.photo[-1].file_id if message.photo else None
    data = await state.get_data()
    await state.clear()

    invite = await session.get(Invite, data["invite_id"])
    if invite is None or not invite.usable:
        await message.answer("🚫 Havola yaroqsiz bo'lib qoldi.")
        return
    shop = await session.get(Shop, invite.shop_id)

    customer = None
    if invite.role == Role.CUSTOMER:
        customer = Customer(
            shop_id=shop.id, name=data["full_name"], phone=data["phone"],
            photo_file_id=photo_id, tg_id=message.from_user.id,
        )
        session.add(customer)
        await session.flush()

    approved = invite.auto_approve
    new_user = User(
        shop_id=shop.id,
        tg_id=message.from_user.id,
        username=message.from_user.username,
        full_name=data["full_name"],
        phone=data["phone"],
        photo_file_id=photo_id,
        role=invite.role,
        status=UserStatus.APPROVED if approved else UserStatus.PENDING,
        customer_id=customer.id if customer else None,
    )
    session.add(new_user)
    invite.uses += 1
    await session.flush()

    if approved:
        await switch_shop(session, message.from_user.id, shop.id)
        await message.answer(f"✅ «{shop.name}» ga qo'shildingiz!", reply_markup=kb.remove)
        await show_menu(message, session, shop, new_user)
    else:
        await message.answer(
            f"✅ Arizangiz «{shop.name}» ga yuborildi.\n"
            "⏳ Biznes egasi yoki admin tasdiqlagandan keyin kira olasiz.",
            reply_markup=kb.remove,
        )

    text = (
        "🆕 <b>Yangi ariza</b>\n\n"
        f"🏬 {shop.name}\n"
        f"👤 {new_user.full_name}\n"
        f"📱 {new_user.phone}\n"
        f"🎭 So'ralgan rol: {new_user.role.value}"
    )
    for manager in await managers(session, shop.id):
        try:
            if photo_id:
                await bot.send_photo(manager.tg_id, photo_id, caption=text,
                                     reply_markup=kb.approve_kb(new_user.id))
            else:
                await bot.send_message(manager.tg_id, text,
                                       reply_markup=kb.approve_kb(new_user.id))
        except Exception:
            continue


# ------------------------- Ariza tasdiqlash -------------------------

@router.callback_query(F.data.startswith("appr:"))
async def approve(call: CallbackQuery, bot: Bot, session: AsyncSession,
                  shop: Shop | None, user: User | None):
    if not user or not user.is_manager:
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    _, action, uid = call.data.split(":")
    target = await session.get(User, int(uid))
    if not target or target.shop_id != shop.id:
        await call.answer("Bu ariza sizning biznesingizga tegishli emas", show_alert=True)
        return

    if action == "ok":
        target.status = UserStatus.APPROVED
        await call.message.answer(f"✅ {target.full_name} tasdiqlandi.")
        try:
            await switch_shop(session, target.tg_id, target.shop_id)
            await bot.send_message(
                target.tg_id,
                f"✅ «{shop.name}» sizni tasdiqladi! Endi botdan foydalanishingiz mumkin.",
                reply_markup=kb.main_menu(target.role),
            )
        except Exception:
            pass
    else:
        target.status = UserStatus.BLOCKED
        await call.message.answer(f"🚫 {target.full_name} rad etildi.")
        try:
            await bot.send_message(target.tg_id, "🚫 Arizangiz rad etildi.")
        except Exception:
            pass
    await call.answer()


# ------------------------- Taklif havolalari -------------------------

@router.message(F.text == "🔗 Taklif havolasi")
async def invites_menu(message: Message, user: User):
    if not user.is_manager:
        return
    await message.answer(
        "🔗 <b>Taklif havolasi</b>\n\n"
        "Havolani hodim yoki mijozga yuboring. Ular havola orqali kirsa, "
        "faqat <b>sizning biznesingizga</b> qo'shiladi va siz tasdiqlaganingizdan "
        "keyin ishlay boshlaydi.\n\nKim uchun havola kerak?",
        reply_markup=kb.invite_role_kb(),
    )


@router.callback_query(F.data.startswith("inv:"))
async def invite_create(call: CallbackQuery, session: AsyncSession,
                        shop: Shop, user: User):
    if not user.is_manager:
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    role = Role(call.data.split(":")[1])
    invite = await create_invite(session, shop.id, role, call.from_user.id)
    await call.message.answer(
        f"🔗 <b>{role.value}</b> uchun havola tayyor:\n\n"
        f"<code>{invite_link(invite.token)}</code>\n\n"
        "Havola cheksiz marta ishlaydi. Har bir ariza sizga tasdiqlash uchun keladi.",
    )
    await call.answer()


# ------------------------- Biznesni almashtirish -------------------------

@router.message(Command("biznes"))
@router.message(F.text == kb.SWITCH)
async def shops_list(message: Message, session: AsyncSession):
    links = await memberships(session, message.from_user.id)
    if len(links) < 2:
        await message.answer("Siz faqat bitta biznesda ishlayapsiz.")
        return
    items = []
    for link in links:
        shop = await session.get(Shop, link.shop_id)
        items.append((shop.id, f"{shop.name} · {link.role.value}"))
    await message.answer("🏬 Qaysi biznesga o'tamiz?",
                         reply_markup=kb.inline_list("switch", items))


@router.callback_query(F.data.startswith("switch:"))
async def shop_switch(call: CallbackQuery, session: AsyncSession):
    shop_id = int(call.data.split(":")[1])
    if not await switch_shop(session, call.from_user.id, shop_id):
        await call.answer("Bu biznesga ruxsatingiz yo'q", show_alert=True)
        return
    shop = await session.get(Shop, shop_id)
    from app.services import get_user
    user = await get_user(session, call.from_user.id, shop_id)
    await call.message.edit_text(f"🏬 Faol biznes: <b>{shop.name}</b>")
    await show_menu(call.message, session, shop, user)
    await call.answer()


# ------------------------- Umumiy -------------------------

@router.message(F.text == "ℹ️ Bot haqida")
@router.message(Command("about"))
async def about(message: Message):
    await message.answer(ABOUT)


@router.message(F.text == "🔐 Litsenziya")
async def license_info(message: Message, shop: Shop, user: User):
    if not user.is_manager:
        return
    status = "✅ Faol" if shop.license_ok else "⛔️ Muddati tugagan"
    until = shop.license_until.strftime("%d.%m.%Y") if shop.license_until else "—"
    await message.answer(
        f"🔐 <b>Litsenziya</b>\n\n"
        f"Biznes: {shop.name}\n"
        f"Kodi: <code>{shop.code}</code>\n"
        f"Holati: {status}\n"
        f"Muddat: {until}\n"
        f"Qolgan kun: {max(shop.days_left, 0)}\n\n"
        "Uzaytirish uchun admin botga murojaat qiling.\n"
        f"👨‍💻 {AUTHOR} — {COMPANY}"
    )


@router.message(F.text == kb.BACK)
async def back_to_menu(message: Message, state: FSMContext, session: AsyncSession,
                       shop: Shop, user: User):
    await state.clear()
    await show_menu(message, session, shop, user)


@router.message(F.text == kb.CANCEL)
async def cancel(message: Message, state: FSMContext, session: AsyncSession,
                 shop: Shop, user: User):
    await state.clear()
    await message.answer("Bekor qilindi.")
    await show_menu(message, session, shop, user)
