from __future__ import annotations

from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.states import OrderForm
from app.models import (
    Customer, DeliveryType, Ledger, Order, OrderItem, OrderStatus, Product, Role,
    Sale, Shop, Unit, User,
)
from app.services import belongs_to, money, parse_amount, qty_fmt, staff_members

router = Router()

STATUS_LABEL = {
    OrderStatus.NEW: "🆕 Yuborildi, ko'rib chiqilmoqda",
    OrderStatus.PRICED: "💵 Narxlandi, tasdiqingiz kutilmoqda",
    OrderStatus.CONFIRMED: "✅ Tasdiqlandi",
    OrderStatus.SCHEDULED: "🚚 Yetkazish vaqti belgilandi",
    OrderStatus.DONE: "📦 Yetkazildi",
    OrderStatus.CANCELLED: "🚫 Bekor qilindi",
}

DELIVERY_LABEL = {
    DeliveryType.PICKUP: "🏬 O'zi olib ketadi",
    DeliveryType.OWN_DRIVER: "🚗 Mijozning o'z haydovchisi",
    DeliveryType.SHOP_TAXI: "🚕 Do'kon taxi xizmati",
}


def order_cart_kb():
    kbd = InlineKeyboardBuilder()
    kbd.button(text="➕ Yana mahsulot", callback_data="oc:more")
    kbd.button(text="🗑 Oxirgisini o'chirish", callback_data="oc:undo")
    kbd.button(text="✅ Davom etish", callback_data="oc:next")
    kbd.button(text="❌ Bekor qilish", callback_data="oc:cancel")
    kbd.adjust(2, 2)
    return kbd.as_markup()


def order_text(order: Order) -> str:
    lines = []
    for i, item in enumerate(order.items, 1):
        price_part = f" × {money(item.price)} = {money(item.amount)}" if item.price else ""
        lines.append(f"{i}. {item.name} — {qty_fmt(item.qty)} {item.unit.value}{price_part}")
    body = "\n".join(lines)
    return (
        f"🧾 <b>Buyurtma #{order.id}</b>\n"
        f"👤 {order.customer.name} · 📱 {order.customer.phone or '—'}\n"
        f"{DELIVERY_LABEL[order.delivery_type]}\n"
        f"🗓 Qachonga: {order.needed_at or '—'}\n"
        f"📍 Manzil: {order.address or '—'}\n"
        f"⏰ Yetkazish vaqti: {order.delivery_time or '—'}\n\n"
        f"{body}\n\n"
        f"💰 Jami: <b>{money(order.total)} so'm</b>\n"
        f"Holati: {STATUS_LABEL[order.status]}"
    )


async def cart_summary(cart: list[dict]) -> str:
    if not cart:
        return "Savat bo'sh."
    lines = [f"{i}. {c['name']} — {qty_fmt(Decimal(c['qty']))} {c['unit']}"
             for i, c in enumerate(cart, 1)]
    return "🧺 <b>Savat</b>\n\n" + "\n".join(lines)


# ------------------------- Buyurtma berish -------------------------

@router.message(F.text == "🛒 Buyurtma berish")
async def order_start(message: Message, state: FSMContext, session: AsyncSession, shop: Shop):
    await state.clear()
    await state.update_data(cart=[])
    products = list(await session.scalars(
        select(Product).where(Product.shop_id == shop.id, Product.is_active.is_(True))
        .order_by(Product.name).limit(40)
    ))
    if not products:
        await message.answer("Hozircha mahsulotlar ro'yxati bo'sh.")
        return
    items = [(p.id, f"{p.name} — {p.price_label}") for p in products]
    await message.answer(
        "🛒 Mahsulotni tanlang (yoki nomini yozib qidiring):",
        reply_markup=kb.inline_list("oprod", items),
    )
    await state.set_state(OrderForm.product_search)


@router.message(OrderForm.product_search, F.text)
async def order_product_search(message: Message, session: AsyncSession, shop: Shop):
    q = f"%{message.text.strip()}%"
    products = list(await session.scalars(
        select(Product).where(
            Product.shop_id == shop.id, Product.is_active.is_(True), Product.name.ilike(q)
        ).limit(20)
    ))
    if not products:
        await message.answer("Topilmadi.")
        return
    items = [(p.id, f"{p.name} — {p.price_label}") for p in products]
    await message.answer("Tanlang:", reply_markup=kb.inline_list("oprod", items))


@router.callback_query(OrderForm.product_search, F.data.startswith("oprod:"))
async def order_product(call: CallbackQuery, state: FSMContext,
                        session: AsyncSession, shop: Shop):
    product = await session.get(Product, int(call.data.split(":")[1]))
    if not belongs_to(product, shop):
        await call.answer("Topilmadi", show_alert=True)
        return
    await state.update_data(product_id=product.id, product_name=product.name,
                            unit=product.unit.value)
    if product.photo_file_id:
        await call.message.answer_photo(product.photo_file_id,
                                        caption=f"📦 {product.name} — {product.price_label}")
    await call.message.answer(f"Qancha kerak? ({product.unit.value} da yozing):",
                              reply_markup=kb.cancel_kb())
    await state.set_state(OrderForm.qty)
    await call.answer()


@router.message(OrderForm.qty, F.text)
async def order_qty(message: Message, state: FSMContext):
    qty = parse_amount(message.text)
    if qty is None or qty <= 0:
        await message.answer("Miqdorni musbat raqamda yozing.")
        return
    data = await state.get_data()
    cart = data.get("cart", [])
    cart.append({
        "product_id": data["product_id"],
        "name": data["product_name"],
        "unit": data["unit"],
        "qty": str(qty),
    })
    await state.update_data(cart=cart)
    await message.answer(await cart_summary(cart), reply_markup=order_cart_kb())


@router.callback_query(F.data.startswith("oc:"))
async def order_cart_action(call: CallbackQuery, state: FSMContext, user: User):
    action = call.data.split(":")[1]
    data = await state.get_data()
    cart = data.get("cart", [])

    if action == "cancel":
        await state.clear()
        await call.message.edit_text("❌ Buyurtma bekor qilindi.")
        await call.message.answer("Bosh menyu", reply_markup=kb.main_menu(user.role))
    elif action == "more":
        await call.message.answer("Mahsulot nomini yozing:", reply_markup=kb.cancel_kb())
        await state.set_state(OrderForm.product_search)
    elif action == "undo":
        if cart:
            cart.pop()
            await state.update_data(cart=cart)
        await call.message.edit_text(await cart_summary(cart), reply_markup=order_cart_kb())
    elif action == "next":
        if not cart:
            await call.answer("Savat bo'sh", show_alert=True)
            return
        await call.message.answer(
            "🗓 <b>Qachonga kerak?</b>\n"
            "Masalan: «ertaga ertalab», «25-avgust soat 10:00»",
            reply_markup=kb.cancel_kb(),
        )
        await state.set_state(OrderForm.needed_at)
    await call.answer()


@router.message(OrderForm.needed_at, F.text)
async def order_needed_at(message: Message, state: FSMContext):
    await state.update_data(needed_at=message.text.strip())
    await message.answer("Yetkazib berish kerakmi?", reply_markup=kb.remove)
    await message.answer("Tanlang:", reply_markup=kb.delivery_kb())


@router.callback_query(F.data == "ord:pickup")
async def order_pickup(call: CallbackQuery, state: FSMContext):
    await state.update_data(delivery=DeliveryType.PICKUP.value)
    await call.message.edit_text("🏬 O'zingiz olib ketasiz.")
    await call.message.answer("💬 Qo'shimcha izoh yozing (yoki o'tkazib yuboring):",
                              reply_markup=kb.cancel_kb([kb.SKIP]))
    await state.set_state(OrderForm.comment)
    await call.answer()


@router.callback_query(F.data == "ord:delivery")
async def order_delivery(call: CallbackQuery):
    await call.message.edit_text(
        "🚚 <b>Dostavka xizmati</b>\n\n"
        "Yetkazib berishni qay tarzda amalga oshiramiz?",
        reply_markup=kb.delivery_choice_kb(),
    )
    await call.answer()


@router.callback_query(F.data.in_({"ord:own_driver", "ord:shop_taxi"}))
async def order_delivery_type(call: CallbackQuery, state: FSMContext):
    dtype = (DeliveryType.OWN_DRIVER if call.data.endswith("own_driver")
             else DeliveryType.SHOP_TAXI)
    await state.update_data(delivery=dtype.value)
    await call.message.edit_text(f"Tanlandi: {DELIVERY_LABEL[dtype]}")
    await call.message.answer("📍 Yetkazish manzilini yozing:", reply_markup=kb.cancel_kb())
    await state.set_state(OrderForm.address)
    await call.answer()


@router.message(OrderForm.address, F.text)
async def order_address(message: Message, state: FSMContext):
    await state.update_data(address=message.text.strip())
    await message.answer("💬 Qo'shimcha izoh yozing (yoki o'tkazib yuboring):",
                         reply_markup=kb.cancel_kb([kb.SKIP]))
    await state.set_state(OrderForm.comment)


@router.message(OrderForm.comment, F.text)
async def order_save(message: Message, state: FSMContext, bot: Bot,
                     session: AsyncSession, shop: Shop, user: User):
    comment = None if message.text == kb.SKIP else message.text.strip()
    data = await state.get_data()
    await state.clear()

    customer = await session.get(Customer, user.customer_id) if user.customer_id else None
    if customer is not None and not belongs_to(customer, shop):
        customer = None
    if customer is None:
        customer = Customer(shop_id=shop.id, name=user.full_name,
                            phone=user.phone, tg_id=user.tg_id)
        session.add(customer)
        await session.flush()
        user.customer_id = customer.id

    order = Order(
        shop_id=shop.id,
        customer_id=customer.id,
        delivery_type=DeliveryType(data.get("delivery", "pickup")),
        needed_at=data.get("needed_at"),
        address=data.get("address") or customer.address,
        comment=comment,
        status=OrderStatus.NEW,
    )
    session.add(order)
    await session.flush()

    total = Decimal(0)
    for item in data.get("cart", []):
        product = await session.get(Product, item["product_id"])
        if not belongs_to(product, shop):
            continue
        price = Decimal(product.price) if product.price is not None else Decimal(0)
        qty = Decimal(item["qty"])
        session.add(OrderItem(
            order_id=order.id, product_id=item["product_id"], name=item["name"],
            unit=Unit(item["unit"]), qty=qty, price=price, amount=qty * price,
        ))
        total += qty * price
    order.total = total
    await session.flush()
    await session.refresh(order)

    await message.answer(
        "✅ Buyurtmangiz qabul qilindi!\n"
        "Do'kon narxlarni tasdiqlab sizga yuboradi.\n\n" + order_text(order),
        reply_markup=kb.main_menu(user.role),
    )

    for member in await staff_members(session, shop.id):
        if member.role == Role.SELLER and order.status == OrderStatus.NEW:
            pass
        try:
            await bot.send_message(member.tg_id, "🆕 <b>Yangi buyurtma!</b>\n\n" + order_text(order),
                                   reply_markup=kb.order_staff_kb(order.id))
        except Exception:
            continue


# ------------------------- Mijoz bo'limlari -------------------------

@router.message(F.text == "📦 Buyurtmalarim")
async def my_orders(message: Message, session: AsyncSession, user: User):
    if not user.customer_id:
        await message.answer("Buyurtmalar yo'q.")
        return
    orders = list(await session.scalars(
        select(Order).where(Order.customer_id == user.customer_id)
        .order_by(Order.created_at.desc()).limit(10)
    ))
    if not orders:
        await message.answer("Buyurtmalar yo'q.")
        return
    for order in orders:
        await message.answer(order_text(order))


@router.message(F.text == "🧾 Xaridlarim")
async def my_purchases(message: Message, session: AsyncSession, user: User):
    if not user.customer_id:
        await message.answer("Xaridlar yo'q.")
        return
    sales = list(await session.scalars(
        select(Sale).where(Sale.customer_id == user.customer_id)
        .order_by(Sale.created_at.desc()).limit(15)
    ))
    if not sales:
        await message.answer("Xaridlar yo'q.")
        return
    blocks = []
    for s in sales:
        items = "\n".join(
            f"   • {i.name} — {qty_fmt(i.qty)} {i.unit.value} × {money(i.price)} = {money(i.amount)}"
            for i in s.items
        )
        blocks.append(
            f"🧾 <b>#{s.id}</b> · {s.created_at:%d.%m.%Y %H:%M}\n{items}\n"
            f"   Jami: <b>{money(s.total)}</b> | To'landi: {money(s.paid)} | Qarz: {money(s.debt)}"
        )
    await message.answer("🧾 <b>Xaridlaringiz</b>\n\n" + "\n\n".join(blocks))


@router.message(F.text == "💰 Balansim")
async def my_balance(message: Message, session: AsyncSession, user: User):
    if not user.customer_id:
        await message.answer("Balans ma'lumoti yo'q.")
        return
    customer = await session.get(Customer, user.customer_id)
    entries = list(await session.scalars(
        select(Ledger).where(Ledger.customer_id == customer.id)
        .order_by(Ledger.created_at.desc()).limit(10)
    ))
    lines = [
        f"{'➕' if Decimal(e.amount) > 0 else '➖'} {money(abs(Decimal(e.amount)))} · "
        f"{e.created_at:%d.%m.%Y}" + (f" — {e.comment}" if e.comment else "")
        for e in entries
    ]
    await message.answer(
        f"💰 <b>Balansingiz: {customer.balance_label}</b>\n\n"
        + ("<b>Oxirgi harakatlar:</b>\n" + "\n".join(lines) if lines else "Harakatlar yo'q.")
    )
