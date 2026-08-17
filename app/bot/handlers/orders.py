from __future__ import annotations

from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.handlers.customer_side import DELIVERY_LABEL, STATUS_LABEL, order_text
from app.bot.states import OrderManage
from app.models import (
    Customer, DeliveryType, LedgerType, Order, OrderStatus, Sale, SaleItem, Shop, User
)
from app.services import (
    apply_balance, belongs_to, money, parse_amount, qty_fmt, staff_members,
)

router = Router()

OPEN_STATUSES = [OrderStatus.NEW, OrderStatus.PRICED, OrderStatus.CONFIRMED,
                 OrderStatus.SCHEDULED]


async def notify_staff(bot: Bot, session: AsyncSession, shop: Shop, text: str,
                       markup=None) -> None:
    for member in await staff_members(session, shop.id):
        try:
            await bot.send_message(member.tg_id, text, reply_markup=markup)
        except Exception:
            continue


@router.message(F.text == "📥 Buyurtmalar")
async def orders_list(message: Message, session: AsyncSession, shop: Shop, user: User):
    if not user.is_staff:
        return
    orders = list(await session.scalars(
        select(Order).where(Order.shop_id == shop.id, Order.status.in_(OPEN_STATUSES))
        .order_by(Order.created_at.desc()).limit(20)
    ))
    if not orders:
        await message.answer("Ochiq buyurtmalar yo'q.")
        return
    for order in orders:
        markup = None
        if order.status == OrderStatus.NEW:
            markup = kb.order_staff_kb(order.id)
        elif order.status == OrderStatus.CONFIRMED:
            markup = _time_kb(order.id)
        elif order.status == OrderStatus.SCHEDULED:
            markup = kb.order_finish_kb(order.id)
        await message.answer(order_text(order), reply_markup=markup)


def _time_kb(order_id: int):
    kbd = InlineKeyboardBuilder()
    kbd.button(text="⏰ Yetkazish vaqtini belgilash", callback_data=f"ordm:time:{order_id}")
    return kbd.as_markup()


# ------------------------- Narxlash -------------------------

@router.callback_query(F.data.startswith("ordm:"))
async def order_manage(call: CallbackQuery, state: FSMContext, bot: Bot,
                       session: AsyncSession, shop: Shop, user: User):
    _, action, oid = call.data.split(":")
    order = await session.get(Order, int(oid))
    if not belongs_to(order, shop):
        await call.answer("Buyurtma topilmadi", show_alert=True)
        return
    if not user.is_staff:
        await call.answer("Ruxsat yo'q", show_alert=True)
        return

    if action == "cancel":
        order.status = OrderStatus.CANCELLED
        await call.message.edit_text(f"🚫 Buyurtma #{order.id} bekor qilindi.")
        await _tell_customer(bot, session, order,
                             f"🚫 Buyurtmangiz #{order.id} bekor qilindi.")
    elif action == "price":
        total = Decimal(0)
        missing = []
        for item in order.items:
            if not item.price:
                missing.append(item.name)
            item.amount = Decimal(item.qty) * Decimal(item.price or 0)
            total += item.amount
        if missing:
            await call.answer(
                "Ba'zi mahsulotlarda narx yo'q: " + ", ".join(missing) +
                ". «Narxlarni qo'lda kiritish» ni tanlang.",
                show_alert=True,
            )
            return
        order.total = total
        order.status = OrderStatus.PRICED
        await session.flush()
        await call.message.edit_text(order_text(order))
        await _send_price_offer(bot, session, order)
    elif action == "manual":
        await state.update_data(order_id=order.id, item_index=0)
        await _ask_item_price(call.message, state, order, 0)
    elif action == "time":
        await state.update_data(order_id=order.id)
        await call.message.answer(
            f"⏰ Buyurtma #{order.id} — yetkazishning <b>taxminiy vaqtini</b> yozing.\n"
            "Masalan: «bugun 16:00 — 17:00»",
            reply_markup=kb.cancel_kb(),
        )
        await state.set_state(OrderManage.delivery_time)
    elif action == "done":
        await _order_to_sale(call, bot, session, shop, order, user)
    await call.answer()


async def _ask_item_price(target: Message, state: FSMContext, order: Order, index: int):
    item = order.items[index]
    await target.answer(
        f"💵 <b>{item.name}</b> — {qty_fmt(item.qty)} {item.unit.value}\n"
        f"1 {item.unit.value} narxini yozing:",
        reply_markup=kb.cancel_kb(),
    )
    await state.set_state(OrderManage.price)


@router.message(OrderManage.price, F.text)
async def order_manual_price(message: Message, state: FSMContext, bot: Bot,
                             session: AsyncSession, shop: Shop):
    price = parse_amount(message.text)
    if price is None or price < 0:
        await message.answer("Narxni raqamda yozing.")
        return
    data = await state.get_data()
    order = await session.get(Order, data["order_id"])
    if not belongs_to(order, shop):
        await message.answer("Buyurtma topilmadi.")
        return
    index = data["item_index"]
    item = order.items[index]
    item.price = price
    item.amount = Decimal(item.qty) * price
    await session.flush()

    if index + 1 < len(order.items):
        await state.update_data(item_index=index + 1)
        await _ask_item_price(message, state, order, index + 1)
        return

    await state.clear()
    order.total = sum(Decimal(i.amount) for i in order.items)
    order.status = OrderStatus.PRICED
    await session.flush()
    await message.answer("✅ Narxlar kiritildi va mijozga yuborildi.\n\n" + order_text(order))
    await _send_price_offer(bot, session, order)


async def _send_price_offer(bot: Bot, session: AsyncSession, order: Order):
    lines = [
        f"{i}. {item.name} — <b>{qty_fmt(item.qty)} {item.unit.value}</b> × "
        f"{money(item.price)} = <b>{money(item.amount)} so'm</b>"
        for i, item in enumerate(order.items, 1)
    ]
    text = (
        f"💵 <b>Buyurtma #{order.id} narxlandi</b>\n\n"
        + "\n".join(lines)
        + f"\n\n💰 <b>Jami: {money(order.total)} so'm</b>\n"
        f"{DELIVERY_LABEL[order.delivery_type]}\n"
        f"🗓 Qachonga: {order.needed_at or '—'}\n\n"
        "Tasdiqlaysizmi?"
    )
    await _tell_customer(bot, session, order, text, kb.order_customer_kb(order.id))


async def _tell_customer(bot: Bot, session: AsyncSession, order: Order,
                         text: str, markup=None):
    customer = order.customer or await session.get(Customer, order.customer_id)
    if customer and customer.tg_id:
        try:
            await bot.send_message(customer.tg_id, text, reply_markup=markup)
        except Exception:
            pass


# ------------------------- Mijoz tasdig'i -------------------------

@router.callback_query(F.data.startswith("ordc:"))
async def order_customer_decision(call: CallbackQuery, state: FSMContext, bot: Bot,
                                  session: AsyncSession, shop: Shop, user: User):
    _, action, oid = call.data.split(":")
    order = await session.get(Order, int(oid))
    if not belongs_to(order, shop):
        await call.answer("Topilmadi", show_alert=True)
        return
    if not user.customer_id or order.customer_id != user.customer_id:
        await call.answer("Bu buyurtma sizniki emas", show_alert=True)
        return

    if action == "no":
        order.status = OrderStatus.CANCELLED
        await call.message.edit_text(f"🚫 Buyurtma #{order.id} bekor qilindi.")
        await notify_staff(bot, session, shop,
                           f"🚫 Mijoz buyurtma #{order.id} ni bekor qildi.")
        await call.answer()
        return

    order.status = OrderStatus.CONFIRMED
    await session.flush()
    await call.message.edit_text(f"✅ Buyurtma #{order.id} tasdiqlandi.")

    if order.delivery_type == DeliveryType.OWN_DRIVER:
        await state.update_data(order_id=order.id)
        await call.message.answer(
            "🚗 Siz o'z haydovchingiz bilan olib ketasiz.\n"
            "<b>Haydovchingiz qachon boradi?</b> Vaqtni yozing:",
            reply_markup=kb.cancel_kb(),
        )
        await state.set_state(OrderManage.driver_time)
    else:
        await call.message.answer(
            "✅ Rahmat! Do'kon yetkazish vaqtini belgilab, sizga xabar beradi."
        )
        await notify_staff(
            bot, session, shop,
            f"✅ Mijoz buyurtma #{order.id} ni tasdiqladi.\n"
            f"{DELIVERY_LABEL[order.delivery_type]}\n"
            "Yetkazishning taxminiy vaqtini belgilang.",
            _time_kb(order.id),
        )
    await call.answer()


@router.message(OrderManage.driver_time, F.text)
async def order_driver_time(message: Message, state: FSMContext, bot: Bot,
                            session: AsyncSession, shop: Shop, user: User):
    data = await state.get_data()
    await state.clear()
    order = await session.get(Order, data["order_id"])
    order.delivery_time = message.text.strip()
    order.driver_note = f"Mijozning haydovchisi: {message.text.strip()}"
    order.status = OrderStatus.SCHEDULED
    await session.flush()

    await message.answer(
        f"✅ Qabul qilindi. Haydovchingiz: <b>{order.delivery_time}</b>",
        reply_markup=kb.main_menu(user.role),
    )
    await notify_staff(
        bot, session, shop,
        f"🚗 Buyurtma #{order.id}: mijozning haydovchisi <b>{order.delivery_time}</b> da boradi.\n"
        f"👤 {order.customer.name} · 📱 {order.customer.phone or '—'}",
        kb.order_finish_kb(order.id),
    )


@router.message(OrderManage.delivery_time, F.text)
async def order_delivery_time(message: Message, state: FSMContext, bot: Bot,
                              session: AsyncSession, user: User):
    data = await state.get_data()
    await state.clear()
    order = await session.get(Order, data["order_id"])
    order.delivery_time = message.text.strip()
    order.status = OrderStatus.SCHEDULED
    await session.flush()

    await message.answer(f"✅ Vaqt belgilandi: {order.delivery_time}",
                         reply_markup=kb.main_menu(user.role))
    await _tell_customer(
        bot, session, order,
        f"🚚 Buyurtma #{order.id} yetkaziladi.\n"
        f"⏰ Taxminiy vaqt: <b>{order.delivery_time}</b>\n"
        f"📍 {order.address or '—'}",
    )


# ------------------------- Yakunlash -------------------------

async def _order_to_sale(call: CallbackQuery, bot: Bot, session: AsyncSession,
                         shop: Shop, order: Order, user: User):
    sale = Sale(
        shop_id=shop.id,
        customer_id=order.customer_id,
        seller_tg_id=call.from_user.id,
        seller_name=user.full_name,
        total=order.total,
        paid=Decimal(0),
        debt=order.total,
        order_id=order.id,
        comment=f"Buyurtma #{order.id} bo'yicha",
    )
    session.add(sale)
    await session.flush()
    for item in order.items:
        session.add(SaleItem(
            sale_id=sale.id, product_id=item.product_id, name=item.name,
            unit=item.unit, qty=item.qty, price=item.price, amount=item.amount,
        ))
    customer = await session.get(Customer, order.customer_id)
    await apply_balance(session, customer, Decimal(order.total), LedgerType.ORDER,
                        f"Buyurtma #{order.id}", call.from_user.id, sale_id=sale.id)
    order.status = OrderStatus.DONE
    await session.flush()

    await call.message.edit_text(
        f"📦 Buyurtma #{order.id} yetkazildi va savdo #{sale.id} sifatida yozildi.\n"
        f"👤 {customer.name}: {customer.balance_label}"
    )
    await _tell_customer(
        bot, session, order,
        f"📦 Buyurtma #{order.id} yetkazildi. Rahmat!\n"
        f"💰 Joriy balansingiz: {customer.balance_label}",
    )
