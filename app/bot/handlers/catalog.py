from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.states import PaymentMethodForm, ProductForm, SupplierForm
from app.models import PaymentMethod, Product, Shop, Supplier, Unit, User
from app.services import belongs_to, money, parse_amount, qty_fmt

router = Router()

UNITS = [u.value for u in Unit]


def unit_kb():
    return kb.cancel_kb(UNITS)


# ------------------------- Mahsulotlar -------------------------

@router.message(F.text == "📦 Mahsulotlar")
async def products_root(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📦 Mahsulotlar bo'limi", reply_markup=kb.products_menu())


@router.message(F.text == "➕ Mahsulot qo'shish")
async def product_add(message: Message, state: FSMContext, user: User):
    if not user.is_manager:
        await message.answer("Bu amal faqat admin uchun.")
        return
    await message.answer("Mahsulot nomini yozing:", reply_markup=kb.cancel_kb())
    await state.set_state(ProductForm.name)


@router.message(ProductForm.name, F.text)
async def product_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer(
        "💵 Narxini yozing.\nNarx <b>majburiy emas</b> — keyinroq «Mahsulotlar» bo'limidan "
        "qo'yishingiz mumkin.",
        reply_markup=kb.cancel_kb([kb.SKIP]),
    )
    await state.set_state(ProductForm.price)


@router.message(ProductForm.price, F.text)
async def product_price(message: Message, state: FSMContext):
    price = None
    if message.text != kb.SKIP:
        price = parse_amount(message.text)
        if price is None or price < 0:
            await message.answer("Narxni raqamda yozing yoki o'tkazib yuboring.")
            return
    await state.update_data(price=str(price) if price is not None else None)
    await message.answer("O'lchov birligini tanlang:", reply_markup=unit_kb())
    await state.set_state(ProductForm.unit)


@router.message(ProductForm.unit, F.text)
async def product_unit(message: Message, state: FSMContext):
    value = message.text.strip().lower()
    if value not in UNITS:
        await message.answer("Ro'yxatdan tanlang.")
        return
    await state.update_data(unit=value)
    await message.answer("🖼 Mahsulot rasmini yuboring (ixtiyoriy):",
                         reply_markup=kb.cancel_kb([kb.SKIP]))
    await state.set_state(ProductForm.photo)


@router.message(ProductForm.photo, F.photo | F.text)
async def product_photo(message: Message, state: FSMContext, session: AsyncSession, shop: Shop):
    photo_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(photo=photo_id)

    suppliers = list(await session.scalars(
        select(Supplier).where(Supplier.shop_id == shop.id, Supplier.is_active.is_(True))
    ))
    if not suppliers:
        await _save_product(message, state, session, shop, supplier_id=None)
        return
    items = [(s.id, s.name) for s in suppliers]
    items.append((0, "➖ Yetkazib beruvchisiz"))
    await message.answer("🚚 Yetkazib beruvchini tanlang:",
                         reply_markup=kb.inline_list("psup", items))
    await state.set_state(ProductForm.supplier)


@router.callback_query(ProductForm.supplier, F.data.startswith("psup:"))
async def product_supplier(call: CallbackQuery, state: FSMContext,
                           session: AsyncSession, shop: Shop):
    sup_id = int(call.data.split(":")[1]) or None
    if sup_id and not belongs_to(await session.get(Supplier, sup_id), shop):
        sup_id = None
    await call.message.delete()
    await _save_product(call.message, state, session, shop, supplier_id=sup_id)
    await call.answer()


async def _save_product(message: Message, state: FSMContext, session: AsyncSession,
                        shop: Shop, supplier_id: int | None):
    data = await state.get_data()
    await state.clear()
    product = Product(
        shop_id=shop.id,
        name=data["name"],
        price=parse_amount(data["price"]) if data.get("price") else None,
        unit=Unit(data.get("unit", "dona")),
        photo_file_id=data.get("photo"),
        supplier_id=supplier_id,
    )
    session.add(product)
    await session.flush()
    price_text = f"{money(product.price)} so'm" if product.price is not None else "belgilanmagan"
    await message.answer(
        f"✅ Mahsulot qo'shildi\n\n"
        f"📦 <b>{product.name}</b>\n"
        f"💵 Narx: {price_text}\n"
        f"⚖️ Birlik: {product.unit.value}",
        reply_markup=kb.products_menu(),
    )


@router.message(F.text == "📃 Mahsulotlar ro'yxati")
async def product_list(message: Message, session: AsyncSession, shop: Shop):
    products = list(await session.scalars(
        select(Product).where(Product.shop_id == shop.id, Product.is_active.is_(True))
        .order_by(Product.name).limit(50)
    ))
    if not products:
        await message.answer("Hozircha mahsulot yo'q. «➕ Mahsulot qo'shish» tugmasini bosing.")
        return
    items = [(p.id, f"{p.name} — {p.price_label}") for p in products]
    await message.answer("📦 Mahsulotni tanlang:", reply_markup=kb.inline_list("pcard", items))


@router.message(F.text == "🔎 Mahsulot qidirish")
async def product_search_start(message: Message, state: FSMContext):
    await message.answer("Mahsulot nomini yozing:", reply_markup=kb.cancel_kb())
    await state.set_state(ProductForm.search)


@router.message(ProductForm.search, F.text)
async def product_search(message: Message, state: FSMContext,
                         session: AsyncSession, shop: Shop):
    await state.clear()
    q = f"%{message.text.strip()}%"
    products = list(await session.scalars(
        select(Product).where(Product.shop_id == shop.id, Product.name.ilike(q)).limit(30)
    ))
    if not products:
        await message.answer("Topilmadi.", reply_markup=kb.products_menu())
        return
    items = [(p.id, f"{p.name} — {p.price_label}") for p in products]
    await message.answer("Natijalar:", reply_markup=kb.inline_list("pcard", items))


@router.callback_query(F.data.startswith("pcard:"))
async def product_card(call: CallbackQuery, session: AsyncSession, shop: Shop):
    product = await session.get(Product, int(call.data.split(":")[1]))
    if not belongs_to(product, shop):
        await call.answer("Topilmadi", show_alert=True)
        return
    text = (
        f"📦 <b>{product.name}</b>\n"
        f"💵 Narx: {product.price_label}\n"
        f"⚖️ Birlik: {product.unit.value}\n"
        f"📊 Qoldiq: {qty_fmt(product.stock)}\n"
        f"🚚 Yetkazib beruvchi: {product.supplier.name if product.supplier else '—'}"
    )
    if product.photo_file_id:
        await call.message.answer_photo(product.photo_file_id, caption=text,
                                        reply_markup=kb.product_card_kb(product.id))
    else:
        await call.message.answer(text, reply_markup=kb.product_card_kb(product.id))
    await call.answer()


@router.callback_query(F.data.startswith("prod:"))
async def product_action(call: CallbackQuery, state: FSMContext,
                         session: AsyncSession, shop: Shop, user: User):
    _, action, pid = call.data.split(":")
    product = await session.get(Product, int(pid))
    if not belongs_to(product, shop):
        await call.answer("Topilmadi", show_alert=True)
        return
    if not user.is_manager:
        await call.answer("Ruxsat yo'q", show_alert=True)
        return

    await state.update_data(product_id=product.id)
    if action == "price":
        await call.message.answer(f"«{product.name}» uchun yangi narxni yozing:",
                                  reply_markup=kb.cancel_kb())
        await state.set_state(ProductForm.edit_price)
    elif action == "name":
        await call.message.answer("Yangi nomni yozing:", reply_markup=kb.cancel_kb())
        await state.set_state(ProductForm.edit_name)
    elif action == "photo":
        await call.message.answer("Yangi rasmni yuboring:", reply_markup=kb.cancel_kb())
        await state.set_state(ProductForm.edit_photo)
    elif action == "del":
        product.is_active = False
        await call.message.answer(f"🗑 «{product.name}» ro'yxatdan olib tashlandi.")
    await call.answer()


@router.message(ProductForm.edit_price, F.text)
async def product_edit_price(message: Message, state: FSMContext,
                     session: AsyncSession, shop: Shop):
    price = parse_amount(message.text)
    if price is None or price < 0:
        await message.answer("Narxni raqamda yozing.")
        return
    data = await state.get_data()
    await state.clear()
    product = await session.get(Product, data["product_id"])
    if not belongs_to(product, shop):
        await message.answer("Mahsulot topilmadi.")
        return
    product.price = price
    await message.answer(f"✅ «{product.name}» narxi {money(price)} so'm qilib belgilandi.",
                         reply_markup=kb.products_menu())


@router.message(ProductForm.edit_name, F.text)
async def product_edit_name(message: Message, state: FSMContext,
                     session: AsyncSession, shop: Shop):
    data = await state.get_data()
    await state.clear()
    product = await session.get(Product, data["product_id"])
    if not belongs_to(product, shop):
        await message.answer("Mahsulot topilmadi.")
        return
    product.name = message.text.strip()
    await message.answer(f"✅ Nomi «{product.name}» ga o'zgartirildi.",
                         reply_markup=kb.products_menu())


@router.message(ProductForm.edit_photo, F.photo)
async def product_edit_photo(message: Message, state: FSMContext,
                     session: AsyncSession, shop: Shop):
    data = await state.get_data()
    await state.clear()
    product = await session.get(Product, data["product_id"])
    if not belongs_to(product, shop):
        await message.answer("Mahsulot topilmadi.")
        return
    product.photo_file_id = message.photo[-1].file_id
    await message.answer("✅ Rasm yangilandi.", reply_markup=kb.products_menu())


# ------------------------- Yetkazib beruvchilar -------------------------

@router.message(F.text == "🚚 Yetkazib beruvchilar")
async def suppliers_root(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🚚 Yetkazib beruvchilar bo'limi", reply_markup=kb.suppliers_menu())


@router.message(F.text == "➕ Yetkazib beruvchi qo'shish")
async def supplier_add(message: Message, state: FSMContext, user: User):
    if not user.is_manager:
        return
    await message.answer("Yetkazib beruvchi nomini yozing:", reply_markup=kb.cancel_kb())
    await state.set_state(SupplierForm.name)


@router.message(SupplierForm.name, F.text)
async def supplier_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("📱 Telefon raqamini yozing:", reply_markup=kb.cancel_kb([kb.SKIP]))
    await state.set_state(SupplierForm.phone)


@router.message(SupplierForm.phone, F.text)
async def supplier_phone(message: Message, state: FSMContext,
                         session: AsyncSession, shop: Shop):
    phone = None if message.text == kb.SKIP else message.text.strip()
    data = await state.get_data()
    await state.clear()
    session.add(Supplier(shop_id=shop.id, name=data["name"], phone=phone))
    await message.answer(f"✅ «{data['name']}» qo'shildi.\n📱 {phone or '—'}",
                         reply_markup=kb.suppliers_menu())


@router.message(F.text == "📃 Yetkazib beruvchilar")
async def supplier_list(message: Message, session: AsyncSession, shop: Shop):
    suppliers = list(await session.scalars(
        select(Supplier).where(Supplier.shop_id == shop.id, Supplier.is_active.is_(True))
        .order_by(Supplier.name)
    ))
    if not suppliers:
        await message.answer("Ro'yxat bo'sh.")
        return
    lines = [f"{i}. <b>{s.name}</b> — 📱 {s.phone or '—'}" for i, s in enumerate(suppliers, 1)]
    await message.answer("🚚 <b>Yetkazib beruvchilar</b>\n\n" + "\n".join(lines))


# ------------------------- To'lov turlari -------------------------

@router.message(F.text == "💳 To'lov turlari")
async def payment_methods(message: Message, session: AsyncSession, shop: Shop, user: User):
    if not user.is_manager:
        return
    methods = list(await session.scalars(
        select(PaymentMethod).where(PaymentMethod.shop_id == shop.id)
    ))
    lines = [f"• {m.name}{'' if m.is_active else ' (o‘chirilgan)'}" for m in methods]
    items = [(m.id, f"🗑 {m.name}") for m in methods if m.is_active]
    items.append((0, "➕ Yangi to'lov turi"))
    await message.answer(
        "💳 <b>To'lov turlari</b>\n\n" + ("\n".join(lines) or "Ro'yxat bo'sh"),
        reply_markup=kb.inline_list("pm", items),
    )


@router.callback_query(F.data.startswith("pm:"))
async def payment_method_action(call: CallbackQuery, state: FSMContext,
                                session: AsyncSession, shop: Shop):
    pm_id = int(call.data.split(":")[1])
    if pm_id == 0:
        await call.message.answer("Yangi to'lov turi nomini yozing (masalan: Click, Payme):",
                                  reply_markup=kb.cancel_kb())
        await state.set_state(PaymentMethodForm.name)
    else:
        method = await session.get(PaymentMethod, pm_id)
        if belongs_to(method, shop):
            method.is_active = False
            await call.message.answer(f"🗑 «{method.name}» o'chirildi.")
    await call.answer()


@router.message(PaymentMethodForm.name, F.text)
async def payment_method_add(message: Message, state: FSMContext,
                             session: AsyncSession, shop: Shop, user: User):
    await state.clear()
    session.add(PaymentMethod(shop_id=shop.id, name=message.text.strip()))
    await message.answer(f"✅ «{message.text.strip()}» qo'shildi.",
                         reply_markup=kb.main_menu(user.role))
