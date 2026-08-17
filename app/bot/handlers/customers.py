from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.states import CustomerForm
from app.models import Customer, Ledger, LedgerType, Sale, Shop, User
from app.services import apply_balance, belongs_to, money, parse_amount, set_balance

router = Router()

LEDGER_LABEL = {
    LedgerType.INITIAL: "Boshlang'ich balans",
    LedgerType.CORRECTION: "To'g'rilash",
    LedgerType.SALE: "Savdo",
    LedgerType.PAYMENT: "To'lov",
    LedgerType.ORDER: "Buyurtma",
}


@router.message(F.text == "👥 Mijozlar")
async def customers_root(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("👥 Mijozlar bo'limi", reply_markup=kb.customers_menu())


@router.message(F.text == "➕ Mijoz qo'shish")
async def customer_add(message: Message, state: FSMContext):
    await message.answer("Mijoz ismini yozing:", reply_markup=kb.cancel_kb())
    await state.set_state(CustomerForm.name)


@router.message(CustomerForm.name, F.text)
async def customer_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("📱 Telefon raqami:", reply_markup=kb.cancel_kb([kb.SKIP]))
    await state.set_state(CustomerForm.phone)


@router.message(CustomerForm.phone, F.contact | F.text)
async def customer_phone(message: Message, state: FSMContext):
    phone = None
    if message.contact:
        phone = message.contact.phone_number
    elif message.text != kb.SKIP:
        phone = message.text.strip()
    await state.update_data(phone=phone)
    await message.answer("📍 Manzili:", reply_markup=kb.cancel_kb([kb.SKIP]))
    await state.set_state(CustomerForm.address)


@router.message(CustomerForm.address, F.text)
async def customer_address(message: Message, state: FSMContext):
    address = None if message.text == kb.SKIP else message.text.strip()
    await state.update_data(address=address)
    await message.answer(
        "💰 <b>Oldingi balansi</b> (eski qarzi) bo'lsa summani yozing.\n"
        "Qarzi yo'q bo'lsa 0 yozing yoki o'tkazib yuboring.",
        reply_markup=kb.cancel_kb([kb.SKIP]),
    )
    await state.set_state(CustomerForm.balance)


@router.message(CustomerForm.balance, F.text)
async def customer_balance(message: Message, state: FSMContext):
    balance = Decimal(0)
    if message.text != kb.SKIP:
        parsed = parse_amount(message.text)
        if parsed is None:
            await message.answer("Summani raqamda yozing.")
            return
        balance = parsed
    await state.update_data(balance=str(balance))
    await message.answer("🖼 Mijoz rasmini yuboring (ixtiyoriy):",
                         reply_markup=kb.cancel_kb([kb.SKIP]))
    await state.set_state(CustomerForm.photo)


@router.message(CustomerForm.photo, F.photo | F.text)
async def customer_photo(message: Message, state: FSMContext,
                         session: AsyncSession, shop: Shop):
    photo_id = message.photo[-1].file_id if message.photo else None
    data = await state.get_data()
    await state.clear()

    customer = Customer(
        shop_id=shop.id,
        name=data["name"],
        phone=data.get("phone"),
        address=data.get("address"),
        photo_file_id=photo_id,
    )
    session.add(customer)
    await session.flush()

    start_balance = Decimal(data.get("balance") or 0)
    if start_balance:
        await apply_balance(session, customer, start_balance, LedgerType.INITIAL,
                            "Boshlang'ich balans", message.from_user.id)

    await message.answer(
        f"✅ Mijoz qo'shildi\n\n"
        f"👤 <b>{customer.name}</b>\n"
        f"📱 {customer.phone or '—'}\n"
        f"📍 {customer.address or '—'}\n"
        f"💰 {customer.balance_label}",
        reply_markup=kb.customers_menu(),
    )


@router.message(F.text == "📃 Mijozlar ro'yxati")
async def customer_list(message: Message, session: AsyncSession, shop: Shop):
    customers = list(await session.scalars(
        select(Customer).where(Customer.shop_id == shop.id, Customer.is_active.is_(True))
        .order_by(Customer.name).limit(50)
    ))
    if not customers:
        await message.answer("Ro'yxat bo'sh.")
        return
    items = [(c.id, f"{c.name} — {c.balance_label}") for c in customers]
    await message.answer("👥 Mijozni tanlang:", reply_markup=kb.inline_list("ccard", items))


@router.message(F.text == "💸 Qarzdorlar")
async def debtors(message: Message, session: AsyncSession, shop: Shop):
    customers = list(await session.scalars(
        select(Customer).where(Customer.shop_id == shop.id, Customer.balance > 0)
        .order_by(Customer.balance.desc()).limit(50)
    ))
    if not customers:
        await message.answer("Qarzdor mijoz yo'q. 👍")
        return
    total = sum(Decimal(c.balance) for c in customers)
    lines = [f"{i}. {c.name} — <b>{money(c.balance)}</b> so'm" for i, c in enumerate(customers, 1)]
    await message.answer(
        "💸 <b>Qarzdorlar</b>\n\n" + "\n".join(lines) +
        f"\n\n<b>Jami: {money(total)} so'm</b>"
    )


@router.message(F.text == "🔎 Mijoz qidirish")
async def customer_search_start(message: Message, state: FSMContext):
    await message.answer("Ism yoki telefon raqamini yozing:", reply_markup=kb.cancel_kb())
    await state.set_state(CustomerForm.search)


@router.message(CustomerForm.search, F.text)
async def customer_search(message: Message, state: FSMContext,
                          session: AsyncSession, shop: Shop):
    await state.clear()
    q = f"%{message.text.strip()}%"
    customers = list(await session.scalars(
        select(Customer).where(
            Customer.shop_id == shop.id,
            or_(Customer.name.ilike(q), Customer.phone.ilike(q)),
        ).limit(30)
    ))
    if not customers:
        await message.answer("Topilmadi.", reply_markup=kb.customers_menu())
        return
    items = [(c.id, f"{c.name} — {c.balance_label}") for c in customers]
    await message.answer("Natijalar:", reply_markup=kb.inline_list("ccard", items))


async def _customer_card(target: Message, session: AsyncSession, customer: Customer):
    text = (
        f"👤 <b>{customer.name}</b>\n"
        f"📱 {customer.phone or '—'}\n"
        f"📍 {customer.address or '—'}\n"
        f"💰 Balans: <b>{customer.balance_label}</b>\n"
        f"🤖 Botda: {'✅ ulangan' if customer.tg_id else '—'}"
    )
    if customer.photo_file_id:
        await target.answer_photo(customer.photo_file_id, caption=text,
                                  reply_markup=kb.customer_card_kb(customer.id))
    else:
        await target.answer(text, reply_markup=kb.customer_card_kb(customer.id))


@router.callback_query(F.data.startswith("ccard:"))
async def customer_card(call: CallbackQuery, session: AsyncSession, shop: Shop):
    customer = await session.get(Customer, int(call.data.split(":")[1]))
    if not belongs_to(customer, shop):
        await call.answer("Topilmadi", show_alert=True)
        return
    await _customer_card(call.message, session, customer)
    await call.answer()


@router.callback_query(F.data.startswith("cust:"))
async def customer_action(call: CallbackQuery, state: FSMContext,
                          session: AsyncSession, shop: Shop):
    _, action, cid = call.data.split(":")
    customer = await session.get(Customer, int(cid))
    if not belongs_to(customer, shop):
        await call.answer("Topilmadi", show_alert=True)
        return
    await state.update_data(customer_id=customer.id)

    if action == "setbal":
        await call.message.answer(
            f"«{customer.name}» uchun <b>to'g'ri balansni</b> yozing.\n"
            f"Hozirgi: {customer.balance_label}\n\n"
            "Qarzdor bo'lsa musbat son, haqdor bo'lsa manfiy son yozing.",
            reply_markup=kb.cancel_kb(),
        )
        await state.set_state(CustomerForm.set_balance)
    elif action == "pay":
        await call.message.answer(
            f"«{customer.name}» qancha pul berdi? Summani yozing:\n"
            f"(Balansdan ayiriladi. Hozirgi: {customer.balance_label})",
            reply_markup=kb.cancel_kb(),
        )
        await state.set_state(CustomerForm.payment)
    elif action == "debt":
        await call.message.answer("Qo'shiladigan qarz summasini yozing:",
                                  reply_markup=kb.cancel_kb())
        await state.set_state(CustomerForm.debt)
    elif action == "photo":
        await call.message.answer("Rasmni yuboring:", reply_markup=kb.cancel_kb())
        await state.set_state(CustomerForm.photo_edit)
    elif action == "sales":
        await _send_sales(call.message, session, customer)
    elif action == "ledger":
        await _send_ledger(call.message, session, customer)
    await call.answer()


@router.message(CustomerForm.set_balance, F.text)
async def customer_set_balance(message: Message, state: FSMContext,
                               session: AsyncSession, shop: Shop, user: User):
    value = parse_amount(message.text)
    if value is None:
        await message.answer("Summani raqamda yozing.")
        return
    data = await state.get_data()
    await state.clear()
    customer = await session.get(Customer, data["customer_id"])
    if not belongs_to(customer, shop):
        await message.answer("Mijoz topilmadi.")
        return
    await set_balance(session, customer, value, "Qo'lda to'g'rilandi", message.from_user.id)
    await message.answer(f"✅ {customer.name}: {customer.balance_label}",
                         reply_markup=kb.customers_menu())


@router.message(CustomerForm.payment, F.text)
async def customer_payment(message: Message, state: FSMContext,
                           session: AsyncSession, shop: Shop, user: User):
    value = parse_amount(message.text)
    if value is None or value <= 0:
        await message.answer("Summani musbat raqamda yozing.")
        return
    data = await state.get_data()
    await state.clear()
    customer = await session.get(Customer, data["customer_id"])
    if not belongs_to(customer, shop):
        await message.answer("Mijoz topilmadi.")
        return
    await apply_balance(session, customer, -value, LedgerType.PAYMENT,
                        f"To'lov qabul qilindi ({user.full_name})", message.from_user.id)
    await message.answer(
        f"✅ {money(value)} so'm qabul qilindi.\n"
        f"👤 {customer.name}: {customer.balance_label}",
        reply_markup=kb.customers_menu(),
    )


@router.message(CustomerForm.debt, F.text)
async def customer_debt(message: Message, state: FSMContext,
                        session: AsyncSession, shop: Shop, user: User):
    value = parse_amount(message.text)
    if value is None or value <= 0:
        await message.answer("Summani musbat raqamda yozing.")
        return
    data = await state.get_data()
    await state.clear()
    customer = await session.get(Customer, data["customer_id"])
    if not belongs_to(customer, shop):
        await message.answer("Mijoz topilmadi.")
        return
    await apply_balance(session, customer, value, LedgerType.CORRECTION,
                        f"Qarz qo'shildi ({user.full_name})", message.from_user.id)
    await message.answer(f"✅ {customer.name}: {customer.balance_label}",
                         reply_markup=kb.customers_menu())


@router.message(CustomerForm.photo_edit, F.photo)
async def customer_photo_edit(message: Message, state: FSMContext,
                              session: AsyncSession, shop: Shop):
    data = await state.get_data()
    await state.clear()
    customer = await session.get(Customer, data["customer_id"])
    if not belongs_to(customer, shop):
        await message.answer("Mijoz topilmadi.")
        return
    customer.photo_file_id = message.photo[-1].file_id
    await message.answer("✅ Rasm saqlandi.", reply_markup=kb.customers_menu())


async def _send_sales(target: Message, session: AsyncSession, customer: Customer):
    sales = list(await session.scalars(
        select(Sale).where(Sale.customer_id == customer.id)
        .order_by(Sale.created_at.desc()).limit(15)
    ))
    if not sales:
        await target.answer("Xaridlar yo'q.")
        return
    blocks = []
    for s in sales:
        items = "\n".join(
            f"   • {i.name} — {i.qty} {i.unit.value} × {money(i.price)} = {money(i.amount)}"
            for i in s.items
        )
        blocks.append(
            f"🧾 <b>#{s.id}</b> · {s.created_at:%d.%m.%Y %H:%M}\n{items}\n"
            f"   Jami: <b>{money(s.total)}</b> | To'landi: {money(s.paid)} | "
            f"Qarz: {money(s.debt)}"
        )
    await target.answer(f"🧾 <b>{customer.name} — xaridlari</b>\n\n" + "\n\n".join(blocks))


async def _send_ledger(target: Message, session: AsyncSession, customer: Customer):
    entries = list(await session.scalars(
        select(Ledger).where(Ledger.customer_id == customer.id)
        .order_by(Ledger.created_at.desc()).limit(25)
    ))
    if not entries:
        await target.answer("Kirim-chiqim yozuvlari yo'q.")
        return
    lines = []
    for e in entries:
        sign = "➕" if Decimal(e.amount) > 0 else "➖"
        lines.append(
            f"{sign} {money(abs(Decimal(e.amount)))} — {LEDGER_LABEL.get(e.type, e.type.value)}\n"
            f"    {e.created_at:%d.%m.%Y %H:%M} · qoldiq: {money(e.balance_after)}"
            + (f"\n    <i>{e.comment}</i>" if e.comment else "")
        )
    await target.answer(
        f"📊 <b>{customer.name} — kirim-chiqim</b>\n\n" + "\n".join(lines) +
        f"\n\n<b>Joriy balans: {customer.balance_label}</b>"
    )
