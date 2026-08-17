from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.states import SaleForm
from app.models import (
    Customer, LedgerType, PaymentMethod, Product, Sale, SaleItem, Shop, User
)
from app.services import apply_balance, belongs_to, money, parse_amount, qty_fmt

router = Router()


def cart_kb() -> "InlineKeyboardBuilder":
    kbd = InlineKeyboardBuilder()
    kbd.button(text="➕ Yana mahsulot", callback_data="sale:more")
    kbd.button(text="🗑 Oxirgisini o'chirish", callback_data="sale:undo")
    kbd.button(text="✅ Yakunlash", callback_data="sale:finish")
    kbd.button(text="❌ Bekor qilish", callback_data="sale:cancel")
    kbd.adjust(2, 2)
    return kbd.as_markup()


def cart_text(cart: list[dict]) -> str:
    if not cart:
        return "Savat bo'sh."
    lines, total = [], Decimal(0)
    for i, item in enumerate(cart, 1):
        amount = Decimal(item["amount"])
        total += amount
        lines.append(
            f"{i}. {item['name']} — {qty_fmt(item['qty'])} {item['unit']} × "
            f"{money(item['price'])} = <b>{money(amount)}</b>"
        )
    lines.append(f"\n💰 <b>Jami: {money(total)} so'm</b>")
    return "\n".join(lines)


@router.message(F.text == "🛒 Savdo")
async def sale_start(message: Message, state: FSMContext, session: AsyncSession, shop: Shop):
    await state.clear()
    customers = list(await session.scalars(
        select(Customer).where(Customer.shop_id == shop.id, Customer.is_active.is_(True))
        .order_by(Customer.name).limit(30)
    ))
    items = [(c.id, f"{c.name} — {c.balance_label}") for c in customers]
    items.insert(0, (0, "🚶 Mijozsiz (tezkor savdo)"))
    await message.answer(
        "🛒 <b>Yangi savdo</b>\n\nMijozni tanlang yoki ismini yozib qidiring:",
        reply_markup=kb.inline_list("scust", items),
    )
    await state.set_state(SaleForm.customer)


@router.message(SaleForm.customer, F.text)
async def sale_customer_search(message: Message, state: FSMContext,
                               session: AsyncSession, shop: Shop):
    q = f"%{message.text.strip()}%"
    customers = list(await session.scalars(
        select(Customer).where(
            Customer.shop_id == shop.id,
            or_(Customer.name.ilike(q), Customer.phone.ilike(q)),
        ).limit(20)
    ))
    if not customers:
        await message.answer("Topilmadi. Boshqa nom yozing.")
        return
    items = [(c.id, f"{c.name} — {c.balance_label}") for c in customers]
    await message.answer("Mijozni tanlang:", reply_markup=kb.inline_list("scust", items))


@router.callback_query(SaleForm.customer, F.data.startswith("scust:"))
async def sale_customer(call: CallbackQuery, state: FSMContext,
                        session: AsyncSession, shop: Shop):
    cid = int(call.data.split(":")[1])
    name = "Tezkor savdo"
    if cid:
        customer = await session.get(Customer, cid)
        if not belongs_to(customer, shop):
            await call.answer("Mijoz topilmadi", show_alert=True)
            return
        name = customer.name
    await state.update_data(customer_id=cid or None, customer_name=name, cart=[])
    await call.message.edit_text(f"👤 Mijoz: <b>{name}</b>")
    await call.message.answer("📦 Mahsulot nomini yozing:", reply_markup=kb.cancel_kb())
    await state.set_state(SaleForm.product_search)
    await call.answer()


@router.message(SaleForm.product_search, F.text)
async def sale_product_search(message: Message, state: FSMContext,
                              session: AsyncSession, shop: Shop):
    q = f"%{message.text.strip()}%"
    products = list(await session.scalars(
        select(Product).where(
            Product.shop_id == shop.id, Product.is_active.is_(True), Product.name.ilike(q)
        ).limit(20)
    ))
    if not products:
        await message.answer("Topilmadi. Boshqa nom yozing.")
        return
    items = [(p.id, f"{p.name} — {p.price_label}") for p in products]
    await message.answer("Mahsulotni tanlang:", reply_markup=kb.inline_list("sprod", items))


@router.callback_query(SaleForm.product_search, F.data.startswith("sprod:"))
async def sale_product(call: CallbackQuery, state: FSMContext,
                       session: AsyncSession, shop: Shop):
    product = await session.get(Product, int(call.data.split(":")[1]))
    if not belongs_to(product, shop):
        await call.answer("Topilmadi", show_alert=True)
        return
    await state.update_data(product_id=product.id, product_name=product.name,
                            unit=product.unit.value,
                            product_price=str(product.price) if product.price is not None else None)
    await call.message.edit_text(f"📦 {product.name} — {product.price_label}")
    await call.message.answer(f"Miqdorini yozing ({product.unit.value}):",
                              reply_markup=kb.cancel_kb())
    await state.set_state(SaleForm.qty)
    await call.answer()


@router.message(SaleForm.qty, F.text)
async def sale_qty(message: Message, state: FSMContext):
    qty = parse_amount(message.text)
    if qty is None or qty <= 0:
        await message.answer("Miqdorni musbat raqamda yozing.")
        return
    data = await state.get_data()
    await state.update_data(qty=str(qty))
    default = data.get("product_price")
    hint = f"\nMahsulot narxi: {money(default)} so'm — o'zgartirmasangiz «{kb.SKIP}» ni bosing." if default else ""
    await message.answer(f"💵 Sotish narxini yozing:{hint}",
                         reply_markup=kb.cancel_kb([kb.SKIP] if default else None))
    await state.set_state(SaleForm.price)


@router.message(SaleForm.price, F.text)
async def sale_price(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.text == kb.SKIP and data.get("product_price"):
        price = Decimal(data["product_price"])
    else:
        price = parse_amount(message.text)
    if price is None or price < 0:
        await message.answer("Narxni raqamda yozing.")
        return

    qty = Decimal(data["qty"])
    cart = data.get("cart", [])
    cart.append({
        "product_id": data["product_id"],
        "name": data["product_name"],
        "unit": data["unit"],
        "qty": str(qty),
        "price": str(price),
        "amount": str(qty * price),
    })
    await state.update_data(cart=cart)
    await message.answer("🧺 <b>Savat</b>\n\n" + cart_text(cart), reply_markup=cart_kb())


@router.callback_query(F.data.startswith("sale:"))
async def sale_cart_action(call: CallbackQuery, state: FSMContext,
                           session: AsyncSession, shop: Shop, user: User):
    action = call.data.split(":")[1]
    data = await state.get_data()
    cart = data.get("cart", [])

    if action == "cancel":
        await state.clear()
        await call.message.edit_text("❌ Savdo bekor qilindi.")
        await call.message.answer("Bosh menyu", reply_markup=kb.main_menu(user.role))
    elif action == "more":
        await call.message.answer("📦 Mahsulot nomini yozing:", reply_markup=kb.cancel_kb())
        await state.set_state(SaleForm.product_search)
    elif action == "undo":
        if cart:
            cart.pop()
            await state.update_data(cart=cart)
        await call.message.edit_text("🧺 <b>Savat</b>\n\n" + cart_text(cart), reply_markup=cart_kb())
    elif action == "finish":
        if not cart:
            await call.answer("Savat bo'sh", show_alert=True)
            return
        methods = list(await session.scalars(
            select(PaymentMethod).where(
                PaymentMethod.shop_id == shop.id, PaymentMethod.is_active.is_(True)
            )
        ))
        items = [(m.id, m.name) for m in methods]
        await call.message.answer("💳 To'lov turini tanlang:",
                                  reply_markup=kb.inline_list("spm", items, per_row=2))
        await state.set_state(SaleForm.payment_method)
    await call.answer()


@router.callback_query(SaleForm.payment_method, F.data.startswith("spm:"))
async def sale_payment_method(call: CallbackQuery, state: FSMContext,
                              session: AsyncSession, shop: Shop):
    method = await session.get(PaymentMethod, int(call.data.split(":")[1]))
    if not belongs_to(method, shop):
        await call.answer("To'lov turi topilmadi", show_alert=True)
        return
    data = await state.get_data()
    total = sum(Decimal(i["amount"]) for i in data.get("cart", []))
    await state.update_data(payment_method_id=method.id if method else None)
    await call.message.edit_text(f"💳 To'lov turi: <b>{method.name if method else '—'}</b>")
    await call.message.answer(
        f"💰 Jami: <b>{money(total)} so'm</b>\n\n"
        "Mijoz qancha pul to'ladi? Summani yozing.\n"
        "To'liq to'lasa «To'liq», umuman to'lamasa 0 yozing.",
        reply_markup=kb.cancel_kb(["To'liq"]),
    )
    await state.set_state(SaleForm.paid)
    await call.answer()


@router.message(SaleForm.paid, F.text)
async def sale_paid(message: Message, state: FSMContext, session: AsyncSession,
                    shop: Shop, user: User):
    data = await state.get_data()
    cart = data.get("cart", [])
    total = sum(Decimal(i["amount"]) for i in cart)

    if message.text.strip().lower() in ("to'liq", "toliq", "to‘liq"):
        paid = total
    else:
        paid = parse_amount(message.text)
    if paid is None or paid < 0:
        await message.answer("Summani raqamda yozing.")
        return

    debt = total - paid
    if debt > 0 and not data.get("customer_id"):
        await message.answer(
            "⚠️ Tezkor savdoda qarz qoldirib bo'lmaydi. To'liq summani kiriting "
            "yoki savdoni mijoz tanlab qayta boshlang."
        )
        return

    sale = Sale(
        shop_id=shop.id,
        customer_id=data.get("customer_id"),
        seller_tg_id=message.from_user.id,
        seller_name=user.full_name,
        payment_method_id=data.get("payment_method_id"),
        total=total,
        paid=paid,
        debt=debt,
    )
    session.add(sale)
    await session.flush()

    for item in cart:
        session.add(SaleItem(
            sale_id=sale.id,
            product_id=item["product_id"],
            name=item["name"],
            unit=item["unit"],
            qty=Decimal(item["qty"]),
            price=Decimal(item["price"]),
            amount=Decimal(item["amount"]),
        ))
        product = await session.get(Product, item["product_id"])
        if belongs_to(product, shop):
            product.stock = Decimal(product.stock or 0) - Decimal(item["qty"])

    customer = None
    if data.get("customer_id"):
        customer = await session.get(Customer, data["customer_id"])
        if customer and not belongs_to(customer, shop):
            await message.answer("Mijoz topilmadi.")
            return
        if debt:
            await apply_balance(session, customer, debt, LedgerType.SALE,
                                f"Savdo #{sale.id}", message.from_user.id, sale_id=sale.id)

    await state.clear()
    text = (
        f"✅ <b>Savdo #{sale.id} saqlandi</b>\n\n"
        f"👤 {data.get('customer_name')}\n"
        f"{cart_text(cart)}\n\n"
        f"💵 To'landi: {money(paid)} so'm\n"
        f"📌 Qarz: {money(debt)} so'm"
    )
    if customer:
        text += f"\n💰 Mijoz balansi: {customer.balance_label}"
    await message.answer(text, reply_markup=kb.main_menu(user.role))
