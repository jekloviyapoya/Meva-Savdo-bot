"""Mini App uchun JSON API.

Har bir so'rov Telegram initData bilan tekshiriladi va faqat foydalanuvchining
faol biznesi doirasida ishlaydi.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AUTHOR, COMPANY, VERSION, settings
from app.db import SessionMaker
from app.models import (
    MediaFile,
    Customer, DeliveryType, Invite, Ledger, LedgerType, Order, OrderItem,
    OrderStatus, PaymentMethod, Product, Role, Sale, SaleItem, Shop, Supplier,
    Unit, User, UserStatus,
)
from app.services import (
    apply_balance, create_invite, find_login, invite_link, managers, memberships,
    hash_password, money, normalize_phone, qty_fmt, set_balance, staff_members,
    switch_shop, verify_password,
)
from app.web.auth import TgContext, get_context, make_token

log = logging.getLogger("api")
router = APIRouter(prefix="/api")

MEDIA = Path(settings.media_dir)
MEDIA.mkdir(parents=True, exist_ok=True)

_bot = None


async def notify(tg_id: int | None, text: str) -> None:
    """Telegram orqali xabar yuboradi (ilova ichidan)."""
    global _bot
    if not tg_id or not settings.bot_token:
        return
    try:
        if _bot is None:
            from aiogram import Bot
            from aiogram.client.default import DefaultBotProperties
            from aiogram.enums import ParseMode

            _bot = Bot(settings.bot_token,
                       default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        await _bot.send_message(tg_id, text)
    except Exception as exc:
        log.warning("Xabar yuborilmadi (%s): %s", tg_id, exc)


async def get_session() -> AsyncSession:
    async with SessionMaker() as session:
        yield session


async def ctx(request: Request, session: AsyncSession = Depends(get_session)) -> TgContext:
    return await get_context(request, session, None)


async def fetch_sale(session: AsyncSession, sale_id: int) -> Sale:
    """Savdoni bog'liq ma'lumotlari bilan qayta o'qiydi (commit'dan keyin kerak)."""
    return await session.scalar(
        select(Sale).options(
            selectinload(Sale.items), selectinload(Sale.customer),
            selectinload(Sale.payment_method),
        ).where(Sale.id == sale_id)
    )


async def fetch_order(session: AsyncSession, order_id: int) -> Order:
    return await session.scalar(
        select(Order).options(selectinload(Order.items), selectinload(Order.customer))
        .where(Order.id == order_id)
    )


def dec(value, default="0") -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except Exception:
        return Decimal(default)


# ------------------------- Serializatsiya -------------------------

def s_product(p: Product) -> dict:
    return {
        "id": p.id, "name": p.name,
        "price": float(p.price) if p.price is not None else None,
        "price_label": p.price_label, "unit": p.unit.value,
        "stock": float(p.stock or 0), "photo": p.photo_url,
        "supplier": p.supplier.name if p.supplier else None,
        "supplier_id": p.supplier_id,
    }


def s_customer(c: Customer) -> dict:
    return {
        "id": c.id, "name": c.name, "phone": c.phone, "address": c.address,
        "balance": float(c.balance or 0), "balance_label": c.balance_label,
        "photo": c.photo_url, "in_bot": bool(c.tg_id),
    }


def s_sale(s: Sale) -> dict:
    return {
        "id": s.id, "date": s.created_at.isoformat(),
        "customer": s.customer.name if s.customer else "Tezkor savdo",
        "customer_id": s.customer_id, "seller": s.seller_name,
        "method": s.payment_method.name if s.payment_method else None,
        "total": float(s.total), "paid": float(s.paid), "debt": float(s.debt),
        "items": [{"name": i.name, "qty": float(i.qty), "unit": i.unit.value,
                   "price": float(i.price), "amount": float(i.amount)} for i in s.items],
    }


def s_order(o: Order) -> dict:
    return {
        "id": o.id, "date": o.created_at.isoformat(), "status": o.status.value,
        "customer": o.customer.name if o.customer else "—",
        "customer_phone": o.customer.phone if o.customer else None,
        "delivery": o.delivery_type.value, "needed_at": o.needed_at,
        "delivery_time": o.delivery_time, "address": o.address,
        "comment": o.comment, "total": float(o.total),
        "items": [{"id": i.id, "name": i.name, "qty": float(i.qty),
                   "unit": i.unit.value, "price": float(i.price),
                   "amount": float(i.amount)} for i in o.items],
    }


def s_ledger(e: Ledger) -> dict:
    return {"id": e.id, "date": e.created_at.isoformat(), "type": e.type.value,
            "amount": float(e.amount), "balance_after": float(e.balance_after),
            "comment": e.comment}


# ------------------------- Profil va kirish -------------------------

@router.get("/me")
async def me(c: TgContext = Depends(ctx), session: AsyncSession = Depends(get_session)):
    links = await memberships(session, c.tg_id) if c.tg_id else ([c.user] if c.user else [])
    shops = []
    for link in links:
        shop = await session.get(Shop, link.shop_id)
        shops.append({"id": shop.id, "name": shop.name, "role": link.role.value,
                      "active": c.shop is not None and shop.id == c.shop.id})
    return {
        "tg": {"id": c.tg_id, "name": c.tg.get("first_name", ""),
               "username": c.tg.get("username")},
        "linked": c.linked,
        "pending": bool(c.user and c.user.status == UserStatus.PENDING),
        "user": None if not c.user else {
            "id": c.user.id, "name": c.user.full_name, "phone": c.user.phone,
            "role": c.user.role.value, "is_staff": c.user.is_staff,
            "is_manager": c.user.is_manager,
        },
        "shop": None if not c.shop else {
            "id": c.shop.id, "name": c.shop.name, "code": c.shop.code,
            "license_ok": c.shop.license_ok, "days_left": max(c.shop.days_left, 0),
            "license_until": c.shop.license_until.isoformat() if c.shop.license_until else None,
        },
        "shops": shops,
        "about": {"author": AUTHOR, "company": COMPANY, "version": VERSION},
    }


@router.post("/auth/password")
async def auth_password(payload: dict = Body(...),
                        session: AsyncSession = Depends(get_session)):
    """Telefon + parol bilan kirish (Telegramdan tashqarida — mobil ilova, brauzer).

    Bir raqam bir nechta biznesga tegishli bo'lsa, ro'yxat qaytariladi va
    foydalanuvchi qaysi biznesga kirishini tanlaydi.
    """
    phone = normalize_phone(payload.get("phone", ""))
    password = payload.get("password") or ""
    if not phone or not password:
        raise HTTPException(400, "Telefon va parolni kiriting")

    found = await find_login(session, phone)
    matched = [u for u in found if verify_password(password, u.password_hash)
               and u.status == UserStatus.APPROVED]
    if not matched:
        raise HTTPException(401, "Telefon yoki parol noto'g'ri")

    want = payload.get("user_id")
    if want:
        chosen = next((u for u in matched if u.id == int(want)), None)
        if chosen is None:
            raise HTTPException(403, "Bu biznesga ruxsatingiz yo'q")
        matched = [chosen]

    if len(matched) > 1:
        options = []
        for user in matched:
            shop = await session.get(Shop, user.shop_id)
            options.append({"user_id": user.id, "shop": shop.name,
                            "role": user.role.value})
        return {"choose": options}

    user = matched[0]
    shop = await session.get(Shop, user.shop_id)
    return {
        "token": make_token(user.id),
        "user": {"id": user.id, "name": user.full_name, "role": user.role.value},
        "shop": {"id": shop.id, "name": shop.name},
    }


@router.post("/auth/change-password")
async def change_password(payload: dict = Body(...), c: TgContext = Depends(ctx),
                          session: AsyncSession = Depends(get_session)):
    """Parolni almashtirish.

    Paroli bor foydalanuvchi eskisini tasdiqlaydi. Telegram orqali kirgan va
    hali paroli yo'q foydalanuvchi esa birinchi parolini shu yerda o'rnatadi.
    """
    new = (payload.get("new_password") or "").strip()
    if len(new) < 6:
        raise HTTPException(400, "Parol kamida 6 belgidan iborat bo'lsin")

    user = await session.get(User, c.user.id)
    if user.password_hash:
        old = payload.get("old_password") or ""
        if not verify_password(old, user.password_hash):
            raise HTTPException(403, "Eski parol noto'g'ri")

    user.password_hash = hash_password(new)
    await session.commit()
    return {"ok": True, "login": user.phone,
            "had_password": bool(payload.get("old_password"))}


@router.post("/login")
async def login(payload: dict = Body(...), c: TgContext = Depends(ctx),
                session: AsyncSession = Depends(get_session)):
    """Telefon (login) orqali Telegram akkauntni biznesga bog'lash."""
    phone = normalize_phone(payload.get("phone", ""))
    if not phone:
        raise HTTPException(400, "Telefon raqamini to'g'ri kiriting")
    found = await find_login(session, phone)
    free = [u for u in found if u.tg_id is None or u.tg_id == c.tg_id]
    if not free:
        raise HTTPException(404, "Bu raqam bo'yicha login topilmadi")
    for user in free:
        user.tg_id = c.tg_id
        user.username = c.tg.get("username")
    await switch_shop(session, c.tg_id, free[0].shop_id)
    await session.commit()
    return {"ok": True, "shops": len(free)}


@router.post("/switch")
async def switch(payload: dict = Body(...), c: TgContext = Depends(ctx),
                 session: AsyncSession = Depends(get_session)):
    if not await switch_shop(session, c.tg_id, int(payload.get("shop_id", 0))):
        raise HTTPException(403, "Bu biznesga ruxsatingiz yo'q")
    await session.commit()
    return {"ok": True}


# ------------------------- Mahsulotlar -------------------------

@router.get("/products")
async def products(q: str = "", c: TgContext = Depends(ctx),
                   session: AsyncSession = Depends(get_session)):
    shop = c.require_shop()
    stmt = select(Product).where(Product.shop_id == shop.id, Product.is_active.is_(True))
    if q:
        stmt = stmt.where(Product.name.ilike(f"%{q}%"))
    items = list(await session.scalars(stmt.order_by(Product.name).limit(300)))
    return [s_product(p) for p in items]


@router.post("/products")
async def product_create(payload: dict = Body(...), c: TgContext = Depends(ctx),
                         session: AsyncSession = Depends(get_session)):
    c.require_manager()
    shop = c.require_shop()
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Mahsulot nomi kerak")
    price = payload.get("price")
    sup_id = payload.get("supplier_id") or None
    if sup_id:
        c.guard(await session.get(Supplier, int(sup_id)))
    product = Product(
        shop_id=shop.id, name=name,
        price=dec(price) if price not in (None, "") else None,
        unit=Unit(payload.get("unit", "dona")),
        photo_url=payload.get("photo") or None,
        supplier_id=int(sup_id) if sup_id else None,
    )
    session.add(product)
    await session.commit()
    return s_product(product)


@router.patch("/products/{product_id}")
async def product_update(product_id: int, payload: dict = Body(...),
                         c: TgContext = Depends(ctx),
                         session: AsyncSession = Depends(get_session)):
    c.require_manager()
    product = c.guard(await session.get(Product, product_id))
    if "name" in payload and payload["name"]:
        product.name = payload["name"].strip()
    if "price" in payload:
        product.price = dec(payload["price"]) if payload["price"] not in (None, "") else None
    if "unit" in payload and payload["unit"]:
        product.unit = Unit(payload["unit"])
    if "photo" in payload:
        product.photo_url = payload["photo"] or None
    if "stock" in payload and payload["stock"] not in (None, ""):
        product.stock = dec(payload["stock"])
    await session.commit()
    return s_product(product)


@router.delete("/products/{product_id}")
async def product_delete(product_id: int, c: TgContext = Depends(ctx),
                         session: AsyncSession = Depends(get_session)):
    c.require_manager()
    product = c.guard(await session.get(Product, product_id))
    product.is_active = False
    await session.commit()
    return {"ok": True}


# ------------------------- Yetkazib beruvchilar / to'lov turlari -------------------------

@router.get("/suppliers")
async def suppliers(c: TgContext = Depends(ctx),
                    session: AsyncSession = Depends(get_session)):
    shop = c.require_shop()
    items = list(await session.scalars(
        select(Supplier).where(Supplier.shop_id == shop.id, Supplier.is_active.is_(True))
        .order_by(Supplier.name)
    ))
    return [{"id": s.id, "name": s.name, "phone": s.phone} for s in items]


@router.post("/suppliers")
async def supplier_create(payload: dict = Body(...), c: TgContext = Depends(ctx),
                          session: AsyncSession = Depends(get_session)):
    c.require_manager()
    shop = c.require_shop()
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nomi kerak")
    supplier = Supplier(shop_id=shop.id, name=name,
                        phone=normalize_phone(payload.get("phone")) or None)
    session.add(supplier)
    await session.commit()
    return {"id": supplier.id, "name": supplier.name, "phone": supplier.phone}


@router.delete("/suppliers/{supplier_id}")
async def supplier_delete(supplier_id: int, c: TgContext = Depends(ctx),
                          session: AsyncSession = Depends(get_session)):
    c.require_manager()
    supplier = c.guard(await session.get(Supplier, supplier_id))
    supplier.is_active = False
    await session.commit()
    return {"ok": True}


@router.get("/payment-methods")
async def payment_methods(c: TgContext = Depends(ctx),
                          session: AsyncSession = Depends(get_session)):
    shop = c.require_shop()
    items = list(await session.scalars(
        select(PaymentMethod).where(PaymentMethod.shop_id == shop.id,
                                    PaymentMethod.is_active.is_(True))
    ))
    return [{"id": m.id, "name": m.name} for m in items]


@router.post("/payment-methods")
async def payment_method_create(payload: dict = Body(...), c: TgContext = Depends(ctx),
                                session: AsyncSession = Depends(get_session)):
    c.require_manager()
    shop = c.require_shop()
    method = PaymentMethod(shop_id=shop.id, name=(payload.get("name") or "").strip())
    if not method.name:
        raise HTTPException(400, "Nomi kerak")
    session.add(method)
    await session.commit()
    return {"id": method.id, "name": method.name}


@router.delete("/payment-methods/{method_id}")
async def payment_method_delete(method_id: int, c: TgContext = Depends(ctx),
                                session: AsyncSession = Depends(get_session)):
    c.require_manager()
    method = c.guard(await session.get(PaymentMethod, method_id))
    method.is_active = False
    await session.commit()
    return {"ok": True}


# ------------------------- Mijozlar -------------------------

@router.get("/customers")
async def customers(q: str = "", debtors: int = 0, c: TgContext = Depends(ctx),
                    session: AsyncSession = Depends(get_session)):
    shop = c.require_shop()
    c.require_staff()
    stmt = select(Customer).where(Customer.shop_id == shop.id, Customer.is_active.is_(True))
    if q:
        stmt = stmt.where(or_(Customer.name.ilike(f"%{q}%"), Customer.phone.ilike(f"%{q}%")))
    if debtors:
        stmt = stmt.where(Customer.balance > 0)
    items = list(await session.scalars(stmt.order_by(Customer.balance.desc()).limit(300)))
    return [s_customer(x) for x in items]


@router.post("/customers")
async def customer_create(payload: dict = Body(...), c: TgContext = Depends(ctx),
                          session: AsyncSession = Depends(get_session)):
    c.require_staff()
    shop = c.require_shop()
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Mijoz ismi kerak")
    customer = Customer(
        shop_id=shop.id, name=name,
        phone=normalize_phone(payload.get("phone")) or None,
        address=(payload.get("address") or "").strip() or None,
        photo_url=payload.get("photo") or None,
    )
    session.add(customer)
    await session.flush()
    start = dec(payload.get("balance"), "0")
    if start:
        await apply_balance(session, customer, start, LedgerType.INITIAL,
                            "Boshlang'ich balans", c.tg_id)
    await session.commit()
    return s_customer(customer)


@router.get("/customers/{customer_id}")
async def customer_detail(customer_id: int, c: TgContext = Depends(ctx),
                          session: AsyncSession = Depends(get_session)):
    c.require_staff()
    customer = c.guard(await session.get(Customer, customer_id))
    entries = list(await session.scalars(
        select(Ledger).where(Ledger.customer_id == customer_id)
        .order_by(Ledger.created_at.desc()).limit(60)
    ))
    sales = list(await session.scalars(
        select(Sale).where(Sale.customer_id == customer_id)
        .order_by(Sale.created_at.desc()).limit(30)
    ))
    return {"customer": s_customer(customer),
            "ledger": [s_ledger(e) for e in entries],
            "sales": [s_sale(x) for x in sales]}


@router.patch("/customers/{customer_id}")
async def customer_update(customer_id: int, payload: dict = Body(...),
                          c: TgContext = Depends(ctx),
                          session: AsyncSession = Depends(get_session)):
    c.require_staff()
    customer = c.guard(await session.get(Customer, customer_id))
    for field in ("name", "address"):
        if payload.get(field):
            setattr(customer, field, payload[field].strip())
    if "phone" in payload:
        customer.phone = normalize_phone(payload["phone"])
    if "photo" in payload:
        customer.photo_url = payload["photo"] or None
    await session.commit()
    return s_customer(customer)


@router.post("/customers/{customer_id}/balance")
async def customer_balance(customer_id: int, payload: dict = Body(...),
                           c: TgContext = Depends(ctx),
                           session: AsyncSession = Depends(get_session)):
    c.require_staff()
    customer = c.guard(await session.get(Customer, customer_id))
    action = payload.get("action")
    amount = dec(payload.get("amount"))
    comment = (payload.get("comment") or "").strip() or None

    if action == "payment":
        if amount <= 0:
            raise HTTPException(400, "Summa musbat bo'lishi kerak")
        await apply_balance(session, customer, -amount, LedgerType.PAYMENT,
                            comment or "To'lov qabul qilindi", c.tg_id)
    elif action == "debt":
        if amount <= 0:
            raise HTTPException(400, "Summa musbat bo'lishi kerak")
        await apply_balance(session, customer, amount, LedgerType.CORRECTION,
                            comment or "Qarz qo'shildi", c.tg_id)
    elif action == "set":
        await set_balance(session, customer, amount, comment or "Balans to'g'rilandi", c.tg_id)
    else:
        raise HTTPException(400, "Noma'lum amal")
    await session.commit()
    return s_customer(customer)


# ------------------------- Savdo -------------------------

@router.get("/sales")
async def sales(c: TgContext = Depends(ctx),
                session: AsyncSession = Depends(get_session)):
    shop = c.require_shop()
    c.require_staff()
    items = list(await session.scalars(
        select(Sale).where(Sale.shop_id == shop.id)
        .order_by(Sale.created_at.desc()).limit(100)
    ))
    return [s_sale(x) for x in items]


@router.post("/sales")
async def sale_create(payload: dict = Body(...), c: TgContext = Depends(ctx),
                      session: AsyncSession = Depends(get_session)):
    c.require_staff()
    shop = c.require_shop()
    cart = payload.get("items") or []
    if not cart:
        raise HTTPException(400, "Savat bo'sh")

    customer = None
    if payload.get("customer_id"):
        customer = c.guard(await session.get(Customer, int(payload["customer_id"])))

    method_id = payload.get("payment_method_id")
    if method_id:
        c.guard(await session.get(PaymentMethod, int(method_id)))

    total = Decimal(0)
    prepared = []
    for row in cart:
        product = c.guard(await session.get(Product, int(row["product_id"])))
        qty, price = dec(row.get("qty"), "1"), dec(row.get("price"))
        if qty <= 0:
            raise HTTPException(400, f"{product.name}: miqdor noto'g'ri")
        amount = qty * price
        total += amount
        prepared.append((product, qty, price, amount))

    paid = dec(payload.get("paid"))
    debt = total - paid
    if debt > 0 and customer is None:
        raise HTTPException(400, "Qarzga sotish uchun mijozni tanlang")

    sale = Sale(shop_id=shop.id, customer_id=customer.id if customer else None,
                seller_tg_id=c.tg_id, seller_name=c.user.full_name,
                payment_method_id=int(method_id) if method_id else None,
                total=total, paid=paid, debt=debt,
                comment=(payload.get("comment") or "").strip() or None)
    session.add(sale)
    await session.flush()

    for product, qty, price, amount in prepared:
        session.add(SaleItem(sale_id=sale.id, product_id=product.id, name=product.name,
                             unit=product.unit, qty=qty, price=price, amount=amount))
        product.stock = dec(product.stock) - qty

    if customer and debt:
        await apply_balance(session, customer, debt, LedgerType.SALE,
                            f"Savdo #{sale.id}", c.tg_id, sale_id=sale.id)
    await session.commit()
    sale = await fetch_sale(session, sale.id)

    if customer and customer.tg_id:
        await notify(customer.tg_id,
                     f"🧾 Yangi xarid #{sale.id}\n"
                     f"Jami: <b>{money(total)} so'm</b>\n"
                     f"To'landi: {money(paid)} so'm\n"
                     f"Balansingiz: {customer.balance_label}")
    return s_sale(sale)


# ------------------------- Buyurtmalar -------------------------

@router.get("/orders")
async def orders(scope: str = "shop", c: TgContext = Depends(ctx),
                 session: AsyncSession = Depends(get_session)):
    shop = c.require_shop()
    stmt = select(Order).where(Order.shop_id == shop.id)
    if scope == "mine" or not c.is_staff:
        if not c.user.customer_id:
            return []
        stmt = stmt.where(Order.customer_id == c.user.customer_id)
    items = list(await session.scalars(stmt.order_by(Order.created_at.desc()).limit(100)))
    return [s_order(o) for o in items]


@router.post("/orders")
async def order_create(payload: dict = Body(...), c: TgContext = Depends(ctx),
                       session: AsyncSession = Depends(get_session)):
    shop = c.require_shop()
    cart = payload.get("items") or []
    if not cart:
        raise HTTPException(400, "Savat bo'sh")

    customer = None
    if c.user.customer_id:
        customer = await session.get(Customer, c.user.customer_id)
        if not c.owns(customer):
            customer = None
    if customer is None:
        customer = Customer(shop_id=shop.id, name=c.user.full_name,
                            phone=c.user.phone, tg_id=c.tg_id)
        session.add(customer)
        await session.flush()
        c.user.customer_id = customer.id

    order = Order(
        shop_id=shop.id, customer_id=customer.id,
        delivery_type=DeliveryType(payload.get("delivery", "pickup")),
        needed_at=(payload.get("needed_at") or "").strip() or None,
        address=(payload.get("address") or "").strip() or customer.address,
        comment=(payload.get("comment") or "").strip() or None,
        status=OrderStatus.NEW,
    )
    session.add(order)
    await session.flush()

    total = Decimal(0)
    for row in cart:
        product = c.guard(await session.get(Product, int(row["product_id"])))
        qty = dec(row.get("qty"), "1")
        price = dec(product.price) if product.price is not None else Decimal(0)
        session.add(OrderItem(order_id=order.id, product_id=product.id,
                              name=product.name, unit=product.unit, qty=qty,
                              price=price, amount=qty * price))
        total += qty * price
    order.total = total
    await session.commit()
    order = await fetch_order(session, order.id)

    lines = "\n".join(f"• {i.name} — {qty_fmt(i.qty)} {i.unit.value}" for i in order.items)
    for member in await staff_members(session, shop.id):
        await notify(member.tg_id,
                     f"🆕 <b>Yangi buyurtma #{order.id}</b>\n"
                     f"👤 {customer.name}\n🗓 {order.needed_at or '—'}\n\n{lines}\n\n"
                     "Ilovadagi «Buyurtmalar» bo'limidan narxlang.")
    return s_order(order)


@router.post("/orders/{order_id}/price")
async def order_price(order_id: int, payload: dict = Body(...),
                      c: TgContext = Depends(ctx),
                      session: AsyncSession = Depends(get_session)):
    """Do'kon buyurtmani narxlab mijozga yuboradi."""
    c.require_staff()
    order = c.guard(await session.get(Order, order_id))
    prices = {int(k): dec(v) for k, v in (payload.get("prices") or {}).items()}
    quantities = {int(k): dec(v) for k, v in (payload.get("quantities") or {}).items()}

    total = Decimal(0)
    for item in order.items:
        if item.id in quantities and quantities[item.id] > 0:
            item.qty = quantities[item.id]
        if item.id in prices:
            item.price = prices[item.id]
        item.amount = dec(item.qty) * dec(item.price)
        total += item.amount
    order.total = total
    order.status = OrderStatus.PRICED
    await session.commit()
    order = await fetch_order(session, order.id)

    lines = "\n".join(
        f"• {i.name} — <b>{qty_fmt(i.qty)} {i.unit.value}</b> × {money(i.price)} "
        f"= {money(i.amount)} so'm" for i in order.items
    )
    await notify(order.customer.tg_id,
                 f"💵 <b>Buyurtma #{order.id} narxlandi</b>\n\n{lines}\n\n"
                 f"💰 Jami: <b>{money(total)} so'm</b>\n\n"
                 "Ilovani ochib tasdiqlang.")
    return s_order(order)


@router.post("/orders/{order_id}/confirm")
async def order_confirm(order_id: int, payload: dict = Body(default={}),
                        c: TgContext = Depends(ctx),
                        session: AsyncSession = Depends(get_session)):
    """Mijoz tasdiqlaydi. O'z haydovchisi bo'lsa — kelish vaqtini ham yozadi."""
    shop = c.require_shop()
    order = c.guard(await session.get(Order, order_id))
    if not c.user.customer_id or order.customer_id != c.user.customer_id:
        raise HTTPException(403, "Bu buyurtma sizniki emas")

    order.status = OrderStatus.CONFIRMED
    driver_time = (payload.get("driver_time") or "").strip()
    if order.delivery_type == DeliveryType.OWN_DRIVER and driver_time:
        order.delivery_time = driver_time
        order.driver_note = f"Mijozning haydovchisi: {driver_time}"
        order.status = OrderStatus.SCHEDULED
    await session.commit()
    order = await fetch_order(session, order.id)

    extra = (f"\n🚗 Mijozning haydovchisi: <b>{order.delivery_time}</b>"
             if order.delivery_time else "\n⏰ Yetkazish vaqtini belgilang.")
    for member in await staff_members(session, shop.id):
        await notify(member.tg_id,
                     f"✅ Buyurtma #{order.id} tasdiqlandi\n"
                     f"👤 {order.customer.name} · {order.customer.phone or '—'}{extra}")
    return s_order(order)


@router.post("/orders/{order_id}/schedule")
async def order_schedule(order_id: int, payload: dict = Body(...),
                         c: TgContext = Depends(ctx),
                         session: AsyncSession = Depends(get_session)):
    """Do'kon yetkazishning taxminiy vaqtini belgilaydi."""
    c.require_staff()
    order = c.guard(await session.get(Order, order_id))
    time_text = (payload.get("delivery_time") or "").strip()
    if not time_text:
        raise HTTPException(400, "Vaqtni kiriting")
    order.delivery_time = time_text
    order.status = OrderStatus.SCHEDULED
    await session.commit()
    order = await fetch_order(session, order.id)
    await notify(order.customer.tg_id,
                 f"🚚 Buyurtma #{order.id} yetkaziladi.\n"
                 f"⏰ Taxminiy vaqt: <b>{time_text}</b>\n📍 {order.address or '—'}")
    return s_order(order)


@router.post("/orders/{order_id}/done")
async def order_done(order_id: int, c: TgContext = Depends(ctx),
                     session: AsyncSession = Depends(get_session)):
    """Yetkazilgan buyurtmani savdoga o'tkazadi."""
    c.require_staff()
    shop = c.require_shop()
    order = c.guard(await session.get(Order, order_id))
    if order.status == OrderStatus.DONE:
        raise HTTPException(400, "Bu buyurtma allaqachon yakunlangan")

    sale = Sale(shop_id=shop.id, customer_id=order.customer_id, seller_tg_id=c.tg_id,
                seller_name=c.user.full_name, total=order.total, paid=Decimal(0),
                debt=order.total, order_id=order.id,
                comment=f"Buyurtma #{order.id} bo'yicha")
    session.add(sale)
    await session.flush()
    for item in order.items:
        session.add(SaleItem(sale_id=sale.id, product_id=item.product_id, name=item.name,
                             unit=item.unit, qty=item.qty, price=item.price,
                             amount=item.amount))
        product = await session.get(Product, item.product_id) if item.product_id else None
        if c.owns(product):
            product.stock = dec(product.stock) - dec(item.qty)

    customer = await session.get(Customer, order.customer_id)
    await apply_balance(session, customer, dec(order.total), LedgerType.ORDER,
                        f"Buyurtma #{order.id}", c.tg_id, sale_id=sale.id)
    order.status = OrderStatus.DONE
    await session.commit()
    order = await fetch_order(session, order.id)

    await notify(customer.tg_id,
                 f"📦 Buyurtma #{order.id} yetkazildi. Rahmat!\n"
                 f"💰 Balansingiz: {customer.balance_label}")
    return {"order": s_order(order), "sale_id": sale.id}


@router.post("/orders/{order_id}/cancel")
async def order_cancel(order_id: int, c: TgContext = Depends(ctx),
                       session: AsyncSession = Depends(get_session)):
    shop = c.require_shop()
    order = c.guard(await session.get(Order, order_id))
    mine = c.user.customer_id and order.customer_id == c.user.customer_id
    if not (c.is_staff or mine):
        raise HTTPException(403, "Ruxsat yo'q")
    order.status = OrderStatus.CANCELLED
    await session.commit()
    order = await fetch_order(session, order.id)
    if c.is_staff:
        await notify(order.customer.tg_id, f"🚫 Buyurtmangiz #{order.id} bekor qilindi.")
    else:
        for member in await staff_members(session, shop.id):
            await notify(member.tg_id, f"🚫 Mijoz buyurtma #{order.id} ni bekor qildi.")
    return s_order(order)


# ------------------------- Hodimlar va takliflar -------------------------

@router.get("/staff")
async def staff(c: TgContext = Depends(ctx),
                session: AsyncSession = Depends(get_session)):
    shop = c.require_shop()
    c.require_manager()
    users = list(await session.scalars(
        select(User).where(User.shop_id == shop.id).order_by(User.role, User.full_name)
    ))
    invites = list(await session.scalars(
        select(Invite).where(Invite.shop_id == shop.id, Invite.is_active.is_(True))
        .order_by(Invite.created_at.desc()).limit(10)
    ))
    return {
        "users": [{"id": u.id, "name": u.full_name, "phone": u.phone,
                   "role": u.role.value, "status": u.status.value,
                   "in_bot": bool(u.tg_id)} for u in users],
        "invites": [{"id": i.id, "role": i.role.value, "link": invite_link(i.token),
                     "uses": i.uses} for i in invites],
    }


@router.post("/staff")
async def staff_create(payload: dict = Body(...), c: TgContext = Depends(ctx),
                       session: AsyncSession = Depends(get_session)):
    """Hodimga login yaratadi (login = telefon raqami)."""
    c.require_manager()
    shop = c.require_shop()
    phone = normalize_phone(payload.get("phone"))
    name = (payload.get("name") or "").strip()
    if not phone or not name:
        raise HTTPException(400, "Ism va telefon kerak")
    existing = await session.scalar(
        select(User).where(User.shop_id == shop.id, User.phone == phone)
    )
    if existing:
        existing.full_name = name
        existing.status = UserStatus.APPROVED
        existing.role = Role(payload.get("role", "seller"))
        user = existing
    else:
        user = User(shop_id=shop.id, phone=phone, full_name=name,
                    role=Role(payload.get("role", "seller")),
                    status=UserStatus.APPROVED)
        session.add(user)
    await session.commit()
    return {"id": user.id, "name": user.full_name, "phone": user.phone,
            "role": user.role.value, "status": user.status.value, "in_bot": bool(user.tg_id)}


@router.patch("/staff/{user_id}")
async def staff_update(user_id: int, payload: dict = Body(...),
                       c: TgContext = Depends(ctx),
                       session: AsyncSession = Depends(get_session)):
    c.require_manager()
    target = c.guard(await session.get(User, user_id))
    if target.role == Role.OWNER and c.user.role != Role.OWNER:
        raise HTTPException(403, "Egasining rolini o'zgartirib bo'lmaydi")
    if payload.get("role"):
        target.role = Role(payload["role"])
    if payload.get("status"):
        target.status = UserStatus(payload["status"])
        if target.status == UserStatus.APPROVED and target.tg_id:
            await switch_shop(session, target.tg_id, target.shop_id)
    await session.commit()
    if target.tg_id and payload.get("status") == "approved":
        await notify(target.tg_id, "✅ Arizangiz tasdiqlandi! Ilovani oching.")
    return {"id": target.id, "role": target.role.value, "status": target.status.value}


@router.post("/invites")
async def invites_create(payload: dict = Body(...), c: TgContext = Depends(ctx),
                         session: AsyncSession = Depends(get_session)):
    c.require_manager()
    shop = c.require_shop()
    invite = await create_invite(session, shop.id, Role(payload.get("role", "seller")),
                                 c.tg_id)
    await session.commit()
    return {"id": invite.id, "role": invite.role.value,
            "link": invite_link(invite.token), "uses": 0}


# ------------------------- Mijozning shaxsiy bo'limi -------------------------

@router.get("/my/summary")
async def my_summary(c: TgContext = Depends(ctx),
                     session: AsyncSession = Depends(get_session)):
    c.require_shop()
    if not c.user.customer_id:
        return {"balance": 0, "balance_label": "qarz yo'q", "ledger": [], "sales": []}
    customer = await session.get(Customer, c.user.customer_id)
    entries = list(await session.scalars(
        select(Ledger).where(Ledger.customer_id == customer.id)
        .order_by(Ledger.created_at.desc()).limit(30)
    ))
    sales = list(await session.scalars(
        select(Sale).where(Sale.customer_id == customer.id)
        .order_by(Sale.created_at.desc()).limit(30)
    ))
    return {"balance": float(customer.balance or 0),
            "balance_label": customer.balance_label,
            "ledger": [s_ledger(e) for e in entries],
            "sales": [s_sale(x) for x in sales]}


# ------------------------- Hisobot -------------------------

@router.get("/report")
async def report(c: TgContext = Depends(ctx),
                 session: AsyncSession = Depends(get_session)):
    shop = c.require_shop()
    c.require_staff()
    now = datetime.now(timezone.utc)

    async def block(since):
        row = await session.execute(
            select(func.coalesce(func.sum(Sale.total), 0),
                   func.coalesce(func.sum(Sale.paid), 0), func.count(Sale.id))
            .where(Sale.shop_id == shop.id, Sale.created_at >= since)
        )
        total, paid, count = row.one()
        return {"total": float(total), "paid": float(paid), "count": count}

    debt = await session.scalar(
        select(func.coalesce(func.sum(Customer.balance), 0))
        .where(Customer.shop_id == shop.id, Customer.balance > 0)
    )
    top = list(await session.execute(
        select(SaleItem.name, func.sum(SaleItem.amount))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(Sale.shop_id == shop.id, Sale.created_at >= now - timedelta(days=30))
        .group_by(SaleItem.name).order_by(func.sum(SaleItem.amount).desc()).limit(5)
    ))
    open_orders = await session.scalar(
        select(func.count()).select_from(Order).where(
            Order.shop_id == shop.id,
            Order.status.in_([OrderStatus.NEW, OrderStatus.PRICED,
                              OrderStatus.CONFIRMED, OrderStatus.SCHEDULED]))
    )
    products_count = await session.scalar(
        select(func.count()).select_from(Product)
        .where(Product.shop_id == shop.id, Product.is_active.is_(True))
    )
    return {
        "day": await block(now - timedelta(days=1)),
        "month": await block(now - timedelta(days=30)),
        "debt_total": float(debt or 0),
        "open_orders": open_orders or 0,
        "products": products_count or 0,
        "top": [{"name": n, "total": float(v)} for n, v in top],
    }


# ------------------------- Rasm yuklash -------------------------

@router.post("/upload")
async def upload(file: UploadFile = File(...), c: TgContext = Depends(ctx),
                 session: AsyncSession = Depends(get_session)):
    c.require_staff()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(400, "Faqat jpg, png yoki webp")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "Rasm 5 MB dan katta bo'lmasin")
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp"}[ext]
    name = f"{secrets.token_hex(8)}{ext}"

    # Bazaga saqlaymiz — konteyner diski qayta joylashda tozalanadi
    session.add(MediaFile(id=name, shop_id=c.shop.id if c.shop else None,
                          mime=mime, data=data, size=len(data)))
    await session.commit()
    return {"url": f"/media/{name}"}
